"""Publishing a trained model to the Hugging Face Hub.

A push is outward-facing and cannot be taken back once someone has
downloaded the model, so the route that calls :func:`push` asks for the
repository name twice, and this module refuses anything it cannot vouch
for: a run that did not succeed, a run with no model files on this server,
a repository that exists as public when a private push was asked for, and a
token that is missing.

What goes up is chosen by allowlist (:func:`model_files`), not by leaving
things out: ``artifacts/`` also holds the model's answers on this project's
items (``predictions.jsonl``, ``raw_answers.jsonl``) and some trainers'
copies of the training data (``yolo_data/``, ``wev_data/``), which are the
project's, not the model's. A ``README.md`` model
card is written from the run record and ``model_card.json``: trainer, base
model, schemes and labels, split sizes, the held-out score and what it was
measured on, the bundle digest, and the Potato version. No item text,
annotation or annotator id is in it.

One commit per push. Every push is recorded in the run ledger
(``training_hub_pushes``) with the commit it made.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

__all__ = ["HubPushError", "push", "model_files", "model_card_markdown",
           "check_repo_id"]

#: Weights and the files that load them. Anything else stays here.
_WEIGHT_EXT = (".safetensors", ".bin", ".pt", ".pth", ".pkl", ".joblib",
               ".onnx", ".gguf")
#: Inside the saved model directory (``model/``): configs, tokenizer and
#: processor files, besides the weights.
_MODEL_DIR_EXT = _WEIGHT_EXT + (".json", ".txt", ".model", ".jinja",
                                ".tiktoken")
#: Small files a trainer writes at the top of ``artifacts/`` that a model
#: needs to load.
_TOP_FILES = {"model_card.json", "calibration.json"}
#: Training state, not the model.
_STATE_FILES = {"optimizer.pt", "scheduler.pt", "training_args.bin",
                "trainer_state.json", "scaler.pt"}
#: Present in every run's artifacts; a run with only these has no model.
NOT_A_MODEL = {"model_card.json", "calibration.json"}

_REPO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class HubPushError(ValueError):
    """Why a push was refused. ``status`` is the HTTP status for the route."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def check_repo_id(repo_id: str) -> str:
    repo_id = str(repo_id or "").strip()
    if not _REPO_ID.match(repo_id) or ".." in repo_id:
        raise HubPushError("repo_id must be <user or organisation>/<name>, "
                           "such as my-lab/sentiment-v1 (got %r)" % repo_id)
    return repo_id


