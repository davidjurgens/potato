"""
Waveform Service

Handles generation and caching of audio waveform data for the audio annotation feature.
Uses BBC's audiowaveform tool to generate pre-computed waveform data files.

Features:
- LRU cache for waveform files
- Background look-ahead pre-computation for upcoming instances
- Support for both local files and URLs
- Graceful fallback if audiowaveform not installed
"""

import os
import logging
import hashlib
import subprocess
import shutil
import tempfile
import threading
import time
from typing import Optional, List, Dict
from collections import OrderedDict
from urllib.parse import urlparse
from pathlib import Path

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)


class WaveformService:
    """
    Service for generating and caching audio waveform data.

    Uses BBC's audiowaveform tool to generate pre-computed waveform data
    that can be efficiently rendered by Peaks.js on the frontend.
    """

    # Default configuration
    DEFAULT_LOOK_AHEAD = 5
    DEFAULT_CACHE_MAX_SIZE = 100
    DEFAULT_CLIENT_FALLBACK_MAX_DURATION = 1800  # 30 minutes in seconds

    # Waveform generation settings
    WAVEFORM_ZOOM_LEVEL = 256  # Samples per pixel
    WAVEFORM_BITS = 8  # 8-bit resolution

    def __init__(
        self,
        cache_dir: str,
        look_ahead: int = DEFAULT_LOOK_AHEAD,
        cache_max_size: int = DEFAULT_CACHE_MAX_SIZE,
        client_fallback_max_duration: int = DEFAULT_CLIENT_FALLBACK_MAX_DURATION
    ):
        """
        Initialize the WaveformService.

        Args:
            cache_dir: Directory to store generated waveform files
            look_ahead: Number of instances to pre-compute ahead
            cache_max_size: Maximum number of cached waveform files
            client_fallback_max_duration: Max duration (seconds) for client-side fallback
        """
        self.cache_dir = cache_dir
        self.look_ahead = look_ahead
        self.cache_max_size = cache_max_size
        self.client_fallback_max_duration = client_fallback_max_duration

        # LRU cache tracking
        self._cache_order: OrderedDict = OrderedDict()
        self._cache_lock = threading.Lock()

        # Background pre-computation
        self._precompute_thread: Optional[threading.Thread] = None
        self._precompute_queue: List[str] = []
        self._precompute_lock = threading.Lock()
        self._stop_precompute = threading.Event()

        # Check if audiowaveform is installed
        self._audiowaveform_available = self._check_audiowaveform_installed()

        # Ensure cache directory exists
        self._ensure_cache_dir()

        logger.info(f"WaveformService initialized: cache_dir={cache_dir}, "
                   f"look_ahead={look_ahead}, audiowaveform_available={self._audiowaveform_available}")

    def _ensure_cache_dir(self) -> None:
        """Create the cache directory if it doesn't exist."""
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
            logger.info(f"Created waveform cache directory: {self.cache_dir}")

    def _check_audiowaveform_installed(self) -> bool:
        """
        Check if the audiowaveform tool is installed and available.

        Returns:
            True if audiowaveform is available, False otherwise
        """
        try:
            result = subprocess.run(
                ['audiowaveform', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                version = result.stdout.strip() or result.stderr.strip()
                logger.info(f"audiowaveform found: {version}")
                return True
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            logger.warning(f"audiowaveform not available: {e}")

        return False

    @property
    def is_available(self) -> bool:
        """Check if waveform generation is available."""
        return self._audiowaveform_available

    def _get_cache_key(self, audio_path: str) -> str:
        """
        Generate a unique cache key for an audio file.

        Args:
            audio_path: Path or URL to the audio file

        Returns:
            MD5 hash of the path as cache key
        """
        return hashlib.md5(audio_path.encode('utf-8')).hexdigest()

    def _get_waveform_cache_path(self, audio_path: str) -> str:
        """
        Get the cache file path for a waveform.

        Args:
            audio_path: Path or URL to the audio file

        Returns:
            Full path to the waveform cache file
        """
        cache_key = self._get_cache_key(audio_path)
        return os.path.join(self.cache_dir, f"{cache_key}.dat")

    def _is_url(self, path: str) -> bool:
        """
        Check if a path is a URL.

        Args:
            path: The path to check

        Returns:
            True if path is a URL, False otherwise
        """
        return path.startswith(('http://', 'https://', '//'))

    def _download_audio(self, url: str) -> Optional[str]:
        """
        Download an audio file from URL to a temporary file.

        Args:
            url: URL of the audio file

        Returns:
            Path to temporary file, or None if download failed
        """
        if not REQUESTS_AVAILABLE:
            logger.error("requests library not available for downloading audio")
            return None

        try:
            # Determine file extension from URL
            parsed = urlparse(url)
            path = parsed.path
            ext = os.path.splitext(path)[1] or '.mp3'

            # Create temporary file
            temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
            os.close(temp_fd)

            logger.debug(f"Downloading audio from {url} to {temp_path}")

            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.debug(f"Downloaded audio: {os.path.getsize(temp_path)} bytes")
            return temp_path

        except Exception as e:
            logger.error(f"Failed to download audio from {url}: {e}")
            return None

    def _generate_waveform(self, audio_path: str, output_path: str) -> bool:
        """
        Generate waveform data using audiowaveform tool.

        Args:
            audio_path: Path to the audio file (local)
            output_path: Path to write the waveform data file

        Returns:
            True if generation succeeded, False otherwise
        """
        if not self._audiowaveform_available:
            logger.warning("audiowaveform not available, cannot generate waveform")
            return False

        try:
            # Build command
            cmd = [
                'audiowaveform',
                '-i', audio_path,
                '-o', output_path,
                '-z', str(self.WAVEFORM_ZOOM_LEVEL),
                '-b', str(self.WAVEFORM_BITS),
            ]

            logger.debug(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for long files
            )

            if result.returncode == 0:
                logger.info(f"Generated waveform: {output_path}")
                return True
            else:
                logger.error(f"audiowaveform failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"audiowaveform timed out for {audio_path}")
            return False
        except Exception as e:
            logger.error(f"Error generating waveform for {audio_path}: {e}")
            return False

    def _update_cache_order(self, cache_path: str) -> None:
        """
        Update LRU cache order and evict if necessary.

        Args:
            cache_path: Path to the cache file being accessed
        """
        with self._cache_lock:
            # Move to end (most recently used)
            if cache_path in self._cache_order:
                self._cache_order.move_to_end(cache_path)
            else:
                self._cache_order[cache_path] = True

            # Evict oldest if over limit
            while len(self._cache_order) > self.cache_max_size:
                oldest_path, _ = self._cache_order.popitem(last=False)
                if os.path.exists(oldest_path):
                    try:
                        os.remove(oldest_path)
                        logger.debug(f"Evicted from cache: {oldest_path}")
                    except OSError as e:
                        logger.warning(f"Failed to remove cache file {oldest_path}: {e}")

    def get_waveform_path(self, audio_path: str, generate: bool = True) -> Optional[str]:
        """
        Get the waveform data file path for an audio file.

        If the waveform doesn't exist and generate=True, it will be generated.

        Args:
            audio_path: Path or URL to the audio file
            generate: Whether to generate if not cached

        Returns:
            Path to waveform data file, or None if not available
        """
        cache_path = self._get_waveform_cache_path(audio_path)

        # Check if already cached
        if os.path.exists(cache_path):
            self._update_cache_order(cache_path)
            logger.debug(f"Waveform cache hit: {cache_path}")
            return cache_path

        if not generate:
            return None

        # Generate waveform
        temp_audio = None
        try:
            # Handle URL vs local path
            if self._is_url(audio_path):
                temp_audio = self._download_audio(audio_path)
                if not temp_audio:
                    return None
                local_path = temp_audio
            else:
                local_path = audio_path
                if not os.path.exists(local_path):
                    logger.warning(f"Audio file not found: {local_path}")
                    return None

            # Generate waveform
            if self._generate_waveform(local_path, cache_path):
                self._update_cache_order(cache_path)
                return cache_path
            else:
                return None

        finally:
            # Clean up temporary file
            if temp_audio and os.path.exists(temp_audio):
                try:
                    os.remove(temp_audio)
                except OSError:
                    pass

    def get_waveform_url(self, audio_path: str, base_url: str = '/api/waveform/') -> Optional[str]:
        """
        Get the URL to fetch waveform data for an audio file.

        Args:
            audio_path: Path or URL to the audio file
            base_url: Base URL for the waveform API endpoint

        Returns:
            URL to fetch waveform data
        """
        cache_key = self._get_cache_key(audio_path)
        return f"{base_url}{cache_key}"

    def precompute_batch(self, audio_paths: List[str]) -> None:
        """
        Pre-compute waveforms for a batch of audio files.

        This is called synchronously and blocks until all are complete.
        Use start_background_precompute for non-blocking operation.

        Args:
            audio_paths: List of audio file paths or URLs
        """
        for audio_path in audio_paths:
            if audio_path:
                self.get_waveform_path(audio_path, generate=True)

    def queue_precompute(self, audio_paths: List[str]) -> None:
        """
        Add audio files to the background pre-computation queue.

        Args:
            audio_paths: List of audio file paths or URLs to pre-compute
        """
        with self._precompute_lock:
            # Only add paths not already in queue or cached
            for path in audio_paths:
                if path and path not in self._precompute_queue:
                    cache_path = self._get_waveform_cache_path(path)
                    if not os.path.exists(cache_path):
                        self._precompute_queue.append(path)

        # Start background thread if not running
        if self._precompute_thread is None or not self._precompute_thread.is_alive():
            self._start_background_precompute()

    def _start_background_precompute(self) -> None:
        """Start the background pre-computation thread."""
        self._stop_precompute.clear()
        self._precompute_thread = threading.Thread(
            target=self._background_precompute_worker,
            daemon=True
        )
        self._precompute_thread.start()
        logger.debug("Started background waveform pre-computation thread")

    def _background_precompute_worker(self) -> None:
        """Background worker for pre-computing waveforms."""
        while not self._stop_precompute.is_set():
            # Get next item from queue
            audio_path = None
            with self._precompute_lock:
                if self._precompute_queue:
                    audio_path = self._precompute_queue.pop(0)

            if audio_path:
                logger.debug(f"Background pre-computing waveform for: {audio_path}")
                self.get_waveform_path(audio_path, generate=True)
            else:
                # No more items, exit thread
                break

            # Small delay between items to avoid overloading
            time.sleep(0.1)

        logger.debug("Background waveform pre-computation thread finished")

    def stop_background_precompute(self) -> None:
        """Stop the background pre-computation thread."""
        self._stop_precompute.set()
        if self._precompute_thread and self._precompute_thread.is_alive():
            self._precompute_thread.join(timeout=5)

    def get_audio_duration(self, audio_path: str) -> Optional[float]:
        """
        Get the duration of an audio file in seconds.

        Uses ffprobe if available, otherwise returns None.

        Args:
            audio_path: Path to the audio file

        Returns:
            Duration in seconds, or None if cannot determine
        """
        try:
            result = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'error',
                    '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    audio_path
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError, FileNotFoundError):
            pass

        return None

    def should_use_client_fallback(self, audio_path: str) -> bool:
        """
        Determine if client-side waveform generation should be used.

        Client-side is preferred for short files when server-side is not available.

        Args:
            audio_path: Path to the audio file

        Returns:
            True if client-side fallback should be used
        """
        if self._audiowaveform_available:
            return False

        duration = self.get_audio_duration(audio_path)
        if duration is not None and duration <= self.client_fallback_max_duration:
            return True

        return False

    def clear_cache(self) -> int:
        """
        Clear all cached waveform files.

        Returns:
            Number of files removed
        """
        count = 0
        with self._cache_lock:
            for cache_path in list(self._cache_order.keys()):
                if os.path.exists(cache_path):
                    try:
                        os.remove(cache_path)
                        count += 1
                    except OSError as e:
                        logger.warning(f"Failed to remove {cache_path}: {e}")
            self._cache_order.clear()

        logger.info(f"Cleared {count} cached waveform files")
        return count

    def get_cache_stats(self) -> Dict:
        """
        Get statistics about the waveform cache.

        Returns:
            Dictionary with cache statistics
        """
        with self._cache_lock:
            cached_files = len(self._cache_order)
            total_size = 0
            for cache_path in self._cache_order.keys():
                if os.path.exists(cache_path):
                    total_size += os.path.getsize(cache_path)

        return {
            'cached_files': cached_files,
            'max_files': self.cache_max_size,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'cache_dir': self.cache_dir,
            'audiowaveform_available': self._audiowaveform_available,
        }


# Global instance (initialized when needed)
_waveform_service: Optional[WaveformService] = None


def get_waveform_service() -> Optional[WaveformService]:
    """Get the global WaveformService instance."""
    return _waveform_service


def init_waveform_service(
    cache_dir: str,
    look_ahead: int = WaveformService.DEFAULT_LOOK_AHEAD,
    cache_max_size: int = WaveformService.DEFAULT_CACHE_MAX_SIZE,
    client_fallback_max_duration: int = WaveformService.DEFAULT_CLIENT_FALLBACK_MAX_DURATION
) -> WaveformService:
    """
    Initialize the global WaveformService instance.

    Args:
        cache_dir: Directory to store generated waveform files
        look_ahead: Number of instances to pre-compute ahead
        cache_max_size: Maximum number of cached waveform files
        client_fallback_max_duration: Max duration for client-side fallback

    Returns:
        The initialized WaveformService instance
    """
    global _waveform_service
    _waveform_service = WaveformService(
        cache_dir=cache_dir,
        look_ahead=look_ahead,
        cache_max_size=cache_max_size,
        client_fallback_max_duration=client_fallback_max_duration
    )
    return _waveform_service
