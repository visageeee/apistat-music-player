"""Presentation helpers for artist descriptions and Plex file metadata."""


def format_artist_description(text):
    return '\n\n'.join(line.strip() for line in text.splitlines() if line.strip())


def file_info_lines(details):
    if not isinstance(details, dict):
        return []
    lines = []
    for label, key, suffix in (('Format', 'codec', ''), ('Container', 'container', ''),
                               ('Bitrate', 'bitrate', ' kbps'),
                               ('Sample rate', 'sample_rate', ' Hz'),
                               ('Bit depth', 'bit_depth', ' bit'),
                               ('Channels', 'channels', ''),
                               ('File size', 'size', ' bytes'), ('File', 'file', ''),
                               ('Title', 'title', ''), ('Artist', 'artist', ''),
                               ('Album artist', 'album_artist', ''), ('Album', 'album', ''),
                               ('Year', 'year', ''), ('Track', 'track', ''), ('Disc', 'disc', ''),
                               ('Release date', 'date', ''), ('Genre', 'genre', ''),
                               ('Mood', 'mood', ''), ('Label', 'label', ''),
                               ('Writer', 'writer', ''), ('Director', 'director', ''),
                               ('Collection', 'collection', ''), ('Country', 'country', ''),
                               ('Rating', 'rating', ''), ('Play count', 'play_count', ''),
                               ('Description', 'summary', '')):
        value = details.get(key)
        if value not in (None, '', 0, '0'):
            lines.append((label, str(value) + suffix))
    for item in details.get('id3_tags', []):
        if isinstance(item, (tuple, list)) and len(item) == 2:
            lines.append(('ID3 ' + str(item[0]), str(item[1])))
    if details.get('id3_status'):
        lines.append(('Embedded tags', str(details['id3_status'])))
    return lines
