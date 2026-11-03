"""Validated Plex music style and mood categories."""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit


FACET_SOURCES = (
    ('style', 8, 'artist.style'),
    ('style', 9, 'album.style'),
    ('mood', 9, 'album.mood'),
    ('mood', 10, 'track.mood'),
)
ALLOWED_FILTERS = {source[2] for source in FACET_SOURCES}


@dataclass(frozen=True)
class MusicFacet:
    field: str
    title: str
    filters: tuple[tuple[str, int], ...]

    def __post_init__(self):
        if (self.field not in ('style', 'mood') or not self.title.strip() or
                not self.filters or any(name not in ALLOWED_FILTERS or
                                        (name.endswith('.style') != (self.field == 'style')) or
                                        type(tag_id) is not int or tag_id <= 0
                                        for name, tag_id in self.filters)):
            raise ValueError('Invalid Plex music category')

    @property
    def cache_key(self):
        return 'facet:' + self.field + ':' + ','.join(
            f'{name}:{tag_id}' for name, tag_id in self.filters)


def category_id(element, field):
    """Read a tag ID from a Plex Directory; never follow its supplied URL."""
    for candidate in (element.get('key'), element.get('id')):
        if candidate and candidate.isdigit() and int(candidate) > 0:
            return int(candidate)
    for attribute in ('fastKey', 'key'):
        value = element.get(attribute, '')
        if not value.startswith('/library/sections/'):
            continue
        query = parse_qs(urlsplit(value).query)
        for name in (field, f'artist.{field}', f'album.{field}', f'track.{field}'):
            candidates = query.get(name, [])
            if len(candidates) == 1 and candidates[0].isdigit() and int(candidates[0]) > 0:
                return int(candidates[0])
    return None


def merge_categories(responses):
    """Combine album/artist/track category directories by server title."""
    found = {}
    for field, _media_type, filter_field, root in responses:
        for element in root.findall('Directory'):
            title = (element.get('title') or element.get('tag') or '').strip()
            tag_id = category_id(element, field)
            if not title or tag_id is None:
                continue
            key = field, title.casefold()
            entry = found.setdefault(key, [title, set()])
            entry[1].add((filter_field, tag_id))
    return tuple(sorted((MusicFacet(field, title, tuple(sorted(filters)))
                         for (field, _key), (title, filters) in found.items()),
                        key=lambda facet: (facet.field, facet.title.casefold())))
    return result
