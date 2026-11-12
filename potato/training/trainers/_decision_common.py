"""What the decision-model trainers share: the scheme as a question, the
annotators' answer as one of its options, and the endpoint config.

Decision models (hosted Jev, OpenJev, laya-serve, in-process Laya) answer
typed questions about a ``state``. A Potato scheme becomes one question
through ``potato.ai.decision_endpoint.questions_for_scheme``, the mapping the
AI assistant already uses, so a model trained or calibrated here is asked the
same question at annotation time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: Decision endpoint types in ``ai_support.endpoint_type``.
DECISION_ENDPOINTS = ("systemone", "laya")

#: Environment variable that carries the endpoint's API key to a local run.
API_KEY_ENV = "POTATO_DECISION_API_KEY"

#: ai_config keys that are secrets and never go into a spec file. Matched by
#: name, not substring: ``state_key`` is an option, not a secret.
_SECRET_KEYS = ("api_key", "token", "secret", "password", "authorization",
                "access_token", "bearer")


def schemes_for(config: Dict[str, Any], schema_names: Sequence[str]
                ) -> Dict[str, Dict[str, Any]]:
    """The named schemes' full config, for the run spec."""
    wanted = set(schema_names)
    return {s["name"]: s for s in config.get("annotation_schemes", []) or []
            if isinstance(s, dict) and s.get("name") in wanted}


def _public(ai_config: Dict[str, Any]) -> Dict[str, Any]:
    def secret(key: str) -> bool:
        key = key.lower()
        return key in _SECRET_KEYS or key.endswith(
            ("_api_key", "_token", "_secret", "_password"))

    return {k: v for k, v in ai_config.items() if not secret(str(k))}


def decision_endpoints(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every decision model the project configures, in the shape
    ``AIEndpointFactory`` takes, with its API key apart.

    Decision models are not ``ai_support`` endpoints (they cannot write
    text, and config validation refuses them there). They are
    ``labeling_engine`` sources with ``kind: decision`` and entries of
    ``solo_mode.labeling_models``. Each entry is ``{"source", "endpoint_type",
    "ai_config", "api_key", "prompt"}``; ``source`` is the engine source's
    id, or ``solo_mode`` for the first decision labeling model.
    """
    found: List[Dict[str, Any]] = []
    engine = config.get("labeling_engine") or {}
    for raw in engine.get("sources") or []:
        if not isinstance(raw, dict) or raw.get("kind") != "decision" \
                or raw.get("endpoint_type") not in DECISION_ENDPOINTS:
            continue
        ai_config: Dict[str, Any] = {"model": raw.get("model") or ""}
        for key in ("base_url", "timeout"):
            if raw.get(key) is not None:
                ai_config[key] = raw[key]
        ai_config.update(raw.get("options") or {})
        found.append({"source": str(raw.get("id") or "decision"),
                      "endpoint_type": raw["endpoint_type"],
                      "ai_config": ai_config,
                      "api_key": str(raw.get("api_key") or ""),
                      "prompt": raw.get("prompt")})
    solo = config.get("solo_mode") or {}
    for model in solo.get("labeling_models") or []:
        if not isinstance(model, dict) \
                or model.get("endpoint_type") not in DECISION_ENDPOINTS:
            continue
        from potato.solo_mode.config import ENDPOINT_OPTION_KEYS
        ai_config = {"model": model.get("model") or ""}
        base_url = model.get("base_url") or model.get("endpoint_url")
        if base_url:
            ai_config["base_url"] = base_url
        ai_config.update({k: model[k] for k in ENDPOINT_OPTION_KEYS
                          if k in model})
        found.append({"source": "solo_mode",
                      "endpoint_type": model["endpoint_type"],
                      "ai_config": ai_config,
                      "api_key": str(model.get("api_key") or ""),
                      "prompt": None})
        break
    return found


def pick_endpoint(config: Dict[str, Any], source: Optional[str]
                  ) -> Optional[Dict[str, Any]]:
    """The decision model named by *source*, or the first one."""
    endpoints = decision_endpoints(config)
    if not source or source == "auto":
        return endpoints[0] if endpoints else None
    return next((e for e in endpoints if e["source"] == source), None)


def spec_endpoint(entry: Dict[str, Any]) -> Dict[str, Any]:
    """What goes into a run's spec: everything but the secret."""
    return {"source": entry["source"], "endpoint_type": entry["endpoint_type"],
            "ai_config": _public(entry["ai_config"]), "prompt": entry.get("prompt")}


def question_for(scheme: Dict[str, Any], instructions: str = ""):
    """The one DecisionQuestion a scheme becomes."""
    from potato.ai.decision_endpoint import questions_for_scheme
    return questions_for_scheme(scheme, instructions)[0]


def question_problem(params: Dict[str, Any], schema_name: str) -> Optional[str]:
    """Why the scheme cannot be asked as a decision question, or None.

    A slider is one only up to MAX_SLIDER_STEPS positions; a 0-100 scale is
    refused here, before any request, rather than on the first item.
    """
    scheme = (params.get("_schemes") or {}).get(schema_name)
    if not scheme:
        return "The run has no config for scheme %r." % schema_name
    try:
        question_for(scheme, "")
    except ValueError as exc:
        return str(exc)
    return None


def option_for(target: Any, options: List[str]) -> Optional[str]:
    """The option an annotated target names, or None.

    A likert or slider target reaches the bundle as a number (3.0), while
    the question's options are strings ("3"); match by value then.
    """
    if target is None:
        return None
    text = str(target)
    if text in options:
        return text
    try:
        number = float(target)
    except (TypeError, ValueError):
        return None
    for option in options:
        try:
            if float(option) == number:
                return option
        except ValueError:
            continue
    return None
