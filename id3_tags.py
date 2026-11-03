"""Read embedded ID3v2 frames from a bounded Plex media byte range."""

import io
import re
from urllib.request import Request

MAX_ID3_BYTES = 4 * 1024 * 1024


def read_id3_tags(client, part_key, file_size=None):
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError
    except ImportError:
        return [], 'Install python3-mutagen to read embedded ID3 tags.'
    if (not isinstance(part_key, str) or
            not re.fullmatch(r'/library/parts/\d+/(?:\d+/)?[^/?#%\\]+', part_key) or
            part_key.rsplit('/', 1)[-1] in ('.', '..')):
        return [], 'Embedded tags are unavailable for this file.'

    def read_range(start, length):
        request = Request(client.url(part_key), headers={
            'X-Plex-Token': client.token, 'X-Plex-Product': 'Apistat',
            'X-Plex-Client-Identifier': client.identifier,
            'Range': f'bytes={start}-{start + length - 1}'})
        with client.opener.open(request, timeout=client.timeout) as response:
            if start and getattr(response, 'status', None) != 206:
                raise ValueError('Server does not support byte ranges')
            return response.read(length)

    try:
        header = read_range(0, 10)
        if len(header) < 10 or header[:3] != b'ID3':
            size = int(file_size or 0)
            if size < 128:
                return [], 'No ID3 tags found; showing Plex metadata.'
            data = read_range(size - 128, 128)
            if len(data) != 128 or data[:3] != b'TAG':
                return [], 'No ID3 tags found; showing Plex metadata.'
        else:
            size_bytes = header[6:10]
            if any(byte & 0x80 for byte in size_bytes):
                return [], 'Invalid embedded ID3 header.'
            size = 10 + sum(byte << shift for byte, shift in zip(size_bytes, (21, 14, 7, 0)))
            if size > MAX_ID3_BYTES:
                return [], 'ID3 tags exceed the 4 MiB reading limit.'
            data = read_range(0, size)
            if len(data) != size:
                return [], 'Could not read the complete ID3 tags.'
        tags = ID3(fileobj=io.BytesIO(data), translate=False)
    except (OSError, ValueError, ID3NoHeaderError):
        return [], 'Could not read embedded ID3 tags.'
    except Exception:
        return [], 'Could not parse embedded ID3 tags.'

    result = []
    for key, frame in tags.items():
        text = getattr(frame, 'text', None)
        if text is not None:
            value = ' / '.join(str(item) for item in text)
        elif getattr(frame, 'url', None):
            value = str(frame.url)
        elif getattr(frame, 'data', None) is not None:
            value = f'[Binary data: {len(frame.data)} bytes]'
        else:
            value = str(frame.pprint())
        if value:
            result.append((str(key), value[:8192] + ('…' if len(value) > 8192 else '')))
    return result, ''
