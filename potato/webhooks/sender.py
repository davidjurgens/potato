"""
Webhook Delivery Queue

Daemon thread + queue for non-blocking webhook dispatch with SQLite-backed
retry store. Annotation requests are never blocked by webhook delivery.
"""

import json
import logging
import os
import queue
import sqlite3
import threading
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from .signing import build_headers

logger = logging.getLogger(__name__)

# Retry schedule in seconds (with jitter added at delivery time)
RETRY_SCHEDULE = [0, 5, 30, 120, 600, 3600]
MAX_RETRIES = len(RETRY_SCHEDULE) - 1

# Queue size limit — if full, events are dropped (never block annotations)
MAX_QUEUE_SIZE = 10000


class WebhookDeliveryQueue:
    """Background delivery queue with retry support.

    Uses a daemon thread and stdlib queue.Queue for non-blocking dispatch.
    Failed deliveries are stored in SQLite for retry.
    """

    def __init__(self, output_dir=None):
        """Initialize the delivery queue.

        Args:
            output_dir: Directory for the retry SQLite database.
                        If None, retries are in-memory only.
        """
        self._queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self._running = False
        self._thread = None
        self._db_path = None
        self._db_lock = threading.Lock()

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            self._db_path = os.path.join(output_dir, "webhook_retries.db")
            self._init_db()

    def _init_db(self):
        """Create the retry store table if it doesn't exist."""
        with self._db_lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS webhook_retries (
                        id TEXT PRIMARY KEY,
                        url TEXT NOT NULL,
                        secret TEXT DEFAULT '',
                        payload TEXT NOT NULL,
                        attempt INTEGER DEFAULT 0,
                        next_retry_at REAL NOT NULL,
                        created_at REAL NOT NULL,
                        last_error TEXT DEFAULT ''
                    )
                """)
                conn.commit()
            finally:
                conn.close()

    def start(self):
        """Start the background delivery thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="webhook-delivery",
            daemon=True,
        )
        self._thread.start()
        logger.debug("Webhook delivery thread started")

    def stop(self):
        """Stop the delivery thread gracefully."""
        self._running = False
        # Push sentinel to unblock the queue
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.debug("Webhook delivery thread stopped")

    def enqueue(self, url, secret, payload_bytes, webhook_id=None):
        """Add a delivery to the queue (non-blocking).

        Args:
            url: Endpoint URL.
            secret: HMAC secret for signing.
            payload_bytes: JSON payload as bytes.
            webhook_id: Optional delivery ID.

        Returns:
            True if enqueued, False if queue was full (event dropped).
        """
        delivery = {
            "id": webhook_id or f"msg_{uuid.uuid4().hex[:24]}",
            "url": url,
            "secret": secret,
            "payload_bytes": payload_bytes,
            "attempt": 0,
        }
        try:
            self._queue.put_nowait(delivery)
            return True
        except queue.Full:
            logger.warning("Webhook queue full, dropping event for %s", url)
            return False

    def _worker_loop(self):
        """Main loop for the delivery thread."""
        while self._running:
            # Process retries first
            self._process_retries()

            # Process new deliveries
            try:
                delivery = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if delivery is None:  # Sentinel for shutdown
                break

            self._deliver(delivery)

    def _deliver(self, delivery):
        """Attempt to deliver a webhook.

        Args:
            delivery: Dict with id, url, secret, payload_bytes, attempt.
        """
        url = delivery["url"]
        secret = delivery.get("secret", "")
        payload_bytes = delivery["payload_bytes"]
        attempt = delivery.get("attempt", 0)
        webhook_id = delivery["id"]

        headers = build_headers(secret, payload_bytes, webhook_id=webhook_id)

        try:
            req = Request(
                url,
                data=payload_bytes,
                headers=headers,
                method="POST",
            )
            resp = urlopen(req, timeout=10)
            status = resp.getcode()
            resp.close()

            if status and 200 <= status < 300:
                logger.debug("Webhook delivered: %s -> %s (attempt %d)",
                             webhook_id, url, attempt)
                # Remove from retry store if it was there
                self._remove_retry(webhook_id)
            else:
                self._handle_failure(delivery, f"HTTP {status}")

        except HTTPError as e:
            self._handle_failure(delivery, f"HTTP {e.code}: {e.reason}")
        except (URLError, OSError) as e:
            self._handle_failure(delivery, str(e))
        except Exception as e:
            self._handle_failure(delivery, str(e))

    def _handle_failure(self, delivery, error_msg):
        """Handle a failed delivery attempt."""
        attempt = delivery.get("attempt", 0)
        url = delivery["url"]
        webhook_id = delivery["id"]

        if attempt >= MAX_RETRIES:
            logger.error("Webhook permanently failed after %d attempts: %s -> %s: %s",
                         attempt + 1, webhook_id, url, error_msg)
            self._remove_retry(webhook_id)
            return

        # Schedule retry with jitter
        next_attempt = attempt + 1
        delay = RETRY_SCHEDULE[min(next_attempt, len(RETRY_SCHEDULE) - 1)]
        jitter = delay * 0.1 * (hash(webhook_id) % 10) / 10  # Deterministic jitter
        next_retry_at = time.time() + delay + jitter

        logger.warning("Webhook delivery failed (attempt %d/%d): %s -> %s: %s. "
                       "Retry in %.0fs",
                       next_attempt, MAX_RETRIES + 1, webhook_id, url,
                       error_msg, delay + jitter)

        self._store_retry(delivery, next_attempt, next_retry_at, error_msg)

    def _store_retry(self, delivery, attempt, next_retry_at, error_msg):
        """Store a failed delivery for retry."""
        if not self._db_path:
            return

        with self._db_lock:
            try:
                conn = sqlite3.connect(self._db_path)
                conn.execute(
                    """INSERT OR REPLACE INTO webhook_retries
                       (id, url, secret, payload, attempt, next_retry_at,
                        created_at, last_error)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        delivery["id"],
                        delivery["url"],
                        delivery.get("secret", ""),
                        delivery["payload_bytes"].decode("utf-8", errors="replace"),
                        attempt,
                        next_retry_at,
                        time.time(),
                        error_msg,
                    ),
                )
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                logger.error("Failed to store webhook retry: %s", e)

    def _remove_retry(self, webhook_id):
        """Remove a delivery from the retry store."""
        if not self._db_path:
            return
        with self._db_lock:
            try:
                conn = sqlite3.connect(self._db_path)
                conn.execute("DELETE FROM webhook_retries WHERE id = ?",
                             (webhook_id,))
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                logger.error("Failed to remove webhook retry: %s", e)

    def _process_retries(self):
        """Check SQLite for deliveries due for retry."""
        if not self._db_path:
            return

        now = time.time()
        with self._db_lock:
            try:
                conn = sqlite3.connect(self._db_path)
                cursor = conn.execute(
                    """SELECT id, url, secret, payload, attempt
                       FROM webhook_retries
                       WHERE next_retry_at <= ?
                       LIMIT 10""",
                    (now,),
                )
                rows = cursor.fetchall()
                # Delete fetched rows so they're not re-processed
                for row in rows:
                    conn.execute("DELETE FROM webhook_retries WHERE id = ?",
                                 (row[0],))
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                logger.error("Failed to process webhook retries: %s", e)
                return

        for row in rows:
            delivery = {
                "id": row[0],
                "url": row[1],
                "secret": row[2],
                "payload_bytes": row[3].encode("utf-8"),
                "attempt": row[4],
            }
            self._deliver(delivery)

    def get_retry_count(self):
        """Get the number of pending retries (for admin API)."""
        if not self._db_path:
            return 0
        with self._db_lock:
            try:
                conn = sqlite3.connect(self._db_path)
                cursor = conn.execute("SELECT COUNT(*) FROM webhook_retries")
                count = cursor.fetchone()[0]
                conn.close()
                return count
            except sqlite3.Error:
                return 0
