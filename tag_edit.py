"""Write selected music tags without touching unrelated metadata."""
import base64
import os
import shutil
import tempfile
from pathlib import Path

FIELDS = ('title', 'artist', 'album', 'album_artist', 'year', 'genre', 'track_number', 'disc')


def image_type(data):
    if not isinstance(data, bytes) or not data or len(data) > 16 * 1024 * 1024:
        raise ValueError('Choose a JPEG or PNG image smaller than 16 MB.')
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    raise ValueError('Artwork must be a JPEG or PNG image.')


def validate_changes(changes):
    if not isinstance(changes, dict) or any(key not in FIELDS for key in changes):
        raise ValueError('Unsupported tag field.')
    clean = {}
    for key, value in changes.items():
        if not isinstance(value, str) or len(value) > 4096 or '\x00' in value:
            raise ValueError('Invalid tag value.')
        value = value.strip()
        if key in ('year', 'track_number', 'disc') and value:
            if not value.isdecimal() or not 1 <= int(value) <= (9999 if key == 'year' else 999):
                raise ValueError(f'{key.replace("_", " ").title()} must be a positive number.')
        clean[key] = value
    return clean


def write_tags(path, changes, artwork=None):
    """Update one file atomically; preserve unrelated tags and non-cover pictures."""
    from mutagen import File
    from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TPE2, TDRC, TCON, TRCK, TPOS
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus
    changes = validate_changes(changes)
    # None leaves artwork unchanged; False removes the front cover.
    mime = image_type(artwork) if artwork is not None and artwork is not False else None
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.apistat-tag-', suffix=path.suffix, dir=path.parent)
    os.close(fd)
    try:
        shutil.copy2(path, temporary)
        audio = File(temporary)
        if audio is None:
            raise ValueError('This file format is not supported for tag editing.')
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        if isinstance(tags, ID3):
            frames = {'title': TIT2, 'artist': TPE1, 'album': TALB, 'album_artist': TPE2,
                      'year': TDRC, 'genre': TCON, 'track_number': TRCK, 'disc': TPOS}
            for key, value in changes.items():
                frame = frames[key]
                existing = tags.getall(frame.__name__)
                if value and key in ('track_number', 'disc') and existing:
                    previous = str(existing[0].text[0]) if existing[0].text else ''
                    if '/' in previous:
                        value += '/' + previous.split('/', 1)[1]
                tags.delall(frame.__name__)
                if value:
                    tags.add(frame(encoding=3, text=[value]))
            if artwork is not None:
                previous = [picture for picture in tags.getall('APIC') if picture.type != 3]
                tags.delall('APIC')
                for picture in previous:
                    tags.add(picture)
                if artwork is not False:
                    description = 'Cover'
                    used = {picture.desc for picture in previous}
                    while description in used:
                        description += ' (front)'
                    tags.add(APIC(encoding=3, mime=mime, type=3, desc=description, data=artwork))
        elif isinstance(audio, MP4):
            fields = {'title': '\xa9nam', 'artist': '\xa9ART', 'album': '\xa9alb',
                      'album_artist': 'aART', 'year': '\xa9day', 'genre': '\xa9gen',
                      'track_number': 'trkn', 'disc': 'disk'}
            for key, value in changes.items():
                field = fields[key]
                if not value:
                    tags.pop(field, None)
                elif key in ('track_number', 'disc'):
                    total = tags.get(field, [(0, 0)])[0][1]
                    tags[field] = [(int(value), total)]
                else:
                    tags[field] = [value]
            if artwork is not None:
                if artwork is False:
                    tags.pop('covr', None)
                else:
                    kind = MP4Cover.FORMAT_JPEG if mime == 'image/jpeg' else MP4Cover.FORMAT_PNG
                    tags['covr'] = [MP4Cover(artwork, imageformat=kind)]
        elif isinstance(audio, (FLAC, OggVorbis, OggOpus)):
            fields = {'album_artist': 'albumartist', 'year': 'date',
                      'track_number': 'tracknumber', 'disc': 'discnumber'}
            for key, value in changes.items():
                field = fields.get(key, key)
                if value:
                    tags[field] = [value]
                else:
                    tags.pop(field, None)
            if artwork is not None:
                picture = None
                if artwork is not False:
                    picture = Picture()
                    picture.type, picture.mime, picture.desc, picture.data = 3, mime, 'Cover', artwork
                if isinstance(audio, FLAC):
                    other = [item for item in audio.pictures if item.type != 3]
                    audio.clear_pictures()
                    for item in other:
                        audio.add_picture(item)
                    if picture is not None:
                        audio.add_picture(picture)
                else:
                    previous = []
                    for encoded in tags.get('metadata_block_picture', []):
                        try:
                            if Picture(base64.b64decode(encoded, validate=True)).type != 3:
                                previous.append(encoded)
                        except (ValueError, TypeError):
                            previous.append(encoded)
                    if picture is not None:
                        previous.append(base64.b64encode(picture.write()).decode('ascii'))
                    if previous:
                        tags['metadata_block_picture'] = previous
                    else:
                        tags.pop('metadata_block_picture', None)
                    tags.pop('coverart', None)
                    tags.pop('coverartmime', None)
        else:
            raise ValueError('This file format is not supported for tag editing.')
        if isinstance(tags, ID3):
            version = tags.version[1] if tags.version[1] in (3, 4) else 4
            audio.save(v2_version=version)
        else:
            audio.save()
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
