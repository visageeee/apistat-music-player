# Plex Music: Linux prototype

A small native GTK 3 music player for a Plex Media Server. Python, GTK and GStreamer; no Electron, browser wrapper or pip environment. The library opens as a wall of album covers on black, sorted by most recently added. A persistent bottom panel shows the playing track, album artwork and controls.

## Ubuntu 24.04 / Xfce

Install the system dependencies:

```bash
sudo apt update
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
```

Extract this archive, open a terminal in `plex-music-prototype`, and run:

```bash
/usr/bin/python3 player.py
```

Enter your server address, for example `http://192.168.1.10:32400`, and an X-Plex-Token. Use an HTTPS address with a valid certificate for remote connections. HTTP sends authentication and audio unencrypted and should be limited to a trusted local network. Enter the server address, not the Plex Web app URL. TLS verification remains enabled; redirects are disabled to avoid forwarding the token elsewhere.

For this prototype you can obtain a temporary token using [Plex's instructions](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/): open a library item's XML in Plex Web and copy the X-Plex-Token value from the URL. Tokens may expire. Enter it only in the app, not in chat. The app keeps the token in memory, uses an authentication header, and does not save credentials or print request URLs.

Select a music library, then click an album cover to open its tracks. Hover a cover to see its title and artist. Use All albums to return to the wall. The bottom Hide library / Show library button toggles the library without interrupting playback or losing your place. Double-click a track or click Play album. Search filters **album titles** and runs when you press Enter. Albums load in pages of 100. Changing the selected album leaves the current playback queue intact. Previous/Next operate on that queue. Shuffle randomly picks another track and can revisit earlier tracks; turn it off for normal album order. Repeat album restarts the queue at its end.

## UI update

Replace the old extracted folder with this version and run `player.py` as before. No additional dependencies are required. The first connection still requires the server address and token.

- Responsive wall of 160-pixel album covers against black
- Newest additions first, including search results
- Hover titles, click-through album details and a back button
- Persistent bottom panel with now-playing art, track/artist/album, Play/Pause and Show/Hide library
- Existing previous/next, volume, seek, shuffle and repeat controls retained
- Four background artwork workers; server-sized thumbnails and placeholders for missing artwork

## Included

- Music-library picker and paginated album browser
- Album-title search, artwork and disc/track numbers
- Direct audio streaming, pause, previous/next, seek and volume
- Automatic next track, shuffle and album repeat
- Background network requests, timeouts and stale-result checks
- Generic errors that avoid exposing tokens

## Prototype boundaries

Streams the original file through GStreamer. There is no Plex transcoding fallback, PIN sign-in, automatic server discovery, persistent credentials, offline download, playlist editor, playback reporting/scrobbling, gapless playback or MPRIS/media-key support yet. A manually reachable server URL is required. Codec support depends on installed GStreamer plugins. Seek support depends on the format and HTTP source.

The code is not affiliated with Plex. Authentication, XML parsing, pagination, search encoding, stream resolution and missing-media handling are tested against a local mock server. No real Plex server was available during development. GTK rendering and audible playback still need testing on a Linux desktop.

## Checks

```bash
/usr/bin/python3 -m unittest -v test_client.py
/usr/bin/python3 -m py_compile player.py plex_client.py
```

Suggested first live check: connect, select a music library, play an album, pause/resume, seek, skip, and let one track finish. Try a second album while the first plays, then a bad token and an unavailable server. A large library should expose Load more albums.

## Implementation references

- [PlexAPI music model documentation](https://python-plexapi.readthedocs.io/en/latest/modules/audio.html)
- [PlexAPI library documentation](https://python-plexapi.readthedocs.io/en/latest/modules/library.html)
- [GStreamer playbin](https://gstreamer.freedesktop.org/documentation/playback/playbin.html)

The client uses Python's standard HTTP/XML libraries directly; PlexAPI is not a dependency.
