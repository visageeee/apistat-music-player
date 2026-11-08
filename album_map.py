"""Deterministic, cached album islands built solely from local metadata."""
from collections import Counter, defaultdict
import hashlib
import json
import math
import time

from album_web import canonical_album_key
from local_cache import LocalCache, _write_bytes

VERSION = 11
CELL = 200.0
MAX_GROUPS = 48
GOLDEN = math.pi * (3 - math.sqrt(5))
BROAD_TAGS = {'pop/rock', 'pop rock', 'pop & rock', 'pop and rock'}
POP_PARENT = '__pop_parent__'
POP_MOOD = '__pop_mood__:'
# Small explicit families guide placement without network access or claiming
# that all members are interchangeable. Unknown tags remain data-driven.
RELATED_FAMILIES = (
    {'ambient', 'electronic', 'electronica', 'downtempo', 'chillout', 'idm'},
    {'folk', 'country', 'americana', 'bluegrass', 'singer-songwriter'},
    {'jazz', 'blues', 'soul', 'rhythm & blues', 'r&b'},
    {'rock', 'alternative rock', 'indie rock', 'punk', 'hard rock', 'metal'},
    {'classical', 'orchestral', 'opera', 'chamber music'},
    {'hip-hop', 'hip hop', 'rap', 'r&b', 'funk'},
    {'happy', 'joyful', 'cheerful', 'upbeat', 'optimistic', 'playful', 'uplifting', 'celebratory'},
    {'sad', 'sadness', 'melancholy', 'melancholic', 'somber', 'mournful', 'angry', 'anger', 'aggressive', 'brooding', 'dark'},
    {'calm', 'peaceful', 'relaxed', 'dreamy', 'soothing', 'mellow', 'meditative'},
)


def _tags(value):
    return [part.strip() for part in str(value or '').replace(';', ',').split(',') if part.strip()]


def cached_links(client, section, albums):
    """Read existing album-web results without initiating any Last.fm requests."""
    folder = LocalCache(client).root / 'album-web'
    if not folder.is_dir():
        return []
    keys = {hashlib.sha256((str(section) + '\0' + album.key).encode('utf-8')).hexdigest(): album.key
            for album in albums}
    by_key = {canonical_album_key(album.key): album.key for album in albums}
    links = set()
    now = time.time()
    for path in folder.glob('*.json'):
        source = keys.get(path.stem)
        if not source:
            continue
        try:
            if path.stat().st_size > 16384:
                continue
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('version') != 2 or not 0 <= now - data['time'] < 86400:
                continue
            for target in data.get('albums', [])[:10]:
                dest = by_key.get(canonical_album_key(target)) if isinstance(target, str) else None
                if dest and dest != source:
                    links.add(tuple(sorted((source, dest))))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    return sorted(links)


def cached_facet_tags(client, section, max_references=250000):
    """Reuse cached Plex style and mood results without querying Plex."""
    cache = LocalCache(client)
    facets = cache.read_music_facets(section, max_age=30 * 86400) or ()
    result = defaultdict(lambda: defaultdict(set))
    references = 0
    for facet in facets:
        if facet.field not in ('style', 'mood') or not cache.song_index_path(section, facet.cache_key).is_file():
            continue
        tracks = cache.read_song_index(section, facet.cache_key, max_age=None) or ()
        for track in tracks:
            if track.album_key:
                result[canonical_album_key(track.album_key)][facet.field].add(facet.title)
            references += 1
            if references >= max_references:
                return {key: {field: sorted(values) for field, values in fields.items()}
                        for key, fields in result.items()}
    return {key: {field: sorted(values) for field, values in fields.items()}
                        for key, fields in result.items()}


def _fingerprint(albums, tracks, links, facets):
    digest = hashlib.sha256()
    for album in sorted(albums, key=lambda item: item.key):
        digest.update(json.dumps([album.key, album.title, album.artist, album.genre, album.mood, album.style], ensure_ascii=False).encode())
        digest.update(b'\n')
    # Track order can differ between server and cached index.
    rows = sorted((track.key, track.album_key, track.album, track.album_artist,
                   track.artist, track.genre, track.mood) for track in tracks)
    for row in rows:
        digest.update(json.dumps(row, ensure_ascii=False).encode())
        digest.update(b'\n')
    # Cached recommendations and facet results can arrive or expire during a
    # session; neither should move the map without an explicit rebuild.
    return digest.hexdigest()


