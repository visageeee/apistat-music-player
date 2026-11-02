# Apistat

A small native GTK 3 music player for a Plex Media Server. Python, GTK and GStreamer; no Electron, browser wrapper or pip environment. A narrow icon sidebar opens Now Playing, Albums, Library, Play Queue and Settings. A persistent bottom panel keeps playback controls available in every view.

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

## Windows build

GitHub Actions builds a portable 64-bit Windows folder on pushes and pull requests. Open the **Windows build** workflow run, download the `Apistat-Windows-x64` artifact, extract it, and run `Apistat.exe`. Keep the whole extracted folder together. `Apistat-Debug.exe` runs the same app with a console for troubleshooting. This is an unsigned development build; Windows may show a SmartScreen prompt. The app stores Plex server and linked-device tokens in Windows Credential Manager, with no plaintext fallback. Settings and caches are kept under the Windows user profile. In-window shortcuts work; the global shortcut editor and MPRIS integration remain Linux/Xfce features.

To build locally, install [MSYS2 UCRT64](https://www.msys2.org/), install the packages listed in [windows.yml](.github/workflows/windows.yml), then run `pyinstaller --noconfirm --clean windows/Apistat.spec` from the repository root in the UCRT64 shell. `python player.py --self-test` checks the GTK/GStreamer source environment; `dist/Apistat/Apistat.exe --self-test` checks the bundled media elements. The workflow also runs the unit tests before uploading its artifact. Playback and Plexamp remote control still need a hands-on check on a Windows desktop with a Plex server; the runner cannot verify audio output or phone discovery.

In the connection dialog, choose **Choose from Plex account…** to link your Plex account at [plex.tv/link](https://plex.tv/link) and select one of its servers. The app checks the server's published local, direct remote, and relay addresses in that order, verifies its identity, and uses the server-specific token supplied by Plex. You can choose a different server later in **Settings → Connection**. The account link also works when Plexamp remote control is off. Both the account link and selected server login are stored in the platform credential store, without a plaintext fallback.

For manual connection, enter your server address, for example `http://192.168.1.10:32400`, and an X-Plex-Token. Use an HTTPS address with a valid certificate for remote connections. HTTP sends authentication and audio unencrypted and should be limited to a trusted local network. Enter the server address, not the Plex Web app URL. TLS verification remains enabled; redirects are disabled to avoid forwarding the token elsewhere.

For this prototype you can obtain a temporary token using [Plex's instructions](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/): open a library item's XML in Plex Web and copy the X-Plex-Token value from the URL. Tokens may expire. Enter it only in the app, not in chat. After a successful connection, the app saves the server address and token in your desktop keyring and reconnects on the next launch. It also restores the window size, open panel, and last queue and track position; playback returns paused. Playback state is saved when paused and periodically while playing. The keyring may ask you to unlock it. If the token expires, the connection dialog opens so you can replace it. The app uses an authentication header and does not print request URLs.

Use the sidebar icons to switch views. Now Playing centers large album art and track details. Click the artwork to switch to full-width layered waves colored from the current cover; click again to return to the art. Each wave reacts to a different frequency range, from bass to treble. The music changes each wave’s height while its shape drifts steadily across the panel. The album color gradient is dithered across the full panel for smoother transitions. Hold **Ctrl** and scroll over the artwork to resize it. In Settings, turn on **Use album art colors behind Now Playing and Albums** for a dark gradient sampled from the current cover in both views. Turn on **Show artist, album title and days since added on album covers** to add labels below each cover. These appearance choices persist between launches; missing artwork leaves the background black. Albums supports 4 to 16 covers per row: hold **Ctrl** and scroll over the wall to change the column count. The grid zoom and Now Playing artwork size persist between launches. Click a cover to flip only the artwork square and reveal a scrollable tracklist; the labels below stay in place. The flipped side uses colors from that album art and highlights the currently playing track. Click a track to play it, use ‹ Cover to flip back, or click the album title on the back for the full album view. Settings has Connection, Appearance, Library, and Keyboard tabs. Appearance offers Dark (the original palette), Black (pure black surfaces without artwork gradients), and Light (a pale palette with readable artwork colors). The selected theme and tab persist between launches. Settings can limit the wall to one flipped album at a time, adjust album grid outer margins and cover spacing, hide the window title bar, change text size, choose a custom font, hide all tooltips, and pick an accent color. The accent can instead follow a bright color from the playing album art. With single-flip mode, the previous cover turns back after the next cover finishes flipping. The flip follows GTK frame timing for a smooth first turn. Press **F** to hide or restore the sidebar and player bar. Use the search icon in the bottom bar to show or hide the entire album toolbar; it focuses the search field when shown. Change the Plex connection in Settings. Press Enter to search album titles, and artists when the local index is enabled. Search results and artist album listings have a ◀ back button at the top left; More albums load automatically as you reach the bottom of the wall. Library lists songs with clickable Song, Artist, Album, and Time column headers; its left panel lists audio playlists. Its search field filters songs by title, artist, and album. Click a Library column header to sort. Right-click a header to add or hide metadata columns such as Genre, Year, Date Added, Mood, Rating, Plays, Last Played, Bitrate, and Codec, or restore the original recent order. Library and playlist views remember their own column visibility, order, widths, and sort. Loved tracks show a small red heart, and alternating rows have a subtle tint. Library loads the full song list and caches it locally for fast filtering on later launches. A fresh cached song index is reused without a server query; it refreshes after one hour or when playlist edits require an update. The three most recently opened Library list views also stay in memory, including their loaded rows, so switching back does not rebuild the table. An interrupted list continues from its existing rows. Double-click a song to play it and the loaded songs after it. Playlist tracks retain Plex's playlist order. Use the + button in the playlist panel to name a playlist and choose its first song, then drag more songs from Library onto the playlist to add them. Albums load in pages of 100; Library displays all songs in the selected list. Settings also shows the current server and lets you change the connection. The compact player bar has borderless icon controls and a bold track title. Its thicker, handle-free seek timeline forms the border above the bar and moves smoothly during playback. The timeline has an invisible pointer area below the visible line for easier scrubbing. Settings can replace it with a taller waveform of the current song; the first play decodes a second, silent stream in the background and later plays reuse cached peaks. Previous, Play/Pause and Next stay centered as the window resizes. Click the compact cover or track title to switch to Now Playing and click again to return to the previous panel; click the artist name for that artist’s albums. Press **Space** to play or pause while the app is focused, except while typing in a text field. Drag sidebar icons to rearrange them; their order persists across launches. Press **1** through **5** to open the corresponding sidebar panels from top to bottom. Right-click for a context menu with playback and navigation actions; right-click an album cover for Show Artist Albums and Show in library. Artist names also open the artist’s albums. Show in library displays that album’s tracks in the Library view. Drag any empty space in the window to move it. When the title bar is hidden, use the context menu’s Quit item or your window manager’s close shortcut. The Play Queue sidebar button shows the current and upcoming tracks in a resizable table. Shift-click to select a range in the Library or Play Queue, drag selected tracks together, or press Backspace to remove selected queue tracks. Drag Library songs, flipped-album tracks, full-album tracks, or album covers onto the queue icon to add them. Right-click a song or album for Add to queue and Play next. Previous/Next operate on the current queue. Shuffle randomly picks another track and can revisit earlier tracks; turn it off for normal order. Repeat restarts the queue at its end.

The first page of each album sort, its artwork, sampled color palettes, rendered gradient backgrounds, song waveform previews, and the complete Library song index are cached locally under `~/.cache/plex-music-prototype` and reused across launches. The cache is separated by server login. In Settings, enable **Cache an album index for title and artist search** to download an index of the selected music library and search album titles and artists locally. The index is kept between launches; use **Refresh search index** after adding or removing albums on Plex. Turning the option off uses Plex search and removes the current login's cached search index.

Right-click a Library song to play it, add it to the play queue, play it next, add up to ten similar songs, love or unlove it on Plex, or show its artist's albums. Similar songs use Plex sonic matches and a varied sample from Plex genre, mood, and artist filters. Picks are limited per album and artist; tracks without enough matches may add fewer than ten. Now Playing artwork can be enlarged to 1000 pixels with Ctrl+scroll. Changing tracks within the same album keeps the existing artwork gradient visible. At launch, the main panel displays Loading and blocks input until the initial album view is ready or the connection dialog opens.

The player exposes MPRIS controls on the desktop session bus. Play/pause, next, previous and stop media keys can control playback, and compatible desktop widgets can show track details and seek. On Xfce, open **Settings → Global keyboard shortcuts** to see the current bindings, record a new key combination, or clear one. The editor preserves shortcuts used by other Xfce commands. `bash setup_xfce_media_keys.sh` can still assign unused default media keys in one step. The player must be running for its media key commands to work.

## Plexamp remote control

In **Settings → Connection**, enable **Allow Plexamp remote control** and choose a player name. Remote control is off by default. The app opens a Companion HTTP receiver on local TCP port 32500 (or an available port if that is occupied) and advertises it with Plex GDM on UDP 32412/32413. This is intended for phones on the same local network; do not forward the port on your router. A local firewall must allow the receiver's TCP port and GDM UDP traffic. The player keeps its own GTK interface and uses GStreamer for playback.

Select **Link Plex account…**, enter the displayed code at [plex.tv/link](https://plex.tv/link), and leave the dialog open until the status says linked. Linking registers the same persistent player identifier used by GDM and the HTTP receiver, then publishes the current local connection URI to plex.tv. The app checks for local IP changes every 30 seconds and republishes when necessary. The device token is stored only in the desktop Secret Service keyring; if no keyring is available, linking fails with an explicit message. **Unlink** deletes the registered device and clears that token. Disabling remote control stops the listener and GDM advertisement without erasing the link.

The receiver accepts music from the Plex server configured in the app. After account linking, controllers on the computer's advertised local subnet can control it even if Plexamp omits a token or sends one the receiver cannot verify. **Any device on that subnet can then control playback while remote control is enabled.** Unlinked receivers and controllers on other private subnets still require a valid Plex token. Requests require a controller identifier, the correct target identifier when supplied, and ordered `commandID` values. Controller-supplied server URLs and media tokens are ignored; only validated metadata paths are requested from the configured server. Its advertised capabilities are `timeline,playback`; it handles tracks, albums, playlists and existing Plex play queues through `playMedia`, up to 1000 tracks. Long queues beyond that limit need live compatibility work.

### Phone check

1. Start the Linux player, connect to your Plex music server, enable remote control and link the same Plex account used by the phone. On iOS, allow Plexamp Local Network access. Keep phone and computer on the same LAN.
2. Open Plexamp on Android or iOS, open its player picker and select the Linux player by the chosen name. If it does not appear, check the link status, local firewall, and `http://<computer LAN IP>:<shown port>/resources` from another LAN device.
3. Send an album from the phone. Confirm the requested track begins at the requested position, with artwork and queue in the Linux window.
4. From the phone, pause, resume, skip backward and forward, seek, and adjust volume. Then use the Linux controls and confirm Plexamp's timeline and track update.
5. Let a track end and confirm the next queue item starts. Try a Plex play queue with several tracks and inspect skip behavior.
6. Restart the Linux app and confirm the player appears under the same name and identifier. Disable remote control and confirm the receiver no longer answers and the player disappears from local discovery.

These phone steps require a real Plex account, server and phone. The automated suite uses mock Plex metadata, plex.tv responses and local HTTP requests; it cannot establish Android or iOS picker compatibility by itself.

If Plexamp lists the player but says **Could not connect to player**, leave the desktop app open and try the exact `http://<LAN address>:<port>/resources` address shown in Settings from Safari on the phone. Settings also shows the last request path and HTTP status without recording tokens or query strings. If Safari cannot reach it, allow incoming TCP on that port from your LAN. For example, on a `192.168.0.0/24` network with port 32500 and UFW:

```bash
sudo ufw allow from 192.168.0.0/24 to any port 32500 proto tcp
```

Use your own LAN range and the port shown by the app. Do not open the port to the internet. If Settings still shows HTTP 401 when Plexamp selects the player, confirm that Settings says **linked to Plex** and that the phone is on the same subnet as the Linux computer. The local subnet fallback applies only while the device link is active.

## UI

- Narrow icon sidebar for Now Playing, Albums, Library, Play Queue and Settings
- Centered large artwork in the Now Playing view
- Clickable artwork that switches to full-width, audio-reactive layered waves in the cover's colors
- Ctrl+wheel zoom from 16 to 4 album columns and sizing for Now Playing artwork
- Optional album art color gradient behind Now Playing and the album wall
- Optional artist, album title and days since added below each cover
- Xfce global keyboard shortcut editor in Settings
- Album wall zoom from 16 to 4 columns, with a pinned full-width sort bar, centered titles and artwork-only flip cards
- Searchable song table with clickable sort headers, extra right-click sorts, and a separate playlist panel
- Compact playback bar with centered transport icons, a full-width seek border, song info, volume, shuffle, repeat and search
- Four background artwork workers; server-sized thumbnails and placeholders for missing artwork

## Included

- Music-library picker, automatically paginated album browser and song library
- Read-only audio playlist browsing and playback
- Album and artist search, artwork and disc/track numbers
- Direct audio streaming, pause, previous/next, seek and volume
- MPRIS media keys and desktop playback controls
- Automatic next track, shuffle and album repeat
- Background network requests, timeouts and stale-result checks
- Generic errors that avoid exposing tokens

## Prototype boundaries

Streams the original file through GStreamer. There is no Plex transcoding fallback, offline download, playback reporting/scrobbling or gapless playback yet. Account server selection depends on the addresses Plex publishes; a server with no reachable published address still needs a working manual URL or Plex Remote Access/Relay configuration. Saved login and Plexamp account linking require a working platform credential store. MPRIS requires a desktop session bus. Codec support depends on installed GStreamer plugins. Seek support depends on the format and HTTP source. Plex Companion compatibility is based on the published protocol and current third-party implementations; live Plexamp Android and iOS testing is still required.

The code is not affiliated with Plex. Authentication, XML parsing, pagination, search encoding, stream resolution and missing-media handling are tested against a local mock server. Song sorting and audio playlists were also checked with a local Plex server. GTK view rendering was checked on a Linux desktop.

Companion support follows the Plex API documentation and independently reads the Music Assistant Plex Connect and plexdlnaplayer implementations for compatibility. No third-party receiver code is copied into this project.

## Checks

```bash
/usr/bin/python3 -m unittest -v test_art_zoom.py test_appearance.py test_client.py test_credentials.py test_player_controls.py test_library_catalog.py test_session.py test_shortcuts.py test_waveform.py
dbus-run-session -- /usr/bin/python3 -m unittest discover -v
/usr/bin/python3 -m py_compile player.py plex_client.py plex_resources.py companion.py companion_account.py companion_config.py
```

Suggested first live check: connect, select a music library, play an album, pause/resume, seek, skip, and let one track finish. Try a second album while the first plays, then a bad token and an unavailable server. A large library should load more albums automatically near the bottom of the wall.

## Implementation references

- [PlexAPI music model documentation](https://python-plexapi.readthedocs.io/en/latest/modules/audio.html)
- [PlexAPI library documentation](https://python-plexapi.readthedocs.io/en/latest/modules/library.html)
- [GStreamer playbin](https://gstreamer.freedesktop.org/documentation/playback/playbin.html)
- [Plex Companion remote control API](https://github.com/plexinc/plex-media-player/wiki/Remote-control-API)
- [Plex developer documentation for server resources and identity](https://developer.plex.tv/pms/)
- [Music Assistant Plex Connect implementation](https://github.com/music-assistant/server/tree/dev/music_assistant/providers/plex_connect)
- [iOS Plexamp device registration findings](https://github.com/music-assistant/support/issues/5782)

The client uses Python's standard HTTP/XML libraries directly; PlexAPI is not a dependency.
