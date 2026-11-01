# Plex Music: Linux prototype

A small native GTK 3 music player for a Plex Media Server. Python, GTK and GStreamer; no Electron, browser wrapper or pip environment. A narrow icon sidebar opens Now Playing, Albums, Library and Settings. A persistent bottom panel keeps playback controls available in every view.

## Ubuntu 24.04 / Xfce

Install the system dependencies:

```bash
sudo apt update
sudo apt install python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gstreamer-1.0 gir1.2-secret-1 gnome-keyring gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
```

Extract this archive, open a terminal in `plex-music-prototype`, and run:

```bash
/usr/bin/python3 player.py
```

Enter your server address, for example `http://192.168.1.10:32400`, and an X-Plex-Token. Use an HTTPS address with a valid certificate for remote connections. HTTP sends authentication and audio unencrypted and should be limited to a trusted local network. Enter the server address, not the Plex Web app URL. TLS verification remains enabled; redirects are disabled to avoid forwarding the token elsewhere.

For this prototype you can obtain a temporary token using [Plex's instructions](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/): open a library item's XML in Plex Web and copy the X-Plex-Token value from the URL. Tokens may expire. Enter it only in the app, not in chat. After a successful connection, the app saves the server address and token in your desktop keyring and reconnects on the next launch. It also restores the window size, open panel, and last queue and track position; playback returns paused. Playback state is saved when paused and periodically while playing. The keyring may ask you to unlock it. If the token expires, the connection dialog opens so you can replace it. The app uses an authentication header and does not print request URLs.

Use the sidebar icons to switch views. Now Playing centers large album art and track details. Click the artwork to switch to full-width layered waves colored from the current cover; click again to return to the art. Each wave reacts to a different frequency range, from bass to treble. The music changes each wave’s height while its shape drifts steadily across the panel. The album color gradient is dithered across the full panel for smoother transitions. Hold **Ctrl** and scroll over the artwork to resize it. In Settings, turn on **Use album art colors behind Now Playing and Albums** for a dark gradient sampled from the current cover in both views. Turn on **Show artist, album title and days since added on album covers** to add labels below each cover. These appearance choices persist between launches; missing artwork leaves the background black. Albums supports 4 to 16 covers per row: hold **Ctrl** and scroll over the wall to change the column count. The grid zoom and Now Playing artwork size persist between launches. Click a cover to flip only the artwork square and reveal a scrollable tracklist; the labels below stay in place. The flipped side uses colors from that album art and highlights the currently playing track. Click a track to play it, use ‹ Cover to flip back, or click the album title on the back for the full album view. Settings can limit the wall to one flipped album at a time, adjust album grid outer margins and cover spacing, hide the window title bar, change text size, choose a custom font, hide all tooltips, and pick an accent color. The accent can instead follow a bright color from the playing album art. With single-flip mode, the previous cover turns back after the next cover finishes flipping. The flip follows GTK frame timing for a smooth first turn. Press **F** to hide or restore the sidebar and player bar. Use the search icon in the bottom bar to show or hide the entire album toolbar; it focuses the search field when shown. Change the Plex connection in Settings. Press Enter to search album titles, and artists when the local index is enabled. Search results and artist album listings have a ◀ back button at the top left; Load more albums appears only when another page exists. Library lists songs with clickable Song, Artist, Album, and Time column headers; its left panel lists audio playlists. Its search field filters songs by title, artist, and album. Click a Library column header to sort. Right-click a header to add or hide metadata columns such as Genre, Year, Date Added, Mood, Rating, Plays, Last Played, Bitrate, and Codec, or restore the original recent order. Library and playlist views remember their own column visibility, order, widths, and sort. Loved tracks show a small red heart, and alternating rows have a subtle tint. Library loads the full song list and caches it locally for fast filtering on later launches. The cache refreshes from Plex in the background; after this update it rebuilds once to include the extra metadata fields. Double-click a song to play it and the loaded songs after it. Playlist tracks retain Plex's playlist order. Use the + button in the playlist panel to name a playlist and choose its first song, then drag more songs from Library onto the playlist to add them. Albums load in pages of 100; Library displays all songs in the selected list. Settings also shows the current server and lets you change the connection. The compact player bar has borderless icon controls and a bold track title. Its thicker, handle-free seek timeline forms the border above the bar and moves smoothly during playback. Previous, Play/Pause and Next stay centered as the window resizes. Click the compact cover or track title to switch to Now Playing and click again to return to the previous panel; click the artist name for that artist’s albums. Press **Space** to play or pause while the app is focused, except while typing in a text field. Press **1**, **2**, **3**, or **4** for Now Playing, Albums, Library, or Settings. Right-click for a context menu with playback and navigation actions; right-click an album cover for Show Artist Albums and Show in library. Artist names also open the artist’s albums. Show in library displays that album’s tracks in the Library view. When the title bar is hidden, use the context menu’s Quit item or your window manager’s close shortcut. Previous/Next operate on the current queue. Shuffle randomly picks another track and can revisit earlier tracks; turn it off for normal order. Repeat restarts the queue at its end.

Album artwork, sampled color palettes, rendered gradient backgrounds, and the complete Library song index are cached locally under `~/.cache/plex-music-prototype` and reused across launches. The cache is separated by server login. In Settings, enable **Cache an album index for title and artist search** to download an index of the selected music library and search album titles and artists locally. The index is kept between launches; use **Refresh search index** after adding or removing albums on Plex. Turning the option off uses Plex search and removes the current login's cached search index.

Right-click a Library song to play it, love or unlove it on Plex, or show its artist's albums. Now Playing artwork can be enlarged to 1000 pixels with Ctrl+scroll. Changing tracks within the same album keeps the existing artwork gradient visible. At launch, the main panel displays Loading and blocks input until the initial album view is ready or the connection dialog opens.

The player exposes MPRIS controls on the desktop session bus. Play/pause, next, previous and stop media keys can control playback, and compatible desktop widgets can show track details and seek. On Xfce, open **Settings → Global keyboard shortcuts** to see the current bindings, record a new key combination, or clear one. The editor preserves shortcuts used by other Xfce commands. `bash setup_xfce_media_keys.sh` can still assign unused default media keys in one step. The player must be running for its media key commands to work.

## UI

- Narrow icon sidebar for Now Playing, Albums, Library and Settings
- Centered large artwork in the Now Playing view
- Clickable artwork that switches to full-width, audio-reactive layered waves in the cover's colors
- Ctrl+wheel zoom from 16 to 4 album columns and sizing for Now Playing artwork
- Optional album art color gradient behind Now Playing and the album wall
- Optional artist, album title and days since added below each cover
- Xfce global keyboard shortcut editor in Settings
- Album wall zoom from 16 to 4 columns, with centered titles and artwork-only flip cards
- Searchable song table with clickable sort headers, extra right-click sorts, and a separate playlist panel
- Compact playback bar with centered transport icons, a full-width seek border, song info, volume, shuffle, repeat and search
- Four background artwork workers; server-sized thumbnails and placeholders for missing artwork

## Included

- Music-library picker, paginated album browser and paginated song library
- Read-only audio playlist browsing and playback
- Album and artist search, artwork and disc/track numbers
- Direct audio streaming, pause, previous/next, seek and volume
- MPRIS media keys and desktop playback controls
- Automatic next track, shuffle and album repeat
- Background network requests, timeouts and stale-result checks
- Generic errors that avoid exposing tokens

## Prototype boundaries

Streams the original file through GStreamer. There is no Plex transcoding fallback, PIN sign-in, automatic server discovery, offline download, playlist editor, playback reporting/scrobbling or gapless playback yet. A manually reachable server URL is required. Saved login requires a working desktop keyring. MPRIS requires a desktop session bus. Codec support depends on installed GStreamer plugins. Seek support depends on the format and HTTP source.

The code is not affiliated with Plex. Authentication, XML parsing, pagination, search encoding, stream resolution and missing-media handling are tested against a local mock server. Song sorting and audio playlists were also checked with a local Plex server. GTK view rendering was checked on a Linux desktop.

## Checks

```bash
/usr/bin/python3 -m unittest -v test_art_zoom.py test_appearance.py test_client.py test_credentials.py test_player_controls.py test_library_catalog.py test_session.py test_shortcuts.py test_waveform.py
dbus-run-session -- /usr/bin/python3 -m unittest -v test_mpris.py
/usr/bin/python3 -m py_compile player.py plex_client.py credentials.py mpris.py appearance.py album_card.py session.py shortcuts.py waveform.py
```

Suggested first live check: connect, select a music library, play an album, pause/resume, seek, skip, and let one track finish. Try a second album while the first plays, then a bad token and an unavailable server. A large library should expose Load more albums.

## Implementation references

- [PlexAPI music model documentation](https://python-plexapi.readthedocs.io/en/latest/modules/audio.html)
- [PlexAPI library documentation](https://python-plexapi.readthedocs.io/en/latest/modules/library.html)
- [GStreamer playbin](https://gstreamer.freedesktop.org/documentation/playback/playbin.html)

The client uses Python's standard HTTP/XML libraries directly; PlexAPI is not a dependency.
