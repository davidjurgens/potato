"""
Media ingest: making files a browser cannot display annotatable anyway.

Researchers arrive with TIFF stacks, HEIC photos, camera RAW, ProRes and MKV.
No browser renders any of them, so today the canvas is simply blank — with no
message, because from the page's point of view nothing went wrong.

This package transcodes such files on first request and caches the result:

* :mod:`potato.media.images` — TIFF (including multi-page and 16-bit), HEIC,
  AVIF and camera RAW to WebP, via Pillow. 16-bit sources keep a windowing
  control so scientific imagery stays usable rather than being crushed to 8-bit
  on the way in.
* :mod:`potato.media.video` — HEVC, ProRes, MKV, MOV and anything else ffmpeg
  reads, to WebM/VP9, with an extracted-frames fallback when ffmpeg is absent.
* :mod:`potato.media.cache` — content-addressed cache under
  ``<output_dir>/.media_cache/``.

Every dependency is optional. Pillow's absence degrades to "this format needs
Pillow", ffmpeg's to a copy-pasteable conversion command — never to a broken
player or an empty canvas, which is the state this package exists to end.

Nothing here is imported at boot: :mod:`potato.media.routes` is registered
lazily and the codecs are imported inside the functions that use them, so a
server with no Pillow and no ffmpeg starts exactly as fast as before.
"""

from .cache import MediaCache, cache_path_for, get_media_cache
from .images import (IMAGE_PASSTHROUGH, TRANSCODE_IMAGE_EXTENSIONS,
                     ImageTranscodeError, describe_image, needs_transcode,
                     transcode_image)
from .video import (VIDEO_PASSTHROUGH, TRANSCODE_VIDEO_EXTENSIONS,
                    VideoTranscodeError, ffmpeg_available, transcode_video)

__all__ = [
    "MediaCache",
    "get_media_cache",
    "cache_path_for",
    "IMAGE_PASSTHROUGH",
    "TRANSCODE_IMAGE_EXTENSIONS",
    "ImageTranscodeError",
    "describe_image",
    "needs_transcode",
    "transcode_image",
    "VIDEO_PASSTHROUGH",
    "TRANSCODE_VIDEO_EXTENSIONS",
    "VideoTranscodeError",
    "ffmpeg_available",
    "transcode_video",
]
