"""
HTTP client for the ``/v1/systemone`` decision API.

One client serves every backend that speaks the protocol: hosted Jev
(``base_url: https://api.typesafe.ai``), an OpenJev shim, or ``laya-serve``.
See decision_endpoint.py for the confirmed wire format.

ai_config keys:
    base_url   required, the server root (a trailing ``/v1`` is accepted)
    model      default 'jev-latest'
    api_key    optional bearer token
    timeout    seconds, default 30
    max_options  per-question option cap; default 255 (Jev). Set 52 for OpenJev
               if its shim's multi-pass split is not wanted.
    state_key  the state is sent as ``{state_key: text}``; default 'text'.
               An empty value sends the bare string.
"""

import logging
from typing import Any, Dict, List

import requests

from .ai_endpoint import AIEndpointConfigError, AIEndpointRequestError
from .decision_endpoint import (
    DecisionModelEndpoint, DecisionQuestion, build_systemone_questions,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "jev-latest"

# Known per-backend caps, used when max_options is not configured.
# Jev: spice.ai/learn/typesafe-jev ("up to 255 options"). OpenJev: HF model
# card ("52 options per question in a single pass").
KNOWN_MAX_OPTIONS = {"openjev": 52}


class SystemOneEndpoint(DecisionModelEndpoint):
    """Decision model reached over HTTP at ``{base_url}/v1/systemone``."""

    def _initialize_client(self) -> None:
        raw_base = self.ai_config.get("base_url")
        if not raw_base or not isinstance(raw_base, str):
            raise AIEndpointConfigError(
                "systemone endpoint needs ai_config.base_url, e.g. https://api.typesafe.ai "
                "or http://localhost:8000 for laya-serve")
        self.base_url = raw_base.rstrip("/")
        # The server root is wanted; the route is added per call. A URL
        # copied with the route on (".../v1/systemone") would otherwise
        # become ".../v1/systemone/v1/systemone".
        for suffix in ("/v1/systemone", "/v1"):
            if self.base_url.endswith(suffix):
                self.base_url = self.base_url[: -len(suffix)]
                break
        self.api_key = self.ai_config.get("api_key") or ""
        self.timeout = self.ai_config.get("timeout", 30)
        self.state_key = self.ai_config.get("state_key", "text")
        configured = self.ai_config.get("max_options")
        if configured is not None:
            self.max_options = int(configured)
        else:
            self.max_options = KNOWN_MAX_OPTIONS.get(str(self.model).lower(), 255)

    def _get_default_model(self) -> str:
        return DEFAULT_MODEL

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _state_payload(self, state: str) -> Any:
        return {self.state_key: state} if self.state_key else state

    def _decide_raw(self, state: str, questions: List[DecisionQuestion]) -> Dict[str, Any]:
        body = {
            "model": self.model,
            "state": self._state_payload(state),
            "questions": build_systemone_questions(questions),
        }
        url = f"{self.base_url}/v1/systemone"
        try:
            resp = requests.post(url, json=body, headers=self._headers(), timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise AIEndpointRequestError(
                f"systemone request to {url} timed out after {self.timeout}s")
        except requests.exceptions.RequestException as e:
            raise AIEndpointRequestError(f"systemone request to {url} failed: {e}")
        if resp.status_code != 200:
            raise AIEndpointRequestError(
                f"systemone request to {url} returned HTTP {resp.status_code}: {resp.text[:500]}")
        try:
            return resp.json()
        except ValueError:
            raise AIEndpointRequestError(
                f"systemone response from {url} is not JSON: {resp.text[:300]}")

    def health_check(self) -> bool:
        """GET /health (laya-serve has one); otherwise ask one noul question."""
        try:
            resp = requests.get(f"{self.base_url}/health", headers=self._headers(), timeout=5)
            if resp.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        try:
            self.decide("ping", [DecisionQuestion(id="ok", kind="noul", text="Is this a test?")])
            return True
        except Exception as e:
            logger.error(f"systemone health check failed: {e}")
            return False
