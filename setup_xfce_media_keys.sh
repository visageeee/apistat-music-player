#!/usr/bin/env bash
set -euo pipefail

if ! command -v xfconf-query >/dev/null || ! command -v gdbus >/dev/null; then
    echo 'Install xfconf and GLib D-Bus tools before configuring Xfce media keys.' >&2
    exit 1
fi

destination='org.mpris.MediaPlayer2.apistat'
object_path='/org/mpris/MediaPlayer2'
interface='org.mpris.MediaPlayer2.Player'
gdbus_path="$(command -v gdbus)"

bind_key() {
    local key="$1" method="$2" property="/commands/custom/$1"
    if xfconf-query -c xfce4-keyboard-shortcuts -p "$property" >/dev/null 2>&1; then
        echo "$key already has a shortcut; leaving it as is."
        return
    fi
    xfconf-query -c xfce4-keyboard-shortcuts -p "$property" -n -t string \
        -s "$gdbus_path call --session --dest $destination --object-path $object_path --method $interface.$method"
    echo "Bound $key to Apistat $method."
}

bind_key XF86AudioPlay PlayPause
bind_key XF86AudioPause Pause
bind_key XF86AudioStop Stop
bind_key XF86AudioNext Next
bind_key XF86AudioPrev Previous
