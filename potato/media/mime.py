"""Content types Potato serves for the media formats it documents.

`send_from_directory` takes the type from the stdlib `mimetypes`, which reads
the host's `/etc/mime.types` at init. So the content type Potato served for the
same file was a property of the machine it ran on: a study working on a
researcher's laptop could serve a different type from the deployment host, and
nothing recorded which was sent.

Two of the defaults on a common host are types Chrome declares unplayable.
Measured with `canPlayType`:

    audio/mp4a-latm   ""           cannot play   <- was served for .m4a
    audio/mp4         "maybe"
    audio/aac         "probably"
    audio/x-flac      ""           cannot play   <- was served for .flac
    audio/flac        "probably"
    audio/x-wav       "maybe"                    <- served for .wav, fine
    audio/mpeg        "probably"

The bytes were always fine. `decodeAudioData` and `<audio src>` both sniff the
container and ignore the declared type, which is why playback worked and this
went unnoticed. What does not ignore it is anything that asks first: a
`<source type="...">` list, a `canPlayType` capability check, a player choosing
a fallback. Those saw "cannot play" for a file that plays perfectly.

Registering these makes the answer Potato's decision rather than the host's,
and makes it testable, which it was not.
"""

import mimetypes

#: extension -> the type Potato serves. Only formats Potato documents support
#: for are listed; anything else keeps the host's answer.
MEDIA_TYPES = {
    # Audio. `.opus` is deliberately absent: the host answers `audio/ogg`,
    # which is correct for Ogg-Opus and which Chrome accepts.
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".oga": "audio/ogg",
    ".weba": "audio/webm",
    # Video.
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
    ".mov": "video/quicktime",
    # Images a browser renders directly.
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
}


def register_media_mime_types() -> None:
    """Pin the content type for every format in `MEDIA_TYPES`.

    Idempotent, and safe to call before or after Flask starts: `add_type` with
    `strict=True` overrides whatever the host's table said.
    """
    for extension, content_type in MEDIA_TYPES.items():
        mimetypes.add_type(content_type, extension, strict=True)
