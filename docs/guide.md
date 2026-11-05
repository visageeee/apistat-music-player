# Apistat guide

Installation details, features, troubleshooting, development builds and protocol notes.

## Ubuntu 24.04 / Xfce

Install the system dependencies:

```bash
sudo apt update
sudo apt install python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gstreamer-1.0 gir1.2-secret-1 gnome-keyring gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
```

Extract this archive, open a terminal in the extracted project directory, and run:

```bash
/usr/bin/python3 player.py
```

To record manual window-resize diagnostics, start the player from a terminal:

```bash
/usr/bin/python3 player.py --resize-log /tmp/apistat-resize.jsonl
```

Load the library, switch to the panel you want to test, and resize the window normally.
Each resize gesture is appended to the log after a short pause or when the player closes.
Repeat with different panels or the frosted effect on and off as needed. The log records
window dimensions and timing, panel and theme names, timeline mode, album and row counts,
main-loop heartbeat gaps, allocation sizes, and inclusive GTK draw times; it does not
record song titles, server addresses, or tokens.
Frame gaps reflect GTK frame callbacks and do not directly measure display presentation.
Remove the file to start a fresh log, and omit `--resize-log` to disable the instrumentation.

## Draft release builds

Run **Actions → Build all platforms and draft release → Run workflow** on the desired branch. The workflow builds a Linux x86-64 Flatpak, a Windows x64 ZIP, and separate Apple Silicon and Intel macOS ZIPs in parallel. All four packages and the draft release share the UTC build date and time in their names. The draft is created only after all builds and runtime checks succeed, and targets the tested commit; the packages are also available as workflow artifacts. The packages are not signed for public distribution, and the macOS packages are not notarized. Edit the draft before publishing it.

## Flatpak build

The **Flatpak build** GitHub Actions workflow runs manually. After the workflow and the application files have been committed and pushed, open **Actions → Flatpak build → Run workflow**. Download the `Apistat-Flatpak-x86_64` artifact from the completed run and extract `Apistat.flatpak`. It is an unsigned development build and is not published to Flathub.

Install the bundle and the GNOME 50 runtime from Flathub:

```bash
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user ./Apistat.flatpak
flatpak run org.apistat.Apistat
```

For a local build, install Flatpak, flatpak-builder, and the `org.gnome.Sdk//50` and `org.gnome.Platform//50` runtimes, then run:

```bash
flatpak-builder --user --install-deps-from=flathub --repo=repo flatpak_app org.apistat.Apistat.json
flatpak build-bundle repo Apistat.flatpak org.apistat.Apistat master --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo
```

The package includes Mutagen for embedded ID3 tags. Its sandbox permits networking for Plex and optional Plexamp discovery, audio output, graphics, the desktop keyring, and Apistat's MPRIS name. Settings and caches are isolated under `~/.var/app/org.apistat.Apistat`; the Flatpak does not automatically import the source installation's settings or cache. The Global Shortcuts portal depends on desktop support; the Xfce command-line fallback is not bundled. Audio playback, account linking, desktop integrations, and Plexamp discovery still need testing on the target desktop.

## Experimental macOS build

The **Experimental macOS build** GitHub Actions workflow builds separate unsigned Apple Silicon and Intel `.app` ZIPs on their respective macOS runners. The Intel build uses MacPorts because current Homebrew packages may need to be built from source on Intel Macs. This is an early test build: it requires hands-on verification of playback, Keychain, networking and Plexamp discovery on a Mac. macOS may block the unsigned, non-notarized app. The app uses macOS Keychain for server and Plex account tokens; global shortcuts and native media-key integration are not yet supported. The four-platform draft release also runs this workflow for both Mac architectures.

## Windows build

GitHub Actions can build a portable 64-bit Windows folder using the manually started Windows build workflow or the combined draft release workflow. Open the **Windows build** workflow run, download the `Apistat-Windows-x64` artifact, extract it, and run `Apistat.exe`. Keep the whole extracted folder together. The executable uses the Apistat icon, and the bundled PNG supplies placeholder artwork. This is an unsigned development build; Windows may show a SmartScreen prompt. The app stores Plex server and linked-device tokens in Windows Credential Manager, with no plaintext fallback. Settings and caches are kept under the Windows user profile. In-window shortcuts work; the global shortcut editor and MPRIS integration remain Linux-only features.

