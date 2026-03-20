"""
LangChain Callback Handler for Potato

Automatically sends LangChain agent traces to a Potato instance
for human evaluation and annotation.

Requires: pip install langchain-core>=0.1.0

Usage:
    from potato.integrations.langchain_callback import PotatoCallbackHandler

    handler = PotatoCallbackHandler(potato_url="http://localhost:8000")
    chain.invoke({"input": "..."}, config={"callbacks": [handler]})
"""

import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Union

import requests

logger = logging.getLogger(__name__)


def _safe_serialize(obj: Any) -> Any:
    """Convert an object to a JSON-safe representation."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    # Fall back to string representation
    try:
        return str(obj)
    except Exception:
        return "<unserializable>"


class PotatoCallbackHandler:
    """
    LangChain callback handler that sends completed traces to Potato.

    Collects run events (chain, LLM, tool starts/ends), tracks
    parent-child relationships, and POSTs the full trace to Potato's
    webhook endpoint when the root chain completes.

    The payload uses the LangSmith format expected by
    ``POST /api/traces/langsmith``.

    Args:
        potato_url: Base URL of the Potato server (e.g., ``http://localhost:8000``)
        api_key: API key for authenticating with Potato's webhook endpoint
        endpoint: Webhook path (default ``/api/traces/langsmith``)
        send_timeout: HTTP timeout in seconds for the POST request (default 10)
        metadata: Extra metadata dict attached to every trace
    """

    def __init__(
        self,
        potato_url: str,
        api_key: str = "",
        endpoint: str = "/api/traces/langsmith",
        send_timeout: int = 10,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.potato_url = potato_url.rstrip("/")
        self.api_key = api_key
        self.endpoint = endpoint
        self.send_timeout = send_timeout
        self.extra_metadata = metadata or {}

        # Run tracking — protected by lock for thread-safety
        self._lock = threading.Lock()
        self._runs: Dict[str, dict] = {}  # run_id -> run dict
        self._root_run_id: Optional[str] = None
        self._pending_sends: List[threading.Thread] = []

    # ------------------------------------------------------------------
    # LangChain BaseCallbackHandler interface
    # ------------------------------------------------------------------

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self._start_run(
            run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            run_type="chain",
            name=serialized.get("name", serialized.get("id", ["unknown"])[-1]
                                if isinstance(serialized.get("id"), list) else "chain"),
            inputs=inputs,
            tags=tags,
            metadata=metadata,
        )

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._end_run(str(run_id), outputs=outputs)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._end_run(str(run_id), error=error)

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self._start_run(
            run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            run_type="llm",
            name=serialized.get("name", "llm"),
            inputs={"prompts": prompts},
            tags=tags,
            metadata=metadata,
        )

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        output = {}
        if hasattr(response, "generations") and response.generations:
            texts = []
            for gen_list in response.generations:
                for gen in gen_list:
                    texts.append(gen.text if hasattr(gen, "text") else str(gen))
            output = {"text": "\n".join(texts)}
        self._end_run(str(run_id), outputs=output)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._end_run(str(run_id), error=error)

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self._start_run(
            run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            run_type="tool",
            name=serialized.get("name", "tool"),
            inputs={"input": input_str},
            tags=tags,
            metadata=metadata,
        )

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._end_run(str(run_id), outputs={"output": output})

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._end_run(str(run_id), error=error)

    # Retriever callbacks
    def on_retriever_start(
        self,
        serialized: Dict[str, Any],
        query: str,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self._start_run(
            run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            run_type="retriever",
            name=serialized.get("name", "retriever"),
            inputs={"query": query},
            tags=tags,
            metadata=metadata,
        )

    def on_retriever_end(
        self,
        documents: Any,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        output = {"documents": _safe_serialize(documents)}
        self._end_run(str(run_id), outputs=output)

    # Text callbacks (no-ops — captured by LLM callbacks)
    def on_text(self, text: str, **kwargs: Any) -> None:
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start_run(
        self,
        run_id: str,
        parent_run_id: Optional[str],
        run_type: str,
        name: str,
        inputs: Any,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        run = {
            "id": run_id,
            "parent_run_id": parent_run_id,
            "run_type": run_type,
            "name": name,
            "inputs": _safe_serialize(inputs),
            "outputs": {},
            "status": "running",
            "start_time": time.time(),
            "end_time": None,
            "tags": tags or [],
            "metadata": metadata or {},
        }

        with self._lock:
            self._runs[run_id] = run
            if parent_run_id is None:
                self._root_run_id = run_id

    def _end_run(
        self,
        run_id: str,
        outputs: Optional[Dict[str, Any]] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return

            run["end_time"] = time.time()
            run["latency"] = run["end_time"] - run["start_time"]

            if error:
                run["status"] = "error"
                run["outputs"] = {"error": str(error)}
            else:
                run["status"] = "completed"
                run["outputs"] = _safe_serialize(outputs or {})

            # If this is the root run, send the trace
            is_root = run_id == self._root_run_id

        if is_root:
            self._send_trace()

    def _build_payload(self) -> dict:
        """Build a LangSmith-format payload from collected runs."""
        with self._lock:
            runs = list(self._runs.values())
            root_id = self._root_run_id

        # Find the root run for metadata
        root_run = None
        for r in runs:
            if r["id"] == root_id:
                root_run = r
                break

        payload = {
            "runs": [
                {
                    "id": r["id"],
                    "parent_run_id": r["parent_run_id"],
                    "run_type": r["run_type"],
                    "name": r["name"],
                    "inputs": r["inputs"],
                    "outputs": r["outputs"],
                    "status": r["status"],
                    "latency": r.get("latency"),
                    "tags": r.get("tags", []),
                }
                for r in runs
            ],
        }

        if root_run:
            payload["project_name"] = root_run.get("name", "langchain")

        return payload

    def _send_trace(self) -> None:
        """POST the trace to Potato in a background thread."""
        payload = self._build_payload()

        def _do_send():
            try:
                url = f"{self.potato_url}{self.endpoint}"
                headers = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                resp = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.send_timeout,
                )
                if resp.status_code < 300:
                    logger.info("Trace sent to Potato: %s", resp.json())
                else:
                    logger.warning(
                        "Potato returned %s: %s", resp.status_code, resp.text
                    )
            except Exception as e:
                logger.error("Failed to send trace to Potato: %s", e)

        thread = threading.Thread(target=_do_send, daemon=True)
        with self._lock:
            self._pending_sends.append(thread)
        thread.start()

    def flush(self, timeout: float = 30.0) -> None:
        """Block until all pending sends complete (or timeout)."""
        with self._lock:
            threads = list(self._pending_sends)
        for t in threads:
            t.join(timeout=timeout)
        with self._lock:
            self._pending_sends = [t for t in self._pending_sends if t.is_alive()]

    def reset(self) -> None:
        """Clear all collected runs (for reuse across multiple chains)."""
        with self._lock:
            self._runs.clear()
            self._root_run_id = None
