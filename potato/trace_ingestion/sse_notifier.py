"""
SSE Notifier for Trace Ingestion

Sends Server-Sent Events to connected annotators when new traces
are ingested, allowing real-time updates without page refresh.
"""

import json
import logging
import threading
from queue import Queue, Empty
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class SSENotifier:
    """
    Manages SSE connections for trace ingestion notifications.

    Annotators connect to the SSE endpoint and receive events
    when new traces are added to the annotation queue.
    """

    def __init__(self):
        self._clients: List[Queue] = []
        self._lock = threading.Lock()

    def add_client(self) -> Queue:
        """Register a new SSE client and return its event queue."""
        q = Queue()
        with self._lock:
            self._clients.append(q)
        logger.debug(f"SSE client connected ({len(self._clients)} total)")
        return q

    def remove_client(self, q: Queue):
        """Remove an SSE client."""
        with self._lock:
            self._clients = [c for c in self._clients if c is not q]
        logger.debug(f"SSE client disconnected ({len(self._clients)} total)")

    def notify_new_trace(self, trace_id: str, task_description: str, source: str):
        """Notify all connected clients about a new trace."""
        event = {
            "type": "new_trace",
            "trace_id": trace_id,
            "task_description": task_description,
            "source": source,
            "message": f"New trace available: {task_description[:80]}",
        }
        self._broadcast(event)

    def notify_queue_update(self, total_items: int, pending_items: int):
        """Notify clients about queue status changes."""
        event = {
            "type": "queue_update",
            "total_items": total_items,
            "pending_items": pending_items,
        }
        self._broadcast(event)

    def _broadcast(self, event: Dict[str, Any]):
        """Send an event to all connected clients."""
        with self._lock:
            dead_clients = []
            for q in self._clients:
                try:
                    q.put_nowait(event)
                except Exception:
                    dead_clients.append(q)

            # Clean up dead clients
            for dead in dead_clients:
                self._clients = [c for c in self._clients if c is not dead]

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def generate_sse_stream(self, client_queue: Queue):
        """Generator that yields SSE formatted events from a client queue."""
        try:
            # Send initial connection event
            yield _sse_format("connected", {"message": "Trace ingestion stream connected"})

            while True:
                try:
                    event = client_queue.get(timeout=30)
                    event_type = event.get("type", "message")
                    yield _sse_format(event_type, event)
                except Empty:
                    yield ": keepalive\n\n"
        finally:
            self.remove_client(client_queue)


def _sse_format(event_type: str, data: dict) -> str:
    """Format an SSE message."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
