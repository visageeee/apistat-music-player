"""Small, UI-independent edits to the shared playback queue."""


def insert_items(queue, current_index, items, play_next=False):
    if not items:
        return list(queue), current_index, -1
    if 0 <= current_index < len(queue):
        position = current_index + 1 if play_next else len(queue)
        updated = list(queue)
        updated[position:position] = items
        return updated, current_index, position
    position = len(queue)
    return list(queue) + list(items), position, position


def reorder_items(queue, current_index, order):
    if len(order) != len(queue) or sorted(order) != list(range(len(queue))):
        raise ValueError('Invalid queue order')
    updated = [queue[old_index] for old_index in order]
    index = order.index(current_index) if 0 <= current_index < len(queue) else -1
    return updated, index


def move_items(queue, current_index, selected, destination):
    indices = sorted(set(selected))
    if not indices or any(index < 0 or index >= len(queue) for index in indices):
        raise ValueError('Invalid selected queue rows')
    if not 0 <= destination <= len(queue):
        raise ValueError('Invalid queue destination')
    selected_set = set(indices)
    order = [index for index in range(len(queue)) if index not in selected_set]
    insert_at = destination - sum(index < destination for index in indices)
    order[insert_at:insert_at] = indices
    return reorder_items(queue, current_index, order)


def move_queue_or_history(queue, current_index, history, selected, destination):
    """Move queue entries and copy selected history entries into the queue."""
    if not selected or len(set(selected)) != len(selected) or not 0 <= destination <= len(queue):
        raise ValueError('Invalid queue drag')
    history = list(history)
    if any((index >= len(queue) if index >= 0 else -index - 1 >= len(history))
           for index in selected):
        raise ValueError('Invalid queue drag')
    selected_queue = {index for index in selected if index >= 0}
    entries = [(index, item) for index, item in enumerate(queue) if index not in selected_queue]
    insertion = destination - sum(index < destination for index in selected_queue)
    dragged = [(index if index >= 0 else None,
                queue[index] if index >= 0 else history[-index - 1]) for index in selected]
    entries[insertion:insertion] = dragged
    new_index = next((position for position, (original, _item) in enumerate(entries)
                      if original == current_index), -1) if current_index >= 0 else -1
    return [item for _original, item in entries], new_index


def playlist_move_plan(items, selected, destination):
    """Return the new order and Plex moves needed to keep selected entries together."""
    ids = [item.playlist_item_id for item in items]
    if any(type(item_id) is not int or item_id <= 0 for item_id in ids) or len(set(ids)) != len(ids):
        raise ValueError('Playlist entries need unique Plex item IDs')
    updated, _ = move_items(items, -1, selected, destination)
    if updated == list(items):
        return updated, []
    selected_ids = {ids[index] for index in selected}
    first = next(index for index, item in enumerate(updated)
                 if item.playlist_item_id in selected_ids)
    after = updated[first - 1].playlist_item_id if first else None
    moves = []
    for item in updated[first:first + len(selected_ids)]:
        moves.append((item.playlist_item_id, after))
        after = item.playlist_item_id
    return updated, moves


def remove_items(queue, current_index, selected):
    indices = set(selected)
    if any(index < 0 or index >= len(queue) for index in indices):
        raise ValueError('Invalid selected queue rows')
    order = [index for index in range(len(queue)) if index not in indices]
    updated = [queue[index] for index in order]
    removed_current = current_index in indices
    if not updated:
        new_index = -1
    elif removed_current:
        new_index = min(sum(index < current_index for index in order), len(updated) - 1)
    else:
        new_index = order.index(current_index) if current_index in order else -1
    return updated, new_index, removed_current


def select_similar_tracks(seed, candidates, limit=10):
    chosen = []
    seen = {seed.key}
    albums = set()
    artist_counts = {}
    for track in candidates:
        if track.key in seen:
            continue
        artist = track.artist.casefold().strip()
        album = (artist, track.album.casefold().strip()) if track.album else None
        if (artist and artist_counts.get(artist, 0) >= 2) or (album and album in albums):
            continue
        seen.add(track.key)
        chosen.append(track)
        if artist:
            artist_counts[artist] = artist_counts.get(artist, 0) + 1
        if album:
            albums.add(album)
        if len(chosen) == limit:
            break
    return chosen
