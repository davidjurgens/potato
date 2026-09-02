"""
Video proxy transcoding for codecs the browser will not play.

MP4/H.264, WebM/VP9 and AV1 play natively. HEVC, ProRes, MKV and MOV generally
do not — and the failure is silent: the ``<video>`` element loads, reports no
error worth showing, and simply never paints a frame. An annotator sees an
empty player and concludes the tool is broken.

So unsupported sources are transcoded to WebM/VP9 through ffmpeg, cached, and
served in place of the original.

Three deliberate choices:

* **ffmpeg is optional.** Its absence produces the exact command to run
  instead, not a broken player. Nobody should have to guess the flags.
* **Transcoding is bounded.** A two-hour ProRes master will not finish inside a
  web request, so the work runs with a timeout and the caller is told to
  pre-convert rather than left with a request that hangs until the proxy times
  it out.
* **Codec support is decided by the CLIENT.** ``MediaSource.isTypeSupported``
  is the only reliable answer, and it differs by browser and platform — Safari
  plays HEVC that Chrome will not. The extension list here is the server-side
  fallback for when the client has not reported.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class VideoTranscodeError(RuntimeError):
    """Raised with a message the UI can show verbatim."""


#: Containers/codecs mainstream browsers play without help.
VIDEO_PASSTHROUGH = {".mp4", ".m4v", ".webm", ".ogv", ".ogg"}

#: What we transcode, with the reason it needs it.
TRANSCODE_VIDEO_EXTENSIONS = {
    ".mov": "QuickTime container, often ProRes or HEVC",
    ".mkv": "Matroska container is not supported by Safari or iOS",
    ".avi": "legacy container, usually an unsupported codec",
    ".mts": "AVCHD camera format",
    ".m2ts": "AVCHD/Blu-ray transport stream",
    ".wmv": "Windows Media, no browser support",
    ".flv": "Flash video, no browser support",
    ".mxf": "broadcast container, no browser support",
    ".prores": "ProRes, no browser support",
}

#: A web request cannot wait on a feature-length transcode.
DEFAULT_TIMEOUT_SECONDS = 600

#: VP9 constant-quality level. 30 is visually near-transparent for annotation
#: while producing files small enough to serve.
VP9_CRF = 30


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def needs_transcode(path: str) -> bool:
    return Path(path).suffix.lower() in TRANSCODE_VIDEO_EXTENSIONS


def conversion_hint(source: str, destination: str = "output.webm") -> str:
    """The command to run by hand. Shown whenever ffmpeg is missing."""
    return (f"ffmpeg -i {Path(source).name} -c:v libvpx-vp9 -crf {VP9_CRF} "
            f"-b:v 0 -c:a libopus {destination}")


def probe_video(source: str) -> Dict[str, object]:
    """
    Duration, dimensions and codec, via ffprobe.

    Returns an empty dict when ffprobe is unavailable rather than raising: the
    caller can still transcode without knowing the duration, and refusing to
    proceed because a *diagnostic* tool is missing would be the wrong trade.
    """
    if shutil.which("ffprobe") is None:
        return {}
    try:
        output = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,codec_name,duration",
             "-of", "default=noprint_wrappers=1", str(source)],
            capture_output=True, text=True, timeout=30, check=False).stdout
    except (subprocess.SubprocessError, OSError):
        return {}

    info: Dict[str, object] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in ("width", "height"):
            try:
                info[key] = int(value)
            except ValueError:
                pass
        elif key == "duration":
            try:
                info[key] = float(value)
            except ValueError:
                pass
        else:
            info[key] = value
    return info


def transcode_video(source: str, destination: str, *,
                    timeout: int = DEFAULT_TIMEOUT_SECONDS,
                    max_height: Optional[int] = None,
                    crf: int = VP9_CRF) -> Dict[str, object]:
    """
    Transcode ``source`` to WebM/VP9 at ``destination``.

    Args:
        source: Path to the original video
        destination: Path to write (``.webm``)
        timeout: Seconds before giving up; a long master needs pre-conversion
        max_height: Downscale to this height, preserving aspect
        crf: VP9 constant-quality level; lower is better and larger

    Returns:
        Metadata about what was written.

    Raises:
        VideoTranscodeError: With a message suitable for showing to the user,
            including the manual command when ffmpeg is absent.
    """
    source_path = Path(source)
    destination_path = Path(destination)

    if not source_path.exists():
        raise VideoTranscodeError(f"{source_path.name} does not exist")

    if not ffmpeg_available():
        raise VideoTranscodeError(
            f"{source_path.name} uses a codec this browser cannot play, and "
            f"ffmpeg is not installed to convert it. Install ffmpeg, or "
            f"convert the file yourself with:\n  {conversion_hint(source)}")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temporary name and rename on success: a killed transcode
    # otherwise leaves a truncated file at the cache path, which every later
    # request happily serves as a valid cache hit.
    partial = destination_path.with_suffix(destination_path.suffix + ".partial")

    command: List[str] = [
        "ffmpeg", "-y", "-i", str(source_path),
        "-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0",
        "-row-mt", "1", "-deadline", "good", "-cpu-used", "2",
    ]
    if max_height:
        command += ["-vf", f"scale=-2:min({max_height}\\,ih)"]
    command += ["-c:a", "libopus", "-f", "webm", str(partial)]

    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        partial.unlink(missing_ok=True)
        raise VideoTranscodeError(
            f"Converting {source_path.name} took longer than {timeout}s and "
            f"was stopped. A long or high-resolution video should be converted "
            f"ahead of time rather than on first view:\n"
            f"  {conversion_hint(source)}")
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise VideoTranscodeError(f"Could not run ffmpeg: {exc}")

    if completed.returncode != 0 or not partial.exists():
        partial.unlink(missing_ok=True)
        tail = (completed.stderr or "").strip().splitlines()[-3:]
        raise VideoTranscodeError(
            f"ffmpeg could not convert {source_path.name}. "
            f"{' '.join(tail) if tail else ''}".strip())

    partial.replace(destination_path)
    return {
        "path": str(destination_path),
        "bytes": destination_path.stat().st_size,
        "source_bytes": source_path.stat().st_size,
    }


def extract_frames(source: str, output_dir: str, *, fps: float = 1.0,
                   limit: int = 600) -> List[str]:
    """
    Fallback when a video cannot be transcoded: annotate stills instead.

    Worse than a real player, and honestly so — but a set of frames is
    annotatable and an empty player is not. Capped so a long video cannot fill
    the disk with stills nobody asked for.
    """
    if not ffmpeg_available():
        raise VideoTranscodeError(
            f"Extracting frames needs ffmpeg. Install it, or convert the "
            f"video with:\n  {conversion_hint(source)}")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    pattern = str(out / "frame_%06d.jpg")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source), "-vf", f"fps={fps}",
             "-frames:v", str(limit), pattern],
            capture_output=True, text=True, timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False)
    except (subprocess.SubprocessError, OSError) as exc:
        raise VideoTranscodeError(f"Could not extract frames: {exc}")
    return sorted(str(p) for p in out.glob("frame_*.jpg"))