def build_layout(albums, tracks, links=(), facets=None):
    """Lay out genre islands in world coordinates without a force simulation."""
    albums = sorted(albums, key=lambda item: item.key)
    by_parent = {canonical_album_key(album.key): album.key for album in albums}
    by_name = defaultdict(list)
    for album in albums:
        by_name[((album.artist or '').strip().casefold(), (album.title or '').strip().casefold())].append(album.key)
    tags = {album.key: Counter({tag.casefold(): 1 for tag in _tags(album.genre)}) for album in albums}
    moods = {album.key: Counter(tag.casefold() for tag in _tags(album.mood)) for album in albums}
    names = {}
    for album in albums:
        for tag in _tags(album.genre) + _tags(album.mood) + _tags(album.style):
            key = tag.casefold()
            names[key] = min(names.get(key, tag), tag)
    for album in albums:
        weight = max(tags[album.key].values(), default=0) + 1
        for tag in _tags(album.style):
            tags[album.key][tag.casefold()] += weight
    artists = defaultdict(set)
    for album in albums:
        if album.artist and album.artist.strip().casefold() not in ('various artists', 'unknown artist'):
            artists[album.artist.casefold()].add(album.key)
    for track in tracks:
        key = by_parent.get(canonical_album_key(track.album_key))
        if key is None:
            candidates = by_name.get(((track.album_artist or track.artist or '').strip().casefold(),
                                      (track.album or '').strip().casefold()), ())
            if len(candidates) == 1:
                key = candidates[0]
        if key is None:
            continue
        for tag in _tags(track.mood):
            normalized = tag.casefold()
            names[normalized] = min(names.get(normalized, tag), tag)
            moods[key][normalized] += 1
        values = _tags(track.genre) or _tags(track.mood)
        for tag in values:
            normalized = tag.casefold()
            names[normalized] = min(names.get(normalized, tag), tag)
            tags[key][tag.casefold()] += 1
        if track.artist and track.artist.strip().casefold() not in ('various artists', 'unknown artist'):
            artists[track.artist.casefold()].add(key)
    chart_styles = {}
    chart_moods = {}
    for parent, values in (facets or {}).items():
        key = by_parent.get(canonical_album_key(parent))
        if key is None:
            continue
        # Keep styles and moods distinct so Pop/Rock can be grouped by mood.
        fields = values if isinstance(values, dict) else {'style': values}
        chart_styles[key] = [tag.casefold() for value in fields.get('chart_style', ()) for tag in _tags(value)]
        chart_moods[key] = [tag.casefold() for value in fields.get('chart_mood', ()) for tag in _tags(value)]
        for value in fields.get('chart_style', ()):
            for tag in _tags(value):
                normalized = tag.casefold()
                names[normalized] = min(names.get(normalized, tag), tag)
                tags[key][normalized] += 1
        for value in (*fields.get('mood', ()), *fields.get('chart_mood', ())):
            for tag in _tags(value):
                normalized = tag.casefold()
                names[normalized] = min(names.get(normalized, tag), tag)
                moods[key][normalized] += 1
        weight = max(tags[key].values(), default=0) + 1
        for value in fields.get('style', ()):
            for tag in _tags(value):
                normalized = tag.casefold()
                names[normalized] = min(names.get(normalized, tag), tag)
                tags[key][normalized] += weight
    primary = {}
    for album in albums:
        counts = tags[album.key]
        specific = [value for value in counts if value not in BROAD_TAGS]
        if chart_styles.get(album.key):
            primary[album.key] = chart_styles[album.key][0]
        elif chart_moods.get(album.key):
            primary[album.key] = chart_moods[album.key][0]
        elif any(value in BROAD_TAGS for value in counts) and moods[album.key]:
            mood = min(moods[album.key], key=lambda value: (-moods[album.key][value], value))
            key = POP_MOOD + mood
            names[key] = 'Pop/Rock · ' + names.get(mood, mood)
            primary[album.key] = key
        elif not counts and moods[album.key]:
            primary[album.key] = min(moods[album.key], key=lambda value: (-moods[album.key][value], value))
        elif specific:
            primary[album.key] = min(specific, key=lambda value: (-counts[value], value))
        else:
            primary[album.key] = min(counts, key=lambda value: (-counts[value], value)) if counts else ''
    # Infer only from already-classified albums. A matching album artist is
    # stronger evidence than a cached related-album result; multiple distinct
    # cached links can also establish a match. Do not propagate guesses.
    artist_groups = defaultdict(Counter)
    unknown_artists = {'', 'unknown artist', 'various artists'}
    for album in albums:
        artist = (album.artist or '').strip().casefold()
        if artist not in unknown_artists and primary[album.key]:
            artist_groups[artist][primary[album.key]] += 1
    related_groups = defaultdict(Counter)
    for left, right in set(tuple(sorted(edge)) for edge in links if len(edge) == 2):
        if left not in primary or right not in primary:
            continue
        if not primary[left] and primary[right]:
            related_groups[left][primary[right]] += 2
        elif not primary[right] and primary[left]:
            related_groups[right][primary[left]] += 2
    inferred = {}
    for album in albums:
        if primary[album.key]:
            continue
        votes = Counter(related_groups[album.key])
        artist = (album.artist or '').strip().casefold()
        for group, count in artist_groups.get(artist, {}).items():
            votes[group] += min(count, 3) * 6
        ranked = sorted(votes.items(), key=lambda pair: (-pair[1], pair[0]))
        if ranked and ranked[0][1] >= 4 and (len(ranked) == 1 or ranked[0][1] >= ranked[1][1] * 1.5):
            inferred[album.key] = ranked[0][0]
    primary.update(inferred)
    # For albums that still lack any classified neighbor, keep locally known
    # artist and cached-similarity communities together without inventing tags.
    remaining = {album.key: album for album in albums if not primary[album.key]}
    parents = {key: key for key in remaining}
    def root(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key
    def union(left, right):
        left, right = root(left), root(right)
        if left != right:
            parents[max(left, right)] = min(left, right)
    by_artist = defaultdict(list)
    for key, album in remaining.items():
        artist = (album.artist or '').strip().casefold()
        if artist not in unknown_artists:
            by_artist[artist].append(key)
    for keys in by_artist.values():
        for key in keys[1:]:
            union(keys[0], key)
    for left, right in links:
        if left in remaining and right in remaining:
            union(left, right)
    communities = defaultdict(list)
    for key in remaining:
        communities[root(key)].append(key)
    ranked_communities = sorted((keys for keys in communities.values() if len(keys) >= 3),
                                key=lambda keys: (-len(keys), min(keys)))[:10]
    for keys in ranked_communities:
        members = [remaining[key] for key in sorted(keys)]
        artists_in_group = Counter((album.artist or '').strip() for album in members
                                   if (album.artist or '').strip().casefold() not in unknown_artists)
        if not artists_in_group:
            continue
        artist = min(artists_in_group, key=lambda value: (-artists_in_group[value], value.casefold(), value))
        group = '__uncharted_related__:' + min(keys)
        names[group] = 'Uncharted · ' + (artist if len(artists_in_group) == 1 else 'related to ' + artist)
        for key in keys:
            primary[key] = group
    counts = Counter(value for value in primary.values() if value)
    has_moods = any(value.startswith(POP_MOOD) for value in counts)
    keep = set(sorted(counts, key=lambda value: (-counts[value], value))[:MAX_GROUPS - 3 if has_moods else MAX_GROUPS - 2])
    for key, value in primary.items():
        if value and value not in keep:
            primary[key] = '' if value.startswith('__uncharted_related__:') else '__other__'
    if has_moods:
        for key, value in primary.items():
            if value in BROAD_TAGS:
                primary[key] = POP_PARENT
        names[POP_PARENT] = 'Pop/Rock'
    names['__other__'] = 'Other styles'
    names[''] = 'Uncharted'
    groups = defaultdict(list)
    for album in albums:
        groups[primary[album.key]].append(album)
    if any(group.startswith(POP_MOOD) for group in groups):
        groups.setdefault(POP_PARENT, [])
    for group in groups.values():
        group.sort(key=lambda album: ((album.artist or '').casefold(), (album.title or '').casefold(), album.key))
    affinity = defaultdict(Counter)
    def connect(a, b, weight=1):
        if a != b:
            affinity[a][b] += weight
            affinity[b][a] += weight
    mood_groups = [group for group in groups if group.startswith(POP_MOOD)]
    for group in mood_groups:
        connect(POP_PARENT, group, 12)
    group_names = {group: group.removeprefix(POP_MOOD) for group in groups}
    for family in RELATED_FAMILIES:
        matches = sorted(group for group, name in group_names.items() if name in family)
        for index, left in enumerate(matches):
            for right in matches[index + 1:]:
                connect(left, right, 30)
    for album in albums:
        origin = primary[album.key]
        for tag in tags[album.key]:
            if tag in keep:
                connect(origin, tag)
    for keys in artists.values():
        clusters = sorted({primary[key] for key in keys})
        for index, left in enumerate(clusters):
            for right in clusters[index + 1:]:
                connect(left, right, 2)
    for left, right in links:
        if left in primary and right in primary:
            connect(primary[left], primary[right], 4)
    # A compact chain captures local artist/collaborator links without a
    # quadratic set of edges for artists with large discographies.
    edges = {tuple(sorted((a, b))) for a, b in links if a in primary and b in primary and a != b}
    for keys in artists.values():
        ordered_keys = sorted(keys)
        edges.update(zip(ordered_keys, ordered_keys[1:]))
    remaining = set(groups)
    order = []
    while remaining:
        best = min(remaining, key=lambda group: (group == '' or group.startswith('__uncharted_related__:'),
                                                  0 if not order and group == POP_PARENT else 1,
                                                  -sum(affinity[group][other] for other in order),
                                                  -len(groups[group]), group))
        remaining.remove(best)
        order.append(best)
    centers, cluster_radii, coordinates, labels = {}, {}, {}, []
    for group in order:
        occupied = defaultdict(list)
        candidate = 0
        local = {}
        for album in groups[group]:
            while True:
                r = CELL * (1.2 + math.sqrt(candidate) * .8)
                x, y = math.cos(candidate * GOLDEN) * r, math.sin(candidate * GOLDEN) * r
                candidate += 1
                bx, by = math.floor(x / CELL), math.floor(y / CELL)
                if all(abs(x - px) >= CELL * .91 or abs(y - py) >= CELL * .91
                       for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                       for px, py in occupied.get((bx + dx, by + dy), ())):
                    break
            occupied[(bx, by)].append((x, y))
            local[album.key] = (x, y)
        # Use actual island bounds so clusters cannot overlap, even for large groups.
        radius = max((math.hypot(x, y) for x, y in local.values()), default=0) + CELL * 1.5
        if (not group or group.startswith('__uncharted_related__:')) and centers:
            # Place uncharted islands outside the already placed clusters,
            # including any preceding uncharted islands, without overlap.
            cx = max(px + cluster_radii[other] for other, (px, _py) in centers.items()) + radius + CELL * .5
            known_y = [point[1] for other, point in centers.items()
                       if other and not other.startswith('__uncharted_related__:')]
            cy = sum(known_y) / len(known_y) if known_y else 0
        else:
            neighbors = [(centers[other], weight) for other, weight in affinity[group].items() if other in centers]
            # Keep contrasting mood families on different sides of their hub.
            # This gives them coherent regions even when each mood has few albums.
            if group.startswith(POP_MOOD) and POP_PARENT in centers:
                mood = group[len(POP_MOOD):]
                side = -1 if mood in RELATED_FAMILIES[-3] else 1 if mood in RELATED_FAMILIES[-2] else 0
                if side:
                    px, py = centers[POP_PARENT]
                    distance = radius + cluster_radii[POP_PARENT] + CELL
                    neighbors.append(((px + side * distance, py), 60))
            total = sum(weight for _, weight in neighbors)
            anchor_x = sum(center[0] * weight for center, weight in neighbors) / total if total else 0
            anchor_y = sum(center[1] * weight for center, weight in neighbors) / total if total else 0
            attempt = 0
            candidates = []
            # Compare a few valid positions rather than accepting the first spiral
            # point: this keeps related islands close without a force simulation.
            while len(candidates) < (12 if neighbors else 1):
                r = CELL * math.sqrt(attempt) * 1.8
                cx = anchor_x + math.cos(attempt * GOLDEN) * r
                cy = anchor_y + math.sin(attempt * GOLDEN) * r
                if all(math.hypot(cx - px, cy - py) >= radius + cluster_radii[other]
                       for other, (px, py) in centers.items()):
                    score = sum(weight * math.hypot(cx - point[0], cy - point[1])
                                for point, weight in neighbors)
                    candidates.append((score, attempt, cx, cy))
                attempt += 1
            _, _, cx, cy = min(candidates)
        centers[group], cluster_radii[group] = (cx, cy), radius
        labels.append((names.get(group, group), cx + CELL * .4, cy + CELL * .4))
        for key, (x, y) in local.items():
            coordinates[key] = (cx + x, cy + y)
    if not coordinates:
        return {'positions': {}, 'labels': [], 'connections': [], 'group_links': [], 'width': 1., 'height': 1.}
    left = min(min(x for x, _ in coordinates.values()), *(x for _, x, _ in labels)) - CELL * 1.5
    top = min(min(y for _, y in coordinates.values()), *(y for _, _, y in labels)) - CELL
    right = max(max(x for x, _ in coordinates.values()), *(x for _, x, _ in labels)) + CELL * 2.5
    bottom = max(max(y for _, y in coordinates.values()), *(y for _, _, y in labels)) + CELL * 2.5
    return {'positions': {key: [round(x - left, 3), round(y - top, 3)] for key, (x, y) in coordinates.items()},
            'labels': [[label, round(x - left, 3), round(y - top, 3)] for label, x, y in labels],
            'connections': [list(edge) for edge in sorted(edges)],
            'group_links': [[order.index(POP_PARENT), order.index(group)] for group in sorted(mood_groups)],
            'width': round(right - left, 3), 'height': round(bottom - top, 3)}


def cached_layout(client, section, albums, tracks, links, refresh=False, facets=None):
    fingerprint = _fingerprint(albums, tracks, links, {})
    cache = LocalCache(client)
    path = cache.root / 'album-map' / (hashlib.sha256(str(section).encode()).hexdigest() + '.json')
    if not refresh:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            layout = data['layout']
            width, height = layout['width'], layout['height']
            positions, labels = layout['positions'], layout['labels']
            def point_valid(point):
                return (isinstance(point, list) and len(point) == 2 and
                        all(type(value) in (int, float) and math.isfinite(value) for value in point) and
                        0 <= point[0] <= width and 0 <= point[1] <= height)
            if (data['version'] == VERSION and data['fingerprint'] == fingerprint and
                type(width) in (int, float) and type(height) in (int, float) and
                math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0 and
                isinstance(positions, dict) and set(positions) == {album.key for album in albums} and
                all(point_valid(point) for point in positions.values()) and
                isinstance(labels, list) and len(labels) <= MAX_GROUPS and
                isinstance(layout.get('group_links'), list) and
                all(isinstance(edge, list) and len(edge) == 2 and
                    all(type(index) is int and 0 <= index < len(labels) for index in edge)
                    for edge in layout['group_links']) and
                isinstance(layout.get('connections'), list) and
                all(isinstance(edge, list) and len(edge) == 2 and
                    edge[0] in positions and edge[1] in positions for edge in layout['connections']) and
                all(isinstance(label, list) and len(label) == 3 and isinstance(label[0], str) and
                    point_valid(label[1:]) for label in labels)):
                return layout
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
    resolved_facets = facets() if callable(facets) else (facets or {})
    layout = build_layout(albums, tracks, links, resolved_facets)
    try:
        _write_bytes(path, json.dumps({'version': VERSION, 'fingerprint': fingerprint,
                                       'layout': layout}, separators=(',', ':')).encode('utf-8'))
    except OSError:
        pass
    return layout
