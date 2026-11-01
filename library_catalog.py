"""Whole-library song filtering and sorts used by the Library view."""


def build_song_catalog(client, section, playlist=None, valid=lambda: True):
    songs = []
    start = 0
    while valid():
        if playlist is None:
            page, total = client.songs(section, start, 'addedAt:desc')
        else:
            page, total = client.playlist_items(playlist, start)
        songs.extend(page)
        start += len(page)
        if not page or start >= total:
            return songs
    return None


def filter_sort_songs(songs, query='', sort=None):
    words = query.casefold().split()
    result = [song for song in songs if all(
        word in f'{song.title} {song.artist} {song.album} {song.genre} '
                f'{song.mood} {song.label} {song.album_artist} {song.year}'.casefold()
        for word in words)]
    if sort is None:
        return result
    field, descending = sort
    if field == 'title':
        key = lambda song: (song.title.casefold(), song.artist.casefold())
    elif field == 'artist':
        key = lambda song: (song.artist.casefold(), song.title.casefold())
    elif field == 'album':
        key = lambda song: (song.album.casefold(), song.number, song.title.casefold())
    elif field == 'duration':
        key = lambda song: (song.duration, song.title.casefold())
    elif field == 'genre':
        key = lambda song: (song.genre.casefold(), song.artist.casefold(), song.title.casefold())
    elif field in ('mood', 'label', 'album_artist', 'codec', 'release_date'):
        key = lambda song: (getattr(song, field).casefold(), song.artist.casefold(),
                            song.title.casefold())
    elif field == 'year':
        key = lambda song: (int(song.year) if str(song.year).isdigit() else -1,
                            song.artist.casefold(), song.title.casefold())
    elif field == 'added_at':
        key = lambda song: (song.added_at, song.title.casefold())
    elif field in ('last_played_at', 'play_count', 'user_rating', 'bitrate',
                   'disc', 'track_number'):
        key = lambda song: (getattr(song, field), song.artist.casefold(),
                            song.title.casefold())
    else:
        raise ValueError('Unsupported Library sort')
    return sorted(result, key=key, reverse=descending)