def _uploadable(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    if name.startswith(".") or name.endswith(".partial") or name in _STATE_FILES \
            or name.startswith("rng_state"):
        return False
    if any(p.startswith("checkpoint-") or p.endswith("_data") or p in
           ("bundle", "yolo_run", "runs") for p in parts[:-1]):
        return False
    if len(parts) == 1:
        return name in _TOP_FILES or name.endswith(_WEIGHT_EXT)
    if parts[0] == "model":
        return name.endswith(_MODEL_DIR_EXT)
    return name.endswith(_WEIGHT_EXT)


def model_files(artifact_dir: str) -> List[str]:
    """Paths under *artifact_dir* that would be uploaded, relative and
    sorted. Empty when the run kept no model here.

    An allowlist: weights anywhere, the saved ``model/`` directory's configs
    and tokenizer, and ``model_card.json``/``calibration.json``. Never a
    symlink that leads out of *artifact_dir*, which would upload whatever it
    points at."""
    root_real = os.path.realpath(artifact_dir)
    out = []
    for root, dirs, files in os.walk(artifact_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            full = os.path.join(root, name)
            real = os.path.realpath(full)
            if not real.startswith(root_real + os.sep) or not os.path.isfile(real):
                continue
            rel = os.path.relpath(full, artifact_dir).replace(os.sep, "/")
            if _uploadable(rel):
                out.append(rel)
    return sorted(out)


def _is_local_path(value: str) -> bool:
    return os.path.isabs(value) or value.startswith((".", "~"))


def _public_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """``model_card.json`` without this server's paths."""
    def clean(value):
        if isinstance(value, str) and _is_local_path(value):
            return "(local: %s)" % os.path.basename(value.rstrip("/"))
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    return clean(card)


def _read_card(artifact_dir: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(artifact_dir, "model_card.json")) as fh:
            card = json.load(fh)
        return card if isinstance(card, dict) else {}
    except (OSError, ValueError):
        return {}


def _library(files: List[str], card: Dict[str, Any]) -> str:
    if card.get("lora") or "model/adapter_config.json" in files:
        return "peft"
    if any(f.endswith(("config.json", ".safetensors")) for f in files):
        return "transformers"
    if any(f.endswith((".pkl", ".joblib")) for f in files):
        return "sklearn"
    return ""


def model_card_markdown(run, card: Dict[str, Any], files: List[str],
                        licence: str = "", trainer_licence: str = "") -> str:
    """The README.md pushed with the model."""
    try:
        from potato import __version__ as potato_version
    except Exception:  # noqa: BLE001
        potato_version = "unknown"
    base = str(card.get("base_model") or card.get("model_name") or "")
    if _is_local_path(base):
        # A path on this server means nothing on the Hub, and says too much.
        base = "%s (a local model)" % os.path.basename(base.rstrip("/"))
    library = _library(files, card)
    front = ["---"]
    if library:
        front.append("library_name: %s" % library)
    # A Hub id, not a local path the Hub could not resolve.
    if base and "(a local model)" not in base:
        front.append("base_model: %s" % base)
    if licence:
        front.append("license: %s" % licence)
    front.append("tags:")
    for tag in ("potato-annotation", run.trainer):
        front.append("- %s" % tag)
    front.append("---")

    metrics = run.metrics or {}
    score, metric = metrics.get("heldout_score"), metrics.get("heldout_metric")
    labels = card.get("tags") or card.get("label_order") or card.get("labels")
    lines = front + ["", "# %s" % (run.model_version or run.run_id), "",
                     "Trained with [Potato](https://github.com/davidjurgens/potato) "
                     "%s from a project's own annotations." % potato_version, "",
                     "| | |", "|---|---|",
                     "| Trainer | `%s` |" % run.trainer]
    if base:
        lines.append("| Base model | `%s` |" % base)
    if card.get("lora"):
        lora = card["lora"]
        lines.append("| Adapter | LoRA r=%s, alpha=%s%s |" % (
            lora.get("r"), lora.get("alpha"),
            ", base weights %s" % lora["quantize"] if lora.get("quantize") else ""))
    dp = card.get("dp")
    if isinstance(dp, dict) and dp.get("epsilon_spent") is not None:
        target = dp.get("epsilon_target")
        delta = dp.get("delta")
        lines.append("| Differential privacy | DP-SGD, epsilon %s spent%s%s, covering "
                     "the train split |" % (
                         dp["epsilon_spent"],
                         " of %s" % target if target is not None else "",
                         ", delta %s" % delta if delta is not None else ""))
    lines.append("| Schemes | %s |" % ", ".join("`%s`" % s for s in run.schema_names))
    if run.kinds:
        lines.append("| Kinds | %s |" % ", ".join(run.kinds))
    if isinstance(labels, list) and labels:
        lines.append("| Labels | %s |" % ", ".join(str(l) for l in labels[:50]))
    lines.append("| Items | %d train, %d val, %d test |"
                 % (run.n_train, run.n_val, run.n_test))
    if isinstance(score, (int, float)):
        lines.append("| Held-out score | %.4f (%s) |" % (score, metric or "held out"))
    else:
        lines.append("| Held-out score | not measured |")
    lines.append("| Run | `%s`, bundle `%s` |" % (run.run_id, run.bundle_digest or "-"))
    if trainer_licence:
        lines.append("| Trainer code licence | %s |" % trainer_licence)
    lines += ["",
              "The held-out score is measured on items the model did not "
              "train on, against the project's own annotators. It says how "
              "the model did on that project's data, not on anyone else's.",
              "",
              "The training data is not included: no item text, annotation "
              "or annotator id is in this repository."]
    if not licence:
        lines += ["", "No licence was given for this repository. The weights "
                      "derive from the base model, whose licence applies."]
    return "\n".join(lines) + "\n"


def _http_status(exc: BaseException) -> int:
    response = getattr(exc, "response", None)
    try:
        return int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _is_not_found(exc: BaseException) -> bool:
    """The Hub said the repository does not exist: an error of the
    RepositoryNotFoundError type (by name, so a stand-in works), or a 404."""
    names = {cls.__name__ for cls in type(exc).__mro__}
    if "RepositoryNotFoundError" in names:
        return True
    return _http_status(exc) == 404


def _redact(text: str, token: str, artifact_dir: str) -> str:
    """An error message safe to show: no token, no server paths."""
    if token:
        text = text.replace(token, "***")
    for path in {artifact_dir, os.path.realpath(artifact_dir)}:
        if path:
            text = text.replace(path, "<artifacts>")
    return text[:500]


def _default_api(token: str):
    from huggingface_hub import HfApi
    return HfApi(token=token)


def push(config: Dict[str, Any], run, artifact_dir: str, repo_id: str,
         private: bool = True, token_env: str = "HF_TOKEN", licence: str = "",
         pushed_by: str = "", trainer_licence: str = "",
         api_factory: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """Upload a run's model. Returns ``{"repo_id", "revision", "url",
    "files"}``; raises :class:`HubPushError` with the reason otherwise."""
    from potato.training import store

    repo_id = check_repo_id(repo_id)
    if run.status != "success":
        raise HubPushError("Run %s is %s; only a successful run's model can be "
                           "pushed" % (run.run_id, run.status))
    files = model_files(artifact_dir)
    if not [f for f in files if f not in NOT_A_MODEL]:
        where = (" The model was left on %s." % run.artifact_uri
                 if run.artifact_uri else "")
        raise HubPushError("Run %s has no model files on this server to push."
                           "%s" % (run.run_id, where))
    token_env = str(token_env or "")
    if not _ENV_NAME.match(token_env) or not (
            "TOKEN" in token_env.upper() or token_env.upper().startswith("HF_")):
        # Any variable's value would be sent to the Hub as the token: PATH,
        # or a database password.
        raise HubPushError("token_env must name a token variable, such as "
                           "HF_TOKEN (its name must contain TOKEN or start "
                           "with HF_); got %r" % token_env)
    token = os.environ.get(token_env, "")
    if not token:
        raise HubPushError("%s is not set in the server's environment. Put a "
                           "Hugging Face write token in it and restart."
                           % token_env)
    if not token.startswith("hf_"):
        raise HubPushError("%s does not hold a Hugging Face token (they start "
                           "with hf_)" % token_env)
    if licence and (not isinstance(licence, str) or not re.match(
            r"^[a-z][a-z0-9.+-]{1,63}$", licence)):
        raise HubPushError("licence must be a Hub licence id such as "
                           "apache-2.0 or other (got %r)" % (licence,))

    api = (api_factory or _default_api)(token)
    try:
        info = api.repo_info(repo_id, repo_type="model")
    except Exception as exc:  # noqa: BLE001
        if not _is_not_found(exc):
            # Unless the Hub says the repository does not exist, its
            # visibility is unknown, and pushing could publish a model into
            # a public repository.
            status = _http_status(exc)
            raise HubPushError(
                "Could not check %s on the Hub (%s), so nothing was pushed: %s"
                % (repo_id, "HTTP %d" % status if status else type(exc).__name__,
                   _redact(str(exc), token, artifact_dir)),
                status=403 if status in (401, 403) else 502)
        info = None
    if info is not None and private and not getattr(info, "private", True):
        raise HubPushError("%s exists and is public. Pushing to it publishes "
                           "the model; untick Private to do that knowingly."
                           % repo_id, status=409)
    created = info is None
    if created:
        try:
            api.create_repo(repo_id, repo_type="model", private=bool(private),
                            exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            raise HubPushError("The Hub would not create %s: %s"
                               % (repo_id, _redact(str(exc), token, artifact_dir)),
                               status=_http_status(exc) in (401, 403) and 403 or 502)

    from huggingface_hub import CommitOperationAdd
    card = _read_card(artifact_dir)
    readme = model_card_markdown(run, card, files, licence=licence,
                                 trainer_licence=trainer_licence)
    operations = []
    for f in files:
        if f.lower() == "readme.md":
            continue
        source = os.path.join(artifact_dir, f)
        if f == "model_card.json":
            source = json.dumps(_public_card(card), indent=2).encode("utf-8")
        operations.append(CommitOperationAdd(path_in_repo=f,
                                             path_or_fileobj=source))
    operations.append(CommitOperationAdd(path_in_repo="README.md",
                                         path_or_fileobj=readme.encode("utf-8")))
    try:
        commit = api.create_commit(
            repo_id=repo_id, repo_type="model", operations=operations,
            commit_message="Potato training run %s (%s)" % (run.run_id, run.trainer))
    except Exception as exc:  # noqa: BLE001
        if created:
            # The empty repository this push made is no use to anyone.
            try:
                api.delete_repo(repo_id, repo_type="model")
            except Exception:  # noqa: BLE001
                pass
        raise HubPushError("The Hub refused the commit: %s"
                           % _redact(str(exc), token, artifact_dir), status=502)
    revision = str(getattr(commit, "oid", "") or "")
    url = str(getattr(commit, "commit_url", "") or
              "https://huggingface.co/%s" % repo_id)
    previous = [p for p in store.hub_pushes(config, run.run_id)
                if p["repo_id"] == repo_id]
    if not (previous and revision and previous[-1]["revision"] == revision):
        store.record_hub_push(config, run.run_id, repo_id, revision, url,
                              bool(private) if info is None else
                              bool(getattr(info, "private", private)), pushed_by)
    return {"repo_id": repo_id, "revision": revision, "url": url,
            "files": [f for f in files if f.lower() != "readme.md"] + ["README.md"]}
