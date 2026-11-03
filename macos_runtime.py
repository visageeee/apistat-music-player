"""Runtime paths for a signed macOS application bundle."""

import os
import tempfile
from pathlib import Path


def configure_gstreamer_registry(cache_dir):
    """Keep GStreamer's writable registry outside the signed app bundle.

    Return a temporary-directory owner when the normal cache is unavailable;
    the caller must keep it alive until GStreamer has stopped.
    """
    temporary = None
    directory = Path(cache_dir) / 'plex-music-prototype'
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        temporary = tempfile.TemporaryDirectory(prefix='apistat-gstreamer-')
        directory = Path(temporary.name)
    os.environ['GST_REGISTRY'] = str(directory / 'gstreamer-registry.bin')
    return temporary
