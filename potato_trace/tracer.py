"""
``@traceable`` decorator and ``trace()`` context manager.

Nested traced calls form a run tree via contextvars: the outermost traced call
is the root and owns a *collector*; inner calls attach to it. When the root
returns, the whole tree is submitted to Potato in one webhook call.

    import potato_trace
    potato_trace.configure(potato_url="http://localhost:8000")

    @potato_trace.traceable(run_type="tool")
    def search(q): ...

    @potato_trace.traceable
    def agent(task):
        return search(task)

Works for sync and async functions. Latency is captured automatically; token
usage / custom outputs can be attached via ``set_outputs`` / ``add_metadata``.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import time
from typing import Any, Callable, Dict, List, Optional

from potato_trace.run_tree import Run, new_run_id

# Active run id (parent for the next nested run) and the collector for the
# current root trace. Both are contextvars so concurrent traces don't collide.
_current_run: contextvars.ContextVar = contextvars.ContextVar("potato_trace_current_run", default=None)
_collector: contextvars.ContextVar = contextvars.ContextVar("potato_trace_collector", default=None)

# Lazily-bound default client (set by configure()).
_default_client = None


def _get_client():
    global _default_client
    if _default_client is None:
        from potato_trace.client import PotatoTraceClient
        _default_client = PotatoTraceClient()
    return _default_client


def configure(**kwargs) -> None:
    """Set the global default client (potato_url, api_key, project_name, …)."""
    global _default_client
    from potato_trace.client import PotatoTraceClient
    _default_client = PotatoTraceClient(**kwargs)


def flush(timeout: float = 30.0) -> None:
    _get_client().flush(timeout=timeout)


def current_run() -> Optional[Run]:
    """The Run currently executing (or None outside any trace)."""
    collector = _collector.get()
    rid = _current_run.get()
    if collector is None or rid is None:
        return None
    return collector["runs"].get(rid)


def set_outputs(outputs: Dict[str, Any]) -> None:
    """Attach/merge outputs on the current run (e.g. an LLM completion)."""
    run = current_run()
    if run is not None:
        run.outputs.update(outputs)


def add_metadata(**kwargs) -> None:
    """Attach extra metadata on the current run (e.g. token usage)."""
    run = current_run()
    if run is not None:
        run.extra.update(kwargs)


class _Span:
    """Internal: opens a run, restores context + submits the tree on close."""

    def __init__(self, name: str, run_type: str, inputs: Optional[Dict[str, Any]],
                 tags: Optional[List[str]], project_name: str):
        self.name = name
        self.run_type = run_type
        self.inputs = inputs or {}
        self.tags = tags or []
        self.project_name = project_name
        self._tok_run = None
        self._tok_coll = None
        self._is_root = False
        self._start = 0.0
        self.run: Optional[Run] = None

    def __enter__(self) -> Run:
        collector = _collector.get()
        self._is_root = collector is None
        if self._is_root:
            collector = {"runs": {}, "root_id": None}
            self._tok_coll = _collector.set(collector)
        run = Run(name=self.name, run_type=self.run_type, id=new_run_id(),
                  parent_run_id=_current_run.get(), inputs=self.inputs, tags=self.tags)
        collector["runs"][run.id] = run
        if self._is_root:
            collector["root_id"] = run.id
        self._tok_run = _current_run.set(run.id)
        self._start = time.time()
        self.run = run
        return run

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        run = self.run
        run.latency = time.time() - self._start
        if exc_type is not None:
            run.status = "error"
            run.error = str(exc_val)
        elif run.status == "running":
            run.status = "success"
        _current_run.reset(self._tok_run)
        if self._is_root:
            collector = _collector.get()
            _collector.reset(self._tok_coll)
            _get_client().submit(list(collector["runs"].values()),
                                 collector["root_id"], self.project_name)
        return False  # never suppress exceptions


def trace(name: str, run_type: str = "chain", inputs: Optional[Dict[str, Any]] = None,
          tags: Optional[List[str]] = None, project_name: str = "") -> _Span:
    """Context manager form: ``with trace("step"): ...``."""
    return _Span(name, run_type, inputs, tags, project_name)


def _capture_inputs(func, args, kwargs) -> Dict[str, Any]:
    # A representative string under "input" so the webhook's langsmith
    # normalizer extracts something meaningful, plus the raw args.
    parts = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
    return {"input": ", ".join(parts), "args": list(args), "kwargs": dict(kwargs)}


def traceable(func: Optional[Callable] = None, *, run_type: str = "chain",
              name: Optional[str] = None, tags: Optional[List[str]] = None,
              project_name: str = "") -> Callable:
    """Decorator. Usable bare (``@traceable``) or parameterized
    (``@traceable(run_type="tool")``)."""

    def decorator(fn: Callable) -> Callable:
        run_name = name or getattr(fn, "__name__", "traced")

        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                with trace(run_name, run_type, _capture_inputs(fn, args, kwargs),
                           tags, project_name) as run:
                    result = await fn(*args, **kwargs)
                    if not run.outputs:
                        run.outputs = {"output": result}
                    return result
            return awrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with trace(run_name, run_type, _capture_inputs(fn, args, kwargs),
                       tags, project_name) as run:
                result = fn(*args, **kwargs)
                if not run.outputs:
                    run.outputs = {"output": result}
                return result
        return wrapper

    # Support both @traceable and @traceable(...)
    if func is not None and callable(func):
        return decorator(func)
    return decorator
