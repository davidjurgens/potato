"""The Docker image a deployment runs when ``--image`` is not given.

The tag is the installed Potato version, not ``latest``. With ``latest`` a
study deployed from 2.10.3 ran whatever image was newest on the day of each
``up``, so two deploys of one study could run different releases.
"""

from potato import __version__

IMAGE_REPO = "ghcr.io/davidjurgens/potato"
DEFAULT_IMAGE = f"{IMAGE_REPO}:{__version__}"