To build locally, install [MSYS2 UCRT64](https://www.msys2.org/), install the packages listed in [windows.yml](../.github/workflows/windows.yml), then run `pyinstaller --noconfirm --clean windows/Apistat.spec` from the repository root in the UCRT64 shell. `python player.py --self-test` checks the GTK/GStreamer source environment; Run `Start-Process -FilePath dist/Apistat/Apistat.exe -ArgumentList --self-test -Wait -PassThru` in PowerShell to check the bundled runtime and exit code. Both Windows workflows install Mutagen and run the unit tests before uploading artifacts; the frozen runtime check also verifies Mutagen, the font, and the icon. Playback and Plexamp remote control still need a hands-on check on a Windows desktop with a Plex server; the runner cannot verify audio output or phone discovery.

On first launch, Apistat opens **Settings → Connection** and starts the [plex.tv/link](https://plex.tv/link) account flow. Choose a server from the linked account, then choose the music library to browse. **Change connection…** in Settings offers manual server URL and token entry if account linking is unavailable. The app checks the server's published local, direct remote, and relay addresses in that order, verifies its identity, and uses the server-specific token supplied by Plex. You can choose a different server later in **Settings → Connection**. The account link also works when Plexamp remote control is off. Both the account link and selected server login are stored in the platform credential store, without a plaintext fallback.

For manual connection, enter your server address, for example `http://192.168.1.10:32400`, and an X-Plex-Token. Use an HTTPS address with a valid certificate for remote connections. HTTP sends authentication and audio unencrypted and should be limited to a trusted local network. Enter the server address, not the Plex Web app URL. TLS verification remains enabled; redirects are disabled to avoid forwarding the token elsewhere.

For this prototype you can obtain a temporary token using [Plex's instructions](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/): open a library item's XML in Plex Web and copy the X-Plex-Token value from the URL. Tokens may expire. Enter it only in the app, not in chat. After a successful connection, the app saves the server address and token in your desktop keyring and reconnects on the next launch. It also restores the window size, open panel, and last queue and track position; playback returns paused. Playback state is saved when paused and periodically while playing. The keyring may ask you to unlock it. If the token expires, the connection dialog opens so you can replace it. The app uses an authentication header and does not print request URLs.

Use the sidebar icons to switch views. Now Playing centers large album art and track details. The artwork and track details stay centered as the window resizes. The album color gradient is dithered across the full panel for smoother transitions. Hold **Ctrl** and scroll over the artwork to resize it. By default, Now Playing and Albums use a dark gradient sampled from the current cover, and album covers show artist, album title and days since added. Both options can be changed in Settings. These appearance choices persist between launches; missing artwork leaves the background black. Albums defaults to 5 covers per row and supports 4 to 16: hold **Ctrl** and scroll over the wall to change the column count. The grid zoom and Now Playing artwork size persist between launches. Click a cover to flip only the artwork square and reveal a scrollable tracklist; the labels below stay in place. The flipped side uses colors from that album art and highlights the currently playing track. Click a track to play it, use ‹ Cover to flip back, or click the album title on the back for the full album view. Settings has Connection, Appearance, Library, and Keyboard tabs. Appearance offers Dark (the original palette), Black (pure black surfaces without artwork gradients), and Light (a pale palette with readable artwork colors). The selected theme and tab persist between launches. Settings can limit the wall to one flipped album at a time, adjust album grid outer margins and cover spacing, hide the window title bar, change text size, choose a custom font, hide all tooltips, and pick an accent color. The accent can instead follow a bright color from the playing album art. With single-flip mode, the previous cover turns back after the next cover finishes flipping. The flip follows GTK frame timing for a smooth first turn. Press **F** to hide or restore the sidebar and player bar. Use the search icon in the bottom bar to show or hide the entire album toolbar; it focuses the search field when shown. Change the Plex connection in Settings. Press Enter to search album and artist names. Search results and artist album listings have a ◀ back button at the top left; More albums load automatically as you reach the bottom of the wall. Library lists songs with clickable Song, Artist, Album, and Time column headers; its left panel lists audio playlists. Its search field filters songs by title, artist, and album. Click a Library column header to sort. Right-click a header to add or hide metadata columns such as Genre, Year, Date Added, Mood, Rating, Plays, Last Played, Bitrate, and Codec, or restore the original recent order. Library and playlist views remember their own column visibility, order, widths, and sort. Loved tracks show a small red heart, and alternating rows have a subtle tint. Library loads the full song list and caches it locally for fast filtering on later launches. A fresh cached song index is reused without a server query; it refreshes after one hour or when playlist edits require an update. The three most recently opened Library list views also stay in memory, including their loaded rows, so switching back does not rebuild the table. An interrupted list continues from its existing rows. Double-click a song to play it and the loaded songs after it. Playlist tracks retain Plex's playlist order. Use the + button in the playlist panel to name a playlist and choose its first song, then drag more songs from Library onto the playlist to add them. Albums load in pages of 100; Library displays all songs in the selected list. Settings also shows the current server and lets you change the connection. The compact player bar has borderless icon controls and a bold track title. Its thicker, handle-free seek timeline forms the border above the bar and moves smoothly during playback. The timeline has an invisible pointer area below the visible line for easier scrubbing. Settings can replace it with a taller waveform of the current song; the first play decodes a second, silent stream in the background and later plays reuse cached peaks. Previous, Play/Pause and Next stay centered as the window resizes. Click the compact cover or track title to switch to Now Playing and click again to return to the previous panel; click the artist name for that artist’s albums. Press **Space** to play or pause while the app is focused, except while typing in a text field. Drag sidebar icons to rearrange them; their order persists across launches. Press **1** through **5** to open the corresponding sidebar panels from top to bottom. Right-click for a context menu with playback and navigation actions; right-click an album cover for Show Artist Albums and Show in library. Artist names also open the artist’s albums. Show in library displays that album’s tracks in the Library view. Drag any empty space in the window to move it. When the title bar is hidden, use the context menu’s Quit item or your window manager’s close shortcut. The Play Queue sidebar button shows the current and upcoming tracks in a resizable table. Shift-click to select a range, or Ctrl-click to select individual tracks, then drag the selection together. This works in the Library, playlists, album track lists, Styles & Moods lists, and the Play Queue; drag Library tracks onto a playlist or the queue icon, and drag album or Styles & Moods tracks onto the queue icon. In Play Queue, drag selected tracks to rearrange them or press Backspace to remove selected queue tracks. Album covers and flipped-album tracks can also be dragged onto the queue icon. Right-click a song or album for Add to queue and Play next. Previous/Next operate on the current queue. Shuffle randomly picks another track and can revisit earlier tracks; turn it off for normal order. Repeat restarts the queue at its end.

Resizing the window changes how many album covers fit without changing their size; Ctrl+scroll still changes cover size. Now Playing shows five rating stars beneath the track information. **Appearance → Smooth scrolling** optionally blends wheel ticks and touchpad scroll input into one glide in scrollable panels. To rearrange a Plex playlist, open it in Library, clear any search filter and return to playlist order, then drag songs to the insertion line. The order is saved to Plex. The same song label follows the pointer when rearranging the Play Queue.

New installs default to rounded window corners, smooth scrolling, a song waveform timeline, 40 px album wall margins, 30 px cover spacing, and 18 px base text. The Appearance tab has an album grid size slider; Ctrl+scroll over the wall changes the same setting. Apistat bundles [Nunito](https://github.com/google/fonts/tree/main/ofl/nunito) under the [SIL Open Font License](../fonts/OFL.txt) as its default rounded font. Apple's [SF Pro license](https://developer.apple.com/fonts/) does not allow bundling SF Pro Rounded with this Linux app. Existing saved appearance preferences stay in effect.

The first page of each album sort, its artwork, sampled color palettes, rendered gradient backgrounds, song waveform previews, and the complete Library song index are cached locally under `~/.cache/plex-music-prototype` and reused across launches. The cache is separated by server login. The Library list starts populating when opened and continues in small batches if you switch panels; GTK rows are recreated from the cached metadata after a restart. A spinner appears for work lasting more than two seconds and stays visible across panels until tracked work finishes. A cached full-library index older than one hour is shown immediately and refreshed from Plex in the background, with the cached data kept if the refresh fails. In Settings, enable **Cache an album index for title and artist search** to download an index of the selected music library and search album titles and artists locally. The index is kept between launches; use **Refresh search index** after adding or removing albums on Plex. With the index off, a search loads the album catalog from Plex in the background and reuses it while paging through the results. Turning the option off removes the current login's cached search index.

Right-click a Library song to play it, add it to the play queue, play it next, add up to ten similar songs, love or unlove it on Plex, or show its artist's albums. Similar songs use Plex sonic matches and a varied sample from Plex genre, mood, and artist filters. Picks are limited per album and artist; tracks without enough matches may add fewer than ten. Now Playing artwork can be enlarged to 1000 pixels with Ctrl+scroll. Changing tracks within the same album keeps the existing artwork gradient visible. At launch, the interface becomes interactive as soon as it is ready while the saved server connection and library load in the background. Album cards and song rows appear in batches.

The player exposes MPRIS controls on the desktop session bus. Play/pause, next, previous and stop media keys can control playback, and compatible desktop widgets can show track details and seek. **Settings → Keyboard** uses the [Global Shortcuts portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html) on desktops that provide it. Choose **Enable global shortcuts**; the desktop asks which keys to assign. Existing assignments are restored when Apistat starts, and **Configure global shortcuts** opens the desktop's shortcut dialog again where supported. This needs a portal backend with Global Shortcuts support and a desktop application ID. The repository includes [org.apistat.Apistat.desktop](../org.apistat.Apistat.desktop); install it as `~/.local/share/applications/org.apistat.Apistat.desktop` with an `Exec` command that launches your Apistat installation. The Xfce editor remains the fallback on Xfce, using `xfconf-query` and `gdbus`; `bash setup_xfce_media_keys.sh` can assign unused default media keys. Other desktops without a Global Shortcuts portal can bind MPRIS commands in their system keyboard settings. Apistat must be running for these shortcuts to work.

## Smart playlists and queue history

The Library sidebar has a **Smart Playlists** panel above Plex playlists. Use **+** to create a local smart playlist, then right-click its row to edit or delete it. Rules can match any or all conditions across Genre, Artist, Album, Title, Mood, Year, Rating, and Play Count. Text comparisons include contains and is; number comparisons include inclusive ranges. Rule filtering can be disabled to start from the entire music library. **Only loved songs** uses the songs marked with a red heart on Plex. A limit can select a number of songs or fit tracks within a duration, ordered by random, date added, title, artist, rating, or play count. Filtering and the loved-song restriction run before ordering and limiting. Smart playlists update from the local song index when it refreshes; their definitions are saved per Plex server and music library on this device. They are not created on the Plex server.

The Play Queue shows the last five played tracks in dim text above the current track and upcoming queue. Those history rows remain when a different album or playlist replaces the queue, and the history persists across launches. Double-click a history row to play that song again. Drag current and upcoming tracks within the queue to rearrange them. The album sort bar has no full-width background; its search icon sits next to **BY ALBUM** and opens the album search controls. Settings can show small minimize, maximize, and close buttons at the top right, and can round the window corners where the window system supports shaped windows. The corners are square while maximized or fullscreen. In Library, **Full music library** appears above Smart Playlists, and the handle between Smart Playlists and Playlists adjusts their heights.

## Experimental GPU album wall

On Linux and Windows, **Settings → Appearance → Album grid → Use experimental GPU album wall** enables a virtualized OpenGL wall. It draws the visible covers and preloads nearby rows using an in-memory texture atlas and the existing local artwork cache. Larger covers use a sharper texture tier when GPU capacity permits. Album sorting, searching, pagination, zoom, artist links and dragging covers to the queue or regular playlists continue to use the current library. Click an album to flip its artwork in place using the GPU; click or drag tracks on its back, and right-click for the album or track menu. The single-flip setting is supported; individual GPU-drawn covers are not yet exposed as separate accessibility elements. The regular wall remains available by turning the option off.

This path requires desktop OpenGL 3.2, with EGL on Linux or a compatible Windows graphics driver. The wall renders in a private GPU context and copies the finished image into GTK; this avoids sharing GTK’s graphics context but may reduce the speed benefit on some systems. If the context cannot be created, Apistat returns to the regular GTK wall. macOS uses the regular wall. While the GPU wall is visible, the album sort and search bars and player bar use a GPU-blurred rendering of the album wall. If GPU blur cannot be initialized, the bars fall back to the shared background. Other panels use the regular GTK backdrop capture.

## Last.fm scrobbling

In **Settings → Connection**, select **Authorize Last.fm…**, approve access in your browser, and select **Finish linking**. Apistat uses its own Last.fm application credentials when they are included in the build. If they are unavailable, an Advanced section offers manual setup using a [Last.fm API account](https://www.last.fm/api/account/create). Developers can also provide credentials at runtime using `APISTAT_LASTFM_API_KEY` and `APISTAT_LASTFM_API_SECRET`. Apistat stores these credentials and the authorized session in your system credential store; there is no plaintext fallback. **Unlink Last.fm** stops scrobbling and removes the stored credentials. Linking enables scrobbling immediately and shares track metadata and listening times with Last.fm.

Apistat sends a now-playing update when playback begins. Tracks longer than 30 seconds are scrobbled after you listen to half their duration or four minutes, whichever is shorter. Paused and buffered time and seeks do not count as listening. A failed submission is reported in Settings; offline scrobbles are not currently queued or retried.

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

- Narrow icon sidebar for Now Playing, Albums, Library, Styles & Moods, Play Queue and Settings; choose visible buttons in Settings → Sidebar
- Centered large artwork in the Now Playing view
- Clickable Now Playing artwork that switches to a full-width, layered ribbon driven by playback audio; rear curves follow lower frequencies and front curves ripple with higher frequencies. Click it to return to the cover.
- Ctrl+wheel zoom from 16 to 4 album columns and sizing for Now Playing artwork
- Optional album art color gradient behind Now Playing and the album wall
- Optional frosted player bar and matching search, sort, and tab bars
- Lyrics sidebar with LRCLIB lookup and timed-line highlighting when available; lyrics.ovh provides plain-text lyrics if LRCLIB fails or has no match. Track metadata is sent to these services, but Plex credentials are not.
- The information icon in the player bar and the “Show info” track menu open a sliding panel with Plex metadata and artist descriptions, when available. For embedded ID3 frames, install `python3-mutagen`; the app reads up to 4 MiB from the Plex media file when the panel is requested. Files without ID3 tags show Plex's metadata instead.
- Drag previously played queue entries into the upcoming queue to hear them again
- Optional artist, album title and days since added below each cover
- Xfce global keyboard shortcut editor in Settings
- Album wall zoom from 16 to 4 columns, with a pinned full-width sort bar, centered titles and artwork-only flip cards
- Searchable song table with clickable sort headers, extra right-click sorts, and a separate playlist panel
- Styles & Moods uses Plex's server-side categories in a square-tile grid that follows the album margin settings. Tiles show cached album artwork and open the category's album grid; List and Albums controls are available within the category. Ctrl+scroll resizes album covers there. Right-click a tile to replace upcoming queue items with up to 25 random tracks from that style or mood. Category results are cached locally. It checks artist and album styles and album and track moods. Sonic similarity is a separate Plex feature used by Add similar songs; named Mood categories are metadata rather than raw sonic-analysis coordinates.
- The Play Queue's “Keep playing songs in the same style” checkbox prepares ten matching songs as soon as the final queued song starts. It tries Plex's mood categories first, then style and genre metadata if mood matches are unavailable.
- Compact playback bar with centered transport icons, a full-width seek border, song info, volume, shuffle, repeat and search
- Four background artwork workers; server-sized thumbnails and placeholders for missing artwork

## Included

- Music-library picker, automatically paginated album browser and song library
- Audio playlist browsing, playback, editing and server-synced song order
- Album and artist search, artwork and disc/track numbers
- Direct audio streaming, pause, previous/next, seek and volume
- MPRIS media keys and desktop playback controls
- Automatic next track, shuffle and album repeat
- Background network requests, timeouts and stale-result checks
- Generic errors that avoid exposing tokens

## Prototype boundaries

Streams the original file through GStreamer. There is no Plex transcoding fallback, offline download, Plex playback reporting or gapless playback yet. Account server selection depends on the addresses Plex publishes; a server with no reachable published address still needs a working manual URL or Plex Remote Access/Relay configuration. Saved login and Plexamp account linking require a working platform credential store. MPRIS requires a desktop session bus. Codec support depends on installed GStreamer plugins. Seek support depends on the format and HTTP source. Plex Companion compatibility is based on the published protocol and current third-party implementations; live Plexamp Android and iOS testing is still required.

The code is not affiliated with Plex. Authentication, XML parsing, pagination, search encoding, stream resolution and missing-media handling are tested against a local mock server. Song sorting and audio playlists were also checked with a local Plex server. GTK view rendering was checked on a Linux desktop.

Companion support follows the Plex API documentation and independently reads the Music Assistant Plex Connect and plexdlnaplayer implementations for compatibility. No third-party receiver code is copied into this project.

## Checks

```bash
/usr/bin/python3 -m unittest -v test_art_zoom.py test_appearance.py test_client.py test_credentials.py test_player_controls.py test_library_catalog.py test_session.py test_shortcuts.py test_track_waveform.py
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

### Building with Last.fm account linking

Register an Apistat application at [Last.fm](https://www.last.fm/api/account/create). For GitHub builds, set the repository Actions secrets `LASTFM_API_KEY` and `LAST_FM_API_SECRET`; the build workflows require both secrets and use them to include the application credentials. Local packagers can set those variables and run `python3 scripts/embed_lastfm_credentials.py` before packaging. The generated `lastfm_build_credentials.py` is ignored by Git. When both variables are absent the script removes any previously generated file.

The application secret is included in distributed packages and can be extracted by their recipients. It is an application credential, not a listener's Last.fm password or session key. Builds without application credentials retain manual setup in the Advanced section.
