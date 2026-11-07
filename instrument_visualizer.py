"""Optional, cancellable instrument analysis for the music ribbon."""
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, url2pathname

from local_cache import _hash, _write_bytes
from track_waveform import allowed_track_uri

MAGIC = b'ASI1'
HEADER = struct.Struct('!4sIII')  # format, duration milliseconds, frame milliseconds, frames
LINE_COUNT = 13
MAX_FRAMES = 20 * 60 * 60  # at most one hour at 20 frames/second
MAX_DOWNLOAD = 1024 * 1024 * 1024


def read_analysis(path, duration):
    try:
        data = path.read_bytes()
        if len(data) < HEADER.size:
            return None
        magic, stored_duration, hop, frames = HEADER.unpack_from(data)
        if (magic != MAGIC or stored_duration != duration or hop != 50 or not 0 < frames <= MAX_FRAMES
                or len(data) != HEADER.size + frames * LINE_COUNT
                or abs(frames * hop - duration) > max(5000, duration * .05)):
            return None
        return hop, memoryview(data)[HEADER.size:]
    except (OSError, ValueError, struct.error):
        return None


def sample_analysis(analysis, position_ms):
    """Interpolate compact source levels at the current playback position."""
    if not analysis or not math.isfinite(position_ms):
        return None
    hop, data = analysis
    count = len(data) // LINE_COUNT
    if not count:
        return None
    pos = max(0., min(count - 1, position_ms / hop))
    left = int(pos)
    right = min(count - 1, left + 1)
    fraction = pos - left
    return tuple((data[left * LINE_COUNT + i] * (1 - fraction) +
                  data[right * LINE_COUNT + i] * fraction) / 255 for i in range(LINE_COUNT))


def analysis_path(cache, track):
    return cache.root / 'instruments' / (_hash('demucs-htdemucs-v1', track.key, track.duration) + '.bin')


def python_executable():
    configured = os.environ.get('APISTAT_DEMUCS_PYTHON')
    if configured:
        return configured
    if sys.platform.startswith('linux') and not os.environ.get('FLATPAK_ID'):
        default = Path.home() / '.local' / 'share' / 'apistat' / 'demucs-env' / 'bin' / 'python'
        if default.is_file():
            return str(default)
    if not getattr(sys, 'frozen', False) and not os.environ.get('FLATPAK_ID'):
        return sys.executable
    return None


def _copy_remote(client, uri, path, cancelled):
    if not allowed_track_uri(uri, client.address):
        raise ValueError('The track is not on the selected server')
    request = Request(uri, headers={'X-Plex-Token': client.token})
    # PlexClient's opener rejects redirects, preventing token forwarding.
    with client.opener.open(request, timeout=15) as response, path.open('wb') as target:
        copied = 0
        while not cancelled():
            chunk = response.read(256 * 1024)
            if not chunk:
                return True
            copied += len(chunk)
            if copied > MAX_DOWNLOAD:
                raise ValueError('Track is too large for instrument analysis')
            target.write(chunk)
            # Keep the extra download from monopolizing a local Plex server.
            time.sleep(.05)
    return False


def run_analysis(cache, client, track, uri, cancelled=lambda: False):
    """Return (analysis, status), without touching GTK or exposing credentials."""
    path = analysis_path(cache, track)
    cached = read_analysis(path, track.duration)
    if cached is not None:
        return cached, 'ready'
    executable = python_executable()
    if not executable:
        return None, 'missing'
    if cancelled():
        return None, 'cancelled'
    worker = Path(__file__).with_name('instrument_worker.py')
    if not worker.is_file():
        return None, 'missing'
    try:
        with tempfile.TemporaryDirectory(prefix='apistat-instruments-') as directory:
            base = Path(directory)
            if getattr(client, 'is_local', False):
                parsed = urlsplit(uri)
                if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost'):
                    raise ValueError('Invalid local track URI')
                input_path = Path(url2pathname(parsed.path))
            else:
                input_path = base / 'track.audio'
                if not _copy_remote(client, uri, input_path, cancelled):
                    return None, 'cancelled'
            if cancelled():
                return None, 'cancelled'
            output = base / 'analysis.bin'
            command = [executable, str(worker), str(input_path), str(output), str(track.duration)]
            if os.name != 'nt' and shutil.which('nice'):
                command = [shutil.which('nice'), '-n', '15'] + command
            env = os.environ.copy()
            env.update(OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
            kwargs = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL, 'env': env}
            if os.name == 'nt':
                kwargs['creationflags'] = 0x00004000 | 0x08000000  # below normal, no console
            process = subprocess.Popen(command, **kwargs)
            try:
                while process.poll() is None:
                    if cancelled():
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        return None, 'cancelled'
                    time.sleep(.2)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            if process.returncode != 0:
                return None, {21: 'missing_numpy', 22: 'missing_demucs'}.get(process.returncode, 'failed')
            result = read_analysis(output, track.duration)
            if result is None or cancelled():
                return None, 'cancelled' if cancelled() else 'failed'
            _write_bytes(path, output.read_bytes())
            return result, 'ready'
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, 'failed'
