"""Personal highlights for tracks on an album's flip side."""


def show_track_duration(cover_size):
    """Reserve space for durations only when the cover is zoomed in close."""
    return cover_size >= 360


def track_highlights(tracks):
    """Mark loved, highly rated, and most-played tracks using library metadata."""
    tracks = list(tracks or ())
    most_played = max((getattr(track, 'play_count', 0) for track in tracks), default=0)
    result = {}
    for track in tracks:
        if getattr(track, 'user_rating', 0) >= 9.5:
            result[track.key] = '♥'
        elif (getattr(track, 'user_rating', 0) >= 8 or
              (most_played >= 2 and getattr(track, 'play_count', 0) == most_played)):
            result[track.key] = '★'
    return result
