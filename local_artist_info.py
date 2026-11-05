"""On-demand artist descriptions from MusicBrainz and English Wikipedia."""
import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

_lock = threading.Lock()
_last_musicbrainz_request = 0.0
_USER_AGENT = 'Apistat/1.0 (https://github.com/visageeee/apistat-music-player)'


def _json(url, musicbrainz=False):
    global _last_musicbrainz_request
    try:
        if musicbrainz:
            # MusicBrainz requests must be at least one second apart, including
            # requests from separate info panels or libraries.
            with _lock:
                delay = 1.1 - (time.monotonic() - _last_musicbrainz_request)
                if delay > 0:
                    time.sleep(delay)
                _last_musicbrainz_request = time.monotonic()
                with urlopen(Request(url, headers={'User-Agent': _USER_AGENT, 'Accept': 'application/json'}), timeout=8) as response:
                    return json.loads(response.read(512 * 1024))
        with urlopen(Request(url, headers={'User-Agent': _USER_AGENT, 'Accept': 'application/json'}), timeout=8) as response:
            return json.loads(response.read(512 * 1024))
    except (OSError, ValueError, HTTPError, URLError) as exc:
        raise RuntimeError('Artist information service is unavailable') from exc


def lookup_artist(name, album=''):
    name = str(name or '').strip()
    if not name or len(name) > 200:
        return None
    escaped = name.replace('\\', '\\\\').replace('"', '\\"')
    query = urlencode({'query': 'artist:"' + escaped + '"', 'fmt': 'json', 'limit': 25})
    result = _json('https://musicbrainz.org/ws/2/artist/?' + query, True)
    matches = [artist for artist in result.get('artists', [])
               if artist.get('name', '').casefold() == name.casefold()]
    # Use the release's artist credit to distinguish artists with the same
    # name; a name match alone is not enough to choose a biography safely.
    if len(matches) > 1 and album and len(album) <= 200:
        escaped_album = str(album).replace('\\', '\\\\').replace('"', '\\"')
        release_query = urlencode({'query': 'artist:"' + escaped + '" AND release:"' +
                                   escaped_album + '"', 'fmt': 'json', 'limit': 100})
        releases = _json('https://musicbrainz.org/ws/2/release/?' + release_query, True)
        candidate_ids = {artist.get('id') for artist in matches}
        credited = set()
        for release in releases.get('releases', []):
            if release.get('title', '').casefold() != str(album).casefold():
                continue
            for credit in release.get('artist-credit', []):
                if isinstance(credit, dict):
                    identifier = credit.get('artist', {}).get('id')
                    if identifier in candidate_ids:
                        credited.add(identifier)
        matches = [artist for artist in matches if artist.get('id') in credited]
    if len(matches) != 1:
        return None
    identifier = matches[0].get('id', '')
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', identifier):
        return None
    artist = _json('https://musicbrainz.org/ws/2/artist/' + identifier + '?inc=url-rels&fmt=json', True)
    title = None
    wikidata_ids = []
    for relation in artist.get('relations', []):
        link = relation.get('url', {}).get('resource', '')
        parsed = urlsplit(link)
        if parsed.scheme != 'https' or parsed.query or parsed.fragment:
            continue
        if (relation.get('type') == 'wikipedia' and parsed.netloc == 'en.wikipedia.org'
                and parsed.path.startswith('/wiki/')):
            title = unquote(parsed.path[len('/wiki/'):]).replace('_', ' ')
            break
        if relation.get('type') == 'wikidata' and parsed.netloc == 'www.wikidata.org':
            match = re.fullmatch(r'/wiki/(Q[1-9][0-9]*)', parsed.path)
            if match:
                wikidata_ids.append(match.group(1))
    if not title and wikidata_ids:
        entity_id = wikidata_ids[0]
        params = urlencode({'action': 'wbgetentities', 'ids': entity_id, 'props': 'sitelinks',
                            'sitefilter': 'enwiki', 'format': 'json'})
        entities = _json('https://www.wikidata.org/w/api.php?' + params)
        title = (entities.get('entities', {}).get(entity_id, {}).get('sitelinks', {})
                 .get('enwiki', {}).get('title'))
    if not title:
        return None
    params = urlencode({'action': 'query', 'format': 'json', 'prop': 'extracts',
                        'exintro': '1', 'explaintext': '1', 'redirects': '1', 'titles': title})
    wiki = _json('https://en.wikipedia.org/w/api.php?' + params)
    pages = wiki.get('query', {}).get('pages', {})
    for page in pages.values():
        summary = page.get('extract', '').strip()
        if summary:
            canonical = page.get('title', title).replace(' ', '_')
            return summary, 'https://en.wikipedia.org/wiki/' + quote(canonical, safe='()_')
    return None
