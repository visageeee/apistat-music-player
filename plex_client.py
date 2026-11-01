"""Small read-only Plex music client. No third-party Python dependencies."""
from dataclasses import dataclass
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
import xml.etree.ElementTree as ET


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward authentication to another host.
        return None


@dataclass
class Item:
    key: str
    title: str
    artist: str = ''
    year: str = ''
    duration: int = 0
    number: str = ''
    thumb: str = ''


class PlexClient:
    def __init__(self, address, token):
        address = address.strip().rstrip('/')
        parsed = urlsplit(address)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Enter a server URL such as http://192.168.1.10:32400')
        self.address, self.token = address, token.strip()
        if not self.token:
            raise ValueError('Enter a Plex token.')
        self.opener = build_opener(NoRedirect())

    def url(self, path, **params):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('Invalid Plex resource path')
        return self.address + path + ('?' + urlencode(params) if params else '')

    def get(self, path, **params):
        req = Request(self.url(path, **params), headers={
            'X-Plex-Token': self.token, 'X-Plex-Product': 'Plex Music Prototype',
            'X-Plex-Client-Identifier': 'linux-plex-music-prototype',
            'Accept': 'application/xml'})
        with self.opener.open(req, timeout=15) as response:
            return response.read()

    def xml(self, path, **params):
        return ET.fromstring(self.get(path, **params))

    def sections(self):
        return [(x.attrib['key'], x.get('title', 'Music'))
                for x in self.xml('/library/sections').findall('Directory')
                if x.get('type') == 'artist']

    def albums(self, section, start=0, title=''):
        params = {'type': 9, 'sort': 'addedAt:desc',
                  'X-Plex-Container-Start': start, 'X-Plex-Container-Size': 100}
        if title:
            params['title'] = title
        root = self.xml('/library/sections/' + section + '/all', **params)
        items = [Item(x.attrib['key'], x.get('title', 'Untitled'),
                      x.get('parentTitle', ''), x.get('year', ''), thumb=x.get('thumb', ''))
                 for x in root.findall('Directory')]
        total = int(root.get('totalSize', start + len(items)))
        return items, total

    def tracks(self, album):
        path = album.key if album.key.endswith('/children') else album.key + '/children'
        return [Item(x.attrib['key'], x.get('title', 'Untitled'),
                     x.get('originalTitle') or x.get('grandparentTitle', album.artist),
                     duration=int(x.get('duration', 0)),
                     number=f"{x.get('parentIndex', '1')}.{x.get('index', '0')}")
                for x in self.xml(path).findall('Track')]

    def stream(self, track):
        part = self.xml(track.key).find('.//Media/Part')
        if part is None or not part.get('key'):
            raise ValueError('This track has no playable file.')
        return self.url(part.attrib['key'])
