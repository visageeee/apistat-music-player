# Apistat

[Website](https://visageeee.github.io/apistat-music-player/) · [Documentation](docs/guide.md)

Apistat is for people who love Plexamp but wish it felt more at home on the desktop. People who appreciate its style and music discovery, but miss the depth and control of classic iTunes.

It brings that inspiration to a Plex music client with smart playlists, party shuffle, and playlist management. Build playlists around precise rules, keep a party queue rolling, and organise your collection. You can also control Apistat from Plexamp on your phone.

Plexamp’s appeal, with some of the iTunes features worth bringing back.

## Features

- Browse and search your Plex music library by album, artist, style or mood.
- Create rule-based smart playlists and manage Plex playlists with drag and drop.
- Organise the play queue, add similar tracks and keep music playing with automatic recommendations.
- Control playback from Plexamp on your phone, or use desktop media controls.
- View lyrics, track information and artwork, with custom themes and album-art colors.
- Optionally scrobble listening history to Last.fm.

## Install

Download a package for Linux, Windows or macOS from [Releases](https://github.com/visageeee/apistat-music-player/releases). Windows and macOS builds are unsigned; macOS builds are also not notarized.

- **Linux:** Install the Flatpak bundle with `flatpak install --user ./Apistat.flatpak`, then run `flatpak run org.apistat.Apistat`. The GNOME runtime is available from [Flathub](https://flathub.org/setup).
- **Windows:** Extract the ZIP and run `Apistat.exe` from the extracted folder.
- **macOS:** Extract the ZIP for your Mac’s architecture and open the app. The macOS build is experimental.

On first launch, link your Plex account and select a server and music library. Apistat requires a reachable Plex Media Server and a working system credential store.

For running from source, build instructions, remote-control setup, troubleshooting and limitations, see the [full guide](docs/guide.md).

Apistat is not affiliated with Plex.
