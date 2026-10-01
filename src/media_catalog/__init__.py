"""Offline media catalog and search tools."""

from importlib import metadata as _metadata

from .models import MediaRecord, Status

try:
    __version__ = _metadata.version("video-library-organizer")
except _metadata.PackageNotFoundError:  # frozen build or source checkout
    __version__ = "0.0.0+unknown"

__all__ = ["MediaRecord", "Status", "__version__"]

