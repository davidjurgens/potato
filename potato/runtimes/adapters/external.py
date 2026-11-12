"""
``type: external``: send the participant to a task on another server (oTree,
Empirica, a hosted jsPsych or Gorilla study, a Qualtrics survey) and take
them back when it ends.

.. code-block:: yaml

    phases:
      order: [consent, game, annotation]
      game:
        type: external
        url: "https://otree.example.org/room/study1/?participant_label={participant}"
        return_params: [completion_code, payoff]
        description: "The next part is a short game with other participants."
        button_text: "Start the game"

The page shows ``description`` and a button to ``url``, where these are
filled in (URL-encoded):

=====================  =====================================================
``{participant}``      the participant's Potato user id
``{return_url}``       the address that brings them back (give it to the
                       other system as its completion redirect)
``{run_id}``           this attempt's id, also part of ``{return_url}``
``{condition.<f>}``    their level of a between-subjects factor
=====================  =====================================================

Coming back to ``{return_url}`` (``/runtime/<page>/return?run=<run_id>``,
plus any query parameters) marks the page done and moves the participant on.
The return must arrive in the same browser session and name the
participant's current run; anything else is refused. The query parameters
listed in ``return_params`` are stored with the run and become answers
``<page>_<param>`` that later page rules can test; ``<page>_returned`` is
``yes``.

The participant can see the return address and type one by hand, so the
parameters are self-reported unless they are signed. With ``return_secret``
set, the return must carry ``sig``: the hex HMAC-SHA256, keyed with the
secret, of the run id followed by ``&<param>=<value>`` for each returned
parameter in ``return_params``, sorted by name (:func:`return_signature`).
A missing or wrong ``sig`` is refused with 409 and the page is not done.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote, urlparse

from potato.runtimes.base import Asset, RuntimeAdapter

_PARAM = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_PLACEHOLDERS = re.compile(r"\{(participant|return_url|run_id|condition\.[A-Za-z0-9_]+)\}")
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


def _allowed_url(url: Any) -> bool:
    """https anywhere; plain http only to this machine."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        return False
    if parsed.scheme == "https":
        return bool(host)
    return parsed.scheme == "http" and host in _LOOPBACK


def return_signature(secret: str, run_id: str, params: Mapping[str, str]) -> str:
    """The ``sig`` a signed return carries: HMAC-SHA256 (hex) keyed with
    ``secret`` over ``run_id`` + ``&name=value`` per parameter, by name.

    Names and values are percent-encoded (``quote(x, safe="")``), so a value
    holding ``&b=2`` cannot sign for a separate parameter ``b``."""
    message = str(run_id) + "".join(
        f"&{quote(str(k), safe='')}={quote(str(params[k]), safe='')}" for k in sorted(params))
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


class ExternalAdapter(RuntimeAdapter):
    kind = "external"
    label = "external task"
    main_key = None
    extra_keys = frozenset({"url", "return_params", "description", "button_text", "new_tab",
                            "return_secret"})
    boot_script = "runtime-boot-external.js"

    def validate(self, where: str, entry: Dict[str, Any]) -> None:
        from potato.server_utils.config_module import ConfigValidationError
        url = entry.get("url")
        if not _allowed_url(url):
            raise ConfigValidationError(
                f"{where}.url must be an https:// address (http only for localhost)")
        unknown = [m.group(0) for m in re.finditer(r"\{[^}]*\}", url)
                   if not _PLACEHOLDERS.fullmatch(m.group(0))]
        if unknown:
            raise ConfigValidationError(
                f"{where}.url has unknown placeholder(s) {', '.join(unknown)}; use "
                "{participant}, {return_url}, {run_id} or {condition.<factor>}")
        params = entry.get("return_params", [])
        if not isinstance(params, list) or not all(isinstance(p, str) and _PARAM.match(p) for p in params):
            raise ConfigValidationError(
                f"{where}.return_params must be a list of query parameter names")
        for key in ("description", "button_text"):
            if key in entry and not isinstance(entry[key], str):
                raise ConfigValidationError(f"{where}.{key} must be text")
        if "new_tab" in entry and not isinstance(entry["new_tab"], bool):
            raise ConfigValidationError(f"{where}.new_tab must be true or false")
        secret = entry.get("return_secret")
        if "return_secret" in entry and not (isinstance(secret, str) and len(secret) >= 16):
            raise ConfigValidationError(
                f"{where}.return_secret must be a private string of at least 16 characters")

    def spec_extras(self, entry):
        return {"url": entry["url"], "return_params": list(entry.get("return_params") or []),
                "description": entry.get("description", ""),
                "button_text": entry.get("button_text") or "Continue to the task",
                "new_tab": bool(entry.get("new_tab", False)),
                "return_secret": entry.get("return_secret") or ""}

    def assets(self, spec):
        return [Asset("static", "runtime-headphone.css")], []

    def client_extras(self, spec):
        return {"description": spec["description"], "button_text": spec["button_text"],
                "new_tab": spec["new_tab"]}

    def link(self, spec, participant: str, run_id: str, return_url: str,
             conditions: Dict[str, Any]) -> str:
        from urllib.parse import quote

        def repl(m):
            key = m.group(1)
            if key == "participant":
                value = participant
            elif key == "return_url":
                value = return_url
            elif key == "run_id":
                value = run_id
            else:
                value = (conditions or {}).get(key.split(".", 1)[1], "")
            return quote(str(value), safe="")
        return _PLACEHOLDERS.sub(repl, spec["url"])

    def return_problem(self, spec, run_id: str, args: Mapping[str, str]) -> Optional[str]:
        """Why a return cannot be accepted, or None. Only a signed page checks."""
        secret = spec.get("return_secret")
        if not secret:
            return None
        params = {p: args[p] for p in spec.get("return_params") or [] if p in args}
        sig = str(args.get("sig") or "")
        if not sig:
            return "the return is not signed"
        if not hmac.compare_digest(sig.lower(), return_signature(secret, run_id, params)):
            return "the return's signature does not match"
        return None

    def answer_schemes(self, name: str, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        out = [{"name": f"{name}_returned", "annotation_type": "radio", "labels": ["yes"],
                "description": "Came back from the external task"}]
        out += [{"name": f"{name}_{p}", "annotation_type": "text",
                 "description": f"External task: {p}"} for p in entry.get("return_params") or []]
        return out

    def summarize(self, spec, trials):
        page = spec.get("page_name", "")
        answers = {f"{page}_returned": "yes"}
        params = (trials[-1] if trials else {}).get("params") or {}
        for p in spec.get("return_params") or []:
            if p in params:
                answers[f"{page}_{p}"] = params[p]
        return answers


ADAPTER = ExternalAdapter()
