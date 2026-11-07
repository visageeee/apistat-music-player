#!/usr/bin/env python3
import os
import sys
from pathlib import Path

if os.name == 'nt' and getattr(sys, 'frozen', False):
    # The Windows Pango/DirectWrite backend can fail to resolve fallback fonts.
    # Use the bundled Fontconfig configuration and the installed Windows fonts.
    os.environ.setdefault('PANGOCAIRO_BACKEND', 'fc')
    os.environ.setdefault('FONTCONFIG_FILE', str(Path(sys._MEIPASS) / 'windows' / 'fonts.conf'))
import random
import math
import hmac
import hashlib
import hashlib
import threading
import time
import weakref
import cairo
import bisect
from collections import deque
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import Future
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlencode
import gi

from gi.repository import GLib
from portal_shortcuts import APP_ID, PortalShortcuts

# GTK derives the Wayland app ID and X11 window class during initialization.
if __name__ == '__main__' and os.name != 'nt':
    GLib.set_prgname(APP_ID)
    GLib.set_application_name('Apistat')

gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, Gst, GLib, GObject, GdkPixbuf, Gdk, Pango
if __name__ == '__main__' and os.name != 'nt':
    Gdk.set_program_class(APP_ID)
from app_font import DEFAULT_FONT_FAMILY, register_bundled_font
from plex_client import PlexClient, ALBUM_SORT_ARTIST
from plex_resources import reachable_music_server
from credentials import load_credentials, save_credentials
if sys.platform.startswith('linux'):
    from mpris import Mpris
else:
    Mpris = None
from appearance import (ALBUM_SIZE_RANGE, ALBUM_COLUMN_RANGE, NOW_SIZE_RANGE,
                        DitheredGradient, added_age_label, album_info_label, album_cover_size, gradient_colors,
                        load_accent_color, load_album_columns, load_album_details_enabled,
                        load_art_accent_enabled, load_art_sizes, load_tooltips_hidden,
                        load_star_ratings_hidden,
                        load_smooth_scrolling_enabled, load_search_shortcut, save_search_shortcut,
                        load_custom_font, load_gradient_enabled, load_search_index_enabled,
                        load_background_visualizer_enabled, save_background_visualizer_enabled,
                        load_visualizer_view, save_visualizer_view,
                        load_instrument_visualizer_enabled, save_instrument_visualizer_enabled,
                        load_album_margins, save_album_margins,
                        load_keep_style_playing_enabled, save_keep_style_playing_enabled,
                        load_gpu_album_wall_enabled, save_gpu_album_wall_enabled,
                        load_classic_album_wall_enabled, save_classic_album_wall_enabled,
                        load_library_layout, save_library_layout,
                        load_library_view_mode, save_library_view_mode,
                        load_library_sort_buttons,
                        load_info_panel_width, save_info_panel_width,
                        load_playlist_order, save_playlist_order,
                        load_sidebar_order, save_sidebar_order,
                        load_sidebar_visible, save_sidebar_visible,
                        load_sidebar_labels_enabled, save_sidebar_labels_enabled,
                        load_sidebar_note_animation_enabled, save_sidebar_note_animation_enabled,
                        load_theme, save_theme,
                        theme_gradient_colors,
                        load_timeline_waveform_enabled, save_timeline_waveform_enabled,
                        load_single_flip_enabled,
                        load_text_size, load_title_bar_hidden, load_window_buttons_enabled,
                        load_rounded_corners_enabled,
                        load_frosted_player_bar, save_frosted_player_bar,
                        save_accent_color, save_album_columns, save_album_details_enabled,
                        save_star_ratings_hidden,
                        save_smooth_scrolling_enabled,
                        save_art_accent_enabled, save_custom_font, save_tooltips_hidden,
                        save_gradient_enabled, save_now_art_size,
                        save_search_index_enabled,
                        save_single_flip_enabled, save_text_size,
                        save_title_bar_hidden, save_window_buttons_enabled,
                        save_rounded_corners_enabled, waveform_colors)
from local_cache import (LocalCache, build_album_index, cached_album_page,
                         search_albums, sort_albums)
from library_catalog import build_song_catalog, filter_sort_songs
from local_library import LocalLibrary, load_sources, save_sources, create_source, DATA as LOCAL_LIBRARY_DATA
from music_facets import MusicFacet
from style_art import square_preview
from smart_playlists import apply_definition, load_for_scope, save_for_scope
from smart_playlist_dialog import SmartPlaylistDialog
from play_queue import (insert_items, move_items, move_queue_or_history, remove_items,
                        playlist_move_plan, select_similar_tracks)
from drag_payload import encode_track_keys, decode_track_keys
from ratings import filled_stars, star_text, stars_from_click
from window_shape import rounded_region
import windows_window
from track_waveform import TrackWaveform, analyze_track_waveform, analyze_audio_uri, server_waveform
from playback_pipeline import PlaybackPipeline
from ribbon_audio import RibbonAudioTap
from instrument_visualizer import run_analysis as analyze_instruments, sample_analysis
from ribbon_visualizer import RibbonVisualizer
from frosted_bar import FrostedBar
from lyrics import LyricsClient, lyrics_error_message
from artist_info import file_info_lines, format_artist_description
from next_track_preload import preload_next_art, preload_next_waveform
from album_card import FlipCard
from album_highlights import show_track_duration, track_highlights
from gtk_snapshot import draw_allocated, normalize_surface_origin
from app_assets import app_icon, placeholder_art, SMALL_PLACEHOLDER_LOGO_RATIO
from album_zoom_icon import AlbumZoomIcon
from smooth_scroll import SmoothScroller
from sidebar_icons import CUSTOM_SIDEBAR_ICONS, SidebarIcon
from library_album_view import AlbumGroupOverlay, album_group_row_height, group_songs_by_album
from time_machine_view import TimeMachineView
from tag_editor import TagEditor
from background_drag_scroll import attach_background_drag
from busy_indicator import BusyIndicator
from session import load_session, save_session, item_to_data, serialize_snapshot
import shortcuts
from companion import CompanionReceiver, local_ip
from companion_account import (PlexAccount, load_device_token, save_device_token,
                               clear_device_token)
from companion_config import load_config, save_config
import lastfm
from similar_recommendations import similar_tracks as lastfm_similar_tracks
from app_paths import migrate_legacy_data

if sys.platform == 'darwin' and getattr(sys, 'frozen', False):
    # GStreamer's HTTP plugin loads libsoup dynamically; preload the bundled
    # library and scan plugins in-process so its symbols are available there.
    os.environ['GST_REGISTRY_FORK'] = 'no'
    from macos_runtime import configure_gstreamer_registry
    _macos_registry_temp = configure_gstreamer_registry(GLib.get_user_cache_dir())
    gi.require_version('Soup', '3.0')
    from gi.repository import Soup
    _macos_soup_session = Soup.Session.new()
Gst.init(None)


def clock(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}:{seconds % 60:02}'


def is_text_editing(widget):
    return (isinstance(widget, (Gtk.Entry, Gtk.Editable)) or
            isinstance(widget, Gtk.TextView) and widget.get_editable())


def create_content_stack():
    stack = Gtk.Stack()
    # Hidden panels can otherwise force a much wider allocation than the window.
    stack.set_hhomogeneous(False)
    return stack


class CenteredLyricsGroup(Gtk.Bin):
    """Center a bounded group without increasing the window's minimum width."""

    def __init__(self):
        super().__init__()
        self.set_has_window(False)
        self.target_width = 1000

    def set_target_width(self, width):
        width = max(1000, min(1500, int(width)))
        if width != self.target_width:
            self.target_width = width
            self.queue_resize()

    def do_get_preferred_width(self):
        child = self.get_child()
        minimum = child.get_preferred_width()[0] if child and child.get_visible() else 0
        return minimum, max(minimum, self.target_width)

    def do_size_allocate(self, allocation):
        self.set_allocation(allocation)
        child = self.get_child()
        if child and child.get_visible():
            width = min(self.target_width, allocation.width)
            bounds = Gdk.Rectangle()
            bounds.x = allocation.x + (allocation.width - width) // 2
            bounds.y = allocation.y
            bounds.width = max(1, width)
            bounds.height = max(1, allocation.height)
            child.size_allocate(bounds)


class LyricsColumns(Gtk.Box):
    """Allocate the artwork and lyric columns without resize-driven size requests."""

    def do_size_allocate(self, allocation):
        Gtk.Box.do_size_allocate(self, allocation)
        children = [child for child in self.get_children() if child.get_visible()]
        if len(children) == 1:
            children[0].size_allocate(allocation)
        elif len(children) == 2:
            gap = min(56, max(0, allocation.width // 10))
            art_width = min(440, max(1, int((allocation.width - gap) * 0.4)))
            for child, x, width in ((children[0], allocation.x, art_width),
                                    (children[1], allocation.x + art_width + gap,
                                     allocation.width - art_width - gap)):
                rect = Gdk.Rectangle()
                rect.x, rect.y = x, allocation.y
                rect.width, rect.height = max(1, width), max(1, allocation.height)
                child.size_allocate(rect)


class LyricsTrackInfo(Gtk.Box):
    def do_size_allocate(self, allocation):
        Gtk.Box.do_size_allocate(self, allocation)
        children = [child for child in self.get_children() if child.get_visible()]
        if len(children) != 4:
            return
        cover, *metadata = children
        heights = [child.get_preferred_height_for_width(max(1, allocation.width))[1]
                   for child in metadata]
        metadata_height = sum(heights) + 8 * len(metadata)
        cover_size = max(1, min(allocation.width, allocation.height - metadata_height))
        y = allocation.y + max(0, (allocation.height - cover_size - metadata_height) // 2)
        rows = [(cover, cover_size, cover_size)] + [
            (child, allocation.width, height) for child, height in zip(metadata, heights)]
        for child, width, height in rows:
            rect = Gdk.Rectangle()
            rect.x, rect.y = allocation.x + (allocation.width - width) // 2, y
            rect.width, rect.height = max(1, width), max(1, height)
            child.size_allocate(rect)
            y += height + 8


class InfoPanelBox(Gtk.Box):
    """Let the stored width control an overlay instead of child natural widths."""
    def do_get_preferred_width(self):
        minimum, _natural = Gtk.Box.do_get_preferred_width(self)
        return minimum, minimum

    def do_get_preferred_width_for_height(self, height):
        minimum, _natural = Gtk.Box.do_get_preferred_width_for_height(self, height)
        return minimum, minimum


LIBRARY_COLUMNS = (
    ('Name', 'title'), ('Artist', 'artist'), ('Album', 'album'),
    ('Time', 'duration'), ('Rating', 'user_rating'), ('Genre', 'genre'), ('Year', 'year'),
    ('Added', 'added_at'), ('Mood', 'mood'), ('Label', 'label'),
    ('Album artist', 'album_artist'), ('Release date', 'release_date'),
    ('Disc', 'disc'), ('Track', 'track_number'), ('Last played', 'last_played_at'),
    ('Plays', 'play_count'), ('Bitrate', 'bitrate'),
    ('Codec', 'codec'),
)
BASE_LIBRARY_FIELDS = ('title', 'artist', 'album', 'duration')
PAUSE_MARKER = '❚❚'
def now_art_fit(preferred, width, height, info_height):
    """Fit artwork beside its metadata inside the current Now Playing panel."""
    width_room = max(80, width - 48)
    height_room = max(80, height - info_height - (64 if height < 480 else 100))
    return min(preferred, width_room, height_room)


QUEUE_HISTORY_LIMIT = 200
QUEUE_HISTORY_PAGE = 20
ALBUM_SORT_OPTIONS = (
    ('Recently added', 'addedAt:desc'), ('By Year', 'year:desc'),
    ('By Artist', ALBUM_SORT_ARTIST), ('By Album', 'titleSort'),
)


class InactiveMpris:
    def changed(self):
        pass

    def seeked(self, _position):
        pass

    def close(self):
        pass


class Player(Gtk.Window):
    def __init__(self, mpris_enabled=False):
        bundled_font_available = register_bundled_font()
        super().__init__(title='Apistat')
        if sys.platform == 'darwin' and getattr(sys, 'frozen', False):
            from macos_runtime import configure_bundled_icons
            configure_bundled_icons(Gtk.Settings.get_default(), Gtk.IconTheme.get_default(), sys._MEIPASS)
        self.default_font_family = DEFAULT_FONT_FAMILY if bundled_font_available else ''
        Gtk.Window.set_default_icon(app_icon())
        self.set_icon(app_icon())
        migrate_legacy_data()
        self.saved_session = load_session()
        self.first_run_setup = not bool(self.saved_session.get('server'))
        self.session_applied = False
        self.previous_panel = 'albums'
        window = self.saved_session.get('window', {})
        self.normal_size = (window.get('width', 1080), window.get('height', 720))
        self.set_default_size(*self.normal_size)
        self.hide_title_bar = load_title_bar_hidden()
        self.window_buttons_enabled = load_window_buttons_enabled()
        self.rounded_corners_enabled = load_rounded_corners_enabled()
        self._window_shape_state = None
        self._window_shape_suspended = False
        self._window_shape_resume_source = 0
        self.set_decorated(not self.hide_title_bar)
        self.set_resizable(True)
        self.connect('size-allocate', self.window_allocated)
        self.connect('size-allocate', self.window_shape_allocated)
        self._last_configure_size = None
        self._last_window_resize_at = None
        self.connect('configure-event', self.window_configured)
        self.connect('realize', self.window_realized)
        self.client = None
        self.lastfm_session = None
        self.lastfm_auth = None
        self.lastfm_generation = 0
        self.lastfm_tracker = None
        self.lastfm_vault_lock = threading.Lock()
        self.remote_config = load_config()
        self.remote_account = PlexAccount(self.remote_config['identifier'],
                                          self.remote_config['name'])
        self.remote_receiver = None
        self.remote_link_token = None
        self.remote_link_user = None
        self.remote_keyring_available = True
        self.remote_published_uri = ''
        self.remote_publish_pending = False
        self.remote_validation_pending = False
        self.remote_pin_generation = 0
        self.remote_link_select_server = False
        self.remote_link_loading = True
        self.pending_server_choice = False
        self.server_choice_generation = 0
        self.remote_container = ''
        self.remote_queue_id = ''
        self.remote_queue_version = ''
        self.remote_item_ids = ()
        self.remote_server_machine = ''
        self.remote_stop_thread = None
        self.remote_token_cache = {}
        self.remote_token_lock = threading.Lock()
        self.index_cache = None
        self.indexed_albums = None
        self.index_section = None
        self.index_generation = 0
        self.index_building = False
        self.album_prefetch_generation = 0
        self.album_prefetch_pending = False
        self.album_prefetch_thread = None
        self.restored_credentials = None
        self.credential_warning = ''
        self.sections = []
        self.source_config = load_sources()
        self.account_servers = []
        self._updating_source_selector = False
        self.albums = []
        self.tracks = []
        self.queue = []
        self.play_history = deque(maxlen=QUEUE_HISTORY_LIMIT)
        self.queue_history_visible = 5
        self.current_played_track = None
        self.smart_playlists = []
        self.active_smart_playlist = None
        self.index = -1
        self.generation = 0
        self.connection_generation = 0
        self.album_generation = 0
        self.play_generation = 0
        self.closed = False
        self.playing = False
        self.stream_open = False
        self.remote_opening = False
        self.playback_position_ms = 0
        self.pending_resume_seek_ms = 0
        self.updating = False
        self.timeline_base_position = 0.0
        self.timeline_base_time = time.monotonic()
        self.timeline_duration = 0.0
        self.timeline_dragging = False
        self.timeline_hover_x = None
        self.pending_timeline_seek = None
        self.timeline_seek_source = 0
        self.waveform_generation = 0
        self.current_stream_uri = ''
        self.offset = 0
        self.total = 0
        self.pipeline = Gst.ElementFactory.make('playbin', None)
        if not self.pipeline:
            raise RuntimeError('Install gstreamer1.0-plugins-base and gstreamer1.0-plugins-good')
        self.pipeline.set_property('flags', 2)  # Audio only
        self.playback_controller = PlaybackPipeline(
            self.pipeline, lambda: GLib.idle_add(self.playback_transition_failed))
        self.playback_poll_workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix='playback-poll')
        self.playback_poll_future = None
        try:
            output = ('osxaudiosink' if sys.platform == 'darwin' and
                      Gst.ElementFactory.find('osxaudiosink') else 'autoaudiosink')
            self.live_waveform_tap = RibbonAudioTap(output)
            self.pipeline.set_property('audio-sink', self.live_waveform_tap.sink_bin)
        except (RuntimeError, GLib.Error):
            self.live_waveform_tap = None
        self.pipeline.connect('source-setup', self.source_setup)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self.message)
        self.connect('destroy', self.close)
        self.connect('key-press-event', self.global_key_pressed)
        self.connect('key-release-event', self.global_key_released)
        self.connect('focus-out-event', self.window_focus_out)
        self.connect('button-press-event', self.context_menu_pressed)
        self.connect('button-press-event', self.background_drag_pressed)
        self.connect('motion-notify-event', self.background_drag_motion)
        self.connect('button-release-event', self.background_drag_released)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK |
                        Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.window_drag_start = None
        self.space_held = False
        self.last_session_save = 0.0
        self.session_save_workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix='session-save')
        self.session_save_future = None
        self.art_workers = ThreadPoolExecutor(max_workers=4)
        self.style_tile_art_workers = ThreadPoolExecutor(max_workers=2)
        self.rating_executor = ThreadPoolExecutor(max_workers=1)
        self.rating_requests = {}
        self.waveform_workers = ThreadPoolExecutor(max_workers=1)
        self.instrument_workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix='instrument-analysis')
        self.instrument_future = None
        self.instrument_pending = None
        self.instrument_analysis = None
        self.instrument_generation = 0
        self.next_art_workers = ThreadPoolExecutor(max_workers=1)
        self.next_waveform_workers = ThreadPoolExecutor(max_workers=1)
        self.next_art_prefetch_future = None
        self.next_wave_prefetch_future = None
        self.next_prefetch_target = None
        self.background_prefetch_source = 0
        self.selected_album = None
        self.queue_album = None
        self.artist_filter = None
        self.artist_catalog = None
        self.album_sort = 'addedAt:desc'
        self.library_album_filter = None
        self.library_tag_filter = None
        self.styles_source = None
        self.styles_facets = None
        self.styles_loading = False
        self.styles_generation = 0
        self.styles_rows_source = None
        self.column_sort = None
        self.song_catalog = None
        self.song_results = None
        self.song_catalog_source = None
        self.song_catalog_loading = False
        self.song_catalog_generation = 0
        self.song_cache_edit_lock = threading.Lock()
        self.song_load_pending = False
        self.song_view_cache = OrderedDict()
        self.song_view_key = None
        self.library_search_timeout = 0
        self.art_epoch = 0
        self.loading_albums = False
        self.startup_loading = True
        self.set_name('plex-player')
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            #plex-player { background: #000; color: #eee; }
            #library-wall, #library-wall viewport, #album-grid,
            #album-grid flowboxchild { background: transparent; }
            #plex-player label, #plex-player button, #plex-player entry,
            #song-view, #style-song-view, #queue-view, #album-track-view { color: #eee; }
            #plex-player entry { background: #252525; }
            #settings-panel button:not(#settings-tab-button) {
                background: #303030; color: #eee; border-color: #555; }
            #settings-panel button:not(#settings-tab-button):hover { background: #404040; }
            #apistat-context-menu { background: #252525; color: #eee; }
            #apistat-context-menu menuitem, #apistat-context-menu menuitem label {
                color: #eee; }
            #apistat-context-menu menuitem:hover { background: #484848; }
            #album-grid flowboxchild { padding: 0; margin: 0; border: 0; }
            #album-grid button { background: transparent; border: 0; padding: 0;
                border-radius: 0; box-shadow: none; }
            #album-grid button:hover { background: rgba(255, 255, 255, 0.12); }
            #album-results-back, #album-results-back:hover { background: transparent;
                border: 0; box-shadow: none; min-width: 0; min-height: 0; padding: 3px 4px; }
            #album-sort-bar { background: transparent; min-height: 28px; }
            #album-sort-bar button { background: rgba(0, 0, 0, 0.68); border: 0;
                border-radius: 0; box-shadow: none; color: #c8c8c8; padding: 3px 10px; }
            #album-sort-bar #album-search-button { padding: 3px 8px; }
            #album-sort-bar button.sort-divider { border-right: 1px solid rgba(255, 255, 255, 0.18); }
            #album-sort-bar button:hover { background: rgba(255, 255, 255, 0.12); }
            #album-sort-bar button.active { color: #fff; font-weight: bold; }
            #album-sort-bar button label { font-size: 0.85em; }
            #album-grid #album-title { font-weight: bold; color: #fff; }
            #album-grid #album-meta { color: #fff; font-size: 11px; }
            #album-card-back { background: transparent; border: 0; }
            #album-card-back button { color: #eee; }
            #album-card-back #playing-marker { color: #e7a641; font-size: 16px; }
            #album-card-back #playing-marker.paused { font-size: 12px; }
            #album-card-back button.playing-track { background: rgba(255, 255, 255, 0.25);
                font-weight: bold; }
            #player-bar { background: #151515; }
            #lyrics-panel, #lyrics-scroll, #lyrics-scroll viewport,
            #lyrics-view, #lyrics-view text { background: transparent; color: #eee; }
            #lyrics-view { padding: 12px 24px; }
            #lyrics-details { font-size: 0.75em; opacity: 0.7; }
            #info-panel { background: #202020; color: #eee; border-left: 1px solid #444; }
            #info-panel label { color: #eee; }
            #info-artist-banner { background: rgba(128, 128, 128, 0.15); }
            #info-artist-name { font-size: 18px; font-weight: bold; padding: 10px 34px; }
            #info-close-button, #info-close-button:hover, #info-close-button:active,
            #info-close-button:focus { background: transparent; background-image: none;
                border: 0; box-shadow: none; }
            #info-section-title { font-size: 16px; font-weight: bold; }
            #info-field-name { font-weight: bold; }
            #info-icon { font-size: 14px; font-weight: bold; min-width: 20px;
                min-height: 20px; border: 1px solid; border-radius: 50%; }
            #player-bar #info-button { padding: 0 5px; }
            #info-resize-handle { background: transparent; }
            #info-resize-handle:hover { background: rgba(128, 128, 128, 0.22); }
            #info-secondary { opacity: 0.7; font-size: 0.85em; }
            #lyrics-song-title { font-weight: bold; }
            #lyrics-song-link, #lyrics-song-link:hover, #lyrics-song-link:active {
                background: transparent; border: 0; box-shadow: none; padding: 0; }
            #lyrics-title-bar button, #lyrics-title-bar button:hover,
            #lyrics-title-bar button:active, #lyrics-title-bar button:focus {
                background: transparent; background-image: none; border: 0; box-shadow: none; }
            #player-bar button, #library-toolbar button { color: #eee;
                background: #252525; border-color: #444; box-shadow: none; }
            #player-bar button, #player-bar button:hover, #player-bar button:active,
            #player-bar button:checked { background: transparent; border: 0;
                border-radius: 0; box-shadow: none; }
            #player-bar button:checked image { color: #e7a641; }
            #player-bar #song-info-button { padding: 0; }
            #player-bar #transport-skip { min-width: 40px; min-height: 40px; padding: 0; }
            #player-bar #transport-skip:disabled image { opacity: 0.35; }
            #player-bar #transport-play { min-width: 52px; min-height: 52px; padding: 0; }
            #side-nav #sidebar-icon-label { font-size: 10px; }
            #side-nav.show-labels button { padding: 5px 3px; }
            #time-machine-subtitle { font-size: 10px; letter-spacing: 2px; opacity: .72; }
            #time-machine-panel, #time-machine-view { background: transparent; color: #eee; }
            #time-machine-album, #time-machine-album:hover { border: 0; box-shadow: none;
                background: transparent; padding: 0; }
            #time-machine-album:hover { background: rgba(128, 128, 128, .18); }
            #album-track-number { font-weight: bold; }
            #full-library-button { background: transparent;
                border: 0; box-shadow: none; border-radius: 0; padding: 6px 8px; }
            #full-library-button:hover { background: rgba(255, 255, 255, 0.09);
                border: 0; box-shadow: none; }
            #full-library-title { font-weight: bold; }
            #now-rating button, #now-rating button:hover, #now-rating button:active {
                background: transparent; border: 0; box-shadow: none; padding: 0 4px;
                font-size: 21px; }
            #song-view header button, #queue-view header button,
            #album-track-view header button {
                background: rgba(48, 48, 48, 0.5); border: 0; box-shadow: none; }
            #song-view header button:hover, #queue-view header button:hover,
            #album-track-view header button:hover {
                background: rgba(70, 70, 70, 0.55); }
            #bar-track-title { font-weight: bold; }
            #bar-track-artist { color: #bbb; }
            #window-controls button { background: rgba(20, 20, 20, 0.78); border: 0;
                border-radius: 0; box-shadow: none; min-width: 22px; min-height: 22px;
                padding: 2px; font-size: 14px; font-weight: bold; }
            #window-controls button:hover { background: rgba(100, 100, 100, 0.5); }
            #window-controls button.close:hover { background: #b83d46; }
            #border-timeline { margin: 0; padding: 0 0 16px 0; min-height: 24px; }
            #border-timeline trough { background: #383838; border: 0;
                border-radius: 0; min-height: 8px; }
            #border-timeline highlight { background: #e7a641; border: 0;
                border-radius: 0; min-height: 8px; }
            #border-timeline:hover trough,
            #border-timeline:hover highlight,
            #border-timeline.hovering trough,
            #border-timeline.hovering highlight { min-height: 13px; }
            #border-timeline slider { background: transparent; border: 0;
                box-shadow: none; min-width: 0; min-height: 0; opacity: 0; }
            #wave-timeline { background: transparent; margin: 8px 0; }
            #plex-player *:focus { outline: none; box-shadow: none; }
            #side-nav-surface { background: #101010; border: 0; box-shadow: none; }
            #side-nav { background: transparent; border: 0; box-shadow: none; }
            #side-nav button { background: transparent; border: 0; box-shadow: none;
                padding: 12px; border-radius: 8px; }
            #side-nav button.active { background: #35302a; }
            #side-nav image { color: #eee; }
            #library-split { background: #181818; border: 0; box-shadow: none; }
            #library-stable-scrollbar { min-width: 14px; padding: 0; margin: 0;
                border: 0; }
            #library-stable-scrollbar slider,
            #library-stable-scrollbar slider:hover,
            #library-stable-scrollbar slider:active {
                min-width: 6px; margin: 0 4px; border: 0; transition: none; }
            #library-split separator { background: #181818; border: 0;
                box-shadow: none; min-width: 8px; }
            #library-side-split separator { background: #363636; border: 0;
                border-radius: 3px; box-shadow: none; min-height: 8px;
                margin: 0 8px; }
            #full-library-button { margin: 8px 8px 0 8px; }
            #playlist-panel, #smart-playlist-panel { background: #181818; border: 0; }
            #smart-playlist-header button, #smart-playlist-header button:hover,
            #smart-playlist-header button:active, #smart-playlist-header button:focus,
            #playlist-header button, #playlist-header button:hover,
            #playlist-header button:active, #playlist-header button:focus {
                background: transparent; background-image: none; border: 0; box-shadow: none; }
            #playlist-scroll, #playlist-scroll viewport, #playlist-list,
            #smart-playlist-scroll, #smart-playlist-scroll viewport, #smart-playlist-list,
            #style-scroll, #style-scroll viewport, #style-list,
            #song-scroll, #song-scroll viewport, #song-view {
                background: #111; border: 0; box-shadow: none; }
            #styles-panel, #styles-results { background: #181818; }
            #style-grid, #style-grid flowboxchild { background: transparent;
                border: 0; box-shadow: none; padding: 0; }
            #style-facet-card { background: #292929; border: 1px solid #444;
                border-radius: 5px; }
            #style-facet-title { font-size: 18px; font-weight: bold; color: #fff; }
            #style-facet-banner { background: rgba(0, 0, 0, 0.65); padding: 9px 8px; }
            #style-facet-card.has-art #style-facet-title {
                color: #fff; text-shadow: 0 1px 4px rgba(0, 0, 0, 0.9); }
            #style-result-mode { background: #3b3b3b; color: #eee;
                border: 1px solid #555; box-shadow: none; }
            #style-result-mode:hover { background: #4a4a4a; }
            #style-song-scroll, #style-song-scroll viewport, #style-song-view {
                background: #111; border: 0; box-shadow: none; }
            #style-song-view header button { background: rgba(48, 48, 48, 0.5);
                border: 0; box-shadow: none; }
            #style-song-view header button:hover { background: rgba(70, 70, 70, 0.55); }
            #style-list row { background: transparent; }
            #style-mode-button { background: transparent; color: #ddd; border: 0;
                border-bottom: 2px solid transparent; border-radius: 0;
                box-shadow: none; min-height: 44px; padding: 8px 16px;
                font-size: 18px; font-weight: bold; }
            #style-mode-button:hover { background: rgba(255, 255, 255, 0.08); }
            #style-tag-button { background: #252525; color: #eee;
                border: 0; border-radius: 0; box-shadow: none; }
            #style-tag-button { border: 0; border-radius: 0; }
            #playlist-panel row, #smart-playlist-panel row, #song-panel row { color: #eee; }
            #settings-panel, #settings-background, #settings-stack, #settings-tabs,
            #settings-tabs scrolledwindow, #settings-tabs viewport,
            #settings-tabs header { background: #181818; border: 0;
                box-shadow: none; }
            #settings-center, #settings-panel, #settings-tabs,
            #settings-tabs scrolledwindow, #settings-tabs viewport {
                background: #101010; }
            #settings-center { border-radius: 10px; }
            #settings-panel { padding: 24px; }
            .settings-section-title { font-weight: bold; font-size: 1.1em; }
            #settings-tabs > border { border: 0; box-shadow: none; }
            #settings-tab-bar { margin: 12px 0 4px 0; }
            #settings-tab-button { background: transparent; color: #ddd; border: 0;
                border-bottom: 2px solid transparent; border-radius: 0;
                box-shadow: none; min-height: 44px; padding: 8px 22px;
                font-size: 17px; font-weight: bold; }
            #settings-tab-button:hover { background: rgba(255, 255, 255, 0.08); }
            #song-drag-ghost { background: #292929; color: #f3f3f3;
                border: 1px solid #777; border-radius: 4px;
                box-shadow: 0 3px 10px rgba(0, 0, 0, 0.35); padding: 5px 10px; }
            #song-drop-line { background: #e7a641; min-height: 4px;
                box-shadow: 0 0 5px rgba(0, 0, 0, 0.75); }
            #song-panel { background: #181818; border: 0; }
            #queue-panel, #queue-scroll, #queue-scroll viewport, #queue-view {
                background: transparent; border: 0; box-shadow: none; }
            #startup-loading { background: #000; }
            #startup-loading label { font-size: 18px; font-weight: bold; }
            #now-scroll, #now-scroll viewport, #now-panel { background: transparent; }
            #song-panel button:checked { background: #514233; border-bottom: 2px solid #e7a641; }
            #now-title { font-size: 28px; font-weight: bold; }
            #now-artist { font-size: 19px; }
            #now-album { font-size: 17px; color: #ddd; }
            #art-toggle, #art-toggle:hover, #art-toggle:active {
                background: transparent; border: 0; padding: 0;
                border-radius: 0; box-shadow: none; }
            #window-resize-grip, #window-resize-grip * {
                background: transparent; border: 0; box-shadow: none; }
        """)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.text_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.text_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        self.accent_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.accent_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 3)
        self.theme_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.theme_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 4)
        self.sort_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.sort_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 5)
        self.theme = load_theme()
        self.gradient_enabled = load_gradient_enabled()
        self.background_visualizer_enabled = load_background_visualizer_enabled()
        self.visualizer_view = load_visualizer_view()
        self.instrument_visualizer_enabled = load_instrument_visualizer_enabled()
        self.frosted_player_bar = load_frosted_player_bar()
        self.timeline_waveform_enabled = load_timeline_waveform_enabled()
        self.accent_color = load_accent_color()
        self.art_accent_enabled = load_art_accent_enabled()
        self.current_art_bright = None
        self.current_wave_colors = None
        self.tooltips_hidden = load_tooltips_hidden()
        self.star_ratings_hidden = load_star_ratings_hidden()
        self.search_shortcut = load_search_shortcut()
        self.smooth_scrolling_enabled = load_smooth_scrolling_enabled()
        self.library_view_mode = load_library_view_mode()
        self.smooth_scrollers = weakref.WeakSet()
        self.tooltip_texts = weakref.WeakKeyDictionary()
        self.desktop_tooltips_enabled = Gtk.Settings.get_default().get_property('gtk-enable-tooltips')
        self.apply_tooltip_setting()
        self.apply_accent()
        self.show_album_details = load_album_details_enabled()
        self.gpu_wall_enabled = load_gpu_album_wall_enabled() and (sys.platform.startswith('linux') or sys.platform == 'win32')
        self.gpu_wall = None
        self.canvas_enabled = (not load_classic_album_wall_enabled() and
                               (sys.platform.startswith('linux') or sys.platform == 'win32'))
        self.album_canvas = None
        self.canvas_catalog = None
        self.canvas_catalog_identity = None
        self.canvas_search_source = 0
        if self.canvas_enabled:
            self.album_sort = 'year:desc'
        self.gpu_rebuild_generation = 0
        self.single_flip_enabled = load_single_flip_enabled()
        self.search_index_enabled = load_search_index_enabled()
        self.last_flipped_tile = None
        self.pending_flipped_tile = None
        self.text_size = load_text_size()
        self.custom_font = load_custom_font()
        self.album_art_size, self.now_art_size = load_art_sizes()
        self.album_columns = load_album_columns()
        self.album_margin, self.album_spacing = load_album_margins()
        self.keep_style_playing_enabled = load_keep_style_playing_enabled()
        self.auto_style_facet = None
        self.auto_style_keys = set()
        self.style_autoplay_pending = False
        self.style_autoplay_waiting = False
        self.style_autoplay_exhausted = False
        self.style_autoplay_generation = 0
        self.album_art_size = album_cover_size(self.normal_size[0] - 70,
                                               self.album_columns, self.album_margin,
                                               self.album_spacing)
        self.zoom_remainder = {'albums': 0.0, 'now': 0.0}
        self.current_art_colors = None
        self.current_art_key = None
        self.window_overlay = Gtk.Overlay()
        self.add(self.window_overlay)
        layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.window_overlay.add(layout)
        self.resize_grip = Gtk.EventBox()
        self.resize_grip.set_name('window-resize-grip')
        self.resize_grip.set_visible_window(True)
        self.resize_grip.set_above_child(True)
        self.resize_grip.set_halign(Gtk.Align.END)
        self.resize_grip.set_valign(Gtk.Align.END)
        self.resize_grip.set_size_request(28, 28)
        self.resize_grip.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                                    Gdk.EventMask.ENTER_NOTIFY_MASK |
                                    Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.resize_grip.get_accessible().set_name('Drag to resize window')
        self.resize_grip.connect('button-press-event', self.resize_grip_pressed)
        self.resize_grip.connect('enter-notify-event', self.resize_grip_entered)
        self.resize_grip.connect('leave-notify-event', self.resize_grip_left)
        grip_marks = Gtk.DrawingArea()
        grip_marks.connect('draw', self.draw_resize_grip)
        self.resize_grip.add(grip_marks)
        self.window_overlay.add_overlay(self.resize_grip)
        self.connect('window-state-event', self.resize_grip_window_state_changed)
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                               margin=8)
        self.sidebar.set_margin_end(8)
        self.sidebar.connect('button-press-event', self.context_menu_pressed)
        self.sidebar.set_name('side-nav')
        self.sidebar.set_size_request(70, -1)
        self.sidebar.set_halign(Gtk.Align.CENTER)
        self.sidebar_overlay = Gtk.Overlay()
        self.sidebar_overlay.set_hexpand(False)
        self.sidebar_volume_indicator = Gtk.DrawingArea()
        self.sidebar_volume_indicator.set_has_window(False)
        self.sidebar_volume_indicator.set_size_request(86, -1)
        self.sidebar_volume_indicator.set_hexpand(False)
        self.sidebar_volume_indicator.set_vexpand(True)
        self.sidebar_volume_indicator.connect('draw', self.draw_sidebar_volume)
        self.sidebar_overlay.add(self.sidebar_volume_indicator)
        self.sidebar_overlay.add_overlay(self.sidebar)
        self.sidebar_volume_visible = False
        self.sidebar_volume_opacity = 0.0
        self.sidebar_volume_timeout = 0
        self.sidebar_volume_tick = 0
        self.sidebar_volume_fade_start = None
        self.sidebar_volume_restore = 0.8
        self.sidebar_drop_surface = Gtk.EventBox()
        self.sidebar_drop_surface.set_hexpand(False)
        self.sidebar_drop_surface.set_visible_window(True)
        self.sidebar_drop_surface.set_name('side-nav-surface')
        self.sidebar_drop_surface.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.sidebar_drop_surface.connect('scroll-event', self.sidebar_volume_scroll)
        self.sidebar_drop_surface.add(self.sidebar_overlay)
        layout.pack_start(self.sidebar_drop_surface, False, False, 0)
        self.nav_drop_target = Gtk.TargetEntry.new('application/x-plex-sidebar-view',
                                                   Gtk.TargetFlags.SAME_APP, 2)
        self.sidebar_drop_surface.drag_dest_set(
            Gtk.DestDefaults.ALL, [self.nav_drop_target], Gdk.DragAction.MOVE)
        self.sidebar_drop_surface.connect('drag-motion', self.nav_drag_motion)
        self.sidebar_drop_surface.connect('drag-data-received', self.nav_drag_data_received)
        self.sidebar_order = load_sidebar_order()
        self.sidebar_visible = load_sidebar_visible()
        self.sidebar_labels_enabled = load_sidebar_labels_enabled()
        self.sidebar_note_animation_enabled = load_sidebar_note_animation_enabled()
        if self.sidebar_labels_enabled:
            self.sidebar.get_style_context().add_class('show-labels')
        self.nav_buttons = {}
        nav_items = {'now': ('Now playing', 'media-playback-start-symbolic'),
                     'albums': ('Albums', 'media-optical-symbolic'),
                     'library': ('Library', 'audio-x-generic-symbolic'),
                     'styles': ('Styles and moods', 'emblem-music-symbolic'),
                     'queue': ('Play queue', 'view-list-symbolic'),
                     'lyrics': ('Lyrics', 'accessories-text-editor-symbolic'),
                     'time': ('Time machine', 'appointment-soon-symbolic'),
                     'settings': ('Settings', 'emblem-system-symbolic')}
        for view in self.sidebar_order:
            label, icon = nav_items[view]
            button = self.add_nav_button(view, label, icon)
            if view not in self.sidebar_visible:
                button.set_no_show_all(True)
                button.hide()
            if view == 'queue':
                self.queue_nav = button
        self.sidebar_spacer = Gtk.Box()
        self.sidebar.pack_start(self.sidebar_spacer, True, True, 0)
        self.sidebar.reorder_child(self.sidebar_spacer, len(self.sidebar_order) - 1)
        self.nav_drop_gap = Gtk.Revealer()
        self.nav_drop_gap.set_no_show_all(True)
        self.nav_drop_gap.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.nav_drop_gap.set_transition_duration(180)
        self.nav_drop_gap.connect('notify::child-revealed', self.nav_gap_reveal_changed)
        gap_space = Gtk.Box()
        gap_space.set_size_request(-1, 48)
        self.nav_drop_gap.add(gap_space)
        gap_space.show()
        self.sidebar.pack_start(self.nav_drop_gap, False, False, 0)
        self.sidebar_volume_button = Gtk.Button()
        self.sidebar_volume_button.set_image(Gtk.Image.new_from_icon_name(
            'audio-volume-high-symbolic', Gtk.IconSize.LARGE_TOOLBAR))
        self.setup_sidebar_label(self.sidebar_volume_button, 'Volume')
        self.sidebar_volume_button.get_accessible().set_name('Volume')
        self.set_tooltip(self.sidebar_volume_button, 'Scroll to change volume; click to mute')
        self.sidebar_volume_button.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.sidebar_volume_button.connect('scroll-event', self.sidebar_volume_scroll)
        self.sidebar_volume_button.connect('clicked', self.sidebar_volume_clicked)
        self.sidebar.pack_start(self.sidebar_volume_button, False, False, 0)
        self.position_sidebar_volume()
        self.nav_drag_source = None
        self.nav_drag_insert = None
        self.nav_drag_centers = []
        self.nav_drag_completed = False
        self.queue_pulse_source = 0
        self.queue_pulse_started = 0.0
        self.queue_drop_targets = [
            Gtk.TargetEntry.new('application/x-plex-song-key', Gtk.TargetFlags.SAME_APP, 0),
            Gtk.TargetEntry.new('application/x-plex-album-key', Gtk.TargetFlags.SAME_APP, 1),
            self.nav_drop_target,
        ]
        self.queue_nav.drag_dest_set(Gtk.DestDefaults.ALL, self.queue_drop_targets,
                                     Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        self.queue_nav.connect('drag-data-received', self.queue_drop_received)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_overlay = Gtk.Overlay()
        main_overlay.add(main)
        layout.pack_start(main_overlay, True, True, 0)
        self.content_views = create_content_stack()
        self.content_views.add_events(Gdk.EventMask.SCROLL_MASK |
                                      Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.content_views.connect('scroll-event', self.lyrics_view_scroll)
        self.content_views.connect('button-press-event', self.context_menu_pressed)
        self.content_overlay = Gtk.Overlay()
        self.shared_background = DitheredGradient()
        self.shared_background.connect('size-allocate', self.background_allocated)
        self.content_overlay.add(self.shared_background)
        self.background_visualizer = RibbonVisualizer(windowless=True)
        self.background_visualizer.set_view(self.visualizer_view)
        self.background_visualizer.set_no_show_all(True)
        self.background_visualizer.set_hexpand(True)
        self.background_visualizer.set_vexpand(True)
        self.content_overlay.add_overlay(self.background_visualizer)
        self.content_overlay.set_overlay_pass_through(self.background_visualizer, True)
        self.content_overlay.add_overlay(self.content_views)
        main.pack_start(self.content_overlay, True, True, 0)
        self.build_info_panel()
        self.song_drag_overlay = Gtk.Fixed()
        self.song_drag_overlay.set_halign(Gtk.Align.FILL)
        self.song_drag_overlay.set_valign(Gtk.Align.FILL)
        self.content_overlay.add_overlay(self.song_drag_overlay)
        self.content_overlay.set_overlay_pass_through(self.song_drag_overlay, True)
        self.song_drop_line = Gtk.EventBox()
        self.song_drop_line.set_name('song-drop-line')
        self.song_drop_line.set_visible_window(True)
        self.song_drop_line.set_size_request(1, 4)
        self.song_drop_line.set_no_show_all(True)
        self.song_drag_overlay.put(self.song_drop_line, 0, 0)
        self.song_drag_ghost = Gtk.Label()
        self.song_drag_ghost.set_name('song-drag-ghost')
        self.song_drag_ghost.set_no_show_all(True)
        self.song_drag_overlay.put(self.song_drag_ghost, 0, 0)
        self.song_drag_row_ghost = Gtk.Image()
        self.song_drag_row_ghost.set_no_show_all(True)
        self.song_drag_overlay.put(self.song_drag_row_ghost, 0, 0)
        self.loading_overlay = Gtk.EventBox()
        self.loading_overlay.set_name('startup-loading')
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        loading_box.set_halign(Gtk.Align.CENTER)
        loading_box.set_valign(Gtk.Align.CENTER)
        self.loading_spinner = Gtk.Spinner()
        loading_box.pack_start(self.loading_spinner, False, False, 0)
        loading_box.pack_start(Gtk.Label(label='Loading…'), False, False, 0)
        self.loading_overlay.add(loading_box)
        self.content_overlay.add_overlay(self.loading_overlay)
        self.busy_spinner = Gtk.Spinner()
        self.busy_spinner.set_halign(Gtk.Align.END)
        self.busy_spinner.set_valign(Gtk.Align.START)
        self.busy_spinner.set_margin_top(12)
        self.busy_spinner.set_margin_end(90 if self.window_buttons_enabled else 14)
        self.busy_spinner.set_no_show_all(True)
        self.content_overlay.add_overlay(self.busy_spinner)
        self.busy = BusyIndicator(self.busy_spinner)
        self.busy.begin()
        self.window_controls = Gtk.Box(spacing=0)
        self.window_controls.set_name('window-controls')
        self.window_controls.set_halign(Gtk.Align.END)
        self.window_controls.set_valign(Gtk.Align.START)
        self.window_controls.set_margin_top(4)
        self.window_controls.set_margin_end(4)
        self.window_controls.set_no_show_all(True)
        for glyph, label, callback in (
                ('−', 'Minimize', lambda *_: self.iconify()),
                ('□', 'Maximize', self.toggle_window_maximize),
                ('×', 'Close', lambda *_: self.destroy())):
            button = Gtk.Button(label=glyph)
            self.set_tooltip(button, label)
            button.get_accessible().set_name(label)
            button.connect('clicked', callback)
            if label == 'Maximize':
                self.maximize_button = button
            if label == 'Close':
                button.get_style_context().add_class('close')
            self.window_controls.pack_start(button, False, False, 0)
        self.content_overlay.add_overlay(self.window_controls)
        self.connect('window-state-event', self.window_state_changed)
        self.buffering_busy = False
        self.album_web_wall = None
        self.album_web_generation = 0
        self.album_web_history = []
        self.album_web_identity = None
        self.album_web_album = None
        self.album_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_views.add_named(self.album_panel, 'albums')
        toolbar = Gtk.Box()
        toolbar.set_name('library-toolbar')
        self.album_toolbar = toolbar
        toolbar_controls = Gtk.Box(spacing=0, margin_top=6, margin_bottom=8,
                                   margin_start=12, margin_end=12)
        toolbar_controls.set_halign(Gtk.Align.CENTER)
        toolbar.pack_start(toolbar_controls, True, True, 0)
        self.library = Gtk.ComboBoxText()
        self.library.connect('changed', self.library_changed)
        self.search = Gtk.SearchEntry(placeholder_text=('Search albums and artists' if self.canvas_enabled else
                                                       'Search albums and artists; press Enter'))
        self.search.connect('key-press-event', self.search_escape_pressed)
        self.search.connect('activate', self.search_album_titles)
        self.search.connect('search-changed', self.canvas_search_changed)
        self.search.set_width_chars(14)
        self.search.set_max_width_chars(22)
        self.search.set_valign(Gtk.Align.CENTER)
        self.search.set_margin_start(6)
        self.album_search_revealer = Gtk.Revealer()
        self.album_search_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.album_search_revealer.set_transition_duration(180)
        self.album_search_revealer.add(toolbar)
        self.album_search_revealer.connect('notify::reveal-child',
                                           lambda *_: self.invalidate_frosted_backdrops())
        self.views = Gtk.Stack()
        self.album_panel.pack_start(self.views, True, True, 0)
        wall = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=self.album_spacing,
                       margin=self.album_margin)
        wall.set_margin_top(self.album_margin + 36)
        self.album_wall = wall
        sort_bar = Gtk.Box()
        sort_bar.set_name('album-sort-bar')
        sort_bar.set_hexpand(True)
        sort_bar.set_valign(Gtk.Align.START)
        sort_bar.set_size_request(-1, 36)
        sort_buttons = Gtk.Box(spacing=0)
        sort_buttons.set_halign(Gtk.Align.CENTER)
        self.album_sort_buttons = {}
        for index, (label, sort) in enumerate(ALBUM_SORT_OPTIONS):
            button = Gtk.Button(label=label.upper())
            if index < len(ALBUM_SORT_OPTIONS) - 1:
                button.get_style_context().add_class('sort-divider')
            button.connect('clicked', self.change_album_sort, sort)
            sort_buttons.pack_start(button, False, False, 0)
            self.album_sort_buttons[sort] = button
        sort_buttons.pack_start(self.search, False, False, 0)
        sort_bar.set_center_widget(sort_buttons)
        album_actions = Gtk.Box(spacing=0)
        album_actions.set_name('album-actions')
        album_actions.set_valign(Gtk.Align.CENTER)
        self.album_reload_button = self.icon_button('view-refresh-symbolic', 'Reload albums',
                                                    self.reload_albums)
        self.album_zoom_in_button = self.icon_button('zoom-in-symbolic', 'Zoom in',
                                                     lambda *_: self.change_album_zoom(1))
        self.album_zoom_out_button = self.icon_button('zoom-out-symbolic', 'Zoom out',
                                                      lambda *_: self.change_album_zoom(-1))
        self.album_zoom_in_button.set_image(AlbumZoomIcon(True))
        self.album_zoom_out_button.set_image(AlbumZoomIcon(False))
        self.album_fewer_columns_button = self.icon_button('list-remove-symbolic', 'Fewer album columns',
                                                           lambda *_: self.change_canvas_columns(-1))
        self.album_more_columns_button = self.icon_button('list-add-symbolic', 'More album columns',
                                                          lambda *_: self.change_canvas_columns(1))
        for button in (self.album_fewer_columns_button, self.album_more_columns_button):
            button.set_no_show_all(True)
            button.set_visible(self.canvas_enabled)
        for button in (self.album_zoom_out_button, self.album_zoom_in_button,
                       self.album_fewer_columns_button, self.album_more_columns_button,
                       self.album_reload_button):
            album_actions.pack_start(button, False, False, 0)
        sort_bar.pack_end(album_actions, False, False, 0)
        self.album_sort_bar = sort_bar
        self.update_album_sort_buttons()
        self.artist_filter_bar = Gtk.Box(spacing=10)
        self.artist_filter_bar.set_no_show_all(True)
        self.album_results_back = Gtk.Button(label='◀')
        self.album_results_back.set_name('album-results-back')
        self.set_tooltip(self.album_results_back, 'Back to all albums')
        self.album_results_back.get_accessible().set_name('Back to all albums')
        self.album_results_back.connect('clicked', self.show_all_albums)
        self.artist_filter_bar.pack_start(self.album_results_back, False, False, 0)
        self.artist_filter_label = Gtk.Label(xalign=0)
        self.artist_filter_label.set_valign(Gtk.Align.CENTER)
        self.album_results_back.set_valign(Gtk.Align.CENTER)
        self.artist_filter_bar.pack_start(self.artist_filter_label, True, True, 0)
        wall.pack_start(self.artist_filter_bar, False, False, 0)
        self.grid = Gtk.FlowBox()
        self.grid.connect('key-press-event', self.search_escape_pressed)
        self.grid.set_name('album-grid')
        self.grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.grid.set_homogeneous(True)
        self.grid.set_min_children_per_line(self.album_columns)
        self.grid.set_max_children_per_line(self.album_columns)
        self.grid.set_row_spacing(self.album_spacing)
        self.grid.set_column_spacing(self.album_spacing)
        self.grid.set_valign(Gtk.Align.START)
        self.grid.set_halign(Gtk.Align.CENTER)
        self.grid.connect('scroll-event', self.zoom_art, 'albums')
        wall.pack_start(self.grid, False, False, 0)
        wall_scroll = self.scroll(wall)
        wall_scroll.set_name('library-wall')
        wall_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_tooltip(wall_scroll, 'Hold Ctrl and scroll to resize album covers')
        wall_scroll.connect('scroll-event', self.zoom_art, 'albums')
        wall_scroll.connect('size-allocate', self.album_wall_allocated)
        wall_scroll.connect('map', self.album_wall_mapped)
        self.wall_scroll = wall_scroll
        wall_adjustment = wall_scroll.get_vadjustment()
        wall_adjustment.connect('value-changed', self.album_scroll_changed)
        wall_adjustment.connect('changed', self.album_scroll_changed)
        wall_overlay = Gtk.Overlay()
        self.album_wall_stack = Gtk.Stack()
        self.album_wall_stack.add_named(wall_scroll, 'gtk')
        wall_overlay.add(self.album_wall_stack)
        album_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        album_top.set_valign(Gtk.Align.START)
        album_top.set_hexpand(True)
        album_top.pack_start(sort_bar, False, False, 0)
        album_top.pack_start(self.album_search_revealer, False, False, 0)
        self.album_top = album_top
        wall_overlay.add_overlay(album_top)
        album_top.connect('size-allocate', self.album_top_allocated)
        self.views.add_named(wall_overlay, 'wall')
        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=16)
        detail.pack_start(self.button('‹ All albums', lambda *_: self.views.set_visible_child_name('wall')), False, False, 0)
        album_header = Gtk.Box(spacing=18)
        self.cover = Gtk.Image()
        self.set_placeholder_art(self.cover, 160)
        album_header.pack_start(self.cover, False, False, 0)
        album_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.album_label = Gtk.Label(label='Choose an album', xalign=0)
        self.album_label.set_line_wrap(True)
        album_info.pack_start(self.album_label, False, False, 0)
        self.album_artist = Gtk.Label(xalign=0)
        album_artist_click = Gtk.EventBox()
        album_artist_click.set_visible_window(False)
        album_artist_click.add(self.album_artist)
        album_artist_click.connect('button-press-event', self.artist_name_pressed,
                                   lambda: self.selected_album.artist if self.selected_album else '')
        album_info.pack_start(album_artist_click, False, False, 0)
        self.album_year = Gtk.Label(xalign=0)
        album_info.pack_start(self.album_year, False, False, 0)
        album_header.pack_start(album_info, True, True, 0)
        album_header.pack_end(self.button('Play album', lambda *_: self.play_album(0)), False, False, 0)
        detail.pack_start(album_header, False, False, 0)
        self.track_store = Gtk.ListStore(str, str, str, str)
        self.track_view = self.table(self.track_store, ['#', 'Track', 'Time', 'Rating'])
        self.track_view.set_name('album-track-view')
        self.detail_rating_column = self.track_view.get_columns()[3]
        detail_marker = Gtk.CellRendererText()
        detail_marker.set_fixed_size(22, -1)
        detail_marker.set_property('xalign', 0.5)
        track_column = self.track_view.get_columns()[1]
        track_column.pack_start(detail_marker, False)
        track_column.reorder(detail_marker, 0)
        track_column.set_cell_data_func(detail_marker, self.album_detail_playing_marker)
        self.track_view.connect('key-press-event', self.search_escape_pressed)
        self.track_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.track_view.connect('row-activated', self.activate_track)
        detail_song_target = [Gtk.TargetEntry.new('application/x-plex-song-key',
                                                  Gtk.TargetFlags.SAME_APP, 0)]
        self.track_view.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK,
                                                  detail_song_target, Gdk.DragAction.COPY)
        self.track_view.connect('drag-begin', self.collection_drag_begin, 'album')
        self.track_view.connect('drag-end', self.collection_drag_end, 'album')
        self.track_view.connect('drag-data-get', self.album_track_drag_data_get)
        self.track_view.connect('button-press-event', self.album_track_pressed)
        detail.pack_start(self.scroll(self.track_view), True, True, 0)
        self.views.add_named(detail, 'detail')
        self.views.set_visible_child_name('wall')
        self.build_now_view()
        self.build_library_view()
        self.build_styles_view()
        self.time_machine = TimeMachineView(self)
        self.content_views.add_named(self.time_machine.widget, 'time')
        self.build_queue_view()
        self.build_lyrics_view()
        self.build_settings_view()
        self.apply_star_rating_visibility()
        self.render_gradient()
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar.set_name('player-bar')
        self.player_bar = bar
        bar.connect('button-press-event', self.context_menu_pressed)
        self.player_bar_spacer = Gtk.Box()
        main.pack_end(self.player_bar_spacer, False, False, 0)
        bar.set_halign(Gtk.Align.FILL)
        bar.set_valign(Gtk.Align.END)
        main_overlay.add_overlay(bar)
        bar.connect('size-allocate', self.player_bar_allocated)
        bar.connect('notify::visible', self.player_bar_visibility_changed)
        self.frosted_style = Gtk.CssProvider()
        self.frosted_style.load_from_data(b'#player-bar.frosted { background: transparent; background-image: none; }')
        bar.get_style_context().add_provider(self.frosted_style, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.frosted_bar = FrostedBar(bar, self.content_views, self.shared_background,
                                      lambda: self.theme,
                                      lambda: Player.solid_timeline_background(self),
                                      capture_allowed=lambda: Player.library_frosted_capture_allowed(self),
                                      capture_content=lambda: not Player.gpu_wall_is_mapped(self),
                                      gpu_surface=lambda: Player.gpu_glass_surface(self, self.player_bar))
        self.setup_frosted_top_bars()
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.01)
        self.seek.set_name('border-timeline')
        self.seek.set_draw_value(False)
        self.seek.set_digits(2)
        self.seek.connect('change-value', self.seek_to)
        self.seek.connect('button-press-event', self.timeline_pressed)
        self.seek.connect('button-release-event', self.timeline_released)
        self.seek.add_events(Gdk.EventMask.POINTER_MOTION_MASK |
                             Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.seek.connect('motion-notify-event', self.timeline_motion)
        self.seek.connect('leave-notify-event', self.timeline_leave)
        self.seek.connect_after('draw', self.draw_timeline_marker)
        self.seek.set_sensitive(False)
        self.wave_timeline = TrackWaveform()
        self.wave_timeline.set_name('wave-timeline')
        self.wave_timeline.set_sensitive(False)
        self.wave_timeline.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                                      Gdk.EventMask.BUTTON_RELEASE_MASK |
                                      Gdk.EventMask.POINTER_MOTION_MASK |
                                      Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.wave_timeline.connect('button-press-event', self.wave_timeline_pressed)
        self.wave_timeline.connect('button-release-event', self.wave_timeline_released)
        self.wave_timeline.connect('motion-notify-event', self.wave_timeline_motion)
        self.wave_timeline.connect('leave-notify-event', self.timeline_leave)
        self.wave_timeline.connect_after('draw', self.draw_timeline_marker)
        self.seek.connect('value-changed', self.timeline_value_changed)
        self.timeline_stack = Gtk.Stack()
        self.timeline_stack.set_vhomogeneous(False)
        self.timeline_stack.add_named(self.seek, 'line')
        self.timeline_stack.add_named(self.wave_timeline, 'waveform')
        self.timeline_stack.set_visible_child_name(
            'waveform' if self.timeline_waveform_enabled else 'line')
        bar.pack_start(self.timeline_stack, False, False, 0)
        controls = Gtk.Overlay()
        bar.pack_start(controls, False, False, 0)
        sides = Gtk.Box(spacing=10, margin=10)
        sides.set_margin_end(32)
        controls.add(sides)
        song_area = Gtk.Box(spacing=9)
        song_area.set_size_request(205, -1)
        song_area.set_hexpand(True)
        sides.pack_start(song_area, True, True, 0)
        self.song_info_button = Gtk.Button()
        self.song_info_button.set_name('song-info-button')
        self.song_info_button.get_accessible().set_name('Show Now Playing')
        self.song_info_button.connect('clicked', self.toggle_now_panel)
        song_area.pack_start(self.song_info_button, False, False, 0)
        self.now_cover = Gtk.Image()
        self.set_placeholder_art(self.now_cover, 48)
        self.song_info_button.add(self.now_cover)
        song_labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        song_labels.set_valign(Gtk.Align.CENTER)
        song_labels.set_hexpand(True)
        song_area.pack_start(song_labels, True, True, 0)
        self.song_title_button = Gtk.Button()
        self.song_title_button.set_name('song-info-button')
        self.song_title_button.get_accessible().set_name('Show Now Playing')
        self.song_title_button.connect('clicked', self.toggle_now_panel)
        song_labels.pack_start(self.song_title_button, False, False, 0)
        self.now_title = Gtk.Label(label='Nothing playing', xalign=0)
        self.now_title.set_name('bar-track-title')
        self.now_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.now_title.set_max_width_chars(24)
        self.song_title_button.add(self.now_title)
        self.song_artist_button = Gtk.Button()
        self.song_artist_button.set_name('song-info-button')
        self.song_artist_button.get_accessible().set_name('Show Artist Albums')
        self.set_tooltip(self.song_artist_button, 'Show Artist Albums')
        self.song_artist_button.connect('clicked', self.show_current_artist_albums)
        song_labels.pack_start(self.song_artist_button, False, False, 0)
        self.now_artist = Gtk.Label(label='', xalign=0)
        self.now_artist.set_name('bar-track-artist')
        self.now_artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.now_artist.set_max_width_chars(24)
        self.song_artist_button.add(self.now_artist)
        playback_buttons = Gtk.Box(spacing=6)
        self.transport_buttons = playback_buttons
        playback_buttons.set_halign(Gtk.Align.CENTER)
        playback_buttons.set_valign(Gtk.Align.CENTER)
        controls.add_overlay(playback_buttons)
        previous_button = self.icon_button('media-skip-backward-symbolic', 'Previous', self.previous)
        self.previous_button = previous_button
        previous_button.set_name('transport-skip')
        previous_button.get_image().set_pixel_size(28)
        playback_buttons.pack_start(previous_button, False, False, 0)
        self.play_button = self.icon_button('media-playback-start-symbolic', 'Play', self.toggle)
        self.play_button.set_name('transport-play')
        self.play_button.get_image().set_pixel_size(38)
        playback_buttons.pack_start(self.play_button, False, False, 0)
        next_button = self.icon_button('media-skip-forward-symbolic', 'Next', lambda *_: self.advance())
        self.next_button = next_button
        next_button.set_name('transport-skip')
        next_button.get_image().set_pixel_size(28)
        playback_buttons.pack_start(next_button, False, False, 0)
        utilities = Gtk.Box(spacing=6)
        utilities.set_hexpand(True)
        utilities.set_halign(Gtk.Align.END)
        sides.pack_end(utilities, True, True, 0)
        self.time = Gtk.Label(label='0:00 / 0:00')
        utilities.pack_start(self.time, False, False, 0)
        self.shuffle = self.icon_toggle('media-playlist-shuffle-symbolic', 'Shuffle')
        self.repeat = self.icon_toggle('media-playlist-repeat-symbolic', 'Repeat')
        self.shuffle.connect('toggled', self.playback_options_changed)
        self.repeat.connect('toggled', self.playback_options_changed)
        self.update_skip_buttons()
        utilities.pack_start(self.shuffle, False, False, 0)
        utilities.pack_start(self.repeat, False, False, 0)
        self.info_button = Gtk.ToggleButton()
        info_icon = Gtk.Label(label='i')
        info_icon.set_name('info-icon')
        info_icon.set_halign(Gtk.Align.CENTER)
        info_icon.set_valign(Gtk.Align.CENTER)
        self.info_button.add(info_icon)
        self.info_button.set_name('info-button')
        self.set_tooltip(self.info_button, 'Track information')
        self.info_button.get_accessible().set_name('Track information')
        self.info_button.connect('toggled', self.info_toggled)
        utilities.pack_start(self.info_button, False, False, 0)
        self.volume = Gtk.Adjustment(value=0.8, lower=0, upper=1,
                                     step_increment=0.05, page_increment=0.1)
        self.pipeline.set_property('volume', 0.8)
        self.hero_waveform.set_volume(0.8)
        self.background_visualizer.set_volume(0.8)
        self.volume.connect('value-changed',
                            lambda adjustment: self.volume_changed(adjustment, adjustment.get_value()))
        self.update_sidebar_volume()
        self.status = Gtk.Label(label='Connect to your Plex server')
        self.status.connect('notify::label', self.status_changed)
        self.status_changed()
        self.apply_theme()
        self.show_all()
        self.apply_frosted_player_bar()
        self.song_drag_ghost.hide()
        self.song_drop_line.hide()
        self.update_window_controls()
        self.timeline_stack.set_visible_child_name(
            'waveform' if self.timeline_waveform_enabled else 'line')
        self.content_views.set_sensitive(False)
        self.sidebar.set_sensitive(False)
        self.player_bar.set_sensitive(False)
        self.loading_spinner.start()
        self.apply_tooltip_setting()
        self.album_search_revealer.set_reveal_child(False)
        self.artist_filter_bar.hide()
        self.library_back_button.hide()
        self.apply_text_size()
        saved_panel = self.saved_session.get('panel', 'albums')
        self.show_view(saved_panel if saved_panel in self.sidebar_visible else
                       ('albums' if 'albums' in self.sidebar_visible else 'settings'))
        settings_tab = self.saved_session.get('settings_tab',
                                              3 if self.saved_session.get('settings_page') == 'shortcuts' else 0)
        self.settings_tabs.set_current_page(settings_tab)
        if settings_tab == 3:
            self.shortcut_scroll.show_all()
            self.refresh_shortcuts()
        if window.get('maximized'):
            self.maximize()
        self.mpris = Mpris(self) if mpris_enabled and Mpris else InactiveMpris()
        self.portal_shortcuts = PortalShortcuts(self, self.refresh_shortcuts) if sys.platform.startswith('linux') else None
        if self.portal_shortcuts:
            self.portal_shortcuts.start()
        GLib.timeout_add(500, self.tick)
        GLib.timeout_add(33, self.animate_timeline)
        GLib.timeout_add_seconds(3600, self.refresh_album_ages)
        GLib.timeout_add_seconds(30, self.refresh_remote_connection)
        GLib.idle_add(self.restore_connection)
        GLib.idle_add(self.initialize_remote)
        GLib.idle_add(self.initialize_lastfm)
        if self.canvas_enabled:
            GLib.idle_add(self.enable_album_canvas)
        elif self.gpu_wall_enabled:
            GLib.idle_add(self.enable_gpu_wall)

    def playback_options_changed(self, *_):
        self.update_skip_buttons()
        if hasattr(self, 'mpris'):
            self.mpris.changed()

    def update_skip_buttons(self):
        if not hasattr(self, 'previous_button') or not hasattr(self, 'next_button'):
            return
        queue = getattr(self, 'queue', ())
        index = getattr(self, 'index', -1)
        self.previous_button.set_sensitive(bool(queue) and index > 0)
        repeat = getattr(self, 'repeat', None)
        shuffle = getattr(self, 'shuffle', None)
        self.next_button.set_sensitive(bool(queue) and (
            index + 1 < len(queue) or
            (repeat is not None and repeat.get_active()) or
            (shuffle is not None and shuffle.get_active() and len(queue) > 1)))

    def volume_changed(self, _button, value):
        self.pipeline.set_property('volume', value)
        if hasattr(self, 'hero_waveform'):
            self.hero_waveform.set_volume(value)
        if hasattr(self, 'background_visualizer'):
            self.background_visualizer.set_volume(value)
        if hasattr(self, 'mpris'):
            self.mpris.changed()
        if hasattr(self, 'sidebar_volume_button'):
            self.update_sidebar_volume()

    def set_volume(self, value):
        self.volume.set_value(value)

    def position_sidebar_volume(self):
        children = [child for child in self.sidebar.get_children()
                    if child is not self.sidebar_volume_button]
        self.sidebar.reorder_child(self.sidebar_volume_button,
                                   children.index(self.nav_buttons['settings']) + 1)

    def update_sidebar_volume(self):
        value = self.volume.get_value()
        icon = ('audio-volume-muted-symbolic' if value <= 0 else
                'audio-volume-low-symbolic' if value < .34 else
                'audio-volume-medium-symbolic' if value < .67 else
                'audio-volume-high-symbolic')
        self.sidebar_volume_button.get_image().set_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
        self.sidebar_volume_button.get_accessible().set_description(f'{round(value * 100)} percent')
        if self.sidebar_volume_visible:
            self.sidebar_volume_indicator.queue_draw()

    def show_sidebar_volume(self):
        self.sidebar_volume_visible = True
        self.sidebar_volume_opacity = 1.0
        if self.sidebar_volume_tick:
            self.sidebar_volume_indicator.remove_tick_callback(self.sidebar_volume_tick)
            self.sidebar_volume_tick = 0
        self.sidebar_volume_indicator.queue_draw()
        if self.sidebar_volume_timeout:
            GLib.source_remove(self.sidebar_volume_timeout)
        self.sidebar_volume_timeout = GLib.timeout_add(1200, self.hide_sidebar_volume)

    def hide_sidebar_volume(self):
        self.sidebar_volume_timeout = 0
        self.sidebar_volume_fade_start = None
        if not self.sidebar_volume_tick:
            self.sidebar_volume_tick = self.sidebar_volume_indicator.add_tick_callback(
                self.fade_sidebar_volume)
        return False

    def fade_sidebar_volume(self, _widget, clock):
        now = clock.get_frame_time()
        if self.sidebar_volume_fade_start is None:
            self.sidebar_volume_fade_start = now
        elapsed = max(0, (now - self.sidebar_volume_fade_start) / 1_000_000)
        self.sidebar_volume_opacity = max(0.0, 1.0 - elapsed / .5)
        self.sidebar_volume_indicator.queue_draw()
        if self.sidebar_volume_opacity <= 0:
            self.sidebar_volume_visible = False
            self.sidebar_volume_tick = 0
            return False
        return True

    def draw_sidebar_volume(self, widget, context):
        if not self.sidebar_volume_visible or not hasattr(self, 'volume'):
            return False
        color = ((self.current_art_bright if self.art_accent_enabled else None) or
                 self.accent_color)
        rgb = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        height = widget.get_allocated_height()
        level = max(0, min(1, self.volume.get_value()))
        context.set_source_rgba(*rgb, .16 * self.sidebar_volume_opacity)
        context.rectangle(0, height * (1 - level), widget.get_allocated_width(), height * level)
        context.fill()
        return False

    def sidebar_volume_scroll(self, _button, event):
        if event.direction == Gdk.ScrollDirection.UP:
            delta = 1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            delta = -1
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            valid, _x, y = event.get_scroll_deltas()
            if not valid or not y:
                return False
            delta = -y
        else:
            return False
        self.set_volume(max(0, min(1, self.volume.get_value() + delta * .05)))
        self.show_sidebar_volume()
        return True

    def sidebar_volume_clicked(self, *_):
        value = self.volume.get_value()
        if value > 0:
            self.sidebar_volume_restore = value
            self.set_volume(0)
        else:
            self.set_volume(self.sidebar_volume_restore or .8)
        self.show_sidebar_volume()

    def apply_text_size(self):
        size = self.text_size
        font = (self.custom_font or self.default_font_family).replace('\\', '\\\\').replace('"', '\\"')
        family = f' font-family: "{font}";' if font else ''
        self.text_provider.load_from_data(
            f'#plex-player {{ font-size: {size}px;{family} }} '
            f'#now-title {{ font-size: {round(size * 2.0)}px; }} '
            f'#now-artist {{ font-size: {round(size * 1.35)}px; }} '
            f'#now-album {{ font-size: {round(size * 1.2)}px; }} '
            f'#lyrics-song-title {{ font-size: {round(size * 1.35)}px; }} '
            f'#lyrics-artist {{ font-size: {round(size * 1.15)}px; }} '
            f'#album-grid #album-meta {{ font-size: {round(size * 0.8)}px; }}'.encode())
        if hasattr(self, 'lyrics_zoom_provider'):
            self.apply_lyrics_zoom()
        canvas = getattr(self, 'album_canvas', None)
        if canvas is not None:
            canvas.layout_changed()

    def apply_tooltip_setting(self):
        Gtk.Settings.get_default().set_property(
            'gtk-enable-tooltips', self.desktop_tooltips_enabled and not self.tooltips_hidden)
        if not hasattr(self, 'tooltip_texts'):
            return
        def visit(widget):
            if self.tooltips_hidden:
                if widget.get_has_tooltip():
                    text = widget.get_tooltip_text()
                    if text is not None and widget not in self.tooltip_texts:
                        self.tooltip_texts[widget] = text
                    widget.set_has_tooltip(False)
            elif widget in self.tooltip_texts:
                widget.set_tooltip_text(self.tooltip_texts[widget])
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    visit(child)
        visit(self)

    def set_tooltip(self, widget, text):
        self.tooltip_texts[widget] = text
        widget.set_tooltip_text(None if self.tooltips_hidden else text)

    def apply_accent(self):
        color = self.current_art_bright if self.art_accent_enabled else None
        color = color or self.accent_color
        red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
        wash = f'rgba({red}, {green}, {blue}, 0.22)'
        hover_wash = f'rgba({red}, {green}, {blue}, 0.30)'
        faded_accent = f'rgba({red}, {green}, {blue}, 0.78)'
        self.accent_provider.load_from_data(f'''
            #border-timeline highlight {{ background: {color}; }}
            #player-bar button:checked image, #side-nav button.active image {{ color: {color}; }}
            #player-bar #info-button:checked {{ color: {color}; }}
            #side-nav button.active, #song-panel button:checked,
            #song-panel treeview.view:selected, #queue-view:selected {{ background: {wash}; }}
            #smart-playlist-list row:selected, #playlist-list row:selected,
            #full-library-button.active {{ background: {wash}; }}
            #side-nav button.queue-pulse image {{ color: {color}; }}
            #song-panel button:checked {{ border-bottom: 2px solid {color}; }}
            #album-card-back button.playing-track {{ background: {wash}; }}
            #album-card-back #playing-marker {{ color: {color}; }}
            #album-card-back #album-explore-button,
            #album-card-back #album-explore-button:hover,
            #album-card-back #album-cover-button,
            #album-card-back #album-cover-button:hover {{
                background: rgba({red}, {green}, {blue}, 0.38); background-image: none; color: #ffffff;
                border: 0; box-shadow: none; padding: 2px 4px; font-size: 0.85em; }}
            #album-card-back #album-explore-button label,
            #album-card-back #album-cover-button label {{ color: #ffffff; }}
            #song-drop-line {{ background: {color}; }}
            #playlist-list row.playlist-drag-target {{
                box-shadow: inset 0 0 0 2px {color}; }}
            #settings-tab-button.active {{ background: {wash};
                border-bottom-color: {color}; }}
            #playlist-header-underline {{ background: {faded_accent}; min-height: 2px; border: 0; }}
            #side-nav button.active #sidebar-icon-label {{ color: {color}; }}
            #time-track-sort-button.active {{ background: {wash}; color: {color}; }}
            #time-action-button, #time-action-button:hover, #time-action-button:active,
            #time-action-button:checked {{ border-bottom-color: {color}; }}
            #time-machine-subtitle {{ color: {faded_accent}; }}
            #time-machine-engage, #time-machine-engage:hover,
            #time-machine-engage:active {{ border-bottom-color: {color}; }}
            #time-machine-rule {{ background: {wash}; min-height: 1px; border: 0; }}
            #style-mode-button.active {{ background: {wash};
                border-bottom: 2px solid {color}; }}
            #style-result-mode.active {{ background: {wash};
                border-bottom: 2px solid {color}; }}
            #style-facet-card:hover {{ border-color: {color}; }}
        '''.encode())
        self.sort_provider.load_from_data(f'''
            #song-view header button.sorted {{ background: {wash}; }}
            #song-view header button.sorted:hover {{ background: {hover_wash}; }}
            #library-sort-header .sort-arrow {{ color: {faded_accent}; }}
            #queue-history-more, #queue-history-more:hover,
            #queue-history-more:active, #queue-history-more:focus {{
                background: transparent; background-image: none;
                border: 0; box-shadow: none; outline: none;
            }}
        '''.encode())
        if hasattr(self, 'wave_timeline'):
            self.wave_timeline.set_color(color)
        if hasattr(self, 'hero_waveform'):
            wave_colors = self.current_wave_colors or (color, color)
            self.hero_waveform.set_colors(*wave_colors)
        if hasattr(self, 'background_visualizer'):
            wave_colors = self.current_wave_colors or (color, color)
            self.background_visualizer.set_colors(*wave_colors)
        if hasattr(self, 'lyrics_highlight'):
            self.lyrics_highlight.set_property('foreground', color)
        if hasattr(self, 'time_machine'):
            self.time_machine.refresh_selection_style()
        if hasattr(self, 'top_frosted_style'):
            self.update_frosted_top_style()
        if hasattr(self, 'sidebar_volume_indicator') and self.sidebar_volume_visible:
            self.sidebar_volume_indicator.queue_draw()
        if getattr(self, 'album_canvas', None) is not None:
            self.album_canvas.labels.queue_draw()
        for wall in (getattr(self, 'album_canvas', None), getattr(self, 'gpu_wall', None),
                     getattr(self, 'album_web_wall', None)):
            if wall is not None and getattr(wall, 'flips', None):
                for flip in wall.flips.values():
                    flip.dirty = True
                wall.queue_frame()
        Player.redraw_sidebar_icons(self)
        for name in ('song_view', 'queue_view', 'track_view'):
            view = getattr(self, name, None)
            if view is not None:
                view.queue_draw()

    def apply_theme(self):
        if self.theme == 'black':
            css = '''
                #plex-player, #side-nav-surface, #player-bar, #library-split,
                #library-split separator, #playlist-panel, #smart-playlist-panel, #song-panel,
                #playlist-scroll, #playlist-scroll viewport, #playlist-list,
                #smart-playlist-scroll, #smart-playlist-scroll viewport, #smart-playlist-list,
                #song-scroll, #song-scroll viewport, #song-view,
                #settings-panel, #settings-background, #settings-stack,
                #styles-panel, #styles-results, #style-scroll, #style-scroll viewport,
                #style-grid, #style-song-scroll, #style-song-scroll viewport,
                #style-song-view,
                #queue-panel, #queue-scroll, #queue-view,
                #startup-loading, #album-sort-bar button,
                #settings-tabs, #settings-tabs scrolledwindow, #settings-tabs viewport,
                #settings-tabs header, #plex-player entry,
                #plex-player notebook, #plex-player notebook header {
                    background: #000; }
                #playlist-list row, #playlist-list row:hover,
                #smart-playlist-list row, #smart-playlist-list row:hover { background: #000; }
                #library-side-split separator { background: #383838; }
                #album-grid button:hover { background: #000; }
                #song-view.view:selected, #queue-view.view:selected,
                #album-track-view.view:selected { background: #303030; color: #fff; }
                #smart-playlist-list row:selected { background: #303030; color: #fff; }
                #playlist-list row:selected, #full-library-button.active {
                    background: #303030; color: #fff; }
                #time-machine-view { background: #000; color: #eee; }
                #style-facet-card { background: #000; border-color: #444; }
                #style-song-view.view:selected { background: #303030; color: #fff; }
                #lyrics-panel, #lyrics-scroll, #lyrics-scroll viewport,
                #lyrics-view, #lyrics-view text { background: #000; color: #eee; }
                #info-panel { background: #000; color: #eee; border-left-color: #555; }
                #info-panel label { color: #eee; }
                #song-drag-ghost { background: #111; color: #fff; border-color: #666; }
                #settings-center, #settings-panel, #settings-tabs,
                #settings-tabs scrolledwindow, #settings-tabs viewport { background: #000; }
            '''
        elif self.theme == 'light':
            css = '''
                #plex-player, #settings-panel, #settings-background,
                #settings-stack, #playlist-panel,
                #smart-playlist-panel, #song-panel, #styles-panel, #styles-results,
                #startup-loading,
                #library-split, #library-split separator { background: #f5f5f3; color: #202326; }
                #library-side-split separator { background: #c9c9c5; }
                #plex-player label, #album-grid #album-title, #album-grid #album-meta,
                #now-album, #bar-track-artist { color: #202326; }
                #apistat-context-menu { background: #f5f5f3; color: #202326; }
                #apistat-context-menu menuitem, #apistat-context-menu menuitem label {
                    color: #202326; }
                #apistat-context-menu menuitem:hover { background: #d8d8d3; }
                #side-nav-surface, #player-bar {
                    background: #e9e9e6; color: #202326; }
                #song-drag-ghost { background: #fff; color: #202326;
                    border-color: #999; }
                #side-nav image, #player-bar image { color: #202326; }
                #playlist-scroll, #playlist-scroll viewport, #playlist-list,
                #smart-playlist-scroll, #smart-playlist-scroll viewport, #smart-playlist-list,
                #style-scroll, #style-scroll viewport, #style-grid,
                #style-song-scroll, #style-song-scroll viewport, #style-song-view,
                #song-scroll, #song-scroll viewport, #song-view,
                #queue-scroll, #queue-scroll viewport, #queue-view {
                    background: #fff; color: #202326; }
                #queue-panel { background: transparent; }
                #time-machine-view { background: transparent; color: #202326; }
                #lyrics-panel, #lyrics-scroll, #lyrics-scroll viewport,
                #lyrics-view, #lyrics-view text { background: transparent; color: #202326; }
                #info-panel { background: #f2f2ef; color: #202326; border-left-color: #c5c5bf; }
                #info-panel label { color: #202326; }
                #album-sort-bar { background: transparent; }
                #album-sort-bar button { background: #e2e2de; color: #202326; }
                #album-sort-bar button.sort-divider { border-right-color: #c6c6c1; }
                #album-sort-bar button:hover { background: #cecec9; }
                #album-sort-bar button.active { color: #101010; }
                #style-facet-card { background: #e7e7e3; border-color: #c5c5bf; }
                #style-facet-title { color: #fff; }
                #style-result-mode { background: #d9d9d4; color: #202326;
                    border-color: #bdbdb7; }
                #style-result-mode:hover { background: #c9c9c3; }
                #style-mode-button { color: #202326; }
                #style-mode-button:hover { background: rgba(0, 0, 0, 0.08); }
                #window-controls button { background: rgba(225, 225, 220, 0.8);
                    color: #202326; }
                #song-view header button, #queue-view header button,
                #album-track-view header button, #style-song-view header button {
                    background: rgba(233, 233, 230, 0.5); color: #202326; border: 0; }
                #song-view header button:hover, #queue-view header button:hover,
                #album-track-view header button:hover, #style-song-view header button:hover {
                    background: rgba(216, 216, 211, 0.6); color: #202326; }
                #plex-player entry, #plex-player notebook, #plex-player notebook header {
                    background: #fff; color: #202326; }
                #settings-tabs scrolledwindow, #settings-tabs viewport {
                    background: #e9e9e6; color: #202326; }
                #settings-center, #settings-panel, #settings-tabs {
                    background: #e9e9e6; color: #202326; }
                #settings-tabs header tab { background: #e9e9e6; color: #202326; }
                #settings-tabs header tab:hover { background: #d8d8d3; color: #202326; }
                #settings-tabs header tab:checked { background: #f5f5f3; color: #202326; }
                #settings-tabs button, #settings-tabs check {
                    background: #e9e9e6; color: #202326; border-color: #b6b6b0; }
                #settings-tab-button { color: #202326; }
                #settings-tab-button:hover { background: rgba(0, 0, 0, 0.08); }
                #plex-player button { color: #202326; }
                #style-tag-button,
                #settings-panel button:not(#settings-tab-button) {
                    background: #e2e2de; color: #202326;
                    border: 1px solid #c6c6c1; box-shadow: none; }
                #style-tag-button:hover,
                #settings-panel button:not(#settings-tab-button):hover {
                    background: #cecec9; color: #202326; }
                #border-timeline trough { background: #c8c8c3; }
                #album-grid button:hover { background: rgba(0, 0, 0, 0.08); }
                #song-view.view:selected, #queue-view.view:selected,
                #album-track-view.view:selected { background: #c6d9ed; color: #172638; }
                #style-song-view.view:selected { background: #c6d9ed; color: #172638; }
                #smart-playlist-list row:selected { background: #c6d9ed; color: #172638; }
                #playlist-list row:selected, #full-library-button.active {
                    background: #c6d9ed; color: #172638; }
                #full-library-button:hover { background: #e9e9e6; }
            '''
        else:
            css = ''
        if self.theme != 'black':
            # These panels sit above the shared gradient and ribbon. Keep their
            # surfaces transparent while preserving card and selection styling.
            css += '''
                #styles-panel, #styles-results, #style-scroll, #style-scroll viewport,
                #style-grid, #style-song-scroll, #style-song-scroll viewport,
                #style-song-view, #styles-results #library-wall,
                #styles-results #library-wall viewport {
                    background: transparent; background-image: none;
                }
            '''
        banner_color = '#eeeeec' if self.theme == 'light' else ('#000000' if self.theme == 'black' else '#242426')
        banner_text = '#222222' if self.theme == 'light' else '#eeeeee'
        css += f'''
            #time-action-banner {{ background: {banner_color}; background-image: none; }}
            #time-action-button, #time-action-button:hover, #time-action-button:active,
            #time-action-button:checked {{ color: {banner_text}; background: transparent;
                background-image: none; border-style: solid; border-width: 0 0 2px;
                border-radius: 0; box-shadow: none; padding: 8px 10px; }}
        '''
        css += '''
            #time-dial-panel { background: transparent; background-image: none;
                border: 0; padding: 8px; }
            #time-dial { background: transparent; border: 0;
                border-radius: 4px; padding: 10px 16px; }
            #time-dial-title { color: #e2ddd0; font-size: 14px; font-weight: bold;
                letter-spacing: 2px; }
            #time-dial-label { color: #c2bdb0; font-size: 12px; font-weight: bold; }
            #time-dial-value { font-family: monospace; font-size: 34px; font-weight: bold;
                color: transparent; background: #080b09; background-image: none;
                border: 1px solid #46483f; border-radius: 2px; padding: 2px 4px; }
            #time-dial-value selection { color: transparent; background: transparent; }
            #time-dial-value:focus { color: transparent; caret-color: transparent;
                border-color: rgba(230, 230, 220, 0.65); }
            #time-dial-step { padding: 0 7px; min-height: 0; font-size: 10px; }
            #time-machine-engage, #time-machine-engage:hover, #time-machine-engage:active {
                padding: 10px 22px; background: transparent; background-image: none;
                border-style: solid; border-width: 0 0 3px; border-radius: 0;
                box-shadow: none; font-weight: bold; letter-spacing: 1px; }
            #time-column-grip { background: rgba(150, 150, 150, 0.14); }
            #time-track-sort-button { border: 0; border-radius: 0;
                background: rgba(100, 100, 100, 0.20); background-image: none; }
            #time-machine-search-effect { color: #f9be67; font-family: monospace;
                font-size: 15px; font-weight: bold; letter-spacing: 1px; }
        '''
        css += '''
            #album-sort-bar #album-actions button,
            #album-sort-bar #album-actions button:hover,
            #album-sort-bar #album-actions button:active,
            #album-sort-bar #album-actions button:focus {
                background: transparent; background-image: none; border: 0; box-shadow: none;
            }
        '''
        self.theme_provider.load_from_data(css.encode())
        if hasattr(self, 'resize_grip'):
            self.resize_grip.queue_draw()
        Player.redraw_sidebar_icons(self)
        if hasattr(self, 'gradient_toggle'):
            self.gradient_toggle.set_sensitive(self.theme != 'black')
        fallback = '#f5f5f3' if self.theme == 'light' else '#000000'
        if hasattr(self, 'shared_background'):
            self.shared_background.set_fallback_color(fallback)
        for grid in (getattr(self, 'grid', None),
                     getattr(self, 'style_album_grid', None)):
            if grid is None:
                continue
            for child in grid.get_children():
                tile = child.get_child()
                tile.back_gradient.set_fallback_color(fallback)
                tile.back_gradient.set_colors(theme_gradient_colors(
                    getattr(tile, 'back_art_colors', None), self.theme))
        if hasattr(self, 'shared_background'):
            self.render_gradient()
        if hasattr(self, 'hero_waveform'):
            self.refresh_live_waveform()
        if hasattr(self, 'song_view'):
            Player.bind_song_cell_backgrounds(self)
            self.song_view.queue_draw()
        if hasattr(self, 'queue_store'):
            self.refresh_queue_view()

    def draw_resize_grip(self, widget, context):
        shade = 0.18 if self.theme == 'light' else 0.78
        context.set_source_rgba(shade, shade, shade, 0.58)
        context.set_line_width(1.6)
        context.set_line_cap(cairo.LINE_CAP_ROUND)
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        for inset in (9, 15, 21):
            context.move_to(width - inset, height - 3)
            context.line_to(width - 3, height - inset)
        context.stroke()
        return False

    def resize_grip_pressed(self, _widget, event):
        self.window_drag_start = None
        if event.button == 1 and not self.is_maximized():
            self.begin_resize_drag(Gdk.WindowEdge.SOUTH_EAST, event.button,
                                   int(event.x_root), int(event.y_root), event.time)
        return True

    def resize_grip_entered(self, _widget, event):
        if not self.is_maximized():
            event.window.set_cursor(Gdk.Cursor.new_for_display(
                self.get_display(), Gdk.CursorType.BOTTOM_RIGHT_CORNER))
        return False

    def resize_grip_left(self, _widget, event):
        event.window.set_cursor(None)
        return False

    def resize_grip_window_state_changed(self, _window, event):
        self.resize_grip.set_visible(not bool(event.new_window_state &
            (Gdk.WindowState.MAXIMIZED | Gdk.WindowState.FULLSCREEN)))
        return False

    def background_drag_pressed(self, _widget, event):
        if event.button == 1 and self.can_drag_window_from(Gtk.get_event_widget(event)):
            self.window_drag_start = (event.x_root, event.y_root)
        else:
            self.window_drag_start = None
        return False

    def background_drag_motion(self, _widget, event):
        start = self.window_drag_start
        if not start:
            return False
        if not event.state & Gdk.ModifierType.BUTTON1_MASK:
            self.window_drag_start = None
            return False
        if math.hypot(event.x_root - start[0], event.y_root - start[1]) < 8:
            return False
        self.window_drag_start = None
        self.begin_move_drag(1, int(event.x_root), int(event.y_root), event.time)
        return True

    def background_drag_released(self, _widget, _event):
        self.window_drag_start = None
        return False

    def can_drag_window_from(self, widget):
        blocked = (Gtk.Button, Gtk.Entry, Gtk.TextView, Gtk.TreeView, Gtk.Scale,
                   Gtk.Scrollbar, Gtk.ComboBox, Gtk.ListBox, Gtk.FlowBox,
                   Gtk.EventBox)
        while widget and widget is not self:
            if isinstance(widget, blocked) and widget is not self.sidebar_drop_surface:
                return False
            widget = widget.get_parent()
        return True

    def global_key_pressed(self, _window, event):
        canvas = getattr(self, 'album_canvas', None)
        if (sys.platform == 'win32' and canvas is not None and
                event.keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R)):
            canvas.windows_wheel_gesture.control_pressed(time.monotonic())
        if getattr(self, 'startup_loading', False):
            return True
        if event.keyval == Gdk.KEY_Escape and self.escape_search():
            return True
        modified = event.state & (Gdk.ModifierType.CONTROL_MASK |
                                  Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SUPER_MASK)
        focus = self.get_focus()
        editor = getattr(self, 'info_tag_editor', None)
        if (event.keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and editor and focus
                and (focus is editor or focus.is_ancestor(editor))):
            return False
        editing = is_text_editing(focus)
        shortcut = getattr(self, 'search_shortcut', 'Tab')
        shortcut_key, shortcut_modifiers = Gtk.accelerator_parse(shortcut)
        modifiers = event.state & Gtk.accelerator_get_default_mod_mask()
        if (not editing and Gdk.keyval_to_lower(event.keyval) == Gdk.keyval_to_lower(shortcut_key)
                and modifiers == shortcut_modifiers):
            if (self.content_views.get_visible_child_name() != 'albums' or
                    not self.album_search_revealer.get_reveal_child()):
                self.toggle_album_search()
            else:
                self.search.grab_focus()
            return True
        if event.keyval == Gdk.KEY_space and not modified:
            if editing:
                return False
            if not self.space_held:
                self.space_held = True
                self.toggle()
            return True
        if not editing and event.keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            disallowed = (Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SUPER_MASK |
                          Gdk.ModifierType.SHIFT_MASK)
            if not event.state & disallowed:
                if event.state & Gdk.ModifierType.CONTROL_MASK:
                    self.previous() if event.keyval == Gdk.KEY_Left else self.advance()
                elif self.seek.get_sensitive():
                    delta = -5 if event.keyval == Gdk.KEY_Left else 5
                    upper = self.seek.get_adjustment().get_upper()
                    self.seek_to(self.seek, None, max(0, min(upper, self.seek.get_value() + delta)))
                return True
        if not modified and not editing and Gdk.KEY_1 <= event.keyval <= Gdk.KEY_8:
            visible = getattr(self, 'sidebar_visible', self.sidebar_order)
            visible_order = [name for name in self.sidebar_order if name in visible]
            number = event.keyval - Gdk.KEY_1
            if number < len(visible_order):
                self.show_view(visible_order[number])
                return True
        if event.keyval != Gdk.KEY_f or modified:
            return False
        if editing:
            return False
        visible = self.sidebar_drop_surface.get_visible()
        self.sidebar_drop_surface.set_visible(not visible)
        self.player_bar.set_visible(not visible)
        return True

    def escape_search(self):
        panel = self.content_views.get_visible_child_name()
        if panel == 'albums':
            if self.views.get_visible_child_name() == 'web':
                self.album_web_back()
                return True
            if self.views.get_visible_child_name() == 'detail':
                self.views.set_visible_child_name('wall')
                return True
            if self.artist_filter or self.search.get_text().strip():
                self.show_all_albums()
                return True
            if self.album_search_revealer.get_reveal_child():
                self.album_search_revealer.set_reveal_child(False)
                return True
        elif panel == 'library':
            if self.library_album_filter or getattr(self, 'library_tag_filter', None):
                self.clear_library_album_filter()
                return True
            if self.library_search.get_text():
                self.library_search.set_text('')
                return True
        elif panel == 'styles':
            if self.styles_stack.get_visible_child_name() == 'results':
                self.style_results_back()
                return True
            if self.style_search.get_text():
                self.style_search.set_text('')
                return True
        return False

    def search_escape_pressed(self, _entry, event):
        return event.keyval == Gdk.KEY_Escape and self.escape_search()

    def global_key_released(self, _window, event):
        canvas = getattr(self, 'album_canvas', None)
        if (sys.platform == 'win32' and canvas is not None and
                event.keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R)):
            canvas.windows_wheel_gesture.control_released()
        if getattr(self, 'startup_loading', False):
            return True
        if event.keyval == Gdk.KEY_space:
            self.space_held = False
            return not is_text_editing(self.get_focus())
        return False

    def window_focus_out(self, *_):
        canvas = getattr(self, 'album_canvas', None)
        if canvas is not None and hasattr(canvas, 'windows_wheel_gesture'):
            canvas.windows_wheel_gesture.control_released()
        self.space_held = False
        self.queue_pointer_drag = None
        self.song_pointer_drag = None
        self.playlist_pointer_drag = None
        Player.set_playlist_drop_target(self, None)
        self.hide_song_drag_ghost()
        self.hide_song_drop_line()
        return False

    def album_wall_allocated(self, _widget, allocation):
        if getattr(self, '_album_wall_width', None) == allocation.width:
            return
        self._album_wall_width = allocation.width
        if not getattr(self, '_album_initial_layout_done', False):
            self.schedule_initial_album_layout()
            return
        if not getattr(self, '_album_layout_pending', False):
            self._album_layout_pending = True
            GLib.idle_add(self.update_album_wall_layout)

    def album_wall_mapped(self, _widget):
        if not getattr(self, '_album_initial_layout_done', False):
            self.schedule_initial_album_layout()

    def schedule_initial_album_layout(self):
        source = getattr(self, '_album_initial_layout_source', 0)
        if source:
            GLib.source_remove(source)
        self._album_initial_layout_source = GLib.timeout_add(350, self.update_album_wall_layout)

    def update_album_wall_layout(self):
        self._album_layout_pending = False
        if not getattr(self, '_album_initial_layout_done', False):
            if not self.wall_scroll.get_mapped() or self.wall_scroll.get_allocated_width() <= 100:
                self._album_initial_layout_source = 0
                return False
            if Player.window_resize_recent(self):
                return True
            self._album_initial_layout_source = 0
            self._album_initial_layout_done = True
            self.apply_album_grid_layout()
        else:
            self.apply_album_grid_columns()
        return False

    def album_scroll_changed(self, *_):
        self.maybe_load_more_albums()

    def gpu_load_more_albums(self):
        wall = getattr(self, 'gpu_wall', None)
        adjustment = wall.adjustment if wall is not None else None
        near_end = (adjustment is not None and adjustment.get_value() +
                    adjustment.get_page_size() >= adjustment.get_upper() - 160)
        if (getattr(self, 'gpu_wall_enabled', False) and near_end and not self.loading_albums and
                self.albums and len(self.albums) < self.total and
                self.content_views.get_visible_child_name() == 'albums' and
                self.views.get_visible_child_name() == 'wall'):
            self.load_albums(True)
        return False

    def classic_album_wall_changed(self, button):
        classic = button.get_active()
        try:
            save_classic_album_wall_enabled(classic)
        except OSError:
            self.status.set_text('Could not save album wall setting.')
        self.canvas_enabled = not classic and (sys.platform.startswith('linux') or sys.platform == 'win32')
        for control in (self.album_fewer_columns_button, self.album_more_columns_button):
            control.set_visible(self.canvas_enabled)
        self.search.set_placeholder_text('Search albums and artists' if self.canvas_enabled else
                                         'Search albums and artists; press Enter')
        self.gpu_wall_toggle.set_sensitive(classic and (sys.platform.startswith('linux') or sys.platform == 'win32'))
        self.generation += 1
        if self.canvas_enabled:
            self.enable_album_canvas()
        elif self.gpu_wall_enabled:
            self.enable_gpu_wall()
        else:
            self.disable_gpu_wall()
        if self.client and self.library.get_active_id():
            self.load_albums()

    def enable_album_canvas(self):
        if not self.canvas_enabled or self.closed:
            return False
        try:
            if self.album_canvas is None:
                from experimental_album_canvas import ExperimentalAlbumCanvas
                container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                header = Gtk.Box(spacing=10, margin_start=self.album_margin, margin_top=40)
                self.canvas_filter_header = header
                back = Gtk.Button(label='◀')
                back.set_name('album-results-back')
                back.set_valign(Gtk.Align.CENTER)
                self.set_tooltip(back, 'Back to all albums')
                back.get_accessible().set_name('Back to all albums')
                back.connect('clicked', self.show_all_albums)
                header.pack_start(back, False, False, 0)
                label = Gtk.Label(xalign=0)
                label.set_valign(Gtk.Align.CENTER)
                self.artist_filter_label.bind_property('label', label, 'label', GObject.BindingFlags.SYNC_CREATE)
                header.pack_start(label, True, True, 0)
                header.show_all()
                header.set_no_show_all(True)
                self.artist_filter_bar.bind_property('visible', header, 'visible', GObject.BindingFlags.SYNC_CREATE)
                header.connect('notify::visible', self.album_top_allocated)
                container.pack_start(header, False, False, 0)
                self.album_canvas = ExperimentalAlbumCanvas(self, self.album_canvas_failed,
                                                            self.album_canvas_pressed, embedded=True)
                container.pack_start(self.album_canvas, True, True, 0)
                self.canvas_hscroll = Gtk.Scrollbar(orientation=Gtk.Orientation.HORIZONTAL,
                                                    adjustment=self.album_canvas.x_adjustment)
                self.canvas_hscroll.set_no_show_all(True)
                self.album_canvas.x_adjustment.connect('changed', self.update_canvas_hscroll)
                container.pack_start(self.canvas_hscroll, False, False, 0)
                self.album_wall_stack.add_named(container, 'canvas')
                container.show_all()
                self.update_canvas_hscroll(self.album_canvas.x_adjustment)
            self.album_wall_stack.set_visible_child_name('canvas')
            self.set_album_frosted_source(self.album_canvas)
            self.album_top_allocated()
            self.update_queue_bottom_inset()
        except (OSError, ImportError, RuntimeError, AttributeError):
            self.album_canvas_failed()
        return False

    def update_canvas_hscroll(self, adjustment):
        canvas = getattr(self, 'album_canvas', None)
        if canvas is not None:
            _width, size, gap, margin, columns, _row, _total, _x = canvas.geometry()
            content_width = 2 * margin + columns * size + (columns - 1) * gap
            needed = content_width > adjustment.get_page_size() + .5
        else:
            needed = adjustment.get_upper() - adjustment.get_lower() > adjustment.get_page_size() + .5
        self.canvas_hscroll.set_visible(needed)

    def album_canvas_failed(self):
        if self.closed or not self.canvas_enabled:
            return False
        self.canvas_enabled = False
        if hasattr(self, 'classic_wall_toggle'):
            self.classic_wall_toggle.set_active(True)
        elif self.gpu_wall_enabled:
            self.enable_gpu_wall()
        else:
            self.disable_gpu_wall()
        self.status.set_text('Album canvas unavailable; using the classic wall.')
        return False

    def album_canvas_pressed(self, album, event, x, y):
        if event.button == 3:
            self.show_context_menu(event, gpu_album=album, gpu_wall=self.album_canvas)
        else:
            self.album_canvas.toggle_album(album)

    def ensure_album_web(self):
        if self.album_web_wall is not None:
            return True
        try:
            from album_web_wall import AlbumWebWall
            panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            header = Gtk.Box(spacing=8, margin_start=16, margin_end=16, margin_top=8, margin_bottom=6)
            header.pack_start(self.button('‹ Back', self.album_web_back), False, False, 0)
            header.pack_start(self.button('All albums', self.close_album_web), False, False, 0)
            self.album_web_title = Gtk.Label(xalign=0)
            self.album_web_title.set_hexpand(True)
            self.album_web_title.set_ellipsize(Pango.EllipsizeMode.END)
            header.pack_start(self.album_web_title, True, True, 0)
            header.pack_start(self.button('Tracklist', self.album_web_tracklist), False, False, 0)
            header.pack_start(self.button('Refresh', self.album_web_refresh), False, False, 0)
            panel.pack_start(header, False, False, 0)
            self.album_web_message = Gtk.Label(xalign=.5)
            self.album_web_message.set_margin_bottom(4)
            panel.pack_start(self.album_web_message, False, False, 0)
            self.album_web_wall = AlbumWebWall(self, self.album_web_failed, self.album_web_pressed)
            panel.pack_start(self.album_web_wall, True, True, 0)
            self.views.add_named(panel, 'web')
            panel.show_all()
            self.update_queue_bottom_inset()
            return True
        except (OSError, ImportError, RuntimeError, AttributeError):
            self.album_web_wall = None
            self.status.set_text('Album web requires a working GPU album wall.')
            return False

    def album_web_failed(self):
        self.close_album_web()
        self.status.set_text('Album web could not initialize GPU rendering.')
        return False

    def close_album_web(self, *_):
        self.album_web_generation += 1
        self.album_web_history.clear()
        if self.views.get_visible_child_name() == 'web':
            self.views.set_visible_child_name('wall')

    def album_web_back(self, *_):
        if len(self.album_web_history) > 1:
            self.album_web_history.pop()
            self.open_album_web(self.album_web_history[-1], add_history=False)
        else:
            self.close_album_web()

    def album_web_tracklist(self, *_):
        if self.album_web_wall and self.album_web_album:
            self.album_web_wall.toggle_album(self.album_web_album)

    def album_web_refresh(self, *_):
        if self.album_web_album:
            self.open_album_web(self.album_web_album, add_history=False, refresh=True)

    def album_web_pressed(self, album, event, _x, _y):
        if event.button == 3:
            self.show_context_menu(event, gpu_album=album, gpu_wall=self.album_web_wall)
        elif self.album_web_album:
            if album.key == self.album_web_album.key:
                self.album_web_wall.toggle_album(album)
            else:
                self.open_album_web(album)

    def open_album_web(self, album, add_history=True, refresh=False):
        client, section = self.client, self.library.get_active_id()
        if client is None or not section or not self.ensure_album_web():
            return
        if self.album_web_identity != (client, section):
            self.album_web_history.clear()
            self.album_web_identity = (client, section)
        if add_history and (not self.album_web_history or self.album_web_history[-1].key != album.key):
            self.album_web_history.append(album)
        self.album_web_generation += 1
        generation = self.album_web_generation
        self.album_web_album = album
        self.album_web_title.set_text(f'{album.artist} — {album.title}')
        self.album_web_message.set_text('Finding related albums with Last.fm…')
        self.album_web_wall.set_graph(client, album, [])
        self.views.set_visible_child_name('web')
        session = getattr(self, 'lastfm_session', None)
        credentials = lastfm.application_credentials() or (
            (session['api_key'], session['secret']) if session else None)
        cached = self.canvas_catalog if self.canvas_catalog_identity == (client, section) else None
        valid = lambda: (not self.closed and self.client is client and
                         self.library.get_active_id() == section and
                         self.album_web_generation == generation and
                         self.views.get_visible_child_name() == 'web')
        def work():
            from album_web import related_albums
            valid_worker = lambda: (not self.closed and self.client is client and
                                    self.album_web_generation == generation)
            catalog = cached if cached is not None else build_album_index(client, section, valid_worker)
            if catalog is None:
                return [], ''
            try:
                return related_albums(client, section, album, catalog, credentials, refresh=refresh), ''
            except lastfm.LastFMError as error:
                return [], str(error)
        def ready(result):
            related, error = result
            self.album_web_wall.set_graph(client, album, related)
            if error:
                self.album_web_message.set_text(error)
            elif related:
                self.album_web_message.set_text(f'{len(related)} related albums · Last.fm')
            else:
                self.album_web_message.set_text('No related albums found in this library.')
        self.async_work(work, ready, valid)

    def canvas_search_changed(self, *_args):
        if (not getattr(self, 'canvas_enabled', False) or not self.client or
                not self.search.has_focus() or
                (self.artist_filter and not self.search.get_text().strip())):
            return
        if self.canvas_search_source:
            GLib.source_remove(self.canvas_search_source)
        self.canvas_search_source = GLib.timeout_add(100, self.apply_canvas_search)

    def apply_canvas_search(self):
        self.canvas_search_source = 0
        if (not self.closed and self.canvas_enabled and self.client and
                self.views.get_visible_child_name() == 'wall' and
                not (self.artist_filter and not self.search.get_text().strip())):
            self.artist_filter = None
            self.load_albums()
        return False

    def load_canvas_albums(self, force_refresh=False):
        from experimental_album_canvas import search_catalog
        client, section = self.client, self.library.get_active_id()
        if not client or not section:
            return
        if self.album_canvas is None:
            self.enable_album_canvas()
        if not self.canvas_enabled or self.album_canvas is None:
            return
        self.views.set_visible_child_name('wall')
        self.generation += 1
        generation = self.generation
        identity = (client, section)
        catalog = self.canvas_catalog if not force_refresh and self.canvas_catalog_identity == identity else None
        title, artist, sort = self.search.get_text().strip(), self.artist_filter, self.album_sort
        if artist or title:
            self.artist_filter_label.set_text(f'Albums by {artist}' if artist else f'Search results for “{title}”')
            self.artist_filter_bar.set_no_show_all(False)
            self.artist_filter_bar.show_all()
        else:
            self.artist_filter_bar.hide()
        self.loading_albums = True
        self.status.set_text('Loading albums…')
        valid_worker = lambda: (not self.closed and self.canvas_enabled and self.client is client and
                                self.generation == generation)
        def work():
            source = catalog if catalog is not None else build_album_index(client, section, valid_worker)
            if source is None:
                return None
            candidates = (album for album in source if not artist or
                          album.artist.strip().casefold() == artist.strip().casefold())
            albums = search_catalog(candidates, title, sort)
            initial = (albums if not artist and not title else sort_albums(source, sort)) if catalog is None else None
            return source, albums, initial
        def loaded(result):
            if result is None:
                return
            source, albums, initial = result
            new_catalog = self.canvas_catalog is not source or self.canvas_catalog_identity != identity
            self.canvas_catalog, self.canvas_catalog_identity = source, identity
            if new_catalog:
                self.album_canvas.sort_order = sort
                # Initialize the persistent artwork atlas from the full catalog.
                self.album_canvas.set_albums(client, initial if initial is not None else source, reset=True)
            self.album_canvas.reorder(sort, albums=albums)
            self.albums, self.total = list(albums), len(albums)
            self.loading_albums = False
            controls = ('Scroll to pan • Pinch to zoom • Ctrl+wheel changes columns'
                        if sys.platform == 'win32' else
                        'Scroll to zoom • Ctrl+scroll changes columns')
            message = f'{len(albums)} albums • {controls}'
            warning = getattr(self, 'credential_warning', '')
            self.status.set_text(f'{warning} • {message}' if warning else message)
            self.finish_startup_loading()
        def failed():
            self.loading_albums = False
            self.finish_startup_loading()
        self.async_work(work, loaded, valid_worker, failed)

    def gpu_wall_toggled(self, button):
        self.gpu_wall_enabled = button.get_active()
        try:
            save_gpu_album_wall_enabled(self.gpu_wall_enabled)
        except OSError:
            self.status.set_text('Could not save album wall setting.')
        if self.gpu_wall_enabled:
            self.enable_gpu_wall()
        else:
            self.disable_gpu_wall()
        if hasattr(self, 'time_machine'):
            self.time_machine.render_albums()

    def enable_gpu_wall(self):
        if not self.gpu_wall_enabled or self.closed or getattr(self, 'canvas_enabled', False):
            return False
        try:
            if self.gpu_wall is None:
                from gpu_album_wall import GPUAlbumWall
                container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                header = Gtk.Box(spacing=10, margin_start=self.album_margin, margin_top=40)
                self.gpu_filter_header = header
                back = Gtk.Button(label='◀')
                back.set_name('album-results-back')
                back.set_valign(Gtk.Align.CENTER)
                self.set_tooltip(back, 'Back to all albums')
                back.get_accessible().set_name('Back to all albums')
                back.connect('clicked', self.show_all_albums)
                header.pack_start(back, False, False, 0)
                label = Gtk.Label(xalign=0)
                label.set_valign(Gtk.Align.CENTER)
                self.artist_filter_label.bind_property('label', label, 'label',
                                                       GObject.BindingFlags.SYNC_CREATE)
                header.pack_start(label, True, True, 0)
                # Show the children before excluding the header from the
                # container's show_all; its own visibility follows the filter.
                header.show_all()
                header.set_no_show_all(True)
                self.artist_filter_bar.bind_property('visible', header, 'visible',
                                                     GObject.BindingFlags.SYNC_CREATE)
                header.connect('notify::visible', self.album_top_allocated)
                container.pack_start(header, False, False, 0)
                self.gpu_wall = GPUAlbumWall(self, self.gpu_wall_failed)
                container.pack_start(self.gpu_wall, True, True, 0)
                self.album_wall_stack.add_named(container, 'gpu')
                container.show_all()
                self.album_top_allocated()
                self.update_queue_bottom_inset()
            self.gpu_rebuild_generation += 1
            self.gpu_rebuild_pending = False
            self.gpu_wall.set_albums(self.client, list(self.albums), reset=True)
            self.album_wall_stack.set_visible_child_name('gpu')
            self.set_album_frosted_source(self.gpu_wall)
            for child in self.grid.get_children():
                child.destroy()
            self.last_flipped_tile = self.pending_flipped_tile = None
        except (OSError, ImportError, RuntimeError, AttributeError):
            self.gpu_wall_failed()
        return False

    def gpu_wall_failed(self):
        if self.closed or not self.gpu_wall_enabled:
            return False
        self.gpu_wall_enabled = False
        if self.gpu_wall_toggle.get_active():
            self.gpu_wall_toggle.set_active(False)
        else:
            self.disable_gpu_wall()
        self.status.set_text('GPU album wall unavailable; using the regular album wall.')
        return False

    def disable_gpu_wall(self):
        self.album_wall_stack.set_visible_child_name('gtk')
        self.set_album_frosted_source(self.wall_scroll)
        if self.gpu_wall is not None:
            self.gpu_wall.set_albums(None, [], reset=True)
        self.gpu_rebuild_generation += 1
        generation = self.gpu_rebuild_generation
        self.gpu_rebuild_pending = True
        for child in self.grid.get_children():
            child.destroy()
        index = 0
        def rebuild():
            nonlocal index
            if self.closed or generation != self.gpu_rebuild_generation or self.gpu_wall_enabled:
                return False
            deadline = time.monotonic() + .006
            while index < len(self.albums):
                self.add_album_tile(self.albums[index])
                index += 1
                if time.monotonic() >= deadline:
                    return True
            self.gpu_rebuild_pending = False
            return False
        GLib.idle_add(rebuild)

    def gpu_album_pressed(self, album, event, x, y):
        if event.button == 3:
            self.show_context_menu(event, gpu_album=album)
        else:
            self.gpu_wall.toggle_album(album)

    def maybe_load_more_albums(self):
        if (self.loading_albums or not self.albums or len(self.albums) >= self.total or
                self.content_views.get_visible_child_name() != 'albums' or
                self.views.get_visible_child_name() != 'wall'):
            return False
        adjustment = self.wall_scroll.get_vadjustment()
        remaining = adjustment.get_upper() - adjustment.get_value() - adjustment.get_page_size()
        if remaining <= 96:
            self.load_albums(True)
        return False

    def apply_album_grid_columns(self):
        self._album_layout_pending = False
        width = self.wall_scroll.get_allocated_width()
        usable = max(0, width - 2 * self.album_margin - 18)
        columns = max(1, min(ALBUM_COLUMN_RANGE[1],
                             (usable + self.album_spacing) //
                             max(1, self.album_art_size + self.album_spacing)))
        if columns != getattr(self, '_album_display_columns', None):
            self._album_display_columns = columns
            self.grid.set_min_children_per_line(columns)
            self.grid.set_max_children_per_line(columns)
        return False

    def apply_album_grid_layout(self):
        gpu = getattr(self, 'gpu_wall', None)
        time_wall = getattr(getattr(self, 'time_machine', None), 'gpu_wall', None)
        if time_wall is not None and time_wall.area.get_mapped():
            gpu = time_wall
        width = (gpu.area.get_allocated_width() if getattr(self, 'gpu_wall_enabled', False) and gpu
                 else self.wall_scroll.get_allocated_width())
        size = album_cover_size(width, self.album_columns,
                                self.album_margin, self.album_spacing)
        if size == self.album_art_size:
            self.apply_album_grid_columns()
            if hasattr(self, 'style_album_grid'):
                self.apply_style_album_columns()
            if hasattr(self, 'time_machine'):
                self.time_machine.update_grid_settings()
            return False
        self.album_art_size = size
        if gpu and getattr(self, 'gpu_wall_enabled', False):
            gpu.layout_changed()
        for grid in (self.grid, getattr(self, 'style_album_grid', None)):
            if grid is None:
                continue
            for child in grid.get_children():
                tile = child.get_child()
                self.set_art_size(tile.art_image, size)
                tile.metadata_box.set_size_request(size, -1)
                tile.flip_card.resize_card(size)
                tile.cover_button.set_label('‹' if size < 100 else '‹ Cover')
                for button in tile.track_buttons:
                    if hasattr(button, 'duration_label'):
                        button.duration_label.set_visible(show_track_duration(size))
            grid.queue_resize()
        self.grid.queue_resize()
        self.apply_album_grid_columns()
        if hasattr(self, 'style_album_grid'):
            self.apply_style_album_columns()
        if hasattr(self, 'time_machine'):
            self.time_machine.update_grid_settings()
        return False

    def window_allocated(self, _window, allocation):
        if not self.is_maximized() and allocation.width >= 640 and allocation.height >= 480:
            self.normal_size = allocation.width, allocation.height

    def window_configured(self, _window, event):
        size = event.width, event.height
        if self._last_configure_size is not None and size != self._last_configure_size:
            self._last_window_resize_at = time.monotonic()
            if os.name != 'nt' and getattr(self, 'rounded_corners_enabled', False):
                self.defer_window_shape()
        self._last_configure_size = size
        return False

    @staticmethod
    def window_resize_recent(player):
        last = getattr(player, '_last_window_resize_at', None)
        return last is not None and time.monotonic() - last < 0.20

    def window_shape_allocated(self, _window, _allocation):
        self.refresh_window_shape()

    def defer_window_shape(self):
        window = self.get_window()
        if window is None:
            return
        if not self._window_shape_suspended:
            # Avoid repeatedly changing the X11 window shape while the compositor
            # is resizing it. Restore the rounded region once the drag settles.
            window.shape_combine_region(None, 0, 0)
            # GTK 3's introspection binding does not accept None for input shape.
            window.input_shape_combine_region(rounded_region(32767, 32767, 0), 0, 0)
            self._window_shape_suspended = True
            self._window_shape_state = None
        if self._window_shape_resume_source:
            GLib.source_remove(self._window_shape_resume_source)
        self._window_shape_resume_source = GLib.timeout_add(200, self.resume_window_shape)

    def resume_window_shape(self):
        self._window_shape_resume_source = 0
        self._window_shape_suspended = False
        self._window_shape_state = None
        if not getattr(self, 'closed', False):
            self.refresh_window_shape()
        return False

    def window_realized(self, *_):
        self._window_shape_state = None
        GLib.idle_add(self.refresh_window_shape)

    def refresh_window_shape(self):
        if getattr(self, '_window_shape_suspended', False):
            return False
        window = self.get_window()
        if window is None:
            return False
        allocation = self.get_allocation()
        if allocation.width < 1 or allocation.height < 1:
            return False
        state = window.get_state()
        rounded = self.rounded_corners_enabled and not bool(
            state & (Gdk.WindowState.MAXIMIZED | Gdk.WindowState.FULLSCREEN))
        if os.name == 'nt':
            shape = ('windows', rounded, self.hide_title_bar)
            if shape != self._window_shape_state:
                windows_window.configure_window(window, rounded)
                self._window_shape_state = shape
            return False
        shape = (allocation.width, allocation.height, True) if rounded else (None, None, False)
        if shape != self._window_shape_state:
            region = (rounded_region(allocation.width, allocation.height)
                      if rounded else None)
            window.shape_combine_region(region, 0, 0)
            window.input_shape_combine_region(
                region if region is not None else rounded_region(32767, 32767, 0), 0, 0)
            self._window_shape_state = shape
        return False

    def restore_connection(self):
        self.finish_startup_loading()
        sources = getattr(self, 'source_config', {'active': '', 'local': []})
        active = sources.get('active', '')
        local = next((item for item in sources['local']
                      if active == 'local:' + item['id']), None)
        if local:
            self.connect_local_source(local)
            return False
        self.status.set_text('Looking for saved server login…')
        def restored(credentials):
            if credentials:
                self.restored_credentials = credentials
                self.connect_to_server(*credentials, remember=False, automatic=True)
            elif self.first_run_setup:
                self.begin_first_run_setup()
            else:
                self.connect_dialog()
        self.async_work(load_credentials, restored,
                        on_error=(self.begin_first_run_setup if self.first_run_setup
                                  else self.connect_dialog))
        return False

    def begin_first_run_setup(self):
        self.finish_startup_loading()
        self.show_view('settings')
        self.settings_tabs.set_current_page(2)
        self.status.set_text('Choose a Plex server or add a local music folder in Library settings.')
        dialog = Gtk.Dialog(title='Choose a music library', transient_for=self, modal=True)
        dialog.add_button('Later', Gtk.ResponseType.CANCEL)
        dialog.add_button('Local music folder', Gtk.ResponseType.NO)
        dialog.add_button('Plex server', Gtk.ResponseType.YES)
        box = dialog.get_content_area()
        box.set_border_width(18)
        box.pack_start(Gtk.Label(label='Where is your music library?', xalign=0), False, False, 0)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.NO:
            self.add_local_source()
        elif response == Gtk.ResponseType.YES:
            self.choose_server_from_account()
        return False

    def choose_initial_library(self, sections):
        """Ask for the music library after the first account connection."""
        if not self.first_run_setup or not sections:
            return None
        dialog = Gtk.Dialog(title='Choose music library', transient_for=self, modal=True)
        dialog.add_button('Use library', Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(12)
        box.set_border_width(18)
        box.pack_start(Gtk.Label(label='Choose the Plex music library to browse', xalign=0),
                       False, False, 0)
        choices = Gtk.ComboBoxText()
        for key, name in sections:
            choices.append(key, name)
        choices.set_active(0)
        box.pack_start(choices, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        selected = choices.get_active_id() if response == Gtk.ResponseType.OK else sections[0][0]
        dialog.destroy()
        self.first_run_setup = False
        return selected

    def remote_work(self, work, done, failed):
        self.busy.begin()
        def run():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, exc
            def deliver():
                try:
                    if not self.closed:
                        failed(error) if error else done(result)
                    return False
                finally:
                    self.busy.end()
            GLib.idle_add(deliver)
        threading.Thread(target=run, daemon=True).start()

    def initialize_remote(self):
        def load():
            token = load_device_token(self.remote_config['identifier'])
            if token:
                try:
                    return token, self.remote_account.user_id(token)
                except Exception:
                    return token, None
            return None, None
        def ready(result):
            self.remote_link_loading = False
            self.remote_link_token, self.remote_link_user = result
            if result[0] and result[1] and hasattr(self, 'source_selector'):
                self.refresh_account_sources()
            if self.remote_receiver:
                self.remote_receiver.set_link(*result)
            if self.remote_config['enabled']:
                self.start_remote_receiver()
                self.refresh_remote_connection()
            else:
                self.update_remote_status()
            if self.remote_link_token and not self.remote_link_user:
                self.update_remote_status('Plex link could not be verified; reconnect or relink.')
            if self.pending_server_choice:
                self.pending_server_choice = False
                self.choose_server_from_account()
        def failed(_error):
            self.remote_link_loading = False
            self.remote_keyring_available = False
            if self.remote_config['enabled']:
                self.start_remote_receiver()
            self.update_remote_status()
            if self.pending_server_choice:
                self.pending_server_choice = False
                self.account_status.set_text('The credential store is unavailable; account linking cannot start.')
        self.remote_work(load, ready, failed)
        return False

    def update_remote_status(self, detail=None):
        if detail is None:
            self.account_status.set_text(
                'Linked to Plex account' if self.remote_link_user else
                'Plex account link needs renewal' if self.remote_link_token else
                'Plex account is not linked')
        if detail:
            self.remote_status.set_text(detail)
        elif not self.remote_config['enabled']:
            self.remote_status.set_text('Remote control is off')
        elif self.remote_receiver:
            link = ('linked to Plex • LAN devices may control playback' if self.remote_link_user else
                    'keyring unavailable; linking disabled' if not self.remote_keyring_available
                    else 'not linked to Plex')
            self.remote_status.set_text(
                f'Listening at http://{local_ip()}:{self.remote_receiver.port} • {link}' +
                (' • Plex server identity unavailable' if self.client and
                 not self.remote_server_machine else '') +
                (' • GDM unavailable (UDP 32412)' if not self.remote_receiver.gdm else ''))
        else:
            self.remote_status.set_text('Starting local receiver…')
        self.remote_link_button.set_sensitive(self.remote_keyring_available)
        self.account_server_button.set_sensitive(self.remote_keyring_available)
        self.remote_unlink_button.set_sensitive(bool(self.remote_link_token))

    def remote_toggle_changed(self, button):
        self.remote_config['enabled'] = button.get_active()
        try:
            save_config(self.remote_config)
        except OSError:
            self.update_remote_status('Could not save the remote-control preference.')
            return
        if button.get_active():
            self.start_remote_receiver()
        else:
            self.stop_remote_receiver()

    def remote_name_changed(self, *_):
        name = self.remote_name_entry.get_text().strip() or 'Apistat'
        self.remote_name_entry.set_text(name)
        if name != self.remote_config['name']:
            self.remote_config['name'] = name
            self.remote_account.name = name
            if self.client:
                self.client.device_name = name
            try:
                save_config(self.remote_config)
            except OSError:
                self.update_remote_status('Could not save the player name.')
                return False
            if self.remote_receiver:
                self.remote_receiver.name = name
                if self.remote_receiver.gdm:
                    self.remote_receiver.gdm.name = name
                    self.remote_receiver.gdm.announce()
                self.remote_published_uri = ''
                self.refresh_remote_connection()
        return False

    def start_remote_receiver(self):
        if self.remote_receiver or getattr(self, '_remote_starting', False):
            return
        self._remote_starting = True
        self.update_remote_status()
        receiver = CompanionReceiver(self.remote_config['identifier'],
                                     self.remote_config['name'], self.remote_account,
                                     self.apply_remote_command, self.verify_remote_token)
        if self.client and not getattr(self.client, 'is_local', False):
            receiver.set_server(self.client, self.remote_server_machine)
        receiver.set_link(self.remote_link_token, self.remote_link_user)
        def work():
            receiver.start()
            if self.closed:
                receiver.stop()
            return receiver
        def ready(result):
            self._remote_starting = False
            if not self.remote_config['enabled']:
                self.remote_stop_thread = threading.Thread(target=result.stop, daemon=True)
                self.remote_stop_thread.start()
                return
            self.remote_receiver = result
            self.remote_request_status.set_text('No phone requests yet')
            self.update_remote_status()
            self.refresh_remote_connection()
        def failed(_error):
            self._remote_starting = False
            self.update_remote_status('Could not start the local receiver.')
        self.remote_work(work, ready, failed)

    def stop_remote_receiver(self):
        receiver = self.remote_receiver
        self.remote_receiver = None
        self.remote_published_uri = ''
        self.remote_request_status.set_text('Receiver stopped')
        self.update_remote_status()
        if receiver:
            self.remote_stop_thread = threading.Thread(target=receiver.stop, daemon=True)
            self.remote_stop_thread.start()

    def verify_remote_token(self, token):
        if self.client and hmac.compare_digest(token, self.client.token):
            return True
        digest = hashlib.sha256(token.encode()).digest()
        with self.remote_token_lock:
            cached = self.remote_token_cache.get(digest)
            if cached and cached[1] > time.monotonic():
                return cached[0]
        valid = False
        if self.client:
            try:
                probe = PlexClient(self.client.address, token,
                                   self.remote_config['identifier'],
                                   self.remote_config['name'])
                valid = bool(probe.sections())
            except Exception:
                pass
        if not valid and self.remote_link_user:
            try:
                valid = hmac.compare_digest(self.remote_account.user_id(token),
                                            self.remote_link_user)
            except Exception:
                pass
        with self.remote_token_lock:
            self.remote_token_cache[digest] = valid, time.monotonic() + (300 if valid else 30)
        return valid

    def remote_uri(self):
        address = local_ip()
        if not self.remote_receiver or address.startswith('127.'):
            return ''
        return f'http://{address}:{self.remote_receiver.port}'

    def refresh_remote_connection(self):
        if not self.remote_config['enabled'] or not self.remote_receiver:
            return True
        if self.remote_link_token and not self.remote_link_user and not self.remote_validation_pending:
            self.remote_validation_pending = True
            token = self.remote_link_token
            def validated(user):
                self.remote_validation_pending = False
                if token != self.remote_link_token:
                    return
                self.remote_link_user = user
                if self.remote_receiver:
                    self.remote_receiver.set_link(token, user)
                self.refresh_remote_connection()
            self.remote_work(lambda: self.remote_account.user_id(token), validated,
                             lambda _error: setattr(self, 'remote_validation_pending', False))
        uri = self.remote_uri()
        if (uri and self.remote_link_user and self.remote_link_token and
                not self.remote_publish_pending and
                uri != self.remote_published_uri):
            self.remote_publish_pending = True
            token = self.remote_link_token
            def ready(_unused):
                self.remote_publish_pending = False
                self.remote_published_uri = uri
                self.update_remote_status()
            def failed(_error):
                self.remote_publish_pending = False
                self.update_remote_status('Linked to Plex; could not publish the local address.')
            self.remote_work(lambda: self.remote_account.publish(token, uri), ready, failed)
        return True

    def start_remote_link(self, _button=None, select_server=False):
        if not self.remote_keyring_available:
            return
        self.remote_link_select_server = select_server
        self.remote_pin_generation += 1
        generation = self.remote_pin_generation
        self.account_status.set_text('Requesting Plex link code…')
        self.update_remote_status('Requesting Plex link code…')
        def ready(result):
            if generation != self.remote_pin_generation:
                return
            pin_id, code = result
            dialog = Gtk.Dialog(title='Link Apistat to Plex', transient_for=self)
            dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
            box = dialog.get_content_area()
            box.set_spacing(10)
            box.set_border_width(18)
            box.pack_start(Gtk.Label(label=f'Enter code {code} at plex.tv/link'), False, False, 0)
            box.pack_start(Gtk.LinkButton.new_with_label('https://plex.tv/link',
                                                         'Open plex.tv/link'), False, False, 0)
            def closed(window, response):
                self.remote_pin_generation += 1
                if response != Gtk.ResponseType.OK:
                    self.remote_link_select_server = False
                window.destroy()
            dialog.connect('response', closed)
            dialog.show_all()
            self.account_status.set_text('Waiting for Plex account link…')
            self.update_remote_status('Waiting for Plex account link…')
            pending = {'active': False}
            def poll():
                if generation != self.remote_pin_generation or self.closed:
                    return False
                if pending['active']:
                    return True
                pending['active'] = True
                def linked(token):
                    pending['active'] = False
                    if generation != self.remote_pin_generation:
                        return
                    if token:
                        dialog.response(Gtk.ResponseType.OK)
                        self.finish_remote_link(token)
                def failed(_error):
                    pending['active'] = False
                    if generation == self.remote_pin_generation:
                        dialog.response(Gtk.ResponseType.CANCEL)
                        self.account_status.set_text('Plex link code expired or could not be checked.')
                        self.update_remote_status('Plex link code expired or could not be checked.')
                self.remote_work(lambda: self.remote_account.check_pin(pin_id), linked, failed)
                return True
            GLib.timeout_add_seconds(3, poll)
        def failed(_error):
            self.remote_link_select_server = False
            self.account_status.set_text('Could not request a Plex link code.')
            self.update_remote_status('Could not request a Plex link code.')
        self.remote_work(self.remote_account.create_pin, ready, failed)

    def finish_remote_link(self, token):
        def work():
            user = self.remote_account.user_id(token)
            save_device_token(self.remote_config['identifier'], token)
            return user
        def ready(user):
            self.remote_link_token, self.remote_link_user = token, user
            if hasattr(self, 'source_selector'):
                self.refresh_account_sources()
            with self.remote_token_lock:
                self.remote_token_cache.clear()
            if self.remote_receiver:
                self.remote_receiver.set_link(token, user)
            self.update_remote_status()
            self.refresh_remote_connection()
            if self.remote_link_select_server:
                self.remote_link_select_server = False
                self.choose_server_from_account()
        def failed(_error):
            self.remote_link_select_server = False
            store = ('Windows Credential Manager' if os.name == 'nt' else ('macOS Keychain' if sys.platform == 'darwin' else 'desktop keyring'))
            self.account_status.set_text(f'Could not save Plex link in {store}.')
            self.update_remote_status('Could not save Plex link; no plaintext fallback is used.')
        self.remote_work(work, ready, failed)

    def populate_source_selector(self):
        if not hasattr(self, 'source_selector'):
            return
        self._updating_source_selector = True
        try:
            self.source_selector.remove_all()
            self.source_selector.append('plex:current', 'Current Plex server')
            for server in self.account_servers:
                self.source_selector.append('plex:' + server.identifier,
                                            'Plex: ' + server.name + ('' if server.owned else ' (shared)'))
            for source in self.source_config['local']:
                self.source_selector.append('local:' + source['id'], 'Local: ' + source['name'])
            client = getattr(self, 'client', None)
            active = ('local:' + client.source['id'] if getattr(client, 'is_local', False) else
                      'plex:' + self.remote_server_machine if client and self.remote_server_machine else
                      self.source_config.get('active', 'plex:current'))
            if not self.source_selector.set_active_id(active):
                self.source_selector.set_active_id('plex:current')
            is_local = bool(getattr(client, 'is_local', False))
            if hasattr(self, 'local_rescan_button'):
                self.local_rescan_button.set_sensitive(is_local)
                self.local_remove_button.set_sensitive(is_local)
        finally:
            self._updating_source_selector = False

    def refresh_account_sources(self, *_):
        if self.remote_link_loading:
            self.account_status.set_text('Checking saved Plex account link…')
            return
        if not self.remote_link_token:
            self.start_remote_link()
            return
        token = self.remote_link_token
        def ready(servers):
            if token != self.remote_link_token:
                return
            self.account_servers = servers
            self.populate_source_selector()
            self.account_status.set_text('Linked to Plex account')
        self.remote_work(lambda: self.remote_account.resources(token), ready,
                         lambda _error: self.account_status.set_text('Could not list Plex servers.'))

    def source_selected(self, selector):
        if self._updating_source_selector:
            return
        chosen = selector.get_active_id() or ''
        client = getattr(self, 'client', None)
        if chosen.startswith('local:'):
            source = next((item for item in self.source_config['local']
                           if 'local:' + item['id'] == chosen), None)
            if source and not (getattr(client, 'is_local', False) and client.source['id'] == source['id']):
                self.connect_local_source(source)
        elif chosen == 'plex:current':
            if client is None or getattr(client, 'is_local', False):
                self.source_config['active'] = ''
                self.restore_connection()
        elif chosen.startswith('plex:'):
            server = next((item for item in self.account_servers
                           if 'plex:' + item.identifier == chosen), None)
            if server and (getattr(client, 'is_local', False) or self.remote_server_machine != server.identifier):
                self.connect_account_server(server)

    def add_local_source(self, *_):
        dialog = Gtk.FileChooserNative.new('Choose a local music folder', self,
                                           Gtk.FileChooserAction.SELECT_FOLDER, 'Add', 'Cancel')
        response = dialog.run()
        path = dialog.get_filename() if response == Gtk.ResponseType.ACCEPT else None
        dialog.destroy()
        if not path:
            return
        try:
            source = create_source(path)
            existing = next((item for item in self.source_config['local']
                             if item['path'] == source['path']), None)
            if existing is None:
                self.source_config['local'].append(source)
                save_sources(self.source_config)
            else:
                source = existing
            self.connect_local_source(source)
        except (OSError, ValueError) as error:
            self.status.set_text(f'Could not add local library: {error}')

    def connect_local_source(self, source):
        try:
            client = LocalLibrary(source)
        except (OSError, ValueError) as error:
            self.status.set_text(f'Could not open local library: {error}')
            self.populate_source_selector()
            return
        self.connect_to_server('', '', source=client)

    def rescan_local_source(self, *_, force=True):
        client = self.client
        if not getattr(client, 'is_local', False):
            return
        self.status.set_text('Scanning local music…')
        self.local_rescan_button.set_sensitive(False)
        valid = lambda: not self.closed and self.client is client
        def done(result):
            self.local_rescan_button.set_sensitive(True)
            if result is None:
                return
            count, errors = result
            self.index_generation += 1
            self.indexed_albums = None
            self.index_section = None
            self.index_building = False
            self.artist_catalog = None
            self.album_search_catalog = None
            self.song_view_cache.clear()
            self.invalidate_song_catalog()
            self.load_albums(force_refresh=True)
            self.load_songs()
            self.status.set_text(f'Scanned {count} local tracks' +
                                 (f' • {errors} files or folders could not be read' if errors else ''))
        def failed():
            self.local_rescan_button.set_sensitive(True)
            self.status.set_text('Local music folder is unavailable or could not be scanned.')
        self.async_work(lambda: client.scan(valid, force=force), done, valid, failed)

    def remove_local_source(self, *_):
        client = self.client
        if not getattr(client, 'is_local', False):
            return
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text=f'Remove “{client.source["name"]}” from Apistat?')
        dialog.format_secondary_text('Your music files will not be deleted.')
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Remove', Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        updated = {'local': [item for item in self.source_config['local']
                             if item['id'] != client.source['id']], 'active': ''}
        try:
            save_sources(updated)
        except OSError:
            self.status.set_text('Could not save library sources.')
            return
        self.source_config = updated
        self.connection_generation += 1
        self.generation += 1
        self.stop(remember=False)
        self.client = self.queue_client = None
        self.remote_server_machine = ''
        if self.remote_receiver:
            self.remote_receiver.set_server(None, '')
        self.library.remove_all()
        self.clear_wall()
        self.albums, self.tracks, self.songs, self.queue = [], [], [], []
        self.index = -1
        self.selected_album = self.queue_album = None
        self.track_store.clear()
        self.song_store.clear()
        self.song_view_cache.clear()
        self.invalidate_song_catalog()
        self.refresh_queue_view()
        self.server_label.set_text('No library selected')
        self.status.set_text('Local library removed; music files were not changed.')
        self.populate_source_selector()

    def choose_server_from_account(self, *_):
        if self.remote_link_loading:
            self.pending_server_choice = True
            self.account_status.set_text('Checking saved Plex account link…')
            self.status.set_text('Checking saved Plex account link…')
            return
        if not self.remote_link_token or not self.remote_link_user:
            self.start_remote_link(select_server=True)
            return
        self.server_choice_generation += 1
        generation = self.server_choice_generation
        token = self.remote_link_token
        self.account_status.set_text('Finding Plex servers…')
        self.status.set_text('Finding Plex servers…')

        def ready(servers):
            if generation != self.server_choice_generation or token != self.remote_link_token:
                return
            if not servers:
                self.account_status.set_text('No Plex servers with usable connections were found for this account.')
                self.status.set_text('No Plex servers with usable connections were found for this account.')
                return
            dialog = Gtk.Dialog(title='Choose Plex music server', transient_for=self, modal=True)
            dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL,
                               'Connect', Gtk.ResponseType.OK)
            box = dialog.get_content_area()
            box.set_spacing(12)
            box.set_border_width(18)
            box.pack_start(Gtk.Label(label='Choose a server from your Plex account', xalign=0),
                           False, False, 0)
            choices = Gtk.ComboBoxText()
            for index, server in enumerate(servers):
                label = server.name + ('' if server.owned else ' (shared)')
                choices.append(str(index), label)
            choices.set_active(0)
            box.pack_start(choices, False, False, 0)
            dialog.show_all()
            response = dialog.run()
            selected = choices.get_active()
            dialog.destroy()
            if response == Gtk.ResponseType.OK and 0 <= selected < len(servers):
                self.connect_account_server(servers[selected])
            else:
                self.account_status.set_text('Linked to Plex account')

        def failed(_error):
            if generation == self.server_choice_generation:
                self.account_status.set_text('Could not list Plex servers. Check the account link and network.')
                self.status.set_text('Could not list Plex servers. Check the account link and network.')

        self.remote_work(lambda: self.remote_account.resources(token), ready, failed)

    def connect_account_server(self, server):
        self.server_choice_generation += 1
        generation = self.server_choice_generation
        self.account_status.set_text(f'Checking {server.name} connections…')
        self.status.set_text(f'Checking {server.name} connections…')

        def ready(connection):
            if generation != self.server_choice_generation:
                return
            if connection is None:
                self.account_status.set_text(
                    'Could not reach a music library on this server. Check Plex Remote Access or Relay.')
                self.status.set_text('Could not reach a music library. Check Plex Remote Access or Relay.')
                return
            address, token = connection
            self.account_status.set_text(f'Connecting to {server.name}…')
            self.connect_to_server(address, token, remember=True)

        def failed(_error):
            if generation == self.server_choice_generation:
                self.account_status.set_text('Could not check this Plex server’s connections.')
                self.status.set_text('Could not check this Plex server’s connections.')

        self.remote_work(lambda: reachable_music_server(
            server, self.remote_config['identifier'], self.remote_config['name']), ready, failed)

    def unlink_remote(self, *_):
        token = self.remote_link_token
        if not token:
            return
        self.server_choice_generation += 1
        self.account_status.set_text('Unlinking Plex account…')
        self.update_remote_status('Unlinking Plex device…')
        def work():
            remote_failed = False
            try:
                self.remote_account.unlink(token)
            except Exception:
                remote_failed = True
            clear_device_token(self.remote_config['identifier'])
            return remote_failed
        def ready(remote_failed):
            self.remote_link_token = self.remote_link_user = None
            with self.remote_token_lock:
                self.remote_token_cache.clear()
            self.remote_published_uri = ''
            if self.remote_receiver:
                self.remote_receiver.set_link(None, None)
            self.account_status.set_text('Plex account is not linked')
            self.update_remote_status('Removed the local link; remove the device in Plex settings when online.'
                                      if remote_failed else None)
        self.remote_work(work, ready, lambda _error: self.update_remote_status(
            'Could not unlink the Plex device; check the connection and retry.'))

    def clear_remote_queue(self):
        self.remote_container = self.remote_queue_id = self.remote_queue_version = ''
        self.remote_item_ids = ()

    def apply_remote_command(self, action, args, media):
        future = Future()
        def deliver():
            try:
                if self.closed or not self.remote_config['enabled']:
                    raise RuntimeError('Remote control is off')
                if action == 'playMedia':
                    if not self.remote_receiver or self.remote_receiver.server_client is not self.client:
                        raise RuntimeError('Plex connection changed')
                    self.queue = list(media.tracks)
                    self.queue_client = self.client
                    self.queue_album = None
                    self.index = media.index
                    self.remote_container = media.container_key
                    self.remote_queue_id = media.queue_id
                    self.remote_queue_version = media.queue_version
                    self.remote_item_ids = media.item_ids
                    self.start_track(resume_position_ms=media.offset)
                elif action == 'play':
                    self.play()
                elif action == 'pause':
                    self.pause()
                elif action == 'stop':
                    self.stop()
                    self.persist_session(force=True)
                elif action == 'skipNext':
                    self.advance()
                elif action == 'skipPrevious':
                    self.previous()
                elif action == 'seekTo':
                    if self.stream_open and self.seek.get_sensitive():
                        self.seek_mpris(args['offset'] * 1000)
                    elif self.queue:
                        self.pending_resume_seek_ms = args['offset']
                        self.playback_position_ms = args['offset']
                elif action == 'setParameters':
                    self.set_volume(args['volume'] / 100)
                future.set_result(self.remote_snapshot())
            except Exception as exc:
                future.set_exception(exc)
            return False
        GLib.idle_add(deliver)
        return future.result(timeout=15)

    def remote_snapshot(self):
        item = self.queue[self.index] if 0 <= self.index < len(self.queue) else None
        state = 'playing' if self.stream_open and self.playing else (
            'paused' if self.stream_open else 'buffering' if self.remote_opening else 'stopped')
        position = self.playback_position_ms
        if self.stream_open and self.playing:
            position = max(position, int((self.timeline_base_position +
                           time.monotonic() - self.timeline_base_time) * 1000))
        server = urlsplit(self.queue_client.address) if item and self.queue_client else None
        album_container = (self.queue_album.key if self.queue_album and
                           self.queue_album.key.endswith('/children') else
                           self.queue_album.key.rstrip('/') + '/children' if self.queue_album else '')
        container = self.remote_container or album_container
        item_id = (self.remote_item_ids[self.index] if self.remote_item_ids and
                   self.index < len(self.remote_item_ids) else '')
        return {'state': state, 'key': item.key if item else '', 'position': position,
                'duration': item.duration if item else 0,
                'volume': round(self.volume.get_value() * 100),
                'machine': self.remote_server_machine if item else '',
                'address': server.hostname if server else '',
                'port': (server.port if server else None) or
                        (443 if server and server.scheme == 'https' else 32400),
                'protocol': server.scheme if server else 'http', 'container': container,
                'queue_id': self.remote_queue_id, 'queue_version': self.remote_queue_version,
                'item_id': item_id, 'queue_length': len(self.queue), 'queue_index': self.index}

    def finish_startup_loading(self):
        if not self.startup_loading:
            return
        self.startup_loading = False
        self.busy.end()
        self.loading_spinner.stop()
        self.loading_overlay.hide()
        self.content_views.set_sensitive(True)
        self.sidebar.set_sensitive(True)
        self.player_bar.set_sensitive(True)

    def add_nav_button(self, view, label, icon):
        button = Gtk.Button()
        button.set_image(SidebarIcon(self, view) if view in CUSTOM_SIDEBAR_ICONS else
                         Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR))
        self.setup_sidebar_label(button, 'Moods\n& styles' if view == 'styles' else label)
        self.set_tooltip(button, label)
        button.get_accessible().set_name(label)
        button.connect('clicked', lambda *_: self.show_view(view))
        button.drag_source_set(Gdk.ModifierType.BUTTON1_MASK,
                               [self.nav_drop_target], Gdk.DragAction.MOVE)
        button.drag_dest_set(Gtk.DestDefaults.ALL,
                             [self.nav_drop_target], Gdk.DragAction.MOVE)
        button.connect('drag-begin', self.nav_drag_begin, view)
        button.connect('drag-end', self.nav_drag_end)
        button.connect('drag-motion', self.nav_drag_motion)
        button.connect('drag-data-get', self.nav_drag_data_get, view)
        button.connect('drag-data-received', self.nav_drag_data_received)
        self.sidebar.pack_start(button, False, False, 0)
        self.nav_buttons[view] = button
        return button

    def setup_sidebar_label(self, button, text):
        button.set_label(text)
        button.set_always_show_image(True)
        button.set_image_position(Gtk.PositionType.TOP)
        def find_label(widget):
            if isinstance(widget, Gtk.Label):
                return widget
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    found = find_label(child)
                    if found is not None:
                        return found
            return None
        label = find_label(button)
        label.set_name('sidebar-icon-label')
        label.set_justify(Gtk.Justification.CENTER)
        label.set_no_show_all(True)
        label.set_visible(self.sidebar_labels_enabled)
        button.sidebar_label = label

    def sidebar_labels_changed(self, button):
        self.sidebar_labels_enabled = button.get_active()
        style = self.sidebar.get_style_context()
        if self.sidebar_labels_enabled:
            style.add_class('show-labels')
        else:
            style.remove_class('show-labels')
        for nav_button in list(self.nav_buttons.values()) + [self.sidebar_volume_button]:
            nav_button.sidebar_label.set_visible(self.sidebar_labels_enabled)
        try:
            save_sidebar_labels_enabled(self.sidebar_labels_enabled)
        except OSError:
            self.status.set_text('Could not save sidebar label setting')

    def sidebar_note_animation_changed(self, button):
        self.sidebar_note_animation_enabled = button.get_active()
        now_icon = self.nav_buttons['now'].get_image()
        if isinstance(now_icon, SidebarIcon):
            now_icon.set_playing(self.sidebar_note_animation_enabled and self.playing)
        try:
            save_sidebar_note_animation_enabled(self.sidebar_note_animation_enabled)
        except OSError:
            self.status.set_text('Could not save sidebar animation setting')

    @staticmethod
    def redraw_sidebar_icons(player):
        for button in getattr(player, 'nav_buttons', {}).values():
            image = button.get_image()
            if isinstance(image, SidebarIcon):
                image.queue_draw()

    def nav_drag_begin(self, button, context, view):
        self.nav_drag_source = view
        self.nav_drag_completed = False
        visible = getattr(self, 'sidebar_visible', self.sidebar_order)
        others = [name for name in self.sidebar_order
                  if name != view and name in visible]
        self.nav_drag_centers = [self.nav_drop_root_y(
            self.nav_buttons[name], 0, self.nav_buttons[name].get_allocated_height() // 2)
                                 for name in others]
        self.nav_drag_insert = sum(self.sidebar_order.index(name) <
                                   self.sidebar_order.index(view) for name in others)
        if view in CUSTOM_SIDEBAR_ICONS:
            drag_icon = SidebarIcon(self, view)
            drag_icon.show()
            Gtk.drag_set_icon_widget(context, drag_icon, 14, 14)
        else:
            name, _size = button.get_image().get_icon_name()
            Gtk.drag_set_icon_name(context, name, 18, 18)
        button.set_opacity(0.2)

    def nav_drag_end(self, button, _context):
        button.set_opacity(1)
        self.nav_drop_gap.set_reveal_child(False)
        self.nav_drag_source = None
        self.nav_drag_insert = None

    @staticmethod
    def nav_gap_reveal_changed(gap, _property):
        if not gap.get_child_revealed() and not gap.get_reveal_child():
            gap.hide()

    def nav_drag_data_get(self, _button, _context, selection, _info, _time, view):
        selection.set(selection.get_target(), 8, view.encode('ascii'))

    def nav_drop_root_y(self, widget, x, y):
        translated = widget.translate_coordinates(self, x, y)
        origin_y = self.get_window().get_origin()[-1]
        if translated is None or len(translated) < 2 or (
                len(translated) == 3 and translated[0] is False):
            return origin_y + widget.get_allocation().y + y
        return origin_y + translated[-1]

    def nav_drag_motion(self, widget, context, x, y, _time):
        target = widget.drag_dest_find_target(context, None)
        if target is not None and target.name() == 'application/x-plex-sidebar-view':
            self.update_nav_drag(self.nav_drop_root_y(widget, x, y))
        return False

    def update_nav_drag(self, root_y):
        source = self.nav_drag_source
        if source is None:
            return
        visible = getattr(self, 'sidebar_visible', self.sidebar_order)
        others = [name for name in self.sidebar_order
                  if name != source and name in visible]
        position = sum(root_y >= center for center in self.nav_drag_centers)
        self.nav_drag_insert = position
        target = self.nav_buttons[others[position]] if position < len(others) else None
        children = self.sidebar.get_children()
        without_gap = [child for child in children if child is not self.nav_drop_gap]
        gap_position = (without_gap.index(target) if target else
                        without_gap.index(self.nav_buttons[others[-1]]) + 1
                        if others else len(without_gap))
        if children.index(self.nav_drop_gap) != gap_position:
            self.sidebar.reorder_child(self.nav_drop_gap, gap_position)
        if not self.nav_drop_gap.get_reveal_child():
            self.nav_drop_gap.show()
            self.nav_drop_gap.set_reveal_child(True)

    def nav_drag_data_received(self, widget, context, x, y, selection, info, event_time):
        if info != 2 or self.nav_drag_completed:
            return
        try:
            source = bytes(selection.get_data()).decode('ascii')
        except (TypeError, UnicodeDecodeError):
            source = ''
        if source not in self.nav_buttons or source != self.nav_drag_source:
            Gtk.drag_finish(context, False, False, event_time)
            return
        self.update_nav_drag(self.nav_drop_root_y(widget, x, y))
        order = [name for name in self.sidebar_order if name != source]
        visible = getattr(self, 'sidebar_visible', self.sidebar_order)
        visible_others = [name for name in order if name in visible]
        if self.nav_drag_insert < len(visible_others):
            destination = order.index(visible_others[self.nav_drag_insert])
        elif visible_others:
            destination = order.index(visible_others[-1]) + 1
        else:
            destination = len(order)
        order.insert(destination, source)
        self.sidebar_order = order
        for index, name in enumerate(order):
            self.sidebar.reorder_child(self.nav_buttons[name], index)
        self.sidebar.reorder_child(self.sidebar_spacer, len(order) - 1)
        self.position_sidebar_volume()
        self.nav_drop_gap.set_reveal_child(False)
        self.nav_drag_completed = True
        try:
            save_sidebar_order(order)
        except OSError:
            self.status.set_text('Could not save sidebar order')
        Gtk.drag_finish(context, True, False, event_time)

    def show_view(self, view, preserve=False):
        self.invalidate_frosted_backdrops()
        if view != 'now':
            self.previous_panel = view
        if view == 'albums' and not preserve:
            self.views.set_visible_child_name('wall')
        elif view == 'settings' and not preserve:
            self.settings_stack.set_visible_child_name('main')
        self.content_views.set_visible_child_name(view)
        if hasattr(self, 'hero_waveform'):
            self.refresh_live_waveform()
        if view == 'albums':
            GLib.idle_add(self.maybe_load_more_albums)
        elif view == 'library' and self.song_load_pending:
            self.load_songs()
        elif view == 'styles':
            self.load_styles_browser()
        elif view == 'time':
            self.time_machine.on_show()
        elif view == 'queue':
            self.refresh_queue_view()
        elif view == 'lyrics':
            self.load_current_lyrics()
        for name, button in self.nav_buttons.items():
            context = button.get_style_context()
            if name == view:
                context.add_class('active')
            else:
                context.remove_class('active')
        Player.redraw_sidebar_icons(self)
        if hasattr(self, 'status'):
            self.status_changed()

    def toggle_now_panel(self, *_):
        current = self.content_views.get_visible_child_name()
        self.show_view(self.previous_panel if current == 'now' else 'now',
                       preserve=current == 'now')

    def toggle_album_search(self, *_):
        if self.content_views.get_visible_child_name() != 'albums':
            self.show_view('albums')
        self.views.set_visible_child_name('wall')
        self.search.grab_focus()

    def album_top_allocated(self, *_):
        """Keep the native GPU surface below the sliding GTK controls."""
        top = getattr(self, 'album_top', None)
        if top is None:
            return
        height = max(36, top.get_allocated_height())
        wall = getattr(self, 'album_wall', None)
        if wall is not None and wall.get_margin_top() != self.album_margin + height:
            wall.set_margin_top(self.album_margin + height)
        gpu = getattr(self, 'gpu_wall', None)
        header = getattr(self, 'gpu_filter_header', None)
        if gpu is not None and header is not None:
            header.set_margin_start(self.album_margin)
            header.set_margin_top(height + 4)
            inset = 0 if header.get_visible() else height
            if gpu.render_surface.get_margin_top() != inset:
                gpu.render_surface.set_margin_top(inset)
                gpu.scrollbar.set_margin_top(inset)
        canvas = getattr(self, 'album_canvas', None)
        header = getattr(self, 'canvas_filter_header', None)
        if canvas is not None and header is not None:
            header.set_margin_start(self.album_margin)
            header.set_margin_top(height + 4)
            inset = 0 if header.get_visible() else height
            if canvas.render_surface.get_margin_top() != inset:
                canvas.render_surface.set_margin_top(inset)
                canvas.scrollbar.set_margin_top(inset)

    def context_menu_pressed(self, _widget, event):
        if event.button != 3:
            return False
        self.show_context_menu(event)
        return True

    def album_context_menu_pressed(self, tile, event):
        if event.button != 3:
            return False
        self.show_context_menu(event, tile)
        return True

    def show_context_menu(self, event, tile=None, gpu_album=None, gpu_wall=None):
        menu = Gtk.Menu()
        menu.set_name('apistat-context-menu')
        menu.attach_to_widget(self, None)
        def item(label, callback):
            entry = Gtk.MenuItem.new_with_label(label)
            entry.connect('activate', lambda *_: callback())
            menu.append(entry)
        def separator():
            menu.append(Gtk.SeparatorMenuItem())
        if gpu_album is not None:
            wall = gpu_wall or self.gpu_wall
            flip = wall.flip
            flipped = bool(flip and flip.album is gpu_album and flip.target)
            item('Show cover' if flipped else 'Flip album',
                 lambda: wall.toggle_album(gpu_album))
            item('Open album', lambda: self.select_album(gpu_album))
            item('Explore related albums', lambda: self.open_album_web(gpu_album))
            item('Show Artist Albums', lambda: self.show_artist_albums(gpu_album.artist))
            item('Show in library', lambda: self.show_in_library(gpu_album))
            item('Add to queue', lambda: self.enqueue_album(gpu_album))
            item('Play next', lambda: self.enqueue_album(gpu_album, play_next=True))
            separator()
        elif tile is not None:
            item('Show cover' if tile.flip_card.side == 'back' else 'Flip album',
                 lambda: self.flip_album_card(tile))
            item('Open album', lambda: tile.open_album(tile.album))
            item('Explore related albums', lambda: self.open_album_web(tile.album))
            item('Show Artist Albums', lambda: self.show_artist_albums(tile.album.artist))
            item('Show in library', lambda: self.show_in_library(tile.album))
            item('Add to queue', lambda: self.enqueue_album(tile.album))
            item('Play next', lambda: self.enqueue_album(tile.album, play_next=True))
            separator()
        elif (self.content_views.get_visible_child_name() == 'albums' and
              self.views.get_visible_child_name() == 'detail' and
              self.selected_album is not None):
            item('Add to queue', lambda: self.enqueue_album(self.selected_album))
            item('Play next', lambda: self.enqueue_album(self.selected_album, play_next=True))
            separator()
        elif self.queue_album is not None:
            item('Show Artist Albums',
                 lambda: self.show_artist_albums(self.queue_album.artist))
            item('Show in library', lambda: self.show_in_library(self.queue_album))
            separator()
        if tile is None and gpu_album is None and 0 <= self.index < len(self.queue):
            item('Show info', self.show_playing_info)
        item('Pause' if self.playing else 'Play', self.toggle)
        item('Previous', self.previous)
        item('Next', self.advance)
        separator()
        item('Now Playing', lambda: self.show_view('now'))
        item('Albums', lambda: self.show_view('albums'))
        item('Library', lambda: self.show_view('library'))
        item('Play queue', lambda: self.show_view('queue'))
        item('Settings', lambda: self.show_view('settings'))
        item('Search Albums', self.toggle_album_search)
        separator()
        item('Quit', self.destroy)
        self.context_menu = menu
        menu.connect('selection-done', lambda selected: selected.destroy())
        menu.show_all()
        menu.popup_at_pointer(event)

    def artist_name_pressed(self, _widget, event, artist_getter):
        if event.button != 1:
            return False
        artist = artist_getter()
        if not artist:
            return False
        self.show_artist_albums(artist)
        return True

    def show_current_artist_albums(self, *_):
        if 0 <= self.index < len(self.queue):
            self.show_artist_albums(self.queue[self.index].artist)

    def now_album_pressed(self, _widget, event):
        if event.button != 1 or not self.client or not 0 <= self.index < len(self.queue):
            return False
        album = self.queue_album.title if self.queue_album else self.queue[self.index].album
        if not album:
            return False
        self.artist_filter = None
        self.artist_catalog = None
        self.search.set_text(album)
        self.album_search_revealer.set_reveal_child(False)
        self.show_view('albums')
        self.load_albums()
        return True

    def library_artist_pressed(self, view, event):
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if event.button == 1:
            if hit and hit[1] is getattr(self, 'song_columns', {}).get('user_rating'):
                index = hit[0].get_indices()[0]
                if 0 <= index < len(self.songs):
                    song = self.songs[index]
                    self.set_song_rating(song, stars_from_click(hit[2], song.user_rating))
                    return True
            self.song_drag_candidate_indices = Player.track_drag_candidates(view, event, self.songs)
            modifiers = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK
            self.song_pointer_drag = (
                {'indices': self.song_drag_candidate_indices, 'x': event.x,
                 'y': event.y, 'active': False}
                if self.song_drag_candidate_indices
                and not (getattr(event, 'state', 0) & modifiers) else None)
            return False
        if event.button == 3 and hit:
            index = hit[0].get_indices()[0]
            if 0 <= index < len(self.songs):
                selection = view.get_selection()
                if not selection.path_is_selected(hit[0]):
                    selection.unselect_all()
                    selection.select_path(hit[0])
                selected = [self.songs[i] for i in self.selected_song_indices()]
                self.show_song_context_menu(event, self.songs[index], index, edit_tracks=selected)
                return True
            return False
        return False

    def update_album_sort_buttons(self):
        for sort, button in self.album_sort_buttons.items():
            context = button.get_style_context()
            if sort == self.album_sort:
                context.add_class('active')
            else:
                context.remove_class('active')

    def change_album_sort(self, _button, sort):
        if getattr(self, 'canvas_enabled', False) and not self.artist_filter:
            if sort != self.album_sort:
                self.album_sort = sort
                self.update_album_sort_buttons()
                if self.client:
                    self.load_albums()
            return
        filtered = bool(self.artist_filter or self.search.get_text().strip())
        if sort == self.album_sort and not filtered:
            return
        self.album_sort = sort
        self.update_album_sort_buttons()
        if filtered:
            self.show_all_albums()
        elif self.client:
            self.load_albums()

    def show_song_context_menu(self, event, song, index, play_action=None, edit_tracks=None):
        menu = Gtk.Menu()
        menu.set_name('apistat-context-menu')
        menu.attach_to_widget(self, None)
        def item(label, action):
            entry = Gtk.MenuItem.new_with_label(label)
            entry.connect('activate', lambda *_: action())
            menu.append(entry)
        item('Play Song', play_action or (lambda: self.play_song(index)))
        item('Show info', lambda: self.show_track_info(song))
        if edit_tracks:
            item('Edit tags…', lambda: self.show_tag_editor(edit_tracks))
        item('Add to queue', lambda: self.enqueue_tracks([song]))
        item('Play next', lambda: self.enqueue_tracks([song], play_next=True))
        item('Add similar songs to queue', lambda: self.enqueue_similar_songs(song))
        loved = song.user_rating >= 9.5
        item('Remove Love' if loved else 'Love Song',
             lambda: self.set_song_loved(song, not loved))
        if song.artist:
            item('Show Artist Albums', lambda: self.show_artist_albums(song.artist))
        self.song_context_menu = menu
        menu.connect('selection-done', lambda selected: selected.destroy())
        menu.show_all()
        menu.popup_at_pointer(event)

    def set_song_loved(self, song, loved):
        self.set_song_rating(song, 5 if loved else 0)

    def apply_song_rating(self, key, rating):
        for collection in (self.song_catalog, self.songs,
                           getattr(self, 'song_results', None),
                           self.queue, self.play_history, self.tracks):
            if collection:
                for candidate in collection:
                    if candidate.key == key:
                        candidate.user_rating = rating
        for child in self.grid.get_children():
            tile = child.get_child()
            for candidate in tile.tracks or []:
                if candidate.key == key:
                    candidate.user_rating = rating
        for tracks in getattr(self, '_album_card_tracks', {}).values():
            for candidate in tracks:
                if candidate.key == key:
                    candidate.user_rating = rating
        for grid in (self.grid, getattr(self, 'style_album_grid', None)):
            if grid is None:
                continue
            for child in grid.get_children():
                tile = child.get_child()
                highlights = track_highlights(tile.tracks)
                for track, button in zip(tile.tracks or (), tile.track_buttons):
                    if hasattr(button, 'highlight_marker'):
                        button.highlight_marker.set_text(highlights.get(track.key, ''))
        for wall in (getattr(self, 'album_canvas', None), getattr(self, 'gpu_wall', None),
                     getattr(self, 'album_web_wall', None),
                     getattr(getattr(self, 'time_machine', None), 'gpu_wall', None)):
            if wall is not None:
                for flip in wall.flips.values():
                    for candidate in flip.tracks or ():
                        if candidate.key == key:
                            candidate.user_rating = rating
                    flip.dirty = True
                wall.queue_frame()
        rating_column = next(index for index, (_label, field) in
                             enumerate(LIBRARY_COLUMNS) if field == 'user_rating')
        views = [(getattr(self, 'song_store', None), self.songs)]
        views.extend((cached.get('store'), cached.get('rows'))
                     for cached in self.song_view_cache.values())
        for cached in self.song_view_cache.values():
            for candidate in cached.get('results') or []:
                if candidate.key == key:
                    candidate.user_rating = rating
        seen_stores = set()
        for store, rows in views:
            if store is None or rows is None or id(store) in seen_stores:
                continue
            seen_stores.add(id(store))
            for index, candidate in enumerate(rows[:len(store)]):
                if candidate.key == key:
                    store[index][rating_column] = star_text(rating)
                    store[index][len(LIBRARY_COLUMNS)] = '♥' if rating >= 9.5 else ''
        for index, candidate in enumerate(self.tracks):
            if candidate.key == key and index < len(self.track_store):
                self.track_store[index][3] = star_text(rating)
        self.refresh_queue_view()
        self.refresh_now_rating()

    def set_song_rating(self, song, stars):
        client = self.client
        if client is None or not 0 <= stars <= 5:
            return
        Player.note_song_cache_edit(self)
        section = self.library.get_active_id()
        rating = float(stars * 2)
        requests = getattr(self, 'rating_requests', None)
        if requests is None:
            self.rating_requests = requests = {}
        request_key = id(client), song.key
        state = requests.setdefault(request_key, {
            'latest': 0, 'confirmed_revision': 0,
            'confirmed_rating': song.user_rating, 'failed_revision': None})
        state['latest'] += 1
        revision = state['latest']
        state['failed_revision'] = None
        Player.apply_song_rating(self, song.key, rating)
        playlist_keys = list(dict.fromkeys(
            [None] + [playlist.key for playlist in self.playlists] +
            ([self.active_playlist.key] if self.active_playlist else [])))
        def save_rating():
            client.set_track_rating(song, stars * 2 if stars else -1)
            if section:
                cache = LocalCache(client)
                for playlist_key in playlist_keys:
                    entry = cache.read_song_index_entry(section, playlist_key)
                    if entry is None:
                        continue
                    catalog, built_at = entry
                    changed = False
                    for candidate in catalog:
                        if candidate.key == song.key:
                            candidate.user_rating = rating
                            changed = True
                    if changed:
                        try:
                            cache.save_song_index(section, catalog, playlist_key, built_at=built_at)
                        except OSError:
                            pass
        def updated(_response):
            if revision > state['confirmed_revision']:
                state['confirmed_revision'] = revision
                state['confirmed_rating'] = rating
            if revision == state['latest']:
                self.status.set_text(f'{song.title} • {stars} stars' if stars else
                                     f'Cleared rating for {song.title}')
            elif state['failed_revision'] == state['latest']:
                Player.apply_song_rating(self, song.key, state['confirmed_rating'])
            if (revision == state['latest'] or
                    state['failed_revision'] == state['latest']):
                active_smart = getattr(self, 'active_smart_playlist', None)
                column_sort = getattr(self, 'column_sort', None)
                if active_smart or (column_sort and column_sort[0] == 'user_rating'):
                    self.song_view_cache.clear()
                    self.load_songs()
        def failed():
            if revision == state['latest']:
                state['failed_revision'] = revision
                Player.apply_song_rating(self, song.key, state['confirmed_rating'])
                self.status.set_text('Could not update song rating on Plex.')
        future = self.rating_executor.submit(save_rating)
        self.async_work(future.result, updated,
                        lambda: client is self.client,
                        failed)

    def show_artist_albums(self, artist):
        if not self.client or not artist:
            return
        self.artist_filter = artist
        self.artist_catalog = None
        self.search.set_text('')
        self.artist_filter_label.set_text(f'Albums by {artist}')
        self.artist_filter_bar.set_no_show_all(False)
        self.artist_filter_bar.show_all()
        self.show_view('albums')
        self.load_albums()

    def show_all_albums(self, *_):
        self.artist_filter = None
        self.artist_catalog = None
        self.artist_filter_bar.hide()
        self.album_search_revealer.set_reveal_child(False)
        self.search.set_text('')
        self.show_view('albums')
        self.load_albums()

    def search_album_titles(self, *_):
        self.artist_filter = None
        self.artist_catalog = None
        self.album_search_catalog = None
        self.artist_filter_bar.hide()
        self.load_albums()

    def show_in_library(self, album):
        if not self.client:
            return
        self.invalidate_song_catalog()
        self.library_album_filter = None
        self.library_tag_filter = None
        self.playlist_list.select_row(self.all_songs_row)
        self.active_playlist = None
        self.library_album_filter = album
        self.update_full_library_selection()
        self.library_back_button.set_no_show_all(False)
        self.library_back_button.show()
        self.songs_heading.set_text(f'{album.title} · {album.artist}')
        self.apply_library_layout()
        self.show_view('library')
        self.load_songs()

    def clear_library_album_filter(self, *_):
        self.invalidate_song_catalog()
        self.library_album_filter = None
        self.library_tag_filter = None
        self.library_back_button.hide()
        self.apply_library_layout()
        if self.playlist_list.get_selected_row() is self.all_songs_row:
            self.songs_heading.set_text('Full music library')
            self.update_full_library_selection()
            self.load_songs()
        else:
            self.playlist_list.select_row(self.all_songs_row)

    def status_changed(self, *_):
        current = self.content_views.get_visible_child_name()
        action = ('Return to ' + self.previous_panel.title()) if current == 'now' else 'Show Now Playing'
        message = self.status.get_text()
        if message == 'Streaming from Plex':
            message = ''
        self.set_tooltip(self.song_info_button, action + ('\n' + message if message else ''))
        self.set_tooltip(self.song_title_button, action + ('\n' + message if message else ''))

    def build_now_view(self):
        panel = Gtk.Overlay()
        panel.set_name('now-panel')
        self.now_panel = panel
        panel.connect('scroll-event', self.zoom_art, 'now')
        self.now_visual_background = Gtk.Stack()
        self.now_visual_background.set_hhomogeneous(False)
        self.now_visual_background.set_vhomogeneous(False)
        self.now_visual_background.add_named(Gtk.Box(), 'art')
        self.hero_waveform = RibbonVisualizer()
        self.hero_waveform.set_view(self.visualizer_view)
        self.hero_waveform.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                                      Gdk.EventMask.SCROLL_MASK)
        self.hero_waveform.connect('button-press-event', self.toggle_now_waveform)
        self.hero_waveform.connect('scroll-event', self.zoom_art, 'now')
        self.now_visual_background.add_named(self.hero_waveform, 'waveform')
        self.now_visual_background.set_visible_child_name('art')
        panel.add(self.now_visual_background)
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=44)
        group.set_hexpand(True)
        group.set_valign(Gtk.Align.CENTER)
        group.set_margin_top(0)
        group.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        group.connect('button-press-event', self.now_group_pressed)
        self.now_group = group
        group.set_halign(Gtk.Align.FILL)
        panel.add_overlay(group)
        self.now_top_spacer = Gtk.Box()
        self.now_top_spacer.set_no_show_all(True)
        group.pack_start(self.now_top_spacer, True, True, 0)
        self.hero_cover = Gtk.DrawingArea()
        self.hero_cover.set_halign(Gtk.Align.CENTER)
        self.hero_cover.set_valign(Gtk.Align.CENTER)
        self.hero_cover.get_accessible().set_name('Album artwork; click to show music ribbon')
        self.hero_cover.connect('draw', self.draw_now_cover)
        self.set_placeholder_art(self.hero_cover, self.now_art_size,
                                 SMALL_PLACEHOLDER_LOGO_RATIO)
        self.update_now_art_slot()
        self.hero_cover.add_events(Gdk.EventMask.SCROLL_MASK |
                                   Gdk.EventMask.BUTTON_PRESS_MASK)
        self.hero_cover.connect('scroll-event', self.zoom_art, 'now')
        self.hero_cover.connect('button-press-event', self.toggle_now_waveform)
        self.now_visual_stack = Gtk.Stack()
        self.now_visual_stack.set_hhomogeneous(False)
        self.now_visual_stack.set_vhomogeneous(False)
        self.now_visual_stack.set_halign(Gtk.Align.CENTER)
        self.now_visual_stack.set_valign(Gtk.Align.CENTER)
        self.now_visual_stack.set_size_request(self.now_art_size, self.now_art_size)
        self.now_visual_stack.add_named(self.hero_cover, 'art')
        placeholder = Gtk.DrawingArea()
        placeholder.get_accessible().set_name('Music ribbon; click to show album artwork')
        placeholder.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK)
        placeholder.connect('button-press-event', self.toggle_now_waveform)
        placeholder.connect('scroll-event', self.zoom_art, 'now')
        self.now_visual_stack.add_named(placeholder, 'waveform')
        self.now_visual_stack.set_visible_child_name('art')
        self.hero_waveform_active = False
        group.pack_start(self.now_visual_stack, False, False, 0)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.now_info = info
        info.set_valign(Gtk.Align.CENTER)
        info.set_margin_top(12)
        group.pack_start(info, False, False, 0)
        self.hero_title = Gtk.Label(label='Nothing playing')
        self.hero_title.set_name('now-title')
        self.hero_title.set_justify(Gtk.Justification.CENTER)
        self.hero_title.set_line_wrap(True)
        self.hero_title.set_lines(2)
        self.hero_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.hero_title.set_max_width_chars(50)
        info.pack_start(self.hero_title, False, False, 0)
        self.hero_artist = Gtk.Label(label='Choose an album or song to start listening')
        self.hero_artist.set_name('now-artist')
        self.hero_artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.hero_artist.set_max_width_chars(40)
        hero_artist_click = Gtk.EventBox()
        hero_artist_click.set_visible_window(False)
        hero_artist_click.add(self.hero_artist)
        hero_artist_click.connect('button-press-event', self.artist_name_pressed,
                                  lambda: self.queue[self.index].artist
                                  if 0 <= self.index < len(self.queue) else '')
        info.pack_start(hero_artist_click, False, False, 0)
        self.hero_album = Gtk.Label()
        self.hero_album.set_name('now-album')
        self.hero_album.set_ellipsize(Pango.EllipsizeMode.END)
        self.hero_album.set_max_width_chars(40)
        hero_album_click = Gtk.EventBox()
        hero_album_click.set_visible_window(False)
        hero_album_click.add(self.hero_album)
        self.set_tooltip(hero_album_click, 'Show album in album grid')
        hero_album_click.get_accessible().set_name('Show album in album grid')
        hero_album_click.connect('button-press-event', self.now_album_pressed)
        info.pack_start(hero_album_click, False, False, 0)
        self.now_rating = Gtk.Box(spacing=0, halign=Gtk.Align.CENTER)
        self.now_rating.set_name('now-rating')
        self.now_rating.set_no_show_all(True)
        self.now_rating_buttons = []
        for stars in range(1, 6):
            button = Gtk.Button(label='☆')
            button.get_accessible().set_name(f'Rate current track {stars} stars')
            button.connect('clicked', self.rate_now_track, stars)
            self.now_rating.pack_start(button, False, False, 0)
            self.now_rating_buttons.append(button)
        info.pack_start(self.now_rating, False, False, 0)
        self.now_bottom_spacer = Gtk.Box()
        self.now_bottom_spacer.set_no_show_all(True)
        group.pack_end(self.now_bottom_spacer, True, True, 0)
        self.refresh_now_rating()
        panel.connect('size-allocate', self.now_view_allocated)
        self.content_views.add_named(panel, 'now')

    def toggle_now_waveform(self, _widget, event):
        if event.button != 1:
            return False
        if (self.now_visual_stack.get_visible_child_name() != 'waveform' and
                self.live_waveform_tap is None):
            self.status.set_text('Music ribbon is unavailable: GStreamer spectrum missing')
            return True
        show_waveform = self.now_visual_stack.get_visible_child_name() != 'waveform'
        self.hero_waveform_active = show_waveform
        self.now_visual_stack.set_visible_child_name(
            'waveform' if show_waveform else 'art')
        self.now_visual_background.set_visible_child_name(
            'waveform' if show_waveform else 'art')
        self.apply_now_view_resize()
        self.now_panel.queue_resize()
        self.refresh_live_waveform()
        return True

    def now_group_pressed(self, _widget, event):
        if not self.hero_waveform_active or event.button != 1:
            return False
        target = Gtk.get_event_widget(event)
        while target is not None and target is not self.now_group:
            if target is self.now_info:
                return False
            target = target.get_parent()
        return self.toggle_now_waveform(_widget, event)

    def refresh_live_waveform(self):
        if self.live_waveform_tap is None:
            return
        view = self.content_views.get_visible_child_name()
        shown = self.hero_waveform_active and view == 'now'
        background = (self.hero_waveform_active and view not in ('now', 'library', 'loading') and
                      getattr(self, 'background_visualizer_enabled', False) and
                      self.gradient_enabled and self.theme != 'black')
        playing = self.stream_open and self.playing
        self.live_waveform_tap.set_enabled(bool((shown or background) and playing))
        self.hero_waveform.set_active(shown)
        self.hero_waveform.set_playing(bool(shown and playing))
        visualizer = getattr(self, 'background_visualizer', None)
        if visualizer is not None:
            visibility_changed = visualizer.get_visible() != background
            visualizer.set_visible(background)
            visualizer.set_active(background)
            visualizer.set_playing(bool(background and playing))
            wall = getattr(self, 'gpu_wall', None)
            if visibility_changed and wall is not None:
                wall.render_surface.queue_draw()

    def background_visualizer_changed(self, button):
        self.background_visualizer_enabled = button.get_active()
        self.refresh_live_waveform()
        try:
            save_background_visualizer_enabled(self.background_visualizer_enabled)
        except OSError:
            self.status.set_text('Could not save the appearance setting.')

    def visualizer_view_changed(self, combo):
        view = combo.get_active_id()
        if view not in ('ribbon', 'perspective'):
            return
        self.visualizer_view = view
        self.hero_waveform.set_view(view)
        self.background_visualizer.set_view(view)
        try:
            save_visualizer_view(view)
        except OSError:
            self.status.set_text('Could not save the visualizer view.')

    def instrument_visualizer_changed(self, button):
        self.instrument_visualizer_enabled = button.get_active()
        self.instrument_generation += 1
        self.instrument_analysis = None
        self.instrument_pending = None
        try:
            save_instrument_visualizer_enabled(self.instrument_visualizer_enabled)
        except OSError:
            self.status.set_text('Could not save the instrument visualizer setting.')
        if self.instrument_visualizer_enabled and self.current_stream_uri and self.queue:
            self.prepare_instrument_analysis(self.queue_client, self.queue[self.index],
                                             self.current_stream_uri, self.play_generation)
        elif self.instrument_visualizer_enabled:
            self.instrument_visualizer_status.set_text('Play a track to begin instrument analysis.')
        else:
            self.instrument_visualizer_status.set_text('Uses the regular audio visualizer.')

    def prepare_instrument_analysis(self, client, track, uri, play_generation):
        if not self.instrument_visualizer_enabled or not client or track.duration <= 0:
            return
        if self.instrument_future is not None:
            # Finish a long-running track so its analysis is useful next time;
            # retain only the latest requested track while that work runs.
            self.instrument_pending = (client, track, uri, play_generation)
            self.instrument_visualizer_status.set_text('Analyzing a previous track; current track is queued.')
            return
        generation = self.instrument_generation
        valid = lambda: not self.closed and self.instrument_visualizer_enabled and generation == self.instrument_generation
        self.instrument_visualizer_status.set_text('Analyzing instruments in the background…')
        def work():
            return analyze_instruments(LocalCache(client), client, track, uri, lambda: not valid())
        def finish(future):
            self.instrument_future = None
            if self.closed:
                return False
            try:
                analysis, status = future.result()
            except Exception:
                analysis, status = None, 'failed'
            if valid() and play_generation == self.play_generation:
                self.instrument_analysis = analysis
                messages = {
                    'ready': 'Instrument analysis ready.',
                    'missing': 'Demucs Python is unavailable. See the guide for setup.',
                    'missing_numpy': 'NumPy is missing from the Demucs environment. See the guide for setup.',
                    'missing_demucs': 'Demucs or a dependency is missing. See the guide for setup.',
                    'failed': 'Instrument analysis failed. Check Demucs setup; regular visualizer remains active.',
                    'cancelled': 'Instrument analysis cancelled.',
                }
                self.instrument_visualizer_status.set_text(messages.get(status, 'Instrument analysis unavailable.'))
            pending = self.instrument_pending
            self.instrument_pending = None
            if (self.instrument_visualizer_enabled and pending and
                    pending[3] == self.play_generation):
                self.prepare_instrument_analysis(*pending)
            return False
        try:
            self.instrument_future = self.instrument_workers.submit(work)
            self.instrument_future.add_done_callback(lambda future: GLib.idle_add(finish, future))
        except RuntimeError:
            self.instrument_future = None

    def rate_now_track(self, _button, stars):
        if 0 <= self.index < len(self.queue) and (self.stream_open or self.remote_opening):
            song = self.queue[self.index]
            self.set_song_rating(song, stars_from_click((stars - 1) * 20,
                                                        song.user_rating))

    def refresh_now_rating(self):
        if not hasattr(self, 'now_rating_buttons'):
            return
        song = (self.queue[self.index] if 0 <= self.index < len(self.queue) and
                (self.stream_open or self.remote_opening) else None)
        filled = filled_stars(song.user_rating) if song else 0
        for stars, button in enumerate(self.now_rating_buttons, 1):
            button.set_label('★' if stars <= filled else '☆')
            button.set_sensitive(song is not None and self.client is not None)

    def now_view_allocated(self, _scroll, allocation):
        if allocation.width < 1 or allocation.height < 1:
            return
        if getattr(self, '_now_resizing', False):
            return
        info_height = self.now_info.get_preferred_height_for_width(
            max(1, allocation.width - 48))[1]
        dimensions = (allocation.width, allocation.height,
                      0 if getattr(self, '_now_horizontal', False) else info_height)
        if dimensions == getattr(self, '_now_view_dimensions', None):
            return
        self._now_view_dimensions = dimensions
        self._now_resizing = True
        try:
            self.apply_now_view_resize()
        finally:
            self._now_resizing = False
        group = getattr(self, 'now_group', None)
        if group is not None and group.get_allocated_width() > 1:
            minimum = group.get_preferred_height_for_width(group.get_allocated_width())[0]
            if group.get_allocated_height() < min(minimum, allocation.height):
                self.request_now_layout_flush()

    def apply_now_view_resize(self):
        if getattr(self, 'closed', False):
            return False
        orientation_changed = False
        layout_changed = False
        viewport = getattr(self, 'now_panel', getattr(self, 'content_views', None))
        if viewport is not None and hasattr(viewport, 'get_allocated_width'):
            width = viewport.get_allocated_width()
            height = viewport.get_allocated_height()
            if width > 0 and height > 0:
                horizontal = height < 480 and width > height * 1.6
                compact = height < 480
                orientation = (Gtk.Orientation.HORIZONTAL if horizontal
                               else Gtk.Orientation.VERTICAL)
                orientation_changed = self.now_group.get_orientation() != orientation
                spacing = 24 if compact else 44
                info_margin = 6 if compact else 12
                info_spacing = 4 if compact else 8
                title_lines = 1 if height < 300 else 2
                layout_changed = (self.now_group.get_spacing() != spacing or
                                  self.now_info.get_margin_top() != info_margin or
                                  self.now_info.get_spacing() != info_spacing or
                                  self.hero_title.get_lines() != title_lines)
                if orientation_changed:
                    self.now_group.set_orientation(orientation)
                self.now_group.set_halign(Gtk.Align.CENTER if horizontal else Gtk.Align.FILL)
                self.now_group.set_hexpand(not horizontal)
                self.now_group.set_valign(Gtk.Align.CENTER)
                self.now_group.set_vexpand(False)
                self.now_top_spacer.set_visible(False)
                self.now_bottom_spacer.set_visible(False)
                self.now_group.set_spacing(spacing)
                self.now_group.set_margin_top(0)
                self.now_info.set_margin_top(info_margin)
                self.now_info.set_spacing(info_spacing)
                self.hero_title.set_lines(title_lines)
                self._now_horizontal = horizontal
                info_height = self.now_info.get_preferred_height_for_width(
                    max(1, min(width - 48, 420) if horizontal else width - 48))[1]
                self._now_view_dimensions = (width, height,
                                             0 if horizontal else info_height)
        self.update_now_art_slot()
        if getattr(self, '_now_horizontal', False):
            self.hero_title.set_max_width_chars(max(8, self.now_display_art_size // 26))
            text_chars = max(8, self.now_display_art_size // 19)
            self.hero_artist.set_max_width_chars(text_chars)
            self.hero_album.set_max_width_chars(text_chars)
        else:
            self.hero_title.set_max_width_chars(50)
            self.hero_artist.set_max_width_chars(40)
            self.hero_album.set_max_width_chars(40)
        if viewport is not None and (orientation_changed or layout_changed):
            viewport.queue_resize()
            self.request_now_layout_flush()
        return False

    def update_now_art_slot(self):
        dimensions = getattr(self, '_now_view_dimensions', None)
        if dimensions:
            if getattr(self, '_now_horizontal', False):
                width, height, _info_height = dimensions
                art_size = max(80, min(self.now_art_size, int(width * 0.38),
                                       height - 32))
            else:
                art_size = now_art_fit(self.now_art_size, *dimensions)
        else:
            art_size = self.now_art_size
        visual_layout = art_size
        if visual_layout == getattr(self, '_now_art_layout', None):
            return
        self._now_art_layout = visual_layout
        self.now_display_art_size = art_size
        if hasattr(self, 'now_visual_stack'):
            self.now_visual_stack.set_size_request(art_size, art_size)
        if (hasattr(self, 'hero_cover') and
                getattr(self.hero_cover, 'art_display_size', None) != art_size):
            self.set_art_size(self.hero_cover, art_size)
        if hasattr(self, 'now_panel'):
            self.now_panel.queue_resize()
            self.request_now_layout_flush()

    def request_now_layout_flush(self):
        if not getattr(self, '_now_layout_flush_pending', False):
            self._now_layout_flush_pending = True
            GLib.idle_add(self.flush_now_layout, priority=GLib.PRIORITY_HIGH_IDLE)

    def flush_now_layout(self):
        self._now_layout_flush_pending = False
        if not getattr(self, 'closed', False):
            self.now_group.queue_resize()
            self.now_panel.check_resize()
            self.now_group.size_allocate(self.now_group.get_allocation())
        return False

    def set_art_size(self, image, size):
        image.art_display_size = size
        if image is getattr(self, 'lyrics_cover', None) and isinstance(image, Gtk.DrawingArea):
            image.queue_draw()
            return
        image.set_size_request(size, size)
        if image is getattr(self, 'hero_cover', None) and isinstance(image, Gtk.DrawingArea):
            image.queue_draw()
            return
        source = getattr(image, 'art_source', None)
        if source:
            pixbuf = source if source.get_width() == size and source.get_height() == size else \
                source.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
            image.set_from_pixbuf(pixbuf)
        elif getattr(image, 'placeholder_art', False):
            image.set_from_pixbuf(placeholder_art(
                size, getattr(image, 'placeholder_ratio', 1.0)))
        elif image.get_storage_type() == Gtk.ImageType.ICON_NAME:
            image.set_pixel_size(min(size // 3, 96))

    def set_placeholder_art(self, image, size, logo_ratio=None):
        if logo_ratio is not None:
            image.placeholder_ratio = logo_ratio
        image.art_source = None
        image.placeholder_art = True
        Player.set_art_size(self, image, size)

    def draw_now_cover(self, image, context):
        size = min(image.get_allocated_width(), image.get_allocated_height())
        source = (app_icon() if getattr(image, 'placeholder_art', False) else
                  getattr(image, 'art_source', None))
        if size < 1 or source is None:
            return False
        ratio = (getattr(image, 'placeholder_ratio', 1.0)
                 if getattr(image, 'placeholder_art', False) else 1.0)
        scale = min(size * ratio / source.get_width(),
                    size * ratio / source.get_height())
        drawn_width = source.get_width() * scale
        drawn_height = source.get_height() * scale
        context.save()
        context.translate((image.get_allocated_width() - drawn_width) / 2,
                          (image.get_allocated_height() - drawn_height) / 2)
        context.scale(scale, scale)
        Gdk.cairo_set_source_pixbuf(context, source, 0, 0)
        context.paint()
        context.restore()
        return False

    def change_album_zoom(self, steps):
        canvas = getattr(self, 'album_canvas', None)
        if getattr(self, 'canvas_enabled', False) and canvas is not None:
            if steps < 0:
                canvas.unflip_for_zoom_out()
            canvas.anchor = (canvas.area.get_allocated_width() / 2, canvas.area.get_allocated_height() / 2)
            canvas.target_zoom = max(.08, min(2.5, canvas.target_zoom * math.exp(.17 * steps)))
            canvas.start_animation()
            return
        low, high = ALBUM_COLUMN_RANGE
        columns = max(low, min(high, self.album_columns - steps))
        if columns == self.album_columns:
            return
        self.album_columns = columns
        self.apply_album_grid_layout()
        if hasattr(self, 'album_grid_scale'):
            self.album_grid_scale.set_value(columns)
        try:
            save_album_columns(columns)
        except OSError:
            self.status.set_text('Could not save album grid zoom.')

    def change_canvas_columns(self, delta):
        canvas = getattr(self, 'album_canvas', None)
        if getattr(self, 'canvas_enabled', False) and canvas is not None:
            canvas.change_columns(delta)

    def reload_albums(self, *_):
        if not self.client:
            return
        self.artist_catalog = None
        self.album_search_catalog = None
        self.load_albums(force_refresh=True)

    def zoom_art(self, _widget, event, view):
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        if event.direction == Gdk.ScrollDirection.UP:
            steps = 1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            steps = -1
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            success, _dx, dy = event.get_scroll_deltas()
            if not success:
                return True
            self.zoom_remainder[view] -= dy
            steps = int(self.zoom_remainder[view])
            self.zoom_remainder[view] -= steps
        else:
            return True
        if not steps:
            return True
        if view == 'albums':
            Player.change_album_zoom(self, steps)
        else:
            low, high = NOW_SIZE_RANGE
            size = max(low, min(high, self.now_art_size + 40 * steps))
            if size == self.now_art_size:
                return True
            self.now_art_size = size
            self.update_now_art_slot()
            try:
                save_now_art_size(size)
            except OSError:
                self.status.set_text('Could not save artwork size.')
        return True

    @staticmethod
    def library_sidebar_heading(text, icon):
        row = Gtk.Box(spacing=8)
        row.set_margin_start(8)
        row.set_margin_end(32)
        row.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
        label = Gtk.Label(label=text, xalign=0)
        label.set_name('full-library-title')
        row.pack_start(label, True, True, 0)
        return row

    def build_library_view(self):
        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_name('library-split')
        split.set_position(225)
        sidebar_panels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        library_title = Gtk.Label(label='Library', xalign=0)
        library_title.set_name('now-title')
        library_title.set_margin_start(20)
        library_title.set_margin_top(18)
        sidebar_panels.pack_start(library_title, False, False, 0)
        self.full_library_button = Gtk.Button()
        full_library_row = Gtk.Box(spacing=8)
        full_library_row.pack_start(Gtk.Image.new_from_icon_name(
            'view-list-symbolic', Gtk.IconSize.MENU), False, False, 0)
        full_library_title = Gtk.Label(label='Full music library', xalign=0)
        full_library_title.set_name('full-library-title')
        full_library_row.pack_start(full_library_title, True, True, 0)
        self.full_library_button.add(full_library_row)
        self.full_library_button.connect('clicked', self.show_full_music_library)
        self.full_library_button.set_name('full-library-button')
        sidebar_panels.pack_start(self.full_library_button, False, False, 0)
        self.library_side_split = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.library_side_split.set_name('library-side-split')
        self.library_side_split.set_wide_handle(True)
        self.library_side_split.set_position(190)
        sidebar_panels.pack_start(self.library_side_split, True, True, 0)
        smart_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        smart_panel.set_margin_end(0)
        smart_panel.set_name('smart-playlist-panel')
        smart_header = Gtk.Overlay()
        smart_header.set_name('smart-playlist-header')
        smart_header.add(self.library_sidebar_heading('Smart playlists', 'emblem-system-symbolic'))
        self.new_smart_playlist_button = Gtk.Button.new_from_icon_name(
            'list-add-symbolic', Gtk.IconSize.BUTTON)
        self.set_tooltip(self.new_smart_playlist_button, 'Create a local smart playlist')
        self.new_smart_playlist_button.get_accessible().set_name('Create smart playlist')
        self.new_smart_playlist_button.connect('clicked', self.create_smart_playlist_dialog)
        self.new_smart_playlist_button.set_halign(Gtk.Align.END)
        self.new_smart_playlist_button.set_valign(Gtk.Align.CENTER)
        self.new_smart_playlist_button.set_margin_bottom(2)
        smart_header.add_overlay(self.new_smart_playlist_button)
        smart_header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        smart_header_box.pack_start(smart_header, False, False, 0)
        underline = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        underline.set_name('playlist-header-underline')
        smart_header_box.pack_start(underline, False, False, 0)
        smart_panel.pack_start(smart_header_box, False, False, 0)
        self.smart_playlist_list = Gtk.ListBox()
        self.smart_playlist_list.set_name('smart-playlist-list')
        self.smart_playlist_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.smart_playlist_list.connect('row-selected', self.select_smart_playlist)
        self.smart_playlist_list.connect('button-press-event', self.playlist_list_pressed)
        self.setup_playlist_drag(self.smart_playlist_list, smart=True)
        smart_scroll = self.scroll(self.smart_playlist_list, overlay_scrolling=False)
        smart_scroll.set_name('smart-playlist-scroll')
        smart_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        smart_scroll.set_min_content_height(50)
        smart_panel.pack_start(self.stable_library_scrollbar(smart_scroll, auto_hide=True), True, True, 0)
        self.library_side_split.pack1(smart_panel, True, False)
        playlists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        playlists.set_margin_end(0)
        playlists.set_name('playlist-panel')
        playlists.set_size_request(170, -1)
        playlist_header = Gtk.Overlay()
        playlist_header.set_name('playlist-header')
        playlist_header.add(self.library_sidebar_heading('Playlists', 'view-list-symbolic'))
        self.new_playlist_button = Gtk.Button.new_from_icon_name('list-add-symbolic', Gtk.IconSize.BUTTON)
        self.set_tooltip(self.new_playlist_button, 'Create playlist on Plex')
        self.new_playlist_button.get_accessible().set_name('Create playlist')
        self.new_playlist_button.connect('clicked', self.create_playlist_dialog)
        self.new_playlist_button.set_halign(Gtk.Align.END)
        self.new_playlist_button.set_valign(Gtk.Align.CENTER)
        self.new_playlist_button.set_margin_bottom(2)
        playlist_header.add_overlay(self.new_playlist_button)
        playlist_header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        playlist_header_box.pack_start(playlist_header, False, False, 0)
        underline = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        underline.set_name('playlist-header-underline')
        playlist_header_box.pack_start(underline, False, False, 0)
        playlists.pack_start(playlist_header_box, False, False, 0)
        self.playlist_list = Gtk.ListBox()
        self.playlist_list.set_name('playlist-list')
        self.playlist_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.playlist_list.connect('row-selected', self.select_playlist)
        self.playlist_list.connect('button-press-event', self.playlist_list_pressed)
        self.setup_playlist_drag(self.playlist_list, smart=False)
        playlist_scroll = self.scroll(self.playlist_list, overlay_scrolling=False)
        playlist_scroll.set_name('playlist-scroll')
        playlist_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        playlists.pack_start(self.stable_library_scrollbar(playlist_scroll, auto_hide=True), True, True, 0)
        self.all_songs_row = self.playlist_row('All songs', None)
        self.all_songs_row.set_no_show_all(True)
        self.all_songs_row.hide()
        self.library_side_split.pack2(playlists, True, False)
        split.pack1(sidebar_panels, False, False)

        songs_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        songs_panel.set_name('song-panel')
        self.library_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.songs_heading = Gtk.Label(label='Full music library', xalign=0.5)
        self.songs_heading.set_name('now-title')
        self.songs_heading.set_margin_top(8)
        self.songs_heading.set_margin_start(8)
        self.songs_heading.set_margin_end(8)
        title_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_group.pack_start(self.songs_heading, False, False, 0)
        self.song_count = Gtk.Label(label='Connect to a server to browse songs', xalign=0.5)
        self.song_count.set_hexpand(True)
        self.song_count.set_halign(Gtk.Align.FILL)
        self.song_count.set_justify(Gtk.Justification.CENTER)
        self.song_count.set_ellipsize(Pango.EllipsizeMode.END)
        self.song_count.set_max_width_chars(1)
        self.song_count.get_style_context().add_class('dim-label')
        title_group.pack_start(self.song_count, False, False, 0)
        self.library_header.pack_start(title_group, False, False, 0)
        self.library_back_button = self.button('‹ All songs', self.clear_library_album_filter)
        self.library_back_button.set_no_show_all(True)
        self.library_back_button.set_halign(Gtk.Align.START)
        self.library_back_button.set_margin_end(8)
        self.library_header.pack_start(self.library_back_button, False, False, 0)
        self.library_search = Gtk.SearchEntry(
            placeholder_text='Filter songs, artists, albums')
        self.library_search.set_margin_end(8)
        self.library_search.connect('key-press-event', self.search_escape_pressed)
        self.library_search.connect('search-changed', self.library_search_changed)
        self.library_search_bar = Gtk.Box()
        self.library_search_bar.pack_start(self.library_search, True, True, 0)
        self.library_list_mode_button = Gtk.ToggleButton()
        self.library_list_mode_button.set_image(Player.library_list_lines_icon())
        self.library_list_mode_button.get_accessible().set_name('Song list view')
        self.set_tooltip(self.library_list_mode_button, 'Song list view')
        self.library_album_mode_button = Gtk.ToggleButton()
        self.library_album_mode_button.set_image(Gtk.Image.new_from_icon_name('view-list-symbolic', Gtk.IconSize.BUTTON))
        self.library_album_mode_button.get_accessible().set_name('Albums and songs view')
        self.set_tooltip(self.library_album_mode_button, 'Albums and songs view')
        self.library_list_mode_button.set_active(self.library_view_mode == 'songs')
        self.library_album_mode_button.set_active(self.library_view_mode == 'albums')
        self.library_list_mode_button.connect('clicked', self.library_view_mode_changed, 'songs')
        self.library_album_mode_button.connect('clicked', self.library_view_mode_changed, 'albums')
        self.tag_edit_button = Gtk.Button(label='Edit tags')
        self.tag_edit_button.set_sensitive(False)
        self.tag_edit_button.connect('clicked', lambda *_: self.edit_selected_library_tracks())
        self.library_search_bar.pack_start(self.tag_edit_button, False, False, 0)
        self.library_search_bar.pack_start(self.library_list_mode_button, False, False, 0)
        self.library_search_bar.pack_start(self.library_album_mode_button, False, False, 0)
        self.library_header.pack_start(self.library_search_bar, False, False, 0)
        songs_panel.pack_start(self.library_header, False, False, 0)
        self.song_sort = 'addedAt:desc'
        self.song_store = Gtk.ListStore(*([str] * (len(LIBRARY_COLUMNS) + 4)))
        self.song_view = self.table(self.song_store, ['Name', 'Artist', 'Album', 'Time'])
        self.song_view.connect('key-press-event', self.search_escape_pressed)
        self.song_view.set_name('song-view')
        self.song_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.song_view.get_selection().connect(
            'changed', lambda selection: self.tag_edit_button.set_sensitive(
                bool(selection.get_selected_rows()[1])))
        self.song_columns = {}
        self.rating_column_preferred = True
        for column, field in zip(self.song_view.get_columns(),
                                 BASE_LIBRARY_FIELDS):
            self.configure_song_column(column, field)
        for index, (label, field) in enumerate(LIBRARY_COLUMNS[4:], 4):
            renderer = Gtk.CellRendererText()
            if field == 'user_rating':
                renderer.set_property('xalign', 0.0)
            column = Gtk.TreeViewColumn(label, renderer, text=index)
            self.song_view.append_column(column)
            self.configure_song_column(column, field)
            column.set_visible(False)
        heart = Gtk.CellRendererText()
        heart.set_property('foreground', '#e84b5a')
        heart.set_property('scale', 0.82)
        heart.set_fixed_size(20, -1)
        heart.set_property('xalign', 0.5)
        title_column = self.song_columns['title']
        title_column.pack_start(heart, False)
        title_column.add_attribute(heart, 'text', len(LIBRARY_COLUMNS))
        title_column.reorder(heart, 0)
        marker = Gtk.CellRendererText()
        marker.set_fixed_size(22, -1)
        marker.set_property('xalign', 0.5)
        title_column.pack_start(marker, False)
        title_column.reorder(marker, 0)
        title_column.set_cell_data_func(marker, self.library_playing_marker)
        self.song_cell_attributes = []
        for index, (_label, field) in enumerate(LIBRARY_COLUMNS):
            column = self.song_columns[field]
            for renderer in column.get_cells():
                text_column = (None if renderer is marker else
                               len(LIBRARY_COLUMNS) if renderer is heart else index)
                self.song_cell_attributes.append((column, renderer, text_column))
        Player.bind_song_cell_backgrounds(self)
        gutter_renderer = Gtk.CellRendererText()
        self.album_gutter_column = Gtk.TreeViewColumn('', gutter_renderer)
        self.album_gutter_column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        self.album_gutter_column.set_fixed_width(AlbumGroupOverlay.GUTTER)
        self.album_gutter_column.set_min_width(AlbumGroupOverlay.MIN_GUTTER)
        self.album_gutter_column.set_max_width(AlbumGroupOverlay.MAX_GUTTER)
        self.album_gutter_column.set_cell_data_func(gutter_renderer, self.album_gutter_row_size)
        self.album_gutter_column.set_resizable(True)
        self.song_view.append_column(self.album_gutter_column)
        self.song_view.move_column_after(self.album_gutter_column, None)
        self.album_gutter_column.set_visible(self.library_view_mode == 'albums')
        Player.apply_library_row_alignment(self)
        self.song_view.connect('columns-changed', self.library_columns_changed)
        self.song_view.connect('row-activated', self.activate_song)
        self.song_view.connect('button-press-event', self.library_artist_pressed)
        self.song_drag_targets = [Gtk.TargetEntry.new('application/x-plex-song-key',
                                                      Gtk.TargetFlags.SAME_APP, 0)]
        self.song_view.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK,
                                                 self.song_drag_targets, Gdk.DragAction.COPY)
        self.song_native_drag_enabled = True
        self.song_view.connect('drag-begin', self.song_drag_begin)
        self.song_view.connect('drag-end', self.song_drag_end)
        self.song_view.connect('drag-data-get', self.song_drag_data_get)
        self.song_view.add_events(Gdk.EventMask.POINTER_MOTION_MASK |
                                  Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.song_view.connect('motion-notify-event', self.song_pointer_motion)
        self.song_view.connect('button-release-event', self.song_pointer_release)
        song_scroll = self.scroll(self.song_view, overlay_scrolling=False)
        self.song_scroll = song_scroll
        song_scroll.set_name('song-scroll')
        song_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        song_scroll_row = self.stable_library_scrollbar(song_scroll)
        song_scroll_row.set_margin_end(8)
        self.library_tracks_container = Gtk.Overlay()
        self.library_tracks_container.add(song_scroll_row)
        self.album_group_overlay = AlbumGroupOverlay(self, self.song_view, song_scroll)
        self.album_gutter_column.connect('notify::width', self.album_group_overlay.redraw)
        self.album_gutter_column.connect('notify::width', self.library_columns_changed)
        self.library_tracks_container.add_overlay(self.album_group_overlay)
        self.library_tracks_container.set_overlay_pass_through(self.album_group_overlay, True)
        self.album_group_overlay.set_no_show_all(True)
        self.album_group_overlay.set_visible(self.library_view_mode == 'albums')
        songs_panel.pack_start(self.library_tracks_container, True, True, 0)
        split.pack2(songs_panel, True, False)
        self.content_views.add_named(split, 'library')
        self.playlists = []
        self.active_playlist = None
        self.active_smart_playlist = None
        self.playlist_restore_key = None
        self.songs = []
        self.song_total = 0
        self.song_generation = 0
        self.playlist_generation = 0
        self.playlist_reorder_pending = False
        self.current_library_layout_key = None
        self.library_layout_restoring = False
        self.library_layout_save_timeout = 0
        self.playlist_list.select_row(self.all_songs_row)

    def build_styles_view(self):
        self.styles_stack = Gtk.Stack()
        self.content_views.add_named(self.styles_stack, 'styles')
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        panel.set_name('styles-panel')
        self.style_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top = Gtk.Overlay()
        top.set_margin_start(20)
        top.set_margin_end(20)
        top.set_margin_top(18)
        sides = Gtk.Box(spacing=8)
        heading = Gtk.Label(label='Styles & Moods', xalign=0)
        heading.set_name('now-title')
        heading.set_ellipsize(Pango.EllipsizeMode.END)
        heading.set_hexpand(True)
        sides.pack_start(heading, True, True, 0)
        self.style_search = Gtk.SearchEntry(placeholder_text='Filter styles and moods')
        self.style_search.set_width_chars(18)
        self.style_search.set_valign(Gtk.Align.CENTER)
        self.style_search.connect('search-changed', lambda *_: self.render_styles_browser())
        self.style_search_bar = Gtk.Box()
        self.style_search_bar.pack_start(self.style_search, True, True, 0)
        sides.pack_end(self.style_search_bar, False, False, 0)
        top.add(sides)
        modes = Gtk.Box(spacing=4)
        modes.set_halign(Gtk.Align.CENTER)
        modes.set_valign(Gtk.Align.CENTER)
        self.style_mode = 'mood'
        self.style_mode_buttons = {}
        for field, label in (('mood', 'Moods'), ('style', 'Styles')):
            button = Gtk.Button(label=label)
            button.set_name('style-mode-button')
            button.connect('clicked', self.set_style_mode, field)
            modes.pack_start(button, False, False, 0)
            self.style_mode_buttons[field] = button
        top.add_overlay(modes)
        self.style_header.pack_start(top, False, False, 0)
        panel.pack_start(self.style_header, False, False, 0)
        self.style_status = Gtk.Label(label='Connect to a server to browse styles and moods',
                                      xalign=0)
        self.style_status.set_no_show_all(True)
        self.style_status.set_margin_start(self.album_margin)
        panel.pack_start(self.style_status, False, False, 0)
        self.style_grid = Gtk.FlowBox()
        self.style_grid.set_name('style-grid')
        self.style_grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.style_grid.set_min_children_per_line(1)
        self.style_grid.set_max_children_per_line(16)
        self.style_grid.set_row_spacing(self.album_spacing)
        self.style_grid.set_column_spacing(self.album_spacing)
        self.style_grid.set_valign(Gtk.Align.START)
        self.style_grid.set_halign(Gtk.Align.CENTER)
        style_wall = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=self.album_margin)
        self.style_wall = style_wall
        style_wall.pack_start(self.style_grid, False, False, 0)
        style_scroll = self.scroll(style_wall)
        style_scroll.set_name('style-scroll')
        self.style_scroll = style_scroll
        style_scroll.connect('size-allocate', lambda *_: self.apply_style_grid_columns())
        style_scroll.get_vadjustment().connect('value-changed', self.style_scroll_changed)
        panel.pack_start(style_scroll, True, True, 0)
        self.styles_stack.add_named(panel, 'browser')

        result = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        result.set_name('styles-results')
        toolbar = Gtk.Box(spacing=12)
        toolbar.set_margin_start(20)
        toolbar.set_margin_end(20)
        toolbar.set_margin_top(20)
        self.style_back_button = self.button('◀ Styles & Moods', self.style_results_back)
        toolbar.pack_start(self.style_back_button, False, False, 0)
        self.style_result_title = Gtk.Label(xalign=0)
        self.style_result_title.set_name('now-title')
        toolbar.pack_start(self.style_result_title, True, True, 0)
        self.style_result_mode_buttons = {}
        for mode, label in (('list', 'List'), ('albums', 'Albums')):
            button = Gtk.Button(label=label)
            button.set_name('style-result-mode')
            button.connect('clicked', self.show_style_result_mode, mode)
            toolbar.pack_end(button, False, False, 0)
            self.style_result_mode_buttons[mode] = button
        result.pack_start(toolbar, False, False, 0)
        self.style_result_status = Gtk.Label(label='', xalign=0)
        self.style_result_status.set_margin_start(20)
        result.pack_start(self.style_result_status, False, False, 0)
        self.style_results_views = Gtk.Stack()
        result.pack_start(self.style_results_views, True, True, 0)
        self.style_song_store = Gtk.ListStore(str, str, str, str)
        self.style_song_view = self.table(self.style_song_store,
                                          ['Song', 'Artist', 'Album', 'Time'])
        self.style_song_view.set_name('style-song-view')
        self.style_song_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.style_song_view.connect('row-activated', self.activate_style_song)
        self.style_song_view.connect('button-press-event', self.style_song_pressed)
        self.style_song_view.enable_model_drag_source(
            Gdk.ModifierType.BUTTON1_MASK, self.song_drag_targets, Gdk.DragAction.COPY)
        self.style_song_view.connect('drag-begin', self.collection_drag_begin, 'style')
        self.style_song_view.connect('drag-end', self.collection_drag_end, 'style')
        self.style_song_view.connect('drag-data-get', self.style_song_drag_data_get)
        for column, field in zip(self.style_song_view.get_columns(),
                                 ('title', 'artist', 'album', 'duration')):
            column.set_clickable(True)
            column.connect('clicked', self.sort_style_songs, field)
        song_scroll = self.scroll(self.style_song_view)
        song_scroll.set_name('style-song-scroll')
        self.style_results_views.add_named(song_scroll, 'list')
        self.style_album_grid = Gtk.FlowBox()
        self.style_album_grid.set_name('album-grid')
        self.style_album_grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.style_album_grid.set_min_children_per_line(1)
        self.style_album_grid.set_max_children_per_line(16)
        self.style_album_grid.set_row_spacing(self.album_spacing)
        self.style_album_grid.set_column_spacing(self.album_spacing)
        self.style_album_grid.set_valign(Gtk.Align.START)
        self.style_album_grid.set_halign(Gtk.Align.CENTER)
        self.style_album_grid.connect('scroll-event', self.zoom_art, 'albums')
        album_wall = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                             margin=self.album_margin)
        self.style_album_wall = album_wall
        album_wall.pack_start(self.style_album_grid, False, False, 0)
        album_scroll = self.scroll(album_wall)
        album_scroll.set_name('library-wall')
        self.style_album_scroll = album_scroll
        album_scroll.connect('scroll-event', self.zoom_art, 'albums')
        album_scroll.connect('size-allocate', lambda *_: self.apply_style_album_columns())
        album_scroll.get_vadjustment().connect('value-changed',
                                                self.style_album_scroll_changed)
        self.style_results_views.add_named(album_scroll, 'albums')
        self.styles_stack.add_named(result, 'results')
        self.styles_stack.set_visible_child_name('browser')
        self.style_result_facet = None
        self.style_result_songs = None
        self.style_result_source = None
        self.style_result_generation = 0
        self.style_result_mode = 'albums'
        self.style_album_filter = None
        self.style_song_sort = ('added_at', True)
        self.style_display_songs = []
        self.style_album_items = []
        self.style_album_offset = 0
        self.style_tile_offset = 0
        self.styles_visible_facets = []
        self.style_render_generation = 0
        self.style_album_render_source = None
        self.style_song_render_source = None
        self.style_queue_generation = 0

    def apply_style_grid_columns(self):
        width = self.style_scroll.get_allocated_width()
        usable = max(0, width - 2 * self.album_margin - 18)
        columns = max(1, min(16, (usable + self.album_spacing) //
                             (224 + self.album_spacing)))
        if columns != getattr(self, '_style_grid_columns', None):
            self._style_grid_columns = columns
            self.style_grid.set_min_children_per_line(columns)
            self.style_grid.set_max_children_per_line(columns)

    def apply_style_album_columns(self):
        width = self.style_album_scroll.get_allocated_width()
        usable = max(0, width - 2 * self.album_margin - 18)
        columns = max(1, min(16, (usable + self.album_spacing) //
                             (self.album_art_size + self.album_spacing)))
        if columns != getattr(self, '_style_album_columns', None):
            self._style_album_columns = columns
            self.style_album_grid.set_min_children_per_line(columns)
            self.style_album_grid.set_max_children_per_line(columns)

    def set_style_mode(self, _button, field):
        self.style_mode = field
        self.render_styles_browser()

    def load_styles_browser(self):
        section = self.library.get_active_id()
        client = self.client
        if client is None or not section:
            self.styles_facets = None
            self.render_styles_browser()
            self.style_status.set_text('Connect to a server to browse styles and moods')
            self.style_status.show()
            return
        source = (client, section)
        if self.styles_source == source and self.styles_facets is not None:
            self.render_styles_browser()
            return
        if self.styles_source == source and self.styles_loading:
            return
        self.styles_source = source
        self.styles_facets = None
        self.render_styles_browser()
        self.styles_loading = True
        self.styles_generation += 1
        generation = self.styles_generation
        self.style_status.set_text('Loading Plex styles and moods…')
        self.style_status.show()
        valid = lambda: (generation == self.styles_generation and
                         self.styles_source == source and self.client is client)
        def work():
            cache = LocalCache(client)
            facets = cache.read_music_facets(section)
            if facets is None:
                facets = client.music_facets(section)
                if valid():
                    try:
                        cache.save_music_facets(section, facets)
                    except OSError:
                        pass
            return facets
        def ready(facets):
            self.styles_loading = False
            self.styles_facets = facets
            self.render_styles_browser()
        def failed():
            self.styles_loading = False
            self.style_status.set_text('Could not load Plex styles and moods')
            self.style_status.show()
        self.async_work(work, ready, valid, failed)

    def render_styles_browser(self):
        if not hasattr(self, 'style_grid'):
            return
        for field, button in self.style_mode_buttons.items():
            context = button.get_style_context()
            (context.add_class if field == self.style_mode else
             context.remove_class)('active')
        facets = self.styles_facets
        query = self.style_search.get_text().strip().casefold()
        render_key = (id(facets), self.style_mode, query)
        if render_key == self.styles_rows_source:
            return
        self.styles_rows_source = render_key
        visible = ([facet for facet in facets if facet.field == self.style_mode and
                    query in facet.title.casefold()] if facets is not None else [])
        self.styles_visible_facets = visible
        self.style_tile_offset = 0
        for child in self.style_grid.get_children():
            child.destroy()
        if facets is None:
            return
        if not facets:
            self.style_status.set_text('Plex returned no styles or moods for this library')
            self.style_status.show()
        elif not visible:
            self.style_status.set_text('No matching styles or moods')
            self.style_status.show()
        else:
            self.style_status.hide()
        self.add_style_tiles()

    def add_style_tiles(self):
        facets = self.styles_visible_facets
        limit = min(len(facets), self.style_tile_offset + 48)
        for facet in facets[self.style_tile_offset:limit]:
            tile = self.make_style_tile(facet)
            self.style_grid.add(tile)
            self.load_style_tile_art(tile, facet)
        self.style_tile_offset = limit
        self.style_grid.show_all()

    def make_style_tile(self, facet):
        tile = Gtk.EventBox()
        tile.set_visible_window(True)
        tile.set_above_child(True)
        tile.set_name('style-facet-card')
        tile.set_size_request(224, 224)
        tile.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        tile.connect('button-press-event', self.style_facet_pressed, facet)
        tile.cover_art = None
        overlay = Gtk.Overlay()
        background = Gtk.DrawingArea()
        background.set_size_request(224, 224)
        background.connect('draw', self.draw_style_tile_art, tile)
        tile.background_area = background
        overlay.add(background)
        banner = Gtk.Box()
        banner.set_name('style-facet-banner')
        banner.set_halign(Gtk.Align.FILL)
        banner.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label=facet.title, xalign=0.5)
        title.set_name('style-facet-title')
        title.set_line_wrap(True)
        title.set_justify(Gtk.Justification.CENTER)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(16)
        title.set_hexpand(True)
        banner.pack_start(title, True, True, 0)
        overlay.add_overlay(banner)
        overlay.set_overlay_pass_through(banner, True)
        tile.add(overlay)
        return tile

    def draw_style_tile_art(self, widget, cr, tile):
        art = tile.cover_art
        if art is None:
            return False
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        cr.save()
        cr.scale(width / art.get_width(), height / art.get_height())
        Gdk.cairo_set_source_pixbuf(cr, art, 0, 0)
        cr.paint()
        cr.restore()
        return False

    def load_style_tile_art(self, tile, facet):
        client = self.client
        section = self.library.get_active_id()
        if client is None or not section:
            return
        source = (client, section)
        def fetch():
            try:
                cache = LocalCache(client)
                cover = cache.read_music_facet_cover(section, facet.cache_key)
                if cover is None:
                    cover = client.music_facet_cover(section, facet)
                    try:
                        cache.save_music_facet_cover(section, facet.cache_key, cover)
                    except OSError:
                        pass
                if not cover:
                    return
                data = cache.read_art(cover, 224)
                if data is None:
                    data = client.get('/photo/:/transcode', width=224, height=224,
                                      minSize=1, upscale=1, url=cover)
                    try:
                        cache.save_art(cover, 224, data)
                    except OSError:
                        pass
            except Exception:
                return  # A missing preview leaves the themed tile background.
            def show():
                if (self.closed or self.client is not client or
                        self.styles_source != source or tile.get_parent() is None):
                    return False
                try:
                    loader = GdkPixbuf.PixbufLoader()
                    loader.write(data)
                    loader.close()
                    tile.cover_art = square_preview(loader.get_pixbuf())
                    tile.get_style_context().add_class('has-art')
                    tile.background_area.queue_draw()
                except (GLib.Error, ValueError):
                    pass
                return False
            GLib.idle_add(show)
        future = self.style_tile_art_workers.submit(fetch)
        self.busy.begin()
        future.add_done_callback(lambda _completed: GLib.idle_add(self.busy.end))

    def style_scroll_changed(self, *_):
        if not getattr(self, '_style_tile_pending', False):
            self._style_tile_pending = True
            GLib.idle_add(self.maybe_more_style_tiles)

    def maybe_more_style_tiles(self):
        self._style_tile_pending = False
        if (self.styles_stack.get_visible_child_name() != 'browser' or
                self.style_tile_offset >= len(self.styles_visible_facets)):
            return False
        adjustment = self.style_scroll.get_vadjustment()
        if adjustment.get_upper() - adjustment.get_value() - adjustment.get_page_size() < 250:
            self.add_style_tiles()
        return False

    def style_facet_pressed(self, widget, event, facet):
        if event.button == 1:
            self.open_style_results(widget, facet, 'albums')
            return True
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        menu.set_name('apistat-context-menu')
        menu.attach_to_widget(widget, None)
        entry = Gtk.MenuItem.new_with_label('Fill play queue')
        entry.connect('activate', lambda *_: self.fill_style_queue(facet))
        menu.append(entry)
        menu.connect('selection-done', lambda selected: selected.destroy())
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def cached_style_songs(self, client, section, facet, valid):
        cache = LocalCache(client)
        songs = cache.read_song_index(section, facet.cache_key)
        if songs is None:
            songs = client.music_facet_tracks(section, facet, valid)
            if songs is not None and valid():
                try:
                    cache.save_song_index(section, songs, facet.cache_key)
                except OSError:
                    pass
        return songs

    def open_style_results(self, _button, facet, mode):
        if not isinstance(facet, MusicFacet) or mode not in ('list', 'albums'):
            return
        section = self.library.get_active_id()
        client = self.client
        if client is None or not section:
            return
        source = (client, section, facet)
        self.style_result_facet = facet
        self.style_album_filter = None
        self.styles_stack.set_visible_child_name('results')
        if source != self.style_result_source:
            self.style_result_source = source
            self.style_result_songs = None
            self.style_result_generation += 1
            self.style_render_generation += 1
            self.style_song_render_source = None
            self.style_album_render_source = None
            self.style_song_store.clear()
            for child in self.style_album_grid.get_children():
                child.destroy()
            self.style_result_status.set_text('Loading songs…')
            self.style_result_loading = True
            generation = self.style_result_generation
            valid = lambda: (generation == self.style_result_generation and
                             self.style_result_source == source and client is self.client)
            def ready(songs):
                self.style_result_loading = False
                self.style_result_songs = songs or []
                self.render_style_results()
            def failed():
                self.style_result_loading = False
                self.style_result_status.set_text('Could not load songs for this category')
            self.async_work(lambda: self.cached_style_songs(client, section, facet, valid),
                            ready, valid, failed)
        self.set_style_result_mode(mode)

    def show_style_result_mode(self, _button, mode):
        self.style_album_filter = None
        self.set_style_result_mode(mode)

    def set_style_result_mode(self, mode):
        self.style_result_mode = mode
        self.style_results_views.set_visible_child_name(mode)
        for name, button in self.style_result_mode_buttons.items():
            context = button.get_style_context()
            (context.add_class if name == mode else context.remove_class)('active')
        self.render_style_results()

    def style_results_back(self, *_):
        if self.style_album_filter is not None:
            self.style_album_filter = None
            self.set_style_result_mode('albums')
        else:
            self.styles_stack.set_visible_child_name('browser')

    def open_style_album(self, album):
        self.style_album_filter = album
        self.set_style_result_mode('list')

    def render_style_results(self):
        facet = self.style_result_facet
        songs = self.style_result_songs
        if facet is None:
            return
        title = f'{facet.title} {"Mood" if facet.field == "mood" else "Style"}'
        self.style_result_title.set_text(
            f'{title} · {self.style_album_filter.title}' if self.style_album_filter else title)
        self.style_back_button.set_label(
            '◀ Albums' if self.style_album_filter else '◀ Styles & Moods')
        if songs is None:
            return
        if self.style_result_mode == 'list':
            self.render_style_song_list()
        else:
            self.render_style_album_grid()

    def render_style_song_list(self):
        album = self.style_album_filter
        source = (self.style_result_source, album.key if album else None,
                  self.style_song_sort)
        if source == self.style_song_render_source:
            self.style_result_status.set_text(f'{len(self.style_display_songs)} songs')
            return
        self.style_song_render_source = source
        self.style_render_generation += 1
        generation = self.style_render_generation
        songs = (song for song in self.style_result_songs
                 if album is None or song.album_key == album.key)
        self.style_display_songs = filter_sort_songs(songs, sort=self.style_song_sort)
        self.style_song_store.clear()
        total = len(self.style_display_songs)
        self.style_result_status.set_text(f'{total} songs')
        offset = 0
        busy = getattr(self, 'busy', None) if total > 150 else None
        if busy is not None:
            busy.begin()
        def finish():
            nonlocal busy
            if busy is not None:
                busy.end()
                busy = None
        def add_rows():
            nonlocal offset
            if generation != self.style_render_generation or self.closed:
                finish()
                return False
            try:
                for song in self.style_display_songs[offset:offset + 150]:
                    self.style_song_store.append([
                        self.song_column_value(song, field)
                        for field in ('title', 'artist', 'album', 'duration')])
            except Exception:
                finish()
                raise
            offset += 150
            if offset < total:
                return True
            finish()
            return False
        if total > 150:
            GLib.idle_add(add_rows)
        else:
            add_rows()

    def sort_style_songs(self, _column, field):
        old = self.style_song_sort
        self.style_song_sort = (field, not old[1]) if old and old[0] == field else (field, False)
        for column, column_field in zip(self.style_song_view.get_columns(),
                                        ('title', 'artist', 'album', 'duration')):
            active = column_field == field
            column.set_sort_indicator(active)
            if active:
                column.set_sort_order(Gtk.SortType.DESCENDING if self.style_song_sort[1]
                                      else Gtk.SortType.ASCENDING)
        self.render_style_song_list()

    def activate_style_song(self, _view, path, _column):
        self.play_style_song(path.get_indices()[0])

    def play_style_song(self, index):
        if not 0 <= index < len(self.style_display_songs):
            return
        Player.clear_remote_queue(self)
        self.queue_album = None
        self.queue = list(self.style_display_songs)
        self.queue_client = self.client
        self.index = index
        self.start_track()

    def style_song_pressed(self, view, event):
        if event.button == 1:
            self.style_drag_candidates = Player.track_drag_candidates(
                view, event, self.style_display_songs)
            return False
        if event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        index = hit[0].get_indices()[0]
        if not 0 <= index < len(self.style_display_songs):
            return False
        view.get_selection().select_path(hit[0])
        self.show_song_context_menu(event, self.style_display_songs[index], index,
                                    lambda: self.play_style_song(index))
        return True

    def style_song_drag_data_get(self, view, _context, selection, _info, _time):
        tracks = getattr(self, 'style_drag_tracks', None)
        if tracks is None:
            tracks = [self.style_display_songs[index] for index in
                      Player.selected_track_indices(view, self.style_display_songs)]
        data = encode_track_keys([track.key for track in tracks])
        if data:
            selection.set(selection.get_target(), 8, data)

    def render_style_album_grid(self):
        source = (self.style_result_source, self.album_sort)
        if source == self.style_album_render_source:
            self.style_result_status.set_text(
                f'{len(self.style_album_items)} albums · {len(self.style_result_songs)} songs')
            return
        self.style_album_render_source = source
        albums = PlexClient.albums_from_tracks(self.style_result_songs)
        self.style_album_items = sort_albums(albums, self.album_sort)
        self.style_album_offset = 0
        for child in self.style_album_grid.get_children():
            child.destroy()
        self.style_result_status.set_text(
            f'{len(self.style_album_items)} albums · {len(self.style_result_songs)} songs')
        self.add_style_albums()

    def add_style_albums(self):
        end = min(len(self.style_album_items), self.style_album_offset + 40)
        for album in self.style_album_items[self.style_album_offset:end]:
            self.add_album_tile(album, grid=self.style_album_grid,
                                on_album=self.open_style_album)
        self.style_album_offset = end

    def style_album_scroll_changed(self, *_):
        if not getattr(self, '_style_album_pending', False):
            self._style_album_pending = True
            GLib.idle_add(self.maybe_more_style_albums)

    def maybe_more_style_albums(self):
        self._style_album_pending = False
        if (self.styles_stack.get_visible_child_name() != 'results' or
                self.style_result_mode != 'albums' or
                self.style_album_offset >= len(self.style_album_items)):
            return False
        adjustment = self.style_album_scroll.get_vadjustment()
        if adjustment.get_upper() - adjustment.get_value() - adjustment.get_page_size() < 250:
            self.add_style_albums()
        return False

    def fill_style_queue(self, facet):
        section = self.library.get_active_id()
        client = self.client
        if not isinstance(facet, MusicFacet) or client is None or not section:
            return
        self.style_queue_generation += 1
        generation = self.style_queue_generation
        play_generation = self.play_generation
        excluded = {song.key for song in self.play_history}
        if ((self.stream_open or self.remote_opening) and
                0 <= self.index < len(self.queue)):
            excluded.add(self.queue[self.index].key)
        valid = lambda: (generation == self.style_queue_generation and
                         play_generation == self.play_generation and
                         client is self.client and section == self.library.get_active_id())
        def ready(songs):
            if not songs:
                self.status.set_text('Plex found no songs in this category')
                return
            Player.clear_remote_queue(self)
            active = bool((self.stream_open or self.remote_opening) and
                          0 <= self.index < len(self.queue))
            if active:
                current = self.queue[self.index]
                upcoming = [song for song in songs if song.key != current.key]
                self.queue = self.queue[:self.index + 1] + upcoming
                count = len(upcoming)
                self.queue_client = client
                self.queue_album = None
                self.pulse_queue_icon()
                self.refresh_queue_view()
                self.mpris.changed()
                self.persist_session(force=True)
            else:
                self.queue = list(songs)
                count = len(songs)
                self.index = 0
                self.queue_client = client
                self.queue_album = None
                self.pulse_queue_icon()
                self.start_track()
            self.status.set_text(
                f'Filled play queue with {count} random songs from {facet.title}')
        self.async_work(lambda: client.music_facet_random_tracks(
                            section, facet, 25, excluded),
                        ready, valid,
                        lambda: self.status.set_text('Could not fill play queue'))

    def build_lyrics_view(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=20)
        panel.set_name('lyrics-panel')
        panel.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.set_name('lyrics-title-bar')
        self.lyrics_track_label = Gtk.Label(label='Lyrics', xalign=0)
        self.lyrics_track_label.set_name('now-title')
        self.lyrics_track_label.set_ellipsize(Pango.EllipsizeMode.END)
        bar.pack_start(self.lyrics_track_label, True, True, 0)
        refresh = self.icon_button('view-refresh-symbolic', 'Refresh lyrics',
                                   lambda *_: self.load_current_lyrics(force=True))
        bar.pack_end(refresh, False, False, 0)
        zoom_in = self.icon_button('zoom-in-symbolic', 'Zoom in',
                                   lambda *_: self.change_lyrics_zoom(1))
        zoom_out = self.icon_button('zoom-out-symbolic', 'Zoom out',
                                    lambda *_: self.change_lyrics_zoom(-1))
        bar.pack_end(zoom_in, False, False, 0)
        bar.pack_end(zoom_out, False, False, 0)
        panel.pack_start(bar, False, False, 0)
        self.lyrics_status = Gtk.Label(label='Play a song to look up lyrics.', xalign=0.5)
        self.lyrics_status.set_name('lyrics-details')
        self.lyrics_status.set_line_wrap(True)
        self.lyrics_source = Gtk.Label(
            label='Track details are sent to LRCLIB and, if needed, lyrics.ovh', xalign=0.5)
        self.lyrics_source.set_name('lyrics-details')
        self.lyrics_source.set_line_wrap(True)
        self.lyrics_details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.lyrics_details.pack_start(self.lyrics_status, False, False, 0)
        self.lyrics_details.pack_start(self.lyrics_source, False, False, 0)
        panel.pack_end(self.lyrics_details, False, False, 0)
        self.lyrics_text = Gtk.TextView()
        self.lyrics_text.set_name('lyrics-view')
        self.lyrics_text.set_editable(False)
        self.lyrics_text.set_cursor_visible(False)
        self.lyrics_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.lyrics_text.set_justification(Gtk.Justification.CENTER)
        self.lyrics_zoom = 1.0
        self.lyrics_zoom_remainder = 0.0
        self.lyrics_zoom_provider = Gtk.CssProvider()
        self.lyrics_text.get_style_context().add_provider(
            self.lyrics_zoom_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.apply_lyrics_zoom()
        self.lyrics_text.connect('scroll-event', self.lyrics_zoom_scroll)
        panel.connect('scroll-event', self.lyrics_zoom_scroll)
        self.lyrics_text.connect('key-press-event', self.global_key_pressed)
        self.lyrics_text.connect('key-release-event', self.global_key_released)
        self.lyrics_buffer = self.lyrics_text.get_buffer()
        self.lyrics_highlight = self.lyrics_buffer.create_tag('current-lyric', weight=Pango.Weight.BOLD)
        self.lyrics_highlight.set_property('foreground', self.accent_color)
        lyrics_scroll = self.scroll(self.lyrics_text)
        lyrics_scroll.set_name('lyrics-scroll')
        lyrics_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        lyrics_scroll.connect('scroll-event', self.lyrics_zoom_scroll)
        self.lyrics_content = Gtk.Stack()
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        message_box.set_halign(Gtk.Align.CENTER)
        message_box.set_valign(Gtk.Align.CENTER)
        self.lyrics_message = Gtk.Label()
        self.lyrics_message.set_line_wrap(True)
        self.lyrics_message.set_justify(Gtk.Justification.CENTER)
        message_box.pack_start(self.lyrics_message, False, False, 0)
        self.lyrics_google = Gtk.Button(label='Search Google for lyrics')
        self.lyrics_google.set_halign(Gtk.Align.CENTER)
        self.lyrics_google.set_no_show_all(True)
        self.lyrics_google.connect('clicked', self.google_current_lyrics)
        message_box.pack_start(self.lyrics_google, False, False, 0)
        self.lyrics_content.add_named(message_box, 'message')
        self.lyrics_content.add_named(lyrics_scroll, 'lyrics')
        self.lyrics_content.set_visible_child_name('message')
        self.lyrics_message.set_text('Play a song to look up lyrics.')
        self.lyrics_content.connect('size-allocate', self.lyrics_panel_allocated, lyrics_scroll)
        body = LyricsColumns(orientation=Gtk.Orientation.HORIZONTAL, spacing=56)
        self.lyrics_track_info = LyricsTrackInfo(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.lyrics_track_info.set_no_show_all(True)
        self.lyrics_cover = Gtk.DrawingArea()
        self.lyrics_cover.connect('draw', self.draw_now_cover)
        self.lyrics_cover.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.lyrics_cover.connect('scroll-event', self.lyrics_zoom_scroll)
        self.set_placeholder_art(self.lyrics_cover, NOW_SIZE_RANGE[1], SMALL_PLACEHOLDER_LOGO_RATIO)
        self.lyrics_track_info.pack_start(self.lyrics_cover, False, False, 0)
        self.lyrics_song_title = Gtk.Label(xalign=0.5)
        self.lyrics_song_title.set_name('lyrics-song-title')
        self.lyrics_artist = Gtk.Label(xalign=0.5)
        self.lyrics_artist.set_name('lyrics-artist')
        for label, tooltip, callback in (
                (self.lyrics_song_title, 'Show song in library', self.show_lyrics_song),
                (self.lyrics_artist, 'Show artist albums', self.show_current_artist_albums)):
            label.set_line_wrap(True)
            label.set_lines(2)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_max_width_chars(30)
            label.set_justify(Gtk.Justification.CENTER)
            button = Gtk.Button()
            button.set_name('lyrics-song-link')
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.add(label)
            self.set_tooltip(button, tooltip)
            button.get_accessible().set_name(tooltip)
            button.connect('clicked', callback)
            button.connect('scroll-event', self.lyrics_zoom_scroll)
            self.lyrics_track_info.pack_start(button, False, False, 0)
        self.lyrics_album = Gtk.Label(xalign=0.5)
        self.lyrics_album.set_line_wrap(True)
        self.lyrics_album.set_lines(2)
        self.lyrics_album.set_ellipsize(Pango.EllipsizeMode.END)
        self.lyrics_album.set_max_width_chars(30)
        self.lyrics_album.set_justify(Gtk.Justification.CENTER)
        self.lyrics_track_info.pack_start(self.lyrics_album, False, False, 0)
        body.pack_start(self.lyrics_track_info, False, False, 0)
        body.pack_start(self.lyrics_content, True, True, 0)
        centered = CenteredLyricsGroup()
        self.lyrics_group = centered
        centered.add(body)
        panel.pack_start(centered, True, True, 0)
        self.content_views.add_named(panel, 'lyrics')
        self.lyrics_cache = OrderedDict()
        self.lyrics_client = LyricsClient()
        self.lyrics_request_key = None
        self.lyrics_generation = 0
        self.lyrics_lines = ()
        self.lyrics_offsets = []
        self.lyrics_current_line = -1
        self.lyrics_art_key = None

    def update_lyrics_track_info(self, track=None):
        if track is None:
            self.lyrics_track_info.hide()
            self.lyrics_art_key = None
            return
        self.lyrics_song_title.set_text(track.title)
        self.lyrics_artist.set_text(track.artist)
        self.lyrics_album.set_text(track.album or '')
        self.lyrics_track_info.set_no_show_all(False)
        self.lyrics_track_info.show_all()
        self.lyrics_track_info.set_no_show_all(True)
        client = self.queue_client
        album = self.queue_album if self.queue_album and self.queue_album.thumb else track
        art_key = (client, album.thumb) if album.thumb else None
        if art_key == self.lyrics_art_key and art_key is not None:
            return
        self.lyrics_art_key = art_key
        self.set_placeholder_art(self.lyrics_cover, NOW_SIZE_RANGE[1], SMALL_PLACEHOLDER_LOGO_RATIO)
        if art_key:
            valid = lambda: (not self.closed and self.lyrics_art_key == art_key)
            self.load_art(client, album, self.lyrics_cover, NOW_SIZE_RANGE[1], valid)

    def show_lyrics_song(self, *_):
        if not self.client or not 0 <= self.index < len(self.queue):
            return
        title = self.queue[self.index].title
        self.show_full_music_library()
        self.library_search.set_text(title)

    def lyrics_view_scroll(self, widget, event):
        if widget.get_visible_child_name() != 'lyrics':
            return False
        return self.lyrics_zoom_scroll(widget, event)

    def apply_lyrics_zoom(self):
        self.lyrics_zoom_provider.load_from_data(
            f'#lyrics-view {{ font-size: {round(self.text_size * self.lyrics_zoom)}px; }}'.encode())
        if hasattr(self, 'lyrics_group'):
            self.update_lyrics_width()

    def update_lyrics_width(self):
        layout = self.lyrics_text.create_pango_layout('')
        font = layout.get_context().get_font_description().copy()
        font.set_absolute_size(round(self.text_size * self.lyrics_zoom) * Pango.SCALE)
        layout.set_font_description(font)
        longest = 0
        for line in getattr(self, 'lyrics_measure_lines', ())[:2000]:
            layout.set_text(line[:500], -1)
            longest = max(longest, layout.get_pixel_size()[0])
            if longest >= 1000:
                break
        self.lyrics_group.set_target_width(longest + 48 + 440 + 28)

    def change_lyrics_zoom(self, steps):
        self.lyrics_zoom = max(0.5, min(3.0, round(self.lyrics_zoom + steps * 0.1, 2)))
        self.apply_lyrics_zoom()

    def lyrics_zoom_scroll(self, _widget, event):
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        if event.direction == Gdk.ScrollDirection.UP:
            steps = 1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            steps = -1
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            success, _dx, dy = event.get_scroll_deltas()
            if not success:
                return True
            self.lyrics_zoom_remainder -= dy
            steps = int(self.lyrics_zoom_remainder)
            self.lyrics_zoom_remainder -= steps
        else:
            return True
        if steps:
            self.change_lyrics_zoom(steps)
        return True

    def set_lyrics_message(self, message, search=False):
        self.lyrics_message.set_text(message)
        self.lyrics_google.set_visible(search)
        self.lyrics_content.set_visible_child_name('message')

    def google_current_lyrics(self, *_):
        if not 0 <= self.index < len(self.queue):
            return
        track = self.queue[self.index]
        query = ' '.join(part for part in (track.artist, track.title, 'lyrics') if part)
        url = 'https://www.google.com/search?' + urlencode({'q': query})
        try:
            Gtk.show_uri_on_window(self, url, Gdk.CURRENT_TIME)
        except GLib.Error:
            self.lyrics_status.set_text('Could not open the web browser.')

    @staticmethod
    def lyrics_panel_allocated(_panel, allocation, scroll):
        scroll._lyrics_desired_margin = max(0, (allocation.width - 1000) // 2)
        if (scroll.get_margin_start() != scroll._lyrics_desired_margin and
                not getattr(scroll, '_lyrics_margin_pending', False)):
            scroll._lyrics_margin_pending = True
            def apply_margin():
                scroll._lyrics_margin_pending = False
                margin = scroll._lyrics_desired_margin
                scroll.set_margin_start(margin)
                scroll.set_margin_end(margin)
                return False
            GLib.idle_add(apply_margin)

    def load_current_lyrics(self, force=False):
        if not 0 <= self.index < len(self.queue) or getattr(self, 'queue_client', None) is None:
            self.lyrics_generation += 1
            self.lyrics_request_key = None
            self.lyrics_track_label.set_text('Lyrics')
            self.update_lyrics_track_info()
            self.lyrics_status.set_text('')
            self.lyrics_source.set_text(
                'Track details are sent to LRCLIB and, if needed, lyrics.ovh')
            self.set_lyrics_message('Play a song to look up lyrics.')
            self.lyrics_buffer.set_text('')
            self.lyrics_lines = ()
            if hasattr(self, 'lyrics_group'):
                self.lyrics_measure_lines = ()
                self.update_lyrics_width()
            return
        track = self.queue[self.index]
        key = (self.queue_client.address, track.key, track.title, track.artist,
               track.album, track.duration)
        if key == self.lyrics_request_key and not force:
            return
        self.lyrics_generation += 1
        generation = self.lyrics_generation
        self.lyrics_request_key = key
        self.lyrics_track_label.set_text('Lyrics')
        self.update_lyrics_track_info(track)
        self.lyrics_source.set_text(
            'Track details are sent to LRCLIB and, if needed, lyrics.ovh')
        self.lyrics_buffer.set_text('')
        self.lyrics_lines = ()
        self.lyrics_current_line = -1
        if hasattr(self, 'lyrics_group'):
            self.lyrics_measure_lines = ()
            self.update_lyrics_width()
        if force:
            self.lyrics_cache.pop(key, None)
        if key in self.lyrics_cache:
            self.show_lyrics_result(self.lyrics_cache[key])
            return
        if not track.title.strip() or not track.artist.strip():
            self.lyrics_status.set_text('')
            self.set_lyrics_message('A song title and artist are needed to look up lyrics.', search=True)
            return
        self.lyrics_status.set_text('')
        self.set_lyrics_message('Looking up lyrics…')
        def lookup():
            try:
                return self.lyrics_client.lookup(track.title, track.artist, track.album,
                                                 track.duration, valid), None
            except Exception as error:
                return None, lyrics_error_message(error)
        def ready(response):
            result, error = response
            if error:
                self.lyrics_request_key = None
                self.lyrics_status.set_text('')
                self.set_lyrics_message(error, search=True)
                return
            if result is None:
                self.lyrics_request_key = None
            else:
                self.lyrics_cache[key] = result
                while len(self.lyrics_cache) > 32:
                    self.lyrics_cache.popitem(last=False)
            self.show_lyrics_result(result)
        def failed():
            self.lyrics_request_key = None
            self.lyrics_status.set_text('')
            self.set_lyrics_message('The lyrics lookup failed unexpectedly. Try refreshing later.', search=True)
        valid = lambda: not self.closed and generation == self.lyrics_generation
        self.async_work(lookup, ready, valid, failed)

    def show_lyrics_result(self, result):
        self.lyrics_current_line = -1
        self.lyrics_lines = result.lines if result else ()
        self.lyrics_offsets = []
        offset = 0
        for _timestamp, line in self.lyrics_lines:
            self.lyrics_offsets.append((offset, offset + len(line)))
            offset += len(line) + 1
        self.lyrics_buffer.set_text(result.text if result else '')
        if hasattr(self, 'lyrics_group'):
            self.lyrics_measure_lines = result.text.splitlines() if result else ()
            self.update_lyrics_width()
        if result is None:
            self.lyrics_status.set_text('')
            self.set_lyrics_message('No lyrics found on LRCLIB or lyrics.ovh.', search=True)
        elif result.instrumental:
            self.lyrics_source.set_text(f'Lyrics from {result.source}')
            self.lyrics_status.set_text('')
            self.set_lyrics_message('This track is marked instrumental.', search=True)
        else:
            self.lyrics_source.set_text(f'Lyrics from {result.source}')
            self.lyrics_content.set_visible_child_name('lyrics')
            self.lyrics_status.set_text('Synced lyrics' if result.lines else 'Lyrics')
            self.update_lyrics_position(self.seek.get_value())

    def update_lyrics_position(self, seconds):
        if not self.lyrics_lines:
            return
        index = bisect.bisect_right(self.lyrics_lines, seconds, key=lambda line: line[0]) - 1
        if index == self.lyrics_current_line:
            return
        if self.lyrics_current_line >= 0:
            start, end = self.lyrics_offsets[self.lyrics_current_line]
            self.lyrics_buffer.remove_tag(self.lyrics_highlight,
                                          self.lyrics_buffer.get_iter_at_offset(start),
                                          self.lyrics_buffer.get_iter_at_offset(end))
        self.lyrics_current_line = index
        if index >= 0:
            start, end = self.lyrics_offsets[index]
            first = self.lyrics_buffer.get_iter_at_offset(start)
            last = self.lyrics_buffer.get_iter_at_offset(end)
            self.lyrics_buffer.apply_tag(self.lyrics_highlight, first, last)
            self.lyrics_text.scroll_to_iter(first, 0.2, True, 0.5, 0.4)

    def build_queue_view(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.set_name('queue-panel')
        heading = Gtk.Label(label='Play queue', xalign=0)
        heading.set_name('now-title')
        heading.set_margin_start(20)
        heading.set_margin_top(18)
        panel.pack_start(heading, False, False, 0)
        self.queue_count = Gtk.Label(label='No tracks queued', xalign=0)
        self.queue_count.set_margin_start(20)
        panel.pack_start(self.queue_count, False, False, 0)
        self.queue_history_button = Gtk.Button(label='Show more previous tracks')
        self.queue_history_button.set_name('queue-history-more')
        self.queue_history_button.set_relief(Gtk.ReliefStyle.NONE)
        self.queue_history_button.set_halign(Gtk.Align.CENTER)
        self.queue_history_button.set_no_show_all(True)
        self.queue_history_button.connect('clicked', self.show_more_previous_tracks)
        panel.pack_start(self.queue_history_button, False, False, 0)
        self.queue_store = Gtk.ListStore(int, str, str, str, str, str, str, str, str,
                                         bool, str, str)
        self.queue_view = Gtk.TreeView(model=self.queue_store)
        self.queue_view.set_name('queue-view')
        self.queue_view.set_headers_visible(True)
        self.queue_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.queue_view.get_selection().set_select_function(self.queue_row_selectable)
        columns = (('#', 1, 55), ('Track', 2, 260), ('Artist', 3, 180),
                   ('Album', 4, 210), ('Time', 5, 75), ('Rating', 11, 125), ('Year', 6, 70),
                   ('Genre', 7, 150), ('Added', 8, 105))
        for label, column_index, width in columns:
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(label, renderer, text=column_index)
            column.add_attribute(renderer, 'foreground-set', 9)
            column.add_attribute(renderer, 'foreground', 10)
            if label == '#':
                column.set_cell_data_func(renderer, self.queue_marker_cell)
            column.set_expand(label == 'Track')
            column.set_resizable(True)
            column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            column.set_fixed_width(width)
            self.queue_view.append_column(column)
            if label == 'Rating':
                self.queue_rating_column = column
        self.queue_view.connect('row-activated', self.activate_queue_track)
        self.queue_view.connect('button-press-event', self.queue_song_pressed)
        self.queue_view.add_events(Gdk.EventMask.POINTER_MOTION_MASK |
                                   Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.queue_view.connect('motion-notify-event', self.queue_pointer_motion)
        self.queue_view.connect('button-release-event', self.queue_pointer_release)
        self.queue_view.connect('key-press-event', self.queue_key_pressed)
        queue_scroll = self.scroll(self.queue_view)
        queue_scroll.set_name('queue-scroll')
        queue_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        queue_scroll.set_margin_start(16)
        queue_scroll.set_margin_end(16)
        queue_scroll.set_margin_bottom(16)
        panel.pack_start(queue_scroll, True, True, 0)
        self.keep_style_playing = Gtk.CheckButton(
            label='Keep playing songs in the same style')
        self.keep_style_playing.set_halign(Gtk.Align.CENTER)
        self.keep_style_playing.set_margin_bottom(16)
        self.keep_style_playing.set_active(self.keep_style_playing_enabled)
        self.keep_style_playing.connect('toggled', self.keep_style_playing_changed)
        panel.pack_end(self.keep_style_playing, False, False, 0)
        self.content_views.add_named(panel, 'queue')

    def keep_style_playing_changed(self, button):
        self.keep_style_playing_enabled = button.get_active()
        if not self.keep_style_playing_enabled:
            self.auto_style_facet = None
            self.auto_style_keys.clear()
            waiting = self.style_autoplay_waiting
            self.style_autoplay_generation += 1
            self.style_autoplay_pending = False
            self.style_autoplay_waiting = False
            self.style_autoplay_exhausted = False
            if waiting:
                self.stop()
        else:
            self.maybe_prefetch_same_style()
        try:
            save_keep_style_playing_enabled(self.keep_style_playing_enabled)
        except OSError:
            self.status.set_text('Could not save the queue option')

    @staticmethod
    def cancel_queue_render(player):
        source = getattr(player, 'queue_render_source', 0)
        if source:
            GLib.source_remove(source)
            player.queue_render_source = 0
        if getattr(player, 'queue_render_busy', False):
            player.queue_render_busy = False
            player.busy.end()
        player.queue_render_generation = getattr(player, 'queue_render_generation', 0) + 1

    def refresh_queue_view(self):
        Player.update_skip_buttons(self)
        prefetch = getattr(self, 'prefetch_next_track', None)
        if prefetch is not None:
            prefetch()
        Player.cancel_queue_render(self)
        if (not hasattr(self, 'queue_store') or
                self.content_views.get_visible_child_name() != 'queue'):
            return
        self.queue_store.clear()
        history_color = '#7a7a7a' if self.theme == 'dark' else (
            '#666666' if self.theme == 'black' else '#777b80')
        normal_color = '#202326' if self.theme == 'light' else '#eeeeee'
        history = list(self.play_history)
        visible = getattr(self, 'queue_history_visible', 5)
        queue = tuple(self.queue)
        first = max(0, self.index)
        current_index = self.index
        history_start = max(0, len(history) - visible)
        total_rows = len(history) - history_start + max(0, len(queue) - first)
        generation = self.queue_render_generation
        def rows():
            for history_index in range(history_start, len(history)):
                track = history[history_index]
                added = time.strftime('%Y-%m-%d', time.localtime(track.added_at)) if track.added_at else ''
                yield [-history_index - 1, '↶', track.title, track.artist,
                       track.album, clock(track.duration / 1000) if track.duration else '',
                       str(track.year), track.genre, added, True, history_color,
                       star_text(track.user_rating)]
            for index in range(first, len(queue)):
                track = queue[index]
                marker = (Player.current_track_marker(self, track.key)
                          if index == current_index else '') or str(index - first + 1)
                added = time.strftime('%Y-%m-%d', time.localtime(track.added_at)) if track.added_at else ''
                yield [index, marker, track.title, track.artist,
                       track.album, clock(track.duration / 1000) if track.duration else '',
                       str(track.year), track.genre, added, False, normal_color,
                       star_text(track.user_rating)]
        pending = iter(rows())
        def append_batch():
            if (getattr(self, 'closed', False) or generation != self.queue_render_generation or
                    self.content_views.get_visible_child_name() != 'queue'):
                if generation == self.queue_render_generation:
                    self.queue_render_source = 0
                    if getattr(self, 'queue_render_busy', False):
                        self.queue_render_busy = False
                        self.busy.end()
                return False
            deadline = time.monotonic() + .006
            for count in range(128 if total_rows <= 128 else 96):
                try:
                    self.queue_store.append(next(pending))
                except StopIteration:
                    self.queue_render_source = 0
                    if getattr(self, 'queue_render_busy', False):
                        self.queue_render_busy = False
                        self.busy.end()
                    return False
                if total_rows > 128 and time.monotonic() >= deadline:
                    break
            return True
        remaining = max(0, len(queue) - max(0, self.index + 1))
        self.queue_count.set_text(
            f'{len(self.play_history)} previously played · {remaining} upcoming · Drag tracks to rearrange'
            if queue or history else 'No tracks queued')
        button = getattr(self, 'queue_history_button', None)
        if button is not None:
            button.set_visible(len(history) > visible)
        if append_batch():
            busy = getattr(self, 'busy', None)
            if busy is not None:
                busy.begin()
                self.queue_render_busy = True
            self.queue_render_source = GLib.idle_add(append_batch)

    def show_more_previous_tracks(self, _button):
        self.queue_history_visible = min(len(self.play_history),
                                         self.queue_history_visible + QUEUE_HISTORY_PAGE)
        Player.refresh_queue_view(self)

    def activate_queue_track(self, _view, path, _column):
        index = self.queue_store[path][0]
        if index < 0:
            self.play_history_track(-index - 1)
        else:
            self.play_queue_track(index)

    def play_history_track(self, history_index):
        history = list(self.play_history)
        if not 0 <= history_index < len(history):
            return
        if not self.queue or not (self.stream_open or self.remote_opening):
            self.enqueue_tracks([history[history_index]], play_next=True)
            return
        self.enqueue_tracks([history[history_index]], play_next=True)
        self.index += 1
        self.start_track()

    def play_queue_track(self, index):
        if 0 <= index < len(self.queue):
            self.index = index
            self.start_track()

    def queue_song_pressed(self, view, event):
        if event.button == 1:
            hit = view.get_path_at_pos(int(event.x), int(event.y))
            if hit and hit[1] is not None and hit[1].get_title() == 'Rating':
                queue_index = self.queue_store[hit[0]][0]
                if queue_index < 0:
                    history = list(self.play_history)
                    song = history[-queue_index - 1] if -queue_index - 1 < len(history) else None
                else:
                    song = self.queue[queue_index] if queue_index < len(self.queue) else None
                if song:
                    self.set_song_rating(song, stars_from_click(hit[2], song.user_rating))
                    return True
            selected = view.get_selection()
            modifiers = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK
            row_index = self.queue_store[hit[0]][0] if hit else None
            selected_indices = (self.selected_queue_drag_indices()
                                if hit and selected.path_is_selected(hit[0]) else [])
            self.queue_pointer_drag = (
                {'indices': selected_indices or [row_index],
                 'x': event.x, 'y': event.y, 'active': False}
                if row_index is not None and not (event.state & modifiers) else None)
            return False
        if event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        path = hit[0]
        index = self.queue_store[path][0]
        if index < 0:
            history_index = -index - 1
            history = list(self.play_history)
            if history_index < len(history):
                track = history[history_index]
                self.show_song_context_menu(event, track, None,
                                            lambda: self.play_history_track(history_index))
                return True
            return False
        if not 0 <= index < len(self.queue):
            return False
        selection = view.get_selection()
        if not selection.path_is_selected(path):
            selection.unselect_all()
            selection.select_path(path)
        self.show_song_context_menu(event, self.queue[index], index,
                                    lambda: self.play_queue_track(index))
        return True

    def selected_queue_indices(self):
        model, paths = self.queue_view.get_selection().get_selected_rows()
        return [model[path][0] for path in paths if model[path][0] >= 0]

    def selected_queue_drag_indices(self):
        model, paths = self.queue_view.get_selection().get_selected_rows()
        return [model[path][0] for path in paths]

    @staticmethod
    def song_drag_description(tracks, indices):
        if not indices:
            return ''
        title = tracks[indices[0]].title
        return title if len(indices) == 1 else f'{title}  +{len(indices) - 1}'

    def show_song_drag_ghost(self, view, event, tracks, indices):
        image = getattr(self, 'song_drag_row_ghost', None)
        if image is not None and image.get_visible():
            ghost = image
        else:
            ghost = self.song_drag_ghost
            ghost.set_text(self.song_drag_description(tracks, indices))
            ghost.set_no_show_all(False)
            ghost.show_all()
        translated = view.translate_coordinates(self.song_drag_overlay,
                                                int(event.x), int(event.y))
        if translated:
            x, y = translated[-2:]
            self.song_drag_overlay.move(ghost, x + 12, y + 12)

    def prepare_song_drag_ghost(self, view, drag):
        image = getattr(self, 'song_drag_row_ghost', None)
        if image is None or not isinstance(view, Gtk.TreeView):
            return
        hit = view.get_path_at_pos(int(drag['x']), int(drag['y']))
        surface = view.create_row_drag_icon(hit[0]) if hit else None
        if surface is not None:
            self.song_drag_ghost.hide()
            image.set_from_surface(normalize_surface_origin(surface))
            image.set_no_show_all(False)
            image.show()

    def hide_song_drag_ghost(self):
        self.song_drag_ghost.hide()
        self.song_drag_ghost.set_no_show_all(True)
        image = getattr(self, 'song_drag_row_ghost', None)
        if image is not None:
            image.hide()
            image.set_no_show_all(True)
            image.clear()

    def show_song_drop_line(self, view, boundary_y):
        bin_window = view.get_bin_window()
        overlay_window = self.song_drag_overlay.get_window()
        if bin_window is None or overlay_window is None:
            return
        bin_x, bin_y = bin_window.get_origin()[-2:]
        overlay_x, overlay_y = overlay_window.get_origin()[-2:]
        self.song_drop_line.set_size_request(max(1, view.get_allocated_width()), 4)
        self.song_drag_overlay.move(self.song_drop_line, bin_x - overlay_x,
                                    bin_y - overlay_y + round(boundary_y) - 2)
        self.song_drop_line.set_no_show_all(False)
        self.song_drop_line.show()

    def hide_song_drop_line(self):
        self.song_drop_line.hide()

    @staticmethod
    def queue_row_selectable(_selection, model, path, _selected):
        return True

    def queue_pointer_destination(self, view, x, y, show_marker=False):
        hit = view.get_path_at_pos(int(x), int(y))
        if hit:
            path = hit[0]
            row_index = self.queue_store[path][0]
            if row_index < 0:
                first_queue_row = min(len(self.play_history),
                                      getattr(self, 'queue_history_visible', 5))
                if show_marker and first_queue_row < len(self.queue_store):
                    path = Gtk.TreePath.new_from_indices([first_queue_row])
                    view.set_drag_dest_row(path, Gtk.TreeViewDropPosition.BEFORE)
                    area = view.get_background_area(path, None)
                    self.show_song_drop_line(view, area.y)
                elif show_marker and len(self.queue_store):
                    path = Gtk.TreePath.new_from_indices([len(self.queue_store) - 1])
                    view.set_drag_dest_row(path, Gtk.TreeViewDropPosition.AFTER)
                    area = view.get_background_area(path, None)
                    self.show_song_drop_line(view, area.y + area.height)
                return max(0, self.index + 1)
            area = view.get_background_area(path, None)
            after = y >= area.y + area.height / 2
            if show_marker:
                view.set_drag_dest_row(path, Gtk.TreeViewDropPosition.AFTER if after
                                       else Gtk.TreeViewDropPosition.BEFORE)
                self.show_song_drop_line(view, area.y + (area.height if after else 0))
            return row_index + int(after)
        if show_marker and len(self.queue_store):
            path = Gtk.TreePath.new_from_indices([len(self.queue_store) - 1])
            view.set_drag_dest_row(path, Gtk.TreeViewDropPosition.AFTER)
            area = view.get_background_area(path, None)
            self.show_song_drop_line(view, area.y + area.height)
        return len(self.queue)

    def queue_pointer_motion(self, view, event):
        drag = getattr(self, 'queue_pointer_drag', None)
        if not drag or not (event.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        if not drag['active']:
            if abs(event.x - drag['x']) < 5 and abs(event.y - drag['y']) < 5:
                return False
            drag['active'] = True
            Player.prepare_song_drag_ghost(self, view, drag)
            if hasattr(view, 'get_selection') and hasattr(self, 'queue_store'):
                selected = set(drag['indices'])
                rows = [row for row in range(len(self.queue_store))
                        if self.queue_store[row][0] in selected]
                Player.restore_drag_selection(view, rows)
        history = list(getattr(self, 'play_history', ()))
        tracks = [self.queue[index] if index >= 0 else history[-index - 1]
                  for index in drag['indices']]
        self.show_song_drag_ghost(view, event, tracks, list(range(len(tracks))))
        if Player.update_playlist_drop_target(self, event):
            self.hide_song_drop_line()
            view.set_drag_dest_row(None, Gtk.TreeViewDropPosition.BEFORE)
        else:
            self.queue_pointer_destination(view, event.x, event.y, show_marker=True)
        return True

    def queue_pointer_release(self, view, event):
        if event.button != 1:
            return False
        drag = getattr(self, 'queue_pointer_drag', None)
        self.queue_pointer_drag = None
        self.hide_song_drag_ghost()
        self.hide_song_drop_line()
        Player.set_playlist_drop_target(self, None)
        if not drag or not drag['active']:
            return False
        if hasattr(self, 'playlist_list'):
            position = self.pointer_position_in(self.playlist_list, event)
            if position is not None:
                row = self.playlist_list.get_row_at_y(int(position[1]))
                playlist = getattr(row, 'playlist', None) if row else None
                if playlist is not None and not getattr(playlist, 'smart', False):
                    history = list(getattr(self, 'play_history', ()))
                    tracks = [self.queue[index] if index >= 0 else history[-index - 1]
                              for index in drag['indices']]
                    self.add_tracks_to_playlist(playlist, tracks)
                view.set_drag_dest_row(None, Gtk.TreeViewDropPosition.BEFORE)
                return True
        destination = self.queue_pointer_destination(view, event.x, event.y)
        view.set_drag_dest_row(None, Gtk.TreeViewDropPosition.BEFORE)
        return Player.move_queue_indices(self, drag['indices'], destination)

    def move_queue_indices(self, indices, destination):
        try:
            updated, index = move_queue_or_history(self.queue, self.index,
                                                   getattr(self, 'play_history', ()),
                                                   indices, destination)
        except ValueError:
            return False
        self.queue, self.index = updated, index
        self.clear_remote_queue()
        if self.shuffle.get_active():
            self.shuffle.set_active(False)
        if any(index < 0 for index in indices):
            self.pulse_queue_icon()
            if self.queue_album and any(track.album != self.queue_album.title
                                        for track in self.queue):
                self.queue_album = None
            if not (self.stream_open or self.remote_opening) and self.client:
                self.queue_client = self.client
                self.index = max(0, self.index)
                self.start_track()
                return True
        self.refresh_queue_view()
        self.mpris.changed()
        self.persist_session(force=True)
        return True

    def queue_key_pressed(self, _view, event):
        if event.keyval != Gdk.KEY_BackSpace:
            return False
        indices = self.selected_queue_indices()
        if not indices:
            return False
        self.remove_queue_indices(indices)
        return True

    def remove_queue_indices(self, indices):
        try:
            updated, index, removed_current = remove_items(self.queue, self.index, indices)
        except ValueError:
            return
        was_open = self.stream_open or self.remote_opening
        resume_paused = self.stream_open and not self.playing
        self.queue, self.index = updated, index
        Player.clear_remote_queue(self)
        if not self.queue:
            self.stop()
            Player.queue_session_save(self)
        elif removed_current and was_open:
            self.start_track(resume_paused=resume_paused)
        else:
            self.refresh_queue_view()
            self.mpris.changed()
            self.persist_session(force=True)
        self.status.set_text(f'Removed {len(set(indices))} track(s) from queue')

    def lastfm_work(self, work, done, generation):
        def run():
            try:
                return work(), None
            except lastfm.LastFMError as error:
                return None, str(error)
            except Exception:
                return None, 'Last.fm operation failed. Check your connection and keyring.'
        def finished(result):
            value, error = result
            if error:
                self.lastfm_status.set_text(error)
            else:
                done(value)
        self.async_work(run, finished, lambda: generation == self.lastfm_generation)

    def initialize_lastfm(self):
        generation = self.lastfm_generation
        def loaded(session):
            self.lastfm_session = session
            if getattr(self, 'time_machine', None):
                self.time_machine.on_show()
            self.lastfm_unlink_button.set_sensitive(bool(session))
            self.lastfm_status.set_text(f'Linked to Last.fm as {session["username"]}'
                                        if session else 'Last.fm is not linked.')
        self.lastfm_work(lastfm.load_session, loaded, generation)
        return False

    def start_lastfm_link(self, *_):
        credentials = lastfm.application_credentials()
        if credentials:
            key, secret = credentials
        else:
            key, secret = self.lastfm_key.get_text().strip(), self.lastfm_secret.get_text().strip()
            if not key or not secret:
                self.lastfm_status.set_text('Application credentials are needed before linking Last.fm.')
                return
        self.lastfm_generation += 1
        generation = self.lastfm_generation
        self.lastfm_auth = None
        self.lastfm_finish_button.set_sensitive(False)
        self.lastfm_status.set_text('Requesting Last.fm authorization…')
        api = lastfm.LastFM(key, secret)
        def token_ready(token):
            self.lastfm_auth = (api, token)
            self.lastfm_finish_button.set_sensitive(True)
            self.lastfm_status.set_text('Approve Apistat in your browser, then select Finish linking.')
            try:
                Gtk.show_uri_on_window(self, api.authorization_url(token), Gdk.CURRENT_TIME)
            except GLib.Error:
                self.lastfm_status.set_text('Could not open your browser. Try authorizing again.')
        self.lastfm_work(api.get_token, token_ready, generation)

    def finish_lastfm_link(self, *_):
        if not self.lastfm_auth:
            return
        api, token = self.lastfm_auth
        self.lastfm_generation += 1
        generation = self.lastfm_generation
        self.lastfm_status.set_text('Finishing Last.fm link…')
        def link():
            session = api.get_session(token)
            with self.lastfm_vault_lock:
                if generation != self.lastfm_generation:
                    return None
                lastfm.save_session(session)
            return session
        def linked(session):
            self.lastfm_session = session
            if getattr(self, 'time_machine', None):
                self.time_machine.on_show()
            self.lastfm_auth = None
            self.lastfm_key.set_text('')
            self.lastfm_secret.set_text('')
            self.lastfm_finish_button.set_sensitive(False)
            self.lastfm_unlink_button.set_sensitive(True)
            self.lastfm_status.set_text(f'Linked to Last.fm as {session["username"]}')
        self.lastfm_work(link, linked, generation)

    def unlink_lastfm(self, *_):
        self.lastfm_generation += 1
        generation = self.lastfm_generation
        self.lastfm_session = None
        if getattr(self, 'time_machine', None):
            self.time_machine.on_show()
        self.lastfm_auth = None
        self.lastfm_finish_button.set_sensitive(False)
        self.lastfm_unlink_button.set_sensitive(False)
        self.lastfm_status.set_text('Unlinking Last.fm…')
        def clear():
            with self.lastfm_vault_lock:
                if generation == self.lastfm_generation:
                    lastfm.clear_session()
        self.lastfm_work(clear,
                         lambda _value: self.lastfm_status.set_text('Last.fm is not linked.'),
                         generation)

    def update_lastfm_playback(self, position, playing):
        tracker = getattr(self, 'lastfm_tracker', None)
        session = getattr(self, 'lastfm_session', None)
        if not tracker:
            return
        events = tracker.update(position, playing and bool(session))
        if not session:
            return
        for event in events:
            api = lastfm.LastFM(session['api_key'], session['secret'])
            if event == 'now_playing':
                work = lambda: api.now_playing(session['session'], tracker.track)
            else:
                work = lambda: api.scrobble(session['session'], tracker.track, tracker.started)
            self.lastfm_work(work, lambda _result: None, self.lastfm_generation)

    def build_settings_view(self):
        self.settings_stack = Gtk.Stack()
        self.settings_stack.set_name('settings-stack')
        self.settings_tabs = Gtk.Notebook()
        self.settings_tabs.set_name('settings-tabs')
        self.settings_tabs.set_show_border(False)
        self.settings_tabs.set_show_tabs(False)
        self.settings_pages = []
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        panel.set_name('settings-panel')
        heading = Gtk.Label(label='Settings', xalign=0)
        heading.set_name('now-title')
        panel.pack_start(heading, False, False, 0)
        panel.pack_start(Gtk.Label(label='Plex server', xalign=0), False, False, 0)
        self.server_label = Gtk.Label(label='Not connected', xalign=0)
        self.server_label.set_selectable(True)
        panel.pack_start(self.server_label, False, False, 0)
        connection_button = self.button('Change connection…', self.connect_dialog)
        connection_button.set_halign(Gtk.Align.START)
        panel.pack_start(connection_button, False, False, 0)
        account_actions = Gtk.Box(spacing=12)
        self.account_server_button = self.button('Choose server from Plex account…',
                                                 self.choose_server_from_account)
        self.remote_link_button = self.button('Link Plex account…', self.start_remote_link)
        self.remote_unlink_button = self.button('Unlink', self.unlink_remote)
        account_actions.pack_start(self.account_server_button, False, False, 0)
        account_actions.pack_start(self.remote_link_button, False, False, 0)
        account_actions.pack_start(self.remote_unlink_button, False, False, 0)
        self.remote_unlink_button.set_sensitive(False)
        panel.pack_start(account_actions, False, False, 0)
        self.account_status = Gtk.Label(label='Checking Plex account link…', xalign=0)
        self.account_status.set_line_wrap(True)
        panel.pack_start(self.account_status, False, False, 0)
        credential_store = ('Windows Credential Manager' if os.name == 'nt'
                            else ('macOS Keychain' if sys.platform == 'darwin' else 'your desktop keyring'))
        info = Gtk.Label(label=f'Server login is stored in {credential_store} after a successful connection.', xalign=0)
        info.set_line_wrap(True)
        panel.pack_start(info, False, False, 0)
        panel.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        panel.pack_start(Gtk.Label(label='Plexamp remote control', xalign=0), False, False, 0)
        self.remote_toggle = Gtk.CheckButton(label='Allow Plexamp remote control')
        self.remote_toggle.set_active(self.remote_config['enabled'])
        self.remote_toggle.connect('toggled', self.remote_toggle_changed)
        panel.pack_start(self.remote_toggle, False, False, 0)
        panel.pack_start(Gtk.Label(label='Player name', xalign=0), False, False, 0)
        self.remote_name_entry = Gtk.Entry()
        self.remote_name_entry.set_max_length(80)
        self.remote_name_entry.set_text(self.remote_config['name'])
        self.remote_name_entry.connect('activate', self.remote_name_changed)
        self.remote_name_entry.connect('focus-out-event', self.remote_name_changed)
        panel.pack_start(self.remote_name_entry, False, False, 0)
        self.remote_status = Gtk.Label(label='Remote control is off', xalign=0)
        self.remote_status.set_line_wrap(True)
        panel.pack_start(self.remote_status, False, False, 0)
        self.remote_request_status = Gtk.Label(label='No phone requests yet', xalign=0)
        self.remote_request_status.set_line_wrap(True)
        panel.pack_start(self.remote_request_status, False, False, 0)
        panel.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        panel.pack_start(Gtk.Label(label='Last.fm scrobbling', xalign=0), False, False, 0)
        explanation = Gtk.Label(label='Link your Last.fm account to share your listening history.', xalign=0)
        explanation.set_line_wrap(True)
        panel.pack_start(explanation, False, False, 0)
        self.lastfm_advanced = Gtk.Expander(label='Advanced: application credentials')
        advanced = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        advanced.pack_start(Gtk.Label(
            label='This build has no application credentials configured.', xalign=0), False, False, 0)
        api_link = Gtk.LinkButton.new_with_label('https://www.last.fm/api/account/create',
                                                 'Get a Last.fm API account')
        api_link.set_halign(Gtk.Align.START)
        advanced.pack_start(api_link, False, False, 0)
        self.lastfm_key = Gtk.Entry(placeholder_text='Last.fm API key')
        self.lastfm_secret = Gtk.Entry(placeholder_text='Last.fm shared secret')
        self.lastfm_secret.set_visibility(False)
        advanced.pack_start(self.lastfm_key, False, False, 0)
        advanced.pack_start(self.lastfm_secret, False, False, 0)
        self.lastfm_advanced.add(advanced)
        self.lastfm_advanced.set_no_show_all(bool(lastfm.application_credentials()))
        panel.pack_start(self.lastfm_advanced, False, False, 0)
        lastfm_actions = Gtk.Box(spacing=12)
        self.lastfm_link_button = self.button('Authorize Last.fm…', self.start_lastfm_link)
        self.lastfm_finish_button = self.button('Finish linking', self.finish_lastfm_link)
        self.lastfm_finish_button.set_sensitive(False)
        self.lastfm_unlink_button = self.button('Unlink Last.fm', self.unlink_lastfm)
        self.lastfm_unlink_button.set_sensitive(False)
        for button in (self.lastfm_link_button, self.lastfm_finish_button, self.lastfm_unlink_button):
            lastfm_actions.pack_start(button, False, False, 0)
        panel.pack_start(lastfm_actions, False, False, 0)
        self.lastfm_status = Gtk.Label(label='Checking Last.fm link…', xalign=0)
        self.lastfm_status.set_line_wrap(True)
        panel.pack_start(self.lastfm_status, False, False, 0)
        self.settings_pages.append(panel)
        self.settings_tabs.append_page(self.scroll(panel), Gtk.Label(label='Connection'))
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        panel.set_name('settings-panel')
        appearance_heading = Gtk.Label(label='Appearance', xalign=0)
        appearance_heading.set_name('now-title')
        panel.pack_start(appearance_heading, False, False, 0)
        appearance_panel = panel

        def appearance_section(title):
            section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            label = Gtk.Label(label=title, xalign=0)
            label.get_style_context().add_class('settings-section-title')
            section.pack_start(label, False, False, 0)
            appearance_panel.pack_start(section, False, False, 0)
            return section

        panel = appearance_section('Theme and colors')
        theme_row = Gtk.Box(spacing=12)
        theme_row.pack_start(Gtk.Label(label='Theme', xalign=0), False, False, 0)
        self.theme_combo = Gtk.ComboBoxText()
        for key, label in (('dark', 'Dark'), ('black', 'Black'), ('light', 'Light')):
            self.theme_combo.append(key, label)
        self.theme_combo.set_active_id(self.theme)
        self.theme_combo.connect('changed', self.theme_changed)
        theme_row.pack_start(self.theme_combo, False, False, 0)
        panel.pack_start(theme_row, False, False, 0)
        self.gradient_toggle = Gtk.CheckButton(label='Use album art colors behind Now Playing and Albums')
        self.gradient_toggle.set_active(self.gradient_enabled)
        self.gradient_toggle.connect('toggled', self.gradient_changed)
        panel.pack_start(self.gradient_toggle, False, False, 0)
        visualizer_row = Gtk.Box(spacing=12)
        visualizer_row.pack_start(Gtk.Label(label='Visualizer view', xalign=0), False, False, 0)
        self.visualizer_view_combo = Gtk.ComboBoxText()
        self.visualizer_view_combo.append('ribbon', 'Ribbon')
        self.visualizer_view_combo.append('perspective', 'Coming towards you')
        self.visualizer_view_combo.set_active_id(self.visualizer_view)
        self.visualizer_view_combo.connect('changed', self.visualizer_view_changed)
        visualizer_row.pack_start(self.visualizer_view_combo, False, False, 0)
        panel.pack_start(visualizer_row, False, False, 0)
        self.background_visualizer_toggle = Gtk.CheckButton(
            label='Show the Now Playing visualizer on other gradient backgrounds')
        self.background_visualizer_toggle.set_active(self.background_visualizer_enabled)
        self.background_visualizer_toggle.connect('toggled', self.background_visualizer_changed)
        panel.pack_start(self.background_visualizer_toggle, False, False, 0)
        self.instrument_visualizer_toggle = Gtk.CheckButton(
            label='Experimental: react to instruments (requires Demucs)')
        self.instrument_visualizer_toggle.set_active(self.instrument_visualizer_enabled)
        self.instrument_visualizer_toggle.connect('toggled', self.instrument_visualizer_changed)
        panel.pack_start(self.instrument_visualizer_toggle, False, False, 0)
        self.instrument_visualizer_status = Gtk.Label(
            label='Demucs runs separately; its model may download on first use.', xalign=0)
        self.instrument_visualizer_status.set_line_wrap(True)
        panel.pack_start(self.instrument_visualizer_status, False, False, 0)
        accent_row = Gtk.Box(spacing=12)
        accent_row.pack_start(Gtk.Label(label='Pick accent color', xalign=0), False, False, 0)
        self.accent_color_button = Gtk.ColorButton()
        self.accent_color_button.set_title('Pick accent color')
        Gtk.ColorChooser.set_use_alpha(self.accent_color_button, False)
        rgba = Gdk.RGBA()
        rgba.parse(self.accent_color)
        self.accent_color_button.set_rgba(rgba)
        self.accent_color_button.connect('color-set', self.accent_color_changed)
        accent_row.pack_start(self.accent_color_button, False, False, 0)
        panel.pack_start(accent_row, False, False, 0)
        self.art_accent_toggle = Gtk.CheckButton(label='Use a bright color from the playing album art')
        self.art_accent_toggle.set_active(self.art_accent_enabled)
        self.art_accent_toggle.connect('toggled', self.art_accent_changed)
        panel.pack_start(self.art_accent_toggle, False, False, 0)
        panel = appearance_section('Playback and interface')
        self.timeline_waveform_toggle = Gtk.CheckButton(
            label='Show song waveform instead of the timeline')
        self.timeline_waveform_toggle.set_active(self.timeline_waveform_enabled)
        self.timeline_waveform_toggle.connect('toggled', self.timeline_waveform_changed)
        panel.pack_start(self.timeline_waveform_toggle, False, False, 0)
        self.tooltips_toggle = Gtk.CheckButton(label='Hide all tooltips')
        self.tooltips_toggle.set_active(self.tooltips_hidden)
        self.tooltips_toggle.connect('toggled', self.tooltips_changed)
        panel.pack_start(self.tooltips_toggle, False, False, 0)
        self.star_ratings_toggle = Gtk.CheckButton(label='Hide star ratings')
        self.star_ratings_toggle.set_active(self.star_ratings_hidden)
        self.star_ratings_toggle.connect('toggled', self.star_ratings_changed)
        panel.pack_start(self.star_ratings_toggle, False, False, 0)
        self.smooth_scrolling_toggle = Gtk.CheckButton(label='Smooth scrolling')
        self.smooth_scrolling_toggle.set_active(self.smooth_scrolling_enabled)
        self.smooth_scrolling_toggle.connect('toggled', self.smooth_scrolling_changed)
        panel.pack_start(self.smooth_scrolling_toggle, False, False, 0)
        panel = appearance_section('Album grid')
        self.classic_wall_toggle = Gtk.CheckButton(label='Use classic album wall')
        self.classic_wall_toggle.set_sensitive(sys.platform.startswith('linux') or sys.platform == 'win32')
        self.classic_wall_toggle.set_active(not self.canvas_enabled)
        self.classic_wall_toggle.connect('toggled', self.classic_album_wall_changed)
        panel.pack_start(self.classic_wall_toggle, False, False, 0)
        self.gpu_wall_toggle = Gtk.CheckButton(label='Use GPU rendering for the classic wall')
        self.gpu_wall_toggle.set_sensitive(not self.canvas_enabled and (sys.platform.startswith('linux') or sys.platform == 'win32'))
        self.gpu_wall_toggle.set_active(self.gpu_wall_enabled)
        self.gpu_wall_toggle.connect('toggled', self.gpu_wall_toggled)
        panel.pack_start(self.gpu_wall_toggle, False, False, 0)
        self.album_details_toggle = Gtk.CheckButton(label='Show artist, album title and days since added on album covers')
        self.album_details_toggle.set_active(self.show_album_details)
        self.album_details_toggle.connect('toggled', self.album_details_changed)
        panel.pack_start(self.album_details_toggle, False, False, 0)
        panel.pack_start(Gtk.Label(label='Album grid size', xalign=0), False, False, 0)
        self.album_grid_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, ALBUM_COLUMN_RANGE[0], ALBUM_COLUMN_RANGE[1], 1)
        self.album_grid_scale.set_inverted(True)
        self.album_grid_scale.set_digits(0)
        self.album_grid_scale.connect('scroll-event', self.ignore_settings_scale_scroll)
        self.album_grid_scale.set_value(self.album_columns)
        self.album_grid_scale.connect('value-changed', self.album_grid_scale_changed)
        panel.pack_start(self.album_grid_scale, False, False, 0)
        panel.pack_start(Gtk.Label(
            label='4–16 covers per row. Ctrl + scroll over the album wall also changes the size.',
            xalign=0), False, False, 0)
        panel.pack_start(Gtk.Label(label='Album grid outer margin', xalign=0), False, False, 0)
        self.album_outer_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 64, 2)
        self.album_outer_scale.set_value(self.album_margin)
        self.album_outer_scale.set_digits(0)
        self.album_outer_scale.connect('scroll-event', self.ignore_settings_scale_scroll)
        self.album_outer_scale.connect('value-changed', self.album_margins_changed)
        panel.pack_start(self.album_outer_scale, False, False, 0)
        panel.pack_start(Gtk.Label(label='Space between album covers', xalign=0), False, False, 0)
        self.album_gap_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 36, 2)
        self.album_gap_scale.set_value(self.album_spacing)
        self.album_gap_scale.set_digits(0)
        self.album_gap_scale.connect('scroll-event', self.ignore_settings_scale_scroll)
        self.album_gap_scale.connect('value-changed', self.album_margins_changed)
        panel.pack_start(self.album_gap_scale, False, False, 0)
        self.single_flip_toggle = Gtk.CheckButton(label='Only one album flipped at a time')
        self.single_flip_toggle.set_active(self.single_flip_enabled)
        self.single_flip_toggle.connect('toggled', self.single_flip_changed)
        panel.pack_start(self.single_flip_toggle, False, False, 0)
        panel = appearance_section('Window and bars')
        self.title_bar_toggle = Gtk.CheckButton(label='Hide window title bar')
        self.title_bar_toggle.set_active(self.hide_title_bar)
        self.title_bar_toggle.connect('toggled', self.title_bar_changed)
        panel.pack_start(self.title_bar_toggle, False, False, 0)
        self.window_buttons_toggle = Gtk.CheckButton(
            label='Show small window buttons in the top right')
        self.window_buttons_toggle.set_active(self.window_buttons_enabled)
        self.window_buttons_toggle.connect('toggled', self.window_buttons_changed)
        panel.pack_start(self.window_buttons_toggle, False, False, 0)
        self.rounded_corners_toggle = Gtk.CheckButton(label='Round window corners')
        self.rounded_corners_toggle.set_active(self.rounded_corners_enabled)
        self.rounded_corners_toggle.connect('toggled', self.rounded_corners_changed)
        panel.pack_start(self.rounded_corners_toggle, False, False, 0)
        self.frosted_bar_toggle = Gtk.CheckButton(
            label='Use translucent blurred bars over content')
        self.frosted_bar_toggle.set_active(self.frosted_player_bar)
        self.frosted_bar_toggle.connect('toggled', self.frosted_player_bar_changed)
        panel.pack_start(self.frosted_bar_toggle, False, False, 0)
        glass_description = Gtk.Label(
            label='Blurs content behind the player bar and top bars.', xalign=0)
        glass_description.set_line_wrap(True)
        glass_description.get_style_context().add_class('dim-label')
        panel.pack_start(glass_description, False, False, 0)
        panel = appearance_section('Text and font')
        panel.pack_start(Gtk.Label(label='Text size', xalign=0), False, False, 0)
        self.text_size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 24, 1)
        self.text_size_scale.set_value(self.text_size)
        self.text_size_scale.set_digits(0)
        self.text_size_scale.connect('scroll-event', self.ignore_settings_scale_scroll)
        self.text_size_scale.connect('value-changed', self.text_size_changed)
        panel.pack_start(self.text_size_scale, False, False, 0)
        self.font_toggle = Gtk.CheckButton(label='Use custom font')
        self.font_toggle.set_active(bool(self.custom_font))
        self.font_toggle.connect('toggled', self.custom_font_toggled)
        panel.pack_start(self.font_toggle, False, False, 0)
        self.font_button = Gtk.FontButton()
        self.font_button.set_show_size(False)
        Gtk.FontChooser.set_font(
            self.font_button, self.custom_font or self.default_font_family or 'Sans')
        self.font_button.set_sensitive(bool(self.custom_font))
        self.font_button.connect('font-set', self.custom_font_changed)
        panel.pack_start(self.font_button, False, False, 0)
        self.settings_pages.append(appearance_panel)
        self.settings_tabs.append_page(self.scroll(appearance_panel), Gtk.Label(label='Appearance'))
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        panel.set_name('settings-panel')
        library_heading = Gtk.Label(label='Library and Search', xalign=0)
        library_heading.set_name('now-title')
        panel.pack_start(library_heading, False, False, 0)
        panel.pack_start(Gtk.Label(label='Library source', xalign=0), False, False, 0)
        source_row = Gtk.Box(spacing=8)
        self.source_selector = Gtk.ComboBoxText()
        self.source_selector.set_hexpand(True)
        self.source_selector.connect('changed', self.source_selected)
        source_row.pack_start(self.source_selector, True, True, 0)
        refresh_sources = self.button('Refresh Plex servers', self.refresh_account_sources)
        source_row.pack_start(refresh_sources, False, False, 0)
        panel.pack_start(source_row, False, False, 0)
        source_actions = Gtk.Box(spacing=8)
        source_actions.pack_start(self.button('Add local library…', self.add_local_source), False, False, 0)
        self.local_rescan_button = self.button('Rescan local library', self.rescan_local_source)
        self.local_rescan_button.set_sensitive(False)
        source_actions.pack_start(self.local_rescan_button, False, False, 0)
        self.local_remove_button = self.button('Remove local library', self.remove_local_source)
        self.local_remove_button.set_sensitive(False)
        source_actions.pack_start(self.local_remove_button, False, False, 0)
        panel.pack_start(source_actions, False, False, 0)
        self.populate_source_selector()
        local_data_label = Gtk.Label(label=f'Local library data: {LOCAL_LIBRARY_DATA}', xalign=0)
        local_data_label.set_line_wrap(True)
        local_data_label.set_selectable(True)
        panel.pack_start(local_data_label, False, False, 0)
        panel.pack_start(Gtk.Label(label='Music library', xalign=0), False, False, 0)
        self.library.set_halign(Gtk.Align.START)
        panel.pack_start(self.library, False, False, 0)
        self.search_index_toggle = Gtk.CheckButton(
            label='Cache an album index for title and artist search')
        self.search_index_toggle.set_active(self.search_index_enabled)
        self.search_index_toggle.connect('toggled', self.search_index_changed)
        panel.pack_start(self.search_index_toggle, False, False, 0)
        self.index_status = Gtk.Label(label='Index is off' if not self.search_index_enabled
                                      else 'Connect to build the search index', xalign=0)
        panel.pack_start(self.index_status, False, False, 0)
        self.index_refresh = self.button('Refresh search index', self.refresh_search_index)
        self.index_refresh.set_halign(Gtk.Align.START)
        self.index_refresh.set_sensitive(False)
        panel.pack_start(self.index_refresh, False, False, 0)
        shortcuts_button = self.button('Global keyboard shortcuts…', self.show_shortcuts_page)
        shortcuts_button.set_halign(Gtk.Align.START)
        panel.pack_start(shortcuts_button, False, False, 0)
        self.settings_pages.append(panel)
        self.settings_tabs.append_page(self.scroll(panel), Gtk.Label(label='Library'))

        shortcut_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        shortcut_page.set_name('settings-panel')
        heading = Gtk.Label(label='Global keyboard shortcuts', xalign=0)
        heading.set_name('now-title')
        shortcut_page.pack_start(heading, False, False, 0)
        local_row = Gtk.Box(spacing=12)
        local_row.pack_start(Gtk.Label(label='Album search (window shortcut)', xalign=0), True, True, 0)
        self.search_shortcut_label = Gtk.Label(xalign=0)
        local_row.pack_start(self.search_shortcut_label, False, False, 0)
        local_row.pack_start(self.button('Set…', self.capture_search_shortcut), False, False, 0)
        local_row.pack_start(self.button('Reset', self.reset_search_shortcut), False, False, 0)
        shortcut_page.pack_start(local_row, False, False, 0)
        self.update_search_shortcut_label()
        description = Gtk.Label(label=(
            'Global shortcut editing is currently available on Xfce/Linux. '
            'The window shortcuts still work on Windows.' if os.name == 'nt' else
            'Global shortcut editing is not available on macOS.' if sys.platform == 'darwin' else
            'This editor manages Xfce keyboard shortcuts. Other desktops can bind '
            'keys to Apistat through MPRIS in their own keyboard settings.'), xalign=0)
        description.set_line_wrap(True)
        shortcut_page.pack_start(description, False, False, 0)
        self.shortcut_description = description
        self.portal_shortcut_button = self.button('Enable global shortcuts…',
                                                  self.configure_portal_shortcuts)
        self.portal_shortcut_button.set_halign(Gtk.Align.START)
        self.portal_shortcut_button.set_no_show_all(True)
        self.portal_shortcut_button.hide()
        shortcut_page.pack_start(self.portal_shortcut_button, False, False, 0)
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        shortcut_page.pack_start(rows, False, False, 0)
        self.shortcut_rows = {}
        for label, method in shortcuts.ACTIONS:
            row = Gtk.Box(spacing=12)
            action_label = Gtk.Label(label=label, xalign=0)
            action_label.set_size_request(155, -1)
            row.pack_start(action_label, False, False, 0)
            current = Gtk.Label(label='Not set', xalign=0)
            current.set_hexpand(True)
            row.pack_start(current, True, True, 0)
            set_button = self.button('Set…', lambda _button, action=method: self.capture_shortcut(action))
            clear_button = self.button('Clear', lambda _button, action=method: self.clear_shortcut(action))
            row.pack_start(set_button, False, False, 0)
            row.pack_start(clear_button, False, False, 0)
            rows.pack_start(row, False, False, 0)
            self.shortcut_rows[method] = (current, set_button, clear_button)
        self.shortcut_status = Gtk.Label(xalign=0)
        self.shortcut_status.set_line_wrap(True)
        shortcut_page.pack_start(self.shortcut_status, False, False, 0)
        self.settings_pages.append(shortcut_page)
        self.shortcut_scroll = self.scroll(shortcut_page)
        self.settings_tabs.append_page(self.shortcut_scroll, Gtk.Label(label='Keyboard'))

        sidebar_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        sidebar_page.set_name('settings-panel')
        sidebar_heading = Gtk.Label(label='Sidebar', xalign=0)
        sidebar_heading.set_name('now-title')
        sidebar_page.pack_start(sidebar_heading, False, False, 0)
        sidebar_page.pack_start(Gtk.Label(
            label='Choose which buttons appear in the left sidebar.', xalign=0),
            False, False, 0)
        labels_toggle = Gtk.CheckButton(label='Show labels under sidebar icons')
        labels_toggle.set_active(self.sidebar_labels_enabled)
        labels_toggle.connect('toggled', self.sidebar_labels_changed)
        sidebar_page.pack_start(labels_toggle, False, False, 0)
        note_toggle = Gtk.CheckButton(label='Animate Now Playing icon during playback')
        note_toggle.set_active(self.sidebar_note_animation_enabled)
        note_toggle.connect('toggled', self.sidebar_note_animation_changed)
        sidebar_page.pack_start(note_toggle, False, False, 0)
        for view, label in (('now', 'Now playing'), ('albums', 'Albums'),
                            ('library', 'Library'), ('styles', 'Styles and moods'),
                            ('queue', 'Play queue'), ('lyrics', 'Lyrics'),
                            ('time', 'Time machine')):
            toggle = Gtk.CheckButton(label=label)
            toggle.set_active(view in self.sidebar_visible)
            toggle.connect('toggled', self.sidebar_visibility_changed, view)
            sidebar_page.pack_start(toggle, False, False, 0)
        sidebar_page.pack_start(Gtk.Label(
            label='Settings stays visible so you can change these choices later.', xalign=0),
            False, False, 0)
        self.settings_pages.append(sidebar_page)
        self.settings_tabs.append_page(self.scroll(sidebar_page), Gtk.Label(label='Sidebar'))
        tab_bar = Gtk.Box(spacing=4)
        tab_bar.set_name('settings-tab-bar')
        tab_bar.set_halign(Gtk.Align.CENTER)
        self.settings_tab_bar = Gtk.Box()
        self.settings_tab_bar.set_center_widget(tab_bar)
        self.settings_tab_buttons = []
        for index, title in enumerate(('Connection', 'Appearance', 'Library',
                                       'Keyboard', 'Sidebar')):
            button = Gtk.Button(label=title)
            button.set_name('settings-tab-button')
            button.connect('clicked', lambda _button, page=index:
                           self.settings_tabs.set_current_page(page))
            tab_bar.pack_start(button, False, False, 0)
            self.settings_tab_buttons.append(button)
        self.settings_tabs.connect('switch-page', self.settings_tab_changed)
        self.settings_tab_changed(self.settings_tabs, None, 0)
        tab_layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tab_layout.set_name('settings-center')
        tab_layout.set_halign(Gtk.Align.CENTER)
        tab_layout.pack_start(self.settings_tab_bar, False, False, 0)
        tab_layout.pack_start(self.settings_tabs, True, True, 0)
        settings_background = Gtk.EventBox()
        settings_background.set_name('settings-background')
        self.settings_center = tab_layout
        settings_background.connect('size-allocate', self.settings_background_allocated)
        settings_background.add(tab_layout)
        self.settings_stack.add_named(settings_background, 'main')
        self.content_views.add_named(self.settings_stack, 'settings')

    def sidebar_visibility_changed(self, button, view):
        if button.get_active():
            self.sidebar_visible.add(view)
        else:
            self.sidebar_visible.discard(view)
            if self.content_views.get_visible_child_name() == view:
                self.show_view('settings')
        nav_button = self.nav_buttons[view]
        nav_button.set_no_show_all(not button.get_active())
        nav_button.set_visible(button.get_active())
        try:
            save_sidebar_visible(self.sidebar_visible)
        except OSError:
            self.status.set_text('Could not save sidebar visibility')

    def settings_background_allocated(self, _background, allocation):
        width = min(900, max(1, allocation.width - 32))
        if getattr(self, '_settings_center_width', None) != width:
            self._settings_center_width = width
            self.settings_center.set_size_request(width, -1)

    def show_shortcuts_page(self, *_):
        self.show_view('settings')
        self.shortcut_scroll.show_all()
        self.settings_tabs.set_current_page(3)
        self.refresh_shortcuts()

    def settings_tab_changed(self, _notebook, _page, index):
        effect = getattr(self, 'settings_top_frost', None)
        if effect is not None:
            effect.set_content(self.settings_tabs.get_nth_page(index))
        for page, button in enumerate(self.settings_tab_buttons):
            context = button.get_style_context()
            if page == index:
                context.add_class('active')
            else:
                context.remove_class('active')
        if index == 3:
            self.refresh_shortcuts()

    def refresh_shortcuts(self):
        portal = getattr(self, 'portal_shortcuts', None)
        if portal and portal.available:
            self.shortcut_description.set_text(
                'Your desktop manages these global shortcuts. Configure them in its '
                'permission dialog; they work while Apistat is running.')
            self.portal_shortcut_button.set_label(
                'Configure global shortcuts…' if portal.shortcuts else
                'Enable global shortcuts…')
            self.portal_shortcut_button.set_no_show_all(False)
            self.portal_shortcut_button.show()
            self.shortcut_status.set_text(
                'Shortcut keys are chosen by the desktop. Use Configure to change or clear them.')
            for method, (current, set_button, clear_button) in self.shortcut_rows.items():
                current.set_text(portal.shortcuts.get(method, 'Not set'))
                set_button.set_sensitive(False)
                clear_button.set_sensitive(False)
            return
        self.portal_shortcut_button.hide()
        if not shortcuts.available():
            self.shortcut_status.set_text(
                'Global shortcut editing is unavailable on this platform.' if os.name == 'nt' or sys.platform == 'darwin' else
                'This desktop has no Global Shortcuts portal. Use its keyboard settings '
                'to bind MPRIS controls, or use Xfce with xfconf-query and gdbus.')
            for current, set_button, clear_button in self.shortcut_rows.values():
                current.set_text('Unavailable')
                set_button.set_sensitive(False)
                clear_button.set_sensitive(False)
            return
        try:
            bindings = shortcuts.bindings()
        except shortcuts.ShortcutError as exc:
            self.shortcut_status.set_text(str(exc))
            return
        self.shortcut_status.set_text('Press Set to record a key combination. Existing Xfce shortcuts are preserved.')
        for method, (current, set_button, clear_button) in self.shortcut_rows.items():
            names = bindings[method]
            labels = []
            for name in names:
                if name.startswith('XF86Audio'):
                    labels.append('Media ' + name[len('XF86Audio'):])
                    continue
                key, modifiers = Gtk.accelerator_parse(name)
                labels.append(Gtk.accelerator_get_label(key, modifiers) if key else name)
            current.set_text(', '.join(labels) if labels else 'Not set')
            set_button.set_sensitive(True)
            clear_button.set_sensitive(bool(names))

    def update_search_shortcut_label(self):
        key, modifiers = Gtk.accelerator_parse(self.search_shortcut)
        self.search_shortcut_label.set_text(Gtk.accelerator_get_label(key, modifiers))

    def reset_search_shortcut(self, *_):
        self.set_search_shortcut('Tab')

    def set_search_shortcut(self, accelerator):
        try:
            save_search_shortcut(accelerator)
        except (OSError, ValueError):
            self.status.set_text('Could not save the search shortcut.')
            return
        self.search_shortcut = accelerator
        self.update_search_shortcut_label()

    def capture_search_shortcut(self, *_):
        dialog = Gtk.Dialog(title='Set album search shortcut', transient_for=self, modal=True)
        dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
        message = Gtk.Label(label='Press a shortcut. Escape cancels.', margin=24)
        dialog.get_content_area().pack_start(message, True, True, 0)
        captured = []
        def key_pressed(_dialog, event):
            if event.keyval == Gdk.KEY_Escape:
                dialog.response(Gtk.ResponseType.CANCEL)
                return True
            key = Gdk.keyval_to_lower(event.keyval)
            modifiers = event.state & Gtk.accelerator_get_default_mod_mask()
            name = Gdk.keyval_name(key) or ''
            if (not modifiers and key != Gdk.KEY_Tab and
                    not (name.startswith('F') and name[1:].isdigit())):
                message.set_text('Use Tab, a function key, or a key combination with modifiers.')
                return True
            if not Gtk.accelerator_valid(key, modifiers) and key != Gdk.KEY_Tab:
                message.set_text('Choose a valid keyboard shortcut.')
                return True
            captured.append(Gtk.accelerator_name(key, modifiers))
            dialog.response(Gtk.ResponseType.OK)
            return True
        dialog.connect('key-press-event', key_pressed)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and captured:
            self.set_search_shortcut(captured[0])

    def configure_portal_shortcuts(self, *_):
        if self.portal_shortcuts and self.portal_shortcuts.available:
            self.portal_shortcuts.configure()

    def capture_shortcut(self, method):
        label = next(name for name, action in shortcuts.ACTIONS if action == method)
        dialog = Gtk.Dialog(title=f'Set {label} shortcut', transient_for=self, modal=True)
        dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
        message = Gtk.Label(label='Press the new shortcut now. Press Escape to cancel.', margin=24)
        dialog.get_content_area().pack_start(message, True, True, 0)
        captured = []
        def key_pressed(_dialog, event):
            if event.keyval == Gdk.KEY_Escape:
                dialog.response(Gtk.ResponseType.CANCEL)
                return True
            modifiers = event.state & Gtk.accelerator_get_default_mod_mask()
            key = Gdk.keyval_to_lower(event.keyval)
            key_name = Gdk.keyval_name(key)
            media_key = key & 0xffff0000 == 0x10080000
            function_key = key_name.startswith('F') and key_name[1:].isdigit()
            if (not Gtk.accelerator_valid(key, modifiers)
                    or (not modifiers and not (media_key or function_key))):
                message.set_text('Use a media key, function key, or a key combination with modifiers.')
                return True
            accelerator = Gtk.accelerator_name(key, modifiers)
            if media_key and not key_name.startswith('XF86'):
                accelerator = accelerator.replace(key_name, 'XF86' + key_name, 1)
            captured.append(accelerator)
            dialog.response(Gtk.ResponseType.OK)
            return True
        dialog.connect('key-press-event', key_pressed)
        dialog.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        seat = Gdk.Display.get_default().get_default_seat()
        grabbed = seat.grab(dialog.get_window(), Gdk.SeatCapabilities.KEYBOARD,
                            False, None, None, None) == Gdk.GrabStatus.SUCCESS
        try:
            response = dialog.run()
        finally:
            if grabbed:
                seat.ungrab()
            dialog.destroy()
        if response != Gtk.ResponseType.OK or not captured:
            return
        try:
            shortcuts.set_binding(method, captured[0])
        except (shortcuts.ShortcutError, ValueError) as exc:
            self.shortcut_status.set_text(str(exc))
            return
        self.refresh_shortcuts()

    def clear_shortcut(self, method):
        try:
            shortcuts.clear_bindings(method)
        except shortcuts.ShortcutError as exc:
            self.shortcut_status.set_text(str(exc))
            return
        self.refresh_shortcuts()

    def gradient_changed(self, button):
        self.gradient_enabled = button.get_active()
        self.refresh_live_waveform()
        self.render_gradient()
        self.prefetch_next_track()
        try:
            save_gradient_enabled(self.gradient_enabled)
        except OSError:
            self.status.set_text('Could not save the appearance setting.')

    def star_ratings_changed(self, button):
        self.star_ratings_hidden = button.get_active()
        self.apply_star_rating_visibility()
        try:
            save_star_ratings_hidden(self.star_ratings_hidden)
        except OSError:
            self.status.set_text('Could not save the appearance setting.')

    def smooth_scrolling_changed(self, button):
        self.smooth_scrolling_enabled = button.get_active()
        for scroller in list(self.smooth_scrollers):
            scroller.set_enabled(self.smooth_scrolling_enabled)
        try:
            save_smooth_scrolling_enabled(self.smooth_scrolling_enabled)
        except OSError:
            self.status.set_text('Could not save the appearance setting.')

    def apply_star_rating_visibility(self):
        hidden = self.star_ratings_hidden
        if hidden:
            self.now_rating.hide()
        else:
            self.now_rating.set_no_show_all(False)
            self.now_rating.show_all()
            self.now_rating.set_no_show_all(True)
        self.detail_rating_column.set_visible(not hidden)
        self.queue_rating_column.set_visible(not hidden)
        self.song_columns['user_rating'].set_visible(
            not hidden and self.rating_column_preferred)

    def theme_changed(self, combo):
        theme = combo.get_active_id()
        if theme is None or theme == self.theme:
            return
        self.invalidate_frosted_backdrops()
        self.theme = theme
        self.apply_theme()
        self.update_frosted_top_style()
        if hasattr(self, 'time_machine'):
            self.time_machine.refresh_selection_style()
        self.prefetch_next_track()
        try:
            save_theme(theme)
        except OSError:
            self.status.set_text('Could not save the theme setting.')

    def timeline_waveform_changed(self, button):
        self.timeline_waveform_enabled = button.get_active()
        self.timeline_stack.set_visible_child_name(
            'waveform' if self.timeline_waveform_enabled else 'line')
        if self.timeline_waveform_enabled and self.current_stream_uri and self.queue:
            self.prepare_track_waveform(self.queue_client, self.queue[self.index],
                                        self.current_stream_uri, self.play_generation)
            self.prefetch_next_track()
        elif not self.timeline_waveform_enabled:
            self.waveform_generation += 1
        try:
            save_timeline_waveform_enabled(self.timeline_waveform_enabled)
        except OSError:
            self.status.set_text('Could not save the waveform timeline setting.')

    def prepare_track_waveform(self, client, track, uri, play_generation, delay_ms=0):
        self.waveform_generation += 1
        waveform_generation = self.waveform_generation
        cache = LocalCache(client)
        cached = cache.read_waveform(track.key, track.duration)
        self.wave_timeline.set_peaks(cached)
        if cached is not None or track.duration <= 0:
            return
        valid = lambda: (not self.closed and self.timeline_waveform_enabled and
                         waveform_generation == self.waveform_generation and
                         play_generation == self.play_generation)
        def work():
            def progress(peaks):
                def deliver_progress():
                    if valid():
                        self.wave_timeline.set_peaks(peaks)
                    return False
                GLib.idle_add(deliver_progress)
            try:
                if valid() and getattr(client, 'is_local', False) and client.stream(track) == uri:
                    peaks = analyze_audio_uri(uri, '', track.duration, lambda: not valid(), progress)
                else:
                    peaks = server_waveform(client, track, lambda: not valid()) if valid() else None
                    if peaks is None and valid():
                        peaks = analyze_track_waveform(uri, client.address, client.token,
                                                       track.duration, lambda: not valid(), progress)
                if peaks is not None and valid():
                    try:
                        cache.save_waveform(track.key, track.duration, peaks)
                    except OSError:
                        pass
            except Exception:
                peaks = None
            def deliver():
                self.busy.end()
                if valid() and peaks is not None:
                    self.wave_timeline.set_peaks(peaks)
                return False
            GLib.idle_add(deliver)
        def start_work():
            if valid():
                self.busy.begin()
                try:
                    self.waveform_workers.submit(work)
                except RuntimeError:
                    self.busy.end()
            return False
        if delay_ms:
            GLib.timeout_add(delay_ms, start_work)
        else:
            start_work()

    def prefetch_next_track(self):
        if (not self.stream_open or not self.queue_client or
                not 0 <= self.index + 1 < len(self.queue)):
            return
        client = self.queue_client
        track = self.queue[self.index + 1]
        art_item = self.queue_album if self.queue_album and self.queue_album.thumb else track
        thumb = art_item.thumb
        background_size = (self.shared_background.get_allocated_width(),
                           self.shared_background.get_allocated_height())
        target = (id(client), track.key, track.duration, thumb, self.theme,
                  self.gradient_enabled, self.timeline_waveform_enabled, background_size)
        previous_target = self.next_prefetch_target
        if target == previous_target:
            return
        self.next_prefetch_target = target
        if self.next_art_prefetch_future is not None:
            self.next_art_prefetch_future.cancel()
        same_waveform = (previous_target is not None and
                         previous_target[:3] == target[:3] and
                         previous_target[6] == target[6])
        if not same_waveform and self.next_wave_prefetch_future is not None:
            self.next_wave_prefetch_future.cancel()
        generation = self.play_generation
        def cancelled():
            return (self.closed or generation != self.play_generation or
                    self.queue_client is not client or
                    self.index + 1 >= len(self.queue) or
                    self.queue[self.index + 1].key != track.key)
        def art_cancelled():
            return cancelled() or self.next_prefetch_target != target
        self.next_art_prefetch_future = self.next_art_workers.submit(
            preload_next_art, client, thumb, self.theme, self.gradient_enabled,
            background_size, art_cancelled)
        if not same_waveform:
            self.next_wave_prefetch_future = (
                self.next_waveform_workers.submit(preload_next_waveform, client, track, cancelled)
                if self.timeline_waveform_enabled else None)

    def background_allocated(self, _background, allocation):
        if (not self.stream_open or not 0 <= self.index + 1 < len(self.queue) or
                not self.gradient_enabled):
            return
        size = allocation.width, allocation.height
        if size == getattr(self, '_background_prefetch_size', None):
            return
        self._background_prefetch_size = size
        if self.background_prefetch_source:
            GLib.source_remove(self.background_prefetch_source)
        self.background_prefetch_source = GLib.timeout_add(200, self.prefetch_resized_background)

    def prefetch_resized_background(self):
        self.background_prefetch_source = 0
        if not self.closed:
            self.prefetch_next_track()
        return False

    def accent_color_changed(self, button):
        rgba = button.get_rgba()
        self.accent_color = '#{:02x}{:02x}{:02x}'.format(
            *(round(channel * 255) for channel in (rgba.red, rgba.green, rgba.blue)))
        self.apply_accent()
        try:
            save_accent_color(self.accent_color)
        except OSError:
            self.status.set_text('Could not save the accent color.')

    def art_accent_changed(self, button):
        self.art_accent_enabled = button.get_active()
        self.apply_accent()
        try:
            save_art_accent_enabled(self.art_accent_enabled)
        except OSError:
            self.status.set_text('Could not save the artwork accent setting.')

    def tooltips_changed(self, button):
        self.tooltips_hidden = button.get_active()
        self.apply_tooltip_setting()
        try:
            save_tooltips_hidden(self.tooltips_hidden)
        except OSError:
            self.status.set_text('Could not save the tooltip setting.')

    def album_details_changed(self, button):
        self.show_album_details = button.get_active()
        if getattr(self, 'gpu_wall', None):
            self.gpu_wall.layout_changed()
        if getattr(self, 'album_canvas', None):
            self.album_canvas.layout_changed()
        for child in self.grid.get_children():
            tile = child.get_child()
            tile.metadata_box.set_visible(self.show_album_details)
        self.grid.queue_resize()
        try:
            save_album_details_enabled(self.show_album_details)
        except OSError:
            self.status.set_text('Could not save the album label setting.')

    def album_margins_changed(self, *_):
        self.album_margin = int(self.album_outer_scale.get_value())
        self.album_spacing = int(self.album_gap_scale.get_value())
        if getattr(self, 'gpu_wall', None):
            self.gpu_wall.layout_changed()
        for side in ('start', 'end', 'bottom'):
            getattr(self.album_wall, f'set_margin_{side}')(self.album_margin)
        self.album_top_allocated()
        self.album_wall.set_spacing(self.album_spacing)
        self.grid.set_row_spacing(self.album_spacing)
        self.grid.set_column_spacing(self.album_spacing)
        if hasattr(self, 'style_album_grid'):
            self.style_album_grid.set_row_spacing(self.album_spacing)
            self.style_album_grid.set_column_spacing(self.album_spacing)
            for side in ('start', 'end', 'top', 'bottom'):
                getattr(self.style_album_wall, f'set_margin_{side}')(self.album_margin)
            self.style_grid.set_row_spacing(self.album_spacing)
            self.style_grid.set_column_spacing(self.album_spacing)
            for side in ('start', 'end', 'top', 'bottom'):
                getattr(self.style_wall, f'set_margin_{side}')(self.album_margin)
            self.style_status.set_margin_start(self.album_margin)
            self.apply_style_grid_columns()
            self.apply_style_album_columns()
        self.apply_album_grid_columns()
        try:
            save_album_margins(self.album_margin, self.album_spacing)
        except OSError:
            self.status.set_text('Could not save album margins.')

    def album_grid_scale_changed(self, scale):
        columns = round(scale.get_value())
        if columns == self.album_columns:
            return
        self.album_columns = columns
        self.apply_album_grid_layout()
        try:
            save_album_columns(columns)
        except OSError:
            self.status.set_text('Could not save album grid size.')

    def single_flip_changed(self, button):
        self.single_flip_enabled = button.get_active()
        time_wall = getattr(getattr(self, 'time_machine', None), 'gpu_wall', None)
        if time_wall is not None:
            if self.single_flip_enabled:
                time_wall.enforce_single_flip()
            else:
                time_wall.pending_exclusive_flip = None
        if self.single_flip_enabled and getattr(self, 'gpu_wall', None):
            self.gpu_wall.enforce_single_flip()
        elif getattr(self, 'gpu_wall', None):
            self.gpu_wall.pending_exclusive_flip = None
        if self.single_flip_enabled and self.pending_flipped_tile is None:
            keep = self.last_flipped_tile
            for child in self.grid.get_children():
                tile = child.get_child()
                if tile is not keep:
                    tile.flip_card.show_side('front')
        try:
            save_single_flip_enabled(self.single_flip_enabled)
        except OSError:
            self.status.set_text('Could not save album flip setting.')

    def title_bar_changed(self, button):
        self.hide_title_bar = button.get_active()
        self.set_decorated(not self.hide_title_bar)
        self.update_window_controls()
        self._window_shape_state = None
        self.refresh_window_shape()
        try:
            save_title_bar_hidden(self.hide_title_bar)
        except OSError:
            self.status.set_text('Could not save title bar setting.')

    def toggle_window_maximize(self, *_):
        self.unmaximize() if self.is_maximized() else self.maximize()

    def window_state_changed(self, _window, event):
        maximized = bool(event.new_window_state & Gdk.WindowState.MAXIMIZED)
        name = 'Restore' if maximized else 'Maximize'
        self.maximize_button.set_label('❐' if maximized else '□')
        self.set_tooltip(self.maximize_button, name)
        self.maximize_button.get_accessible().set_name(name)
        self._window_shape_state = None
        GLib.idle_add(self.refresh_window_shape)
        return False

    def update_window_controls(self):
        visible = self.window_buttons_enabled
        if visible:
            self.window_controls.set_no_show_all(False)
            self.window_controls.show_all()
        else:
            self.window_controls.hide()
            self.window_controls.set_no_show_all(True)
        self.busy_spinner.set_margin_end(90 if visible else 14)

    def window_buttons_changed(self, button):
        self.window_buttons_enabled = button.get_active()
        self.update_window_controls()
        try:
            save_window_buttons_enabled(self.window_buttons_enabled)
        except OSError:
            self.status.set_text('Could not save window button setting.')

    @staticmethod
    def ignore_settings_scale_scroll(scale, event):
        scroller = scale.get_ancestor(Gtk.ScrolledWindow)
        if scroller is not None:
            Gtk.propagate_event(scroller, event)
        return True

    def player_bar_allocated(self, _bar, allocation):
        if allocation.height > 1 and self.player_bar_spacer.get_size_request().height != allocation.height:
            self.player_bar_spacer.set_size_request(-1, allocation.height)
        self.update_queue_bottom_inset()

    def player_bar_visibility_changed(self, bar, _property):
        self.player_bar_spacer.set_visible(bar.get_visible() and not self.frosted_player_bar)
        self.update_queue_bottom_inset()

    @staticmethod
    def solid_timeline_background(player):
        stack = getattr(player, 'timeline_stack', None)
        return stack if stack is not None and stack.get_visible_child_name() == 'line' else None

    @staticmethod
    def library_frosted_capture_allowed(player):
        return (not getattr(player, '_song_row_builds', 0) or
                player.content_views.get_visible_child_name() != 'library')

    def update_queue_bottom_inset(self):
        bar = getattr(self, 'player_bar', None)
        inset = (bar.get_allocated_height()
                 if bar and self.frosted_player_bar and bar.get_visible() else 0)
        if getattr(self, 'gpu_wall', None):
            self.gpu_wall.set_bottom_inset(inset)
        if getattr(self, 'album_canvas', None):
            self.album_canvas.set_bottom_inset(0)
            self.canvas_hscroll.set_margin_bottom(max(0, inset))
        if getattr(self, 'album_web_wall', None):
            self.album_web_wall.set_bottom_inset(inset)
        info = getattr(self, 'info_revealer', None)
        if info is not None and info.get_margin_bottom() != inset:
            info.set_margin_bottom(max(0, inset))
        for page in getattr(self, 'settings_pages', ()):
            if page.get_margin_bottom() != inset:
                page.set_margin_bottom(max(0, inset))
        if hasattr(self, 'keep_style_playing'):
            self.keep_style_playing.set_margin_bottom(16 + max(0, inset))
        if hasattr(self, 'lyrics_details'):
            self.lyrics_details.set_margin_bottom(max(0, inset))
        bottom = getattr(self, 'library_tracks_container', getattr(self, 'song_count', None))
        if bottom is not None:
            margin = 8 + max(0, inset)
            if bottom.get_margin_bottom() != margin:
                bottom.set_margin_bottom(margin)

    def apply_frosted_player_bar(self):
        self.invalidate_frosted_backdrops()
        context = self.player_bar.get_style_context()
        if self.frosted_player_bar:
            context.add_class('frosted')
        else:
            context.remove_class('frosted')
        self.player_bar_visibility_changed(self.player_bar, None)
        self.frosted_bar.set_enabled(self.frosted_player_bar)
        for widget, effect in self.top_frosted_bars:
            style = widget.get_style_context()
            (style.add_class if self.frosted_player_bar else style.remove_class)('frosted-top')
            effect.set_enabled(self.frosted_player_bar)
        for control in self.frosted_top_controls():
            style = control.get_style_context()
            (style.add_class if self.frosted_player_bar else style.remove_class)('solid-top-control')
        if getattr(self, 'gpu_wall', None):
            self.gpu_wall.queue_frame()

    def frosted_top_controls(self):
        return (self.search, self.style_search,
                *self.album_sort_buttons.values(),
                *self.style_mode_buttons.values(), *self.settings_tab_buttons)

    def update_frosted_top_style(self):
        if not hasattr(self, 'top_frosted_style'):
            return
        base = ((232, 232, 229) if self.theme == 'light' else
                (0, 0, 0) if self.theme == 'black' else (38, 38, 40))
        hover = ((211, 211, 207) if self.theme == 'light' else
                 (46, 46, 46) if self.theme == 'black' else (57, 57, 59))
        accent = ((self.current_art_bright if self.art_accent_enabled else None)
                  or self.accent_color)
        rgb = tuple(int(accent[index:index + 2], 16) for index in (1, 3, 5))
        active = tuple(round(base[index] * 0.7 + rgb[index] * 0.3) for index in range(3))
        foreground = '#202326' if self.theme == 'light' else '#eeeeee'
        css_color = lambda color: '#{:02x}{:02x}{:02x}'.format(*color)
        self.top_frosted_style.load_from_data(f'''
            .frosted-top {{ background: transparent; background-image: none; padding: 5px; }}
            .solid-top-control {{ background: {css_color(base)}; background-image: none;
                                  color: {foreground}; }}
            .solid-top-control:hover {{ background: {css_color(hover)}; }}
            .solid-top-control.active {{ background: {css_color(active)}; }}
        '''.encode())

    def setup_frosted_top_bars(self):
        self.top_frosted_style = Gtk.CssProvider()
        self.update_frosted_top_style()
        self.top_frosted_bars = []
        for widget, source in ((self.album_toolbar, self.wall_scroll),
                               (self.album_sort_bar, self.wall_scroll),
                               (self.style_header, self.style_scroll),
                               (self.settings_tab_bar,
                                self.settings_tabs.get_nth_page(self.settings_tabs.get_current_page()))):
            widget.get_style_context().add_provider(self.top_frosted_style,
                                                    Gtk.STYLE_PROVIDER_PRIORITY_USER)
            effect = FrostedBar(widget, source, self.shared_background,
                                lambda: self.theme, edge='top',
                                window_capture=widget is self.settings_tab_bar,
                                capture_content=lambda: not Player.gpu_wall_is_mapped(self),
                                gpu_surface=lambda bar=widget: Player.gpu_glass_surface(self, bar))
            self.top_frosted_bars.append((widget, effect))
            if widget is self.settings_tab_bar:
                self.settings_top_frost = effect
        for control in self.frosted_top_controls():
            control.get_style_context().add_provider(self.top_frosted_style,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_USER)

    @staticmethod
    def gpu_wall_is_mapped(player):
        walls = (getattr(player, 'album_canvas', None), getattr(player, 'gpu_wall', None),
                 getattr(player, 'album_web_wall', None),
                 getattr(getattr(player, 'time_machine', None), 'gpu_wall', None))
        return any(wall is not None and wall.area.get_mapped() for wall in walls)

    @staticmethod
    def gpu_glass_surface(player, bar):
        walls = (getattr(player, 'album_canvas', None), getattr(player, 'gpu_wall', None),
                 getattr(player, 'album_web_wall', None),
                 getattr(getattr(player, 'time_machine', None), 'gpu_wall', None))
        for wall in walls:
            if wall is not None and wall.area.get_mapped():
                return wall.glass_surfaces.get(id(bar))
        return None

    def set_album_frosted_source(self, source):
        for widget, effect in getattr(self, 'top_frosted_bars', ()):
            if widget is self.album_toolbar or widget is self.album_sort_bar:
                effect.set_content(source)

    def invalidate_frosted_backdrops(self):
        effects = [getattr(self, 'frosted_bar', None)]
        effects.extend(effect for _widget, effect in getattr(self, 'top_frosted_bars', ()))
        for effect in effects:
            if effect is not None:
                effect.invalidate(effect.content, None)

    def frosted_player_bar_changed(self, button):
        self.frosted_player_bar = button.get_active()
        self.apply_frosted_player_bar()
        try:
            save_frosted_player_bar(self.frosted_player_bar)
        except OSError:
            self.status.set_text('Could not save the appearance setting.')

    def rounded_corners_changed(self, button):
        self.rounded_corners_enabled = button.get_active()
        if self._window_shape_resume_source:
            GLib.source_remove(self._window_shape_resume_source)
            self._window_shape_resume_source = 0
        self._window_shape_suspended = False
        self._window_shape_state = None
        self.refresh_window_shape()
        try:
            save_rounded_corners_enabled(self.rounded_corners_enabled)
        except OSError:
            self.status.set_text('Could not save rounded corner setting.')

    def text_size_changed(self, scale):
        self.text_size = round(scale.get_value())
        self.apply_text_size()
        try:
            save_text_size(self.text_size)
        except OSError:
            self.status.set_text('Could not save text size.')

    def custom_font_toggled(self, button):
        enabled = button.get_active()
        self.font_button.set_sensitive(enabled)
        self.custom_font = self.selected_font_family() if enabled else ''
        self.apply_text_size()
        self.save_custom_font_setting()

    def custom_font_changed(self, _button):
        if not self.font_toggle.get_active():
            return
        self.custom_font = self.selected_font_family()
        self.apply_text_size()
        self.save_custom_font_setting()

    def selected_font_family(self):
        description = Pango.FontDescription.from_string(
            Gtk.FontChooser.get_font(self.font_button))
        return description.get_family() or 'Sans'

    def save_custom_font_setting(self):
        try:
            save_custom_font(self.custom_font)
        except (OSError, ValueError):
            self.status.set_text('Could not save custom font.')

    def search_index_changed(self, button):
        self.search_index_enabled = button.get_active()
        self.index_generation += 1
        self.index_building = False
        try:
            save_search_index_enabled(self.search_index_enabled)
            if not self.search_index_enabled and self.client:
                LocalCache(self.client).clear_indices()
        except OSError:
            self.status.set_text('Could not save the search index setting.')
        self.indexed_albums = None
        self.index_section = None
        self.index_refresh.set_sensitive(self.search_index_enabled and bool(self.client))
        self.index_status.set_text('Index is off' if not self.search_index_enabled
                                   else 'Connect to build the search index')
        if self.search_index_enabled:
            self.ensure_search_index()
        if self.search.get_text().strip():
            self.load_albums()

    def ensure_search_index(self):
        section = self.library.get_active_id()
        if not self.search_index_enabled or not self.client or not section:
            return
        if getattr(self.client, 'is_local', False):
            self.index_refresh.set_sensitive(False)
            self.index_status.set_text('Local library is indexed automatically')
            return
        self.index_refresh.set_sensitive(True)
        if self.index_section == section and (self.indexed_albums is not None or
                                              self.index_building):
            return
        self.index_generation += 1
        generation = self.index_generation
        client = self.client
        self.index_section = section
        self.index_cache = LocalCache(client)
        cache = self.index_cache
        self.indexed_albums = None
        self.index_building = True
        self.index_status.set_text('Loading album index…')
        valid = lambda: (generation == self.index_generation and self.client is client and
                         self.index_section == section and self.search_index_enabled)
        def loaded(albums):
            self.index_building = False
            if albums is None:
                self.start_search_index_build()
            else:
                self.indexed_albums = albums
                self.index_status.set_text(f'{len(albums)} albums indexed • Refresh to update')
                if self.search.get_text().strip():
                    self.load_albums()
        def failed():
            self.index_building = False
            self.start_search_index_build()
        self.async_work(lambda: cache.read_index(section), loaded, valid, failed)

    def refresh_search_index(self, *_):
        self.start_search_index_build()

    def start_search_index_build(self):
        section = self.library.get_active_id()
        if not self.search_index_enabled or not self.client or not section:
            return
        self.index_generation += 1
        generation = self.index_generation
        client = self.client
        cache = LocalCache(client)
        self.index_cache = cache
        self.index_section = section
        self.index_building = True
        self.index_refresh.set_sensitive(False)
        self.index_status.set_text('Building album index…')
        valid = lambda: (generation == self.index_generation and self.client is client and
                         self.index_section == section and self.search_index_enabled)
        def work():
            albums = build_album_index(client, section, valid)
            if albums is not None and valid():
                cache.save_index(section, albums)
            return albums
        def done(albums):
            self.index_building = False
            self.index_refresh.set_sensitive(True)
            if albums is None:
                return
            self.indexed_albums = albums
            self.index_status.set_text(f'{len(albums)} albums indexed • Refresh to update')
            if self.search.get_text().strip():
                self.load_albums()
        def failed():
            self.index_building = False
            self.index_refresh.set_sensitive(True)
            self.index_status.set_text('Index build failed • Refresh to retry')
        self.async_work(work, done, valid, failed)

    def render_gradient(self):
        colors = theme_gradient_colors(
            self.current_art_colors if self.gradient_enabled else None, self.theme)
        self.shared_background.set_colors(colors)

    def cached_art_colors(self, client, item, pixbuf):
        palettes = getattr(self, '_album_palette_cache', None)
        if palettes is None:
            palettes = self._album_palette_cache = {}
        key = (client, item.thumb)
        if key in palettes:
            return palettes[key]
        cache = LocalCache(client)
        try:
            palette = cache.read_palette(item.thumb)
        except OSError:
            palette = None
        if palette is not None:
            palettes[key] = palette
            return palette
        gradient, wave = gradient_colors(pixbuf), waveform_colors(pixbuf)
        if gradient:
            try:
                cache.save_palette(item.thumb, gradient, wave)
            except OSError:
                pass
            palettes[key] = (gradient, wave)
        return gradient, wave

    def update_art_gradient(self, client, item, pixbuf):
        try:
            self.current_art_colors, wave = self.cached_art_colors(client, item, pixbuf)
            self.current_art_bright = wave[0]
            self.current_wave_colors = wave
        except Exception:
            self.current_art_colors = None
            self.current_art_key = None
            self.current_art_bright = None
            self.current_wave_colors = None
        self.render_gradient()
        self.apply_accent()

    def build_info_panel(self):
        self.info_generation = 0
        self.info_target = None
        self.info_pending_update = None
        self.info_mode = 'track'
        self.info_revealer = Gtk.Revealer()
        self.info_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.info_revealer.set_transition_duration(220)
        self.info_revealer.set_halign(Gtk.Align.END)
        self.info_revealer.set_valign(Gtk.Align.FILL)
        self.info_revealer.connect('notify::child-revealed', self.info_reveal_finished)
        self.info_panel_width = load_info_panel_width()
        self.info_panel_resize = None
        self.info_panel = InfoPanelBox(orientation=Gtk.Orientation.HORIZONTAL)
        self.info_panel.set_name('info-panel')
        self.info_panel.set_size_request(self.info_panel_width, -1)
        left_handle = self.info_resize_handle('left')
        self.info_panel.pack_start(left_handle, False, False, 0)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.set_margin_top(16)
        panel.set_margin_bottom(16)
        panel.set_margin_start(10)
        panel.set_margin_end(10)
        self.info_panel.pack_start(panel, True, True, 0)
        right_handle = self.info_resize_handle('right')
        self.info_panel.pack_end(right_handle, False, False, 0)
        header = Gtk.Overlay()
        header.set_name('info-artist-banner')
        self.info_artist_name = Gtk.Label(label='Artist', xalign=0.5)
        self.info_artist_name.set_name('info-artist-name')
        self.info_artist_name.set_ellipsize(Pango.EllipsizeMode.END)
        header.add(self.info_artist_name)
        close = self.icon_button('window-close-symbolic', 'Close track information',
                                 lambda *_: self.info_button.set_active(False))
        close.set_name('info-close-button')
        close.set_halign(Gtk.Align.END)
        close.set_valign(Gtk.Align.CENTER)
        header.add_overlay(close)
        panel.pack_start(header, False, False, 0)
        self.info_content_stack = Gtk.Stack()
        self.info_content_stack.set_hhomogeneous(False)
        self.info_content_stack.set_vhomogeneous(False)
        self.info_content_stack.set_vexpand(True)
        panel.pack_start(self.info_content_stack, True, True, 0)
        details_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.info_content_stack.add_named(details_panel, 'track')
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.info_biography = Gtk.Label(label='Play a song to see artist information.', xalign=0)
        self.info_biography.set_line_wrap(True)
        self.info_biography.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.info_biography.set_max_width_chars(42)
        self.info_biography.set_selectable(True)
        content.pack_start(self.info_biography, False, False, 0)
        self.info_source_label = Gtk.Label(xalign=0)
        self.info_source_label.set_name('info-secondary')
        self.info_source_label.set_line_wrap(True)
        content.pack_start(self.info_source_label, False, False, 0)
        self.info_artist_scroll = Gtk.ScrolledWindow()
        self.info_artist_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.info_artist_scroll.set_vexpand(True)
        self.info_artist_scroll.add(content)
        details_panel.pack_start(self.info_artist_scroll, True, True, 0)
        details_panel.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        file_header = Gtk.Label(label='Track information', xalign=0)
        file_header.set_name('info-section-title')
        details_panel.pack_start(file_header, False, False, 0)
        self.info_track_title = Gtk.Label(label='Nothing playing', xalign=0)
        self.info_track_title.set_ellipsize(Pango.EllipsizeMode.END)
        details_panel.pack_start(self.info_track_title, False, False, 0)
        track_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.info_file = Gtk.Label(label='Play a song to see file information.', xalign=0)
        self.info_file.set_line_wrap(True)
        self.info_file.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        track_content.pack_start(self.info_file, False, False, 0)
        self.info_file_grid = Gtk.Grid(column_spacing=14, row_spacing=4)
        track_content.pack_start(self.info_file_grid, False, False, 0)
        self.info_track_scroll = Gtk.ScrolledWindow()
        self.info_track_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.info_track_scroll.set_max_content_height(260)
        self.info_track_scroll.set_propagate_natural_height(True)
        self.info_track_scroll.add(track_content)
        details_panel.pack_start(self.info_track_scroll, False, True, 0)
        lost_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.info_lost_count = Gtk.Label(xalign=0)
        self.info_lost_count.set_line_wrap(True)
        lost_panel.pack_start(self.info_lost_count, False, False, 0)
        self.info_lost_store = Gtk.ListStore(str, str, str, str)
        self.info_lost_view = Gtk.TreeView(model=self.info_lost_store)
        self.info_lost_view.set_name('song-view')
        for index, title in enumerate(('Song', 'Artist', 'Album', 'Listened')):
            cell = Gtk.CellRendererText()
            cell.set_property('ellipsize', Pango.EllipsizeMode.END)
            column = Gtk.TreeViewColumn(title, cell, text=index)
            column.set_resizable(True)
            column.set_min_width(80)
            self.info_lost_view.append_column(column)
        lost_scroll = Gtk.ScrolledWindow()
        lost_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        lost_scroll.add(self.info_lost_view)
        lost_panel.pack_start(lost_scroll, True, True, 0)
        self.info_content_stack.add_named(lost_panel, 'lost')
        self.info_tag_editor = TagEditor(self)
        self.info_content_stack.add_named(self.info_tag_editor, 'edit')
        self.info_content_stack.set_visible_child_name('track')
        self.info_revealer.add(self.info_panel)
        self.content_overlay.add_overlay(self.info_revealer)

    def info_resize_handle(self, edge):
        handle = Gtk.EventBox()
        handle.set_name('info-resize-handle')
        handle.set_visible_window(True)
        handle.set_size_request(10, -1)
        handle.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                          Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK |
                          Gdk.EventMask.LEAVE_NOTIFY_MASK)
        handle.get_accessible().set_name('Drag to resize track information')
        handle.connect('button-press-event', self.info_resize_pressed, edge)
        handle.connect('motion-notify-event', self.info_resize_motion)
        handle.connect('button-release-event', self.info_resize_released)
        handle.connect('enter-notify-event', self.info_resize_cursor, True)
        handle.connect('leave-notify-event', self.info_resize_cursor, False)
        return handle

    def info_resize_pressed(self, _handle, event, edge):
        if event.button != 1:
            return False
        self.info_panel_resize = (edge, event.x_root, self.info_panel_width)
        if _handle is not None:
            _handle.grab_add()
        return True

    def info_resize_motion(self, _handle, event):
        drag = self.info_panel_resize
        if drag is None or not event.state & Gdk.ModifierType.BUTTON1_MASK:
            return False
        edge, start, width = drag
        delta = event.x_root - start
        available = max(240, self.content_overlay.get_allocated_width() - 24)
        self.info_panel_width = max(240, min(1000, available,
                                             round(width + (delta if edge == 'right' else -delta))))
        self.info_panel.set_size_request(self.info_panel_width, -1)
        return True

    def info_resize_released(self, _handle, event):
        if event.button != 1 or self.info_panel_resize is None:
            return False
        self.info_panel_resize = None
        if _handle is not None:
            _handle.grab_remove()
        try:
            save_info_panel_width(self.info_panel_width)
        except (OSError, ValueError):
            self.info_source_label.set_text('Could not save the information panel width.')
        return True

    def info_resize_cursor(self, _handle, event, entering):
        if event.window is not None:
            cursor = Gdk.Cursor.new_from_name(event.window.get_display(), 'ew-resize') if entering else None
            event.window.set_cursor(cursor)
        return False

    @staticmethod
    def set_info_file(player, lines, message=''):
        for child in player.info_file_grid.get_children():
            player.info_file_grid.remove(child)
        player.info_file.set_text(message if not lines else '')
        for index, (name, value) in enumerate(lines):
            descriptor = Gtk.Label(label=name, xalign=0)
            descriptor.set_name('info-field-name')
            descriptor.set_valign(Gtk.Align.START)
            field = Gtk.Label(label=value, xalign=0)
            field.set_hexpand(True)
            field.set_line_wrap(True)
            field.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            field.set_max_width_chars(28)
            field.set_selectable(True)
            player.info_file_grid.attach(descriptor, 0, index, 1, 1)
            player.info_file_grid.attach(field, 1, index, 1, 1)
        player.info_file_grid.show_all()

    def info_toggled(self, button):
        visible = button.get_active()
        if visible:
            if getattr(self, 'info_mode', 'track') not in ('lost', 'edit'):
                self.info_content_stack.set_visible_child_name('track')
                self.load_current_info()
        else:
            self.info_mode = 'track'
            self.info_target = None
            self.info_pending_update = None
            self.info_generation += 1
        self.info_revealer.set_reveal_child(visible)

    def edit_selected_library_tracks(self):
        tracks = [self.songs[index] for index in self.selected_song_indices()]
        if tracks:
            self.show_tag_editor(tracks)

    def show_tag_editor(self, tracks):
        if self.client is None or not tracks:
            return
        section = self.library.get_active_id()
        if not section:
            return
        self.info_generation += 1
        self.info_pending_update = None
        self.info_target = None
        self.info_mode = 'edit'
        self.info_artist_name.set_text('Edit tags')
        self.info_tag_editor.load(self.client, section, tracks)
        self.info_content_stack.set_visible_child_name('edit')
        if not self.info_button.get_active():
            self.info_button.set_active(True)

    def show_track_info(self, track):
        if self.client is None:
            return
        self.info_mode = 'track'
        if hasattr(self, 'info_content_stack'):
            self.info_content_stack.set_visible_child_name('track')
        self.info_target = (self.client, track)
        if self.info_button.get_active():
            self.load_current_info()
        else:
            self.info_button.set_active(True)

    def show_playing_info(self):
        self.info_mode = 'track'
        if hasattr(self, 'info_content_stack'):
            self.info_content_stack.set_visible_child_name('track')
        self.info_target = None
        if self.info_button.get_active():
            self.load_current_info()
        else:
            self.info_button.set_active(True)

    def show_lost_time_info(self, listens):
        """Open a snapshot of unmatched Last.fm listens without changing playback."""
        self.info_generation += 1
        generation = self.info_generation
        self.info_pending_update = None
        self.info_target = None
        self.info_mode = 'lost'
        self.info_artist_name.set_text('Lost to time')
        self.info_lost_count.set_text(
            f'{len(listens):,} listens could not be matched to this library.' if listens else
            'Every listen was matched to this library.')
        self.info_lost_store.clear()
        self.info_content_stack.set_visible_child_name('lost')
        if not self.info_button.get_active():
            self.info_button.set_active(True)
        snapshot = tuple(listens)
        offset = 0
        def append():
            nonlocal offset
            if (self.closed or generation != self.info_generation or
                    getattr(self, 'info_mode', None) != 'lost'):
                return False
            for listen in snapshot[offset:offset + 150]:
                timestamp = listen.get('timestamp')
                try:
                    played = time.strftime('%Y-%m-%d %H:%M', time.localtime(timestamp)) if timestamp else ''
                except (ValueError, TypeError, OverflowError, OSError):
                    played = ''
                self.info_lost_store.append([listen.get('title', ''), listen.get('artist', ''),
                                             listen.get('album', ''), played])
            offset += 150
            return offset < len(snapshot)
        if snapshot:
            GLib.idle_add(append)

    def info_reveal_finished(self, revealer, _property):
        pending = self.info_pending_update
        if revealer.get_child_revealed() and pending is not None:
            self.info_pending_update = None
            generation, callback = pending
            if generation == self.info_generation and revealer.get_reveal_child():
                callback()

    def apply_info_after_slide(self, generation, callback):
        reveal_finished = getattr(self.info_revealer, 'get_child_revealed', None)
        if reveal_finished is not None and not reveal_finished():
            self.info_pending_update = (generation, callback)
        else:
            callback()

    def load_current_info(self):
        self.info_generation += 1
        generation = self.info_generation
        self.info_pending_update = None
        self.info_source_label.set_text('')
        target = getattr(self, 'info_target', None)
        client = target[0] if target else getattr(self, 'queue_client', None)
        track = target[1] if target else (self.queue[self.index]
                                           if 0 <= self.index < len(self.queue) else None)
        if client is None or track is None:
            self.info_track_title.set_text('Nothing playing')
            self.info_artist_name.set_text('Artist')
            Player.set_info_file(self, [], 'Play a song to see file information.')
            self.info_biography.set_text('Play a song to see artist information.')
            return
        self.info_track_title.set_text(track.title)
        self.info_artist_name.set_text(track.artist or 'Artist')
        fallback = file_info_lines({'codec': track.codec, 'bitrate': track.bitrate})
        Player.set_info_file(self, fallback, 'Loading file information…')
        self.info_biography.set_text('Looking up artist information…')
        valid = lambda: (not self.closed and generation == self.info_generation and
                         self.info_revealer.get_reveal_child() and
                         (getattr(self, 'info_target', None) == target) and
                         (self.client is client if target else self.queue_client is client))
        local = getattr(client, 'is_local', False) is True
        def lookup_local_artist():
            def lookup():
                try:
                    return client.artist_description(track.artist, track.album), False
                except Exception:
                    return None, True
            def ready(result):
                def apply():
                    description, failed = result
                    if description:
                        summary, url = description
                        self.info_biography.set_text(format_artist_description(summary))
                        self.info_source_label.set_text('Wikipedia · ' + url)
                    else:
                        self.info_biography.set_text(
                            'Could not reach the artist information service.' if failed else
                            'No unambiguous artist description was found on Wikipedia.')
                Player.apply_info_after_slide(self, generation, apply)
            self.async_work(lookup, ready, valid)
        def details_ready(result):
            def apply():
                details, summary = result
                lines = file_info_lines(details)
                Player.set_info_file(self, lines, 'No file information is available.')
                if local:
                    lookup_local_artist()
                elif summary:
                    self.info_biography.set_text(format_artist_description(summary))
                    self.info_source_label.set_text('Artist information from Plex')
                else:
                    self.info_biography.set_text('No artist description was found on Plex.')
            Player.apply_info_after_slide(self, generation, apply)
        def details_failed():
            def apply():
                if not fallback:
                    Player.set_info_file(self, [], 'Could not load file information.')
                if local:
                    lookup_local_artist()
                else:
                    self.info_biography.set_text('Could not load the artist description from Plex.')
            Player.apply_info_after_slide(self, generation, apply)
        self.async_work(lambda: client.track_details(track), details_ready, valid, details_failed)

    def playlist_row(self, title, playlist):
        row = Gtk.ListBoxRow()
        row.playlist = playlist
        row.add(Gtk.Label(label=title, xalign=0, margin=8))
        self.playlist_list.add(row)
        row.show_all()
        return row

    def playlist_list_pressed(self, widget, event):
        if event.button == 1:
            row = widget.get_row_at_y(int(event.y))
            valid = row is not None and (getattr(row, 'playlist', None) is not None or
                                         getattr(row, 'definition', None) is not None)
            self.playlist_pointer_drag = ({'widget': widget, 'row': row, 'client': self.client,
                                           'x': event.x, 'y': event.y, 'active': False}
                                          if valid else None)
            return False
        if event.button != 3:
            return False
        row = widget.get_row_at_y(int(event.y))
        if row is None:
            return False
        if widget is self.playlist_list and getattr(row, 'playlist', None) is not None:
            return self.playlist_row_pressed(row, event)
        if widget is self.smart_playlist_list and getattr(row, 'definition', None) is not None:
            return self.smart_playlist_pressed(row, event)
        return False

    def setup_playlist_drag(self, widget, smart):
        widget.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        widget.connect('motion-notify-event', self.playlist_pointer_motion)
        widget.connect('button-release-event', self.playlist_pointer_release)
        if smart:
            return
        song = Gtk.TargetEntry.new('application/x-plex-song-key',
                                   Gtk.TargetFlags.SAME_APP, 0)
        album = Gtk.TargetEntry.new('application/x-plex-album-key',
                                    Gtk.TargetFlags.SAME_APP, 3)
        widget.drag_dest_set(Gtk.DestDefaults.ALL, [song, album], Gdk.DragAction.COPY)
        widget.connect('drag-motion', self.playlist_drag_motion)
        widget.connect('drag-leave', self.playlist_drag_leave)
        widget.connect('drag-data-received', self.playlist_list_drop_received)

    def playlist_pointer_motion(self, widget, event):
        drag = getattr(self, 'playlist_pointer_drag', None)
        if (not drag or drag['widget'] is not widget or drag['client'] is not self.client or
                not event.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        if not drag['active']:
            if abs(event.x - drag['x']) < 5 and abs(event.y - drag['y']) < 5:
                return False
            drag['active'] = True
        row = drag['row']
        self.song_drag_ghost.set_text(row.get_child().get_text())
        self.song_drag_ghost.set_no_show_all(False)
        self.song_drag_ghost.show_all()
        position = widget.translate_coordinates(self.song_drag_overlay, int(event.x), int(event.y))
        if position:
            self.song_drag_overlay.move(self.song_drag_ghost, position[-2] + 12, position[-1] + 12)
        _index, boundary = self.playlist_drop_index(widget, event.y)
        position = widget.translate_coordinates(self.song_drag_overlay, 0, int(boundary))
        if position:
            self.song_drop_line.set_size_request(max(1, widget.get_allocated_width()), 4)
            self.song_drag_overlay.move(self.song_drop_line, position[-2], position[-1] - 2)
            self.song_drop_line.set_no_show_all(False)
            self.song_drop_line.show()
        return True

    def playlist_pointer_release(self, widget, event):
        if event.button != 1:
            return False
        drag = getattr(self, 'playlist_pointer_drag', None)
        self.playlist_pointer_drag = None
        if not drag or drag['widget'] is not widget or not drag['active']:
            return False
        self.hide_song_drag_ghost()
        self.hide_song_drop_line()
        position = self.pointer_position_in(widget, event)
        if position is not None and drag['client'] is self.client:
            index, _boundary = self.playlist_drop_index(widget, position[1])
            self.reorder_playlist_sidebar(widget, drag['row'], index)
        return True

    def playlist_drop_index(self, widget, y):
        rows = [row for row in widget.get_children() if row.get_visible()]
        for index, row in enumerate(rows):
            area = row.get_allocation()
            if y < area.y + area.height / 2:
                return index, area.y
        if rows:
            area = rows[-1].get_allocation()
            return len(rows), area.y + area.height
        return 0, 0

    def playlist_drag_motion(self, widget, context, x, y, _time):
        target = widget.drag_dest_find_target(context, None)
        row = widget.get_row_at_y(int(y)) if (target is not None and
              target.name() in ('application/x-plex-song-key',
                                'application/x-plex-album-key')) else None
        self.set_playlist_drop_target(row)
        return False

    def playlist_drag_leave(self, _widget, _context, _time):
        self.set_playlist_drop_target(None)

    def set_playlist_drop_target(self, row):
        playlist = getattr(row, 'playlist', None) if row is not None else None
        if playlist is None or getattr(playlist, 'smart', False):
            row = None
        previous = getattr(self, 'playlist_drop_target', None)
        if previous is row:
            return row is not None
        if previous is not None:
            previous.get_style_context().remove_class('playlist-drag-target')
        self.playlist_drop_target = row
        if row is not None:
            row.get_style_context().add_class('playlist-drag-target')
        return row is not None

    def update_playlist_drop_target(self, event):
        if not hasattr(self, 'playlist_list') or not hasattr(self, 'pointer_position_in'):
            return False
        position = self.pointer_position_in(self.playlist_list, event)
        row = self.playlist_list.get_row_at_y(int(position[1])) if position is not None else None
        return Player.set_playlist_drop_target(self, row)

    def playlist_list_drop_received(self, widget, context, x, y, selection, info, event_time):
        Player.set_playlist_drop_target(self, None)
        if info in (0, 3) and widget is self.playlist_list:
            row = widget.get_row_at_y(int(y))
            if row is not None and getattr(row, 'playlist', None) is not None:
                self.playlist_drop_received(row, context, x, y, selection, info, event_time)
                return
        Gtk.drag_finish(context, False, False, event_time)

    def reorder_playlist_sidebar(self, widget, row, destination):
        rows = [child for child in widget.get_children() if child.get_visible()]
        if row not in rows or not 0 <= destination <= len(rows):
            return False
        old_index = rows.index(row)
        rows.pop(old_index)
        destination -= old_index < destination
        rows.insert(destination, row)
        if old_index == destination:
            return True
        if widget is self.smart_playlist_list:
            previous = self.smart_playlists
            self.smart_playlists = [child.definition for child in rows]
            if not self.save_smart_playlist_definitions():
                self.smart_playlists = previous
                return False
        elif widget is self.playlist_list:
            try:
                save_playlist_order(self.client.address, self.client.token,
                                    [child.playlist.key for child in rows])
            except (OSError, ValueError):
                self.song_count.set_text('Could not save playlist order on this device')
                return False
            self.playlists = [child.playlist for child in rows]
        else:
            return False
        selected = widget.get_selected_row()
        self.smart_list_rebuilding = True
        self.playlist_list_rebuilding = True
        try:
            if selected is row:
                widget.unselect_row(row)
            widget.remove(row)
            widget.insert(row, destination + (1 if widget is self.playlist_list else 0))
            row.show()
            if selected is row:
                widget.select_row(row)
        finally:
            self.smart_list_rebuilding = False
            self.playlist_list_rebuilding = False
        return True

    def playlist_row_pressed(self, row, event):
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        menu.set_name('apistat-context-menu')
        menu.attach_to_widget(self, None)
        for label, callback in (
                ('Rename playlist…', self.rename_playlist_dialog),
                ('Delete playlist…', self.delete_playlist_dialog)):
            item = Gtk.MenuItem.new_with_label(label)
            item.connect('activate', lambda _item, action=callback: action(row.playlist))
            menu.append(item)
        menu.connect('selection-done', lambda selected: selected.destroy())
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def rename_playlist_dialog(self, playlist):
        if not self.client:
            return
        dialog = Gtk.Dialog(title='Rename playlist', transient_for=self, modal=True)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Rename', Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_border_width(18)
        entry = Gtk.Entry(text=playlist.title, activates_default=True)
        box.add(entry)
        entry.connect('changed', lambda field: dialog.set_response_sensitive(
            Gtk.ResponseType.OK, bool(field.get_text().strip())))
        dialog.show_all()
        entry.select_region(0, -1)
        entry.grab_focus()
        response = dialog.run()
        title = entry.get_text().strip()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and title and title != playlist.title:
            self.change_plex_playlist(playlist, title)

    def delete_playlist_dialog(self, playlist):
        if not self.client:
            return
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text=f'Delete “{playlist.title}”?')
        dialog.format_secondary_text('This removes the playlist from Plex. Its songs remain in your library.')
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Delete', Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.change_plex_playlist(playlist, None)

    def change_plex_playlist(self, playlist, title):
        client = self.client
        if client is None:
            return
        pending = getattr(self, '_playlist_changes', None)
        if pending is None:
            pending = self._playlist_changes = set()
        operation = (client, playlist.key)
        if operation in pending:
            return
        pending.add(operation)
        sections = tuple(section for section, _name in self.sections)
        if title is None:
            Player.note_song_cache_edit(self)
        def work():
            if title is not None:
                client.rename_playlist(playlist, title)
            else:
                client.delete_playlist(playlist)
                for section in sections:
                    try:
                        LocalCache(client).song_index_path(section, playlist.key).unlink(missing_ok=True)
                    except OSError:
                        pass
        def finished(_result):
            pending.discard(operation)
            if self.client is not client:
                return
            self.playlist_generation += 1
            if title is not None:
                playlist.title = title
                for item in self.playlists:
                    if item.key == playlist.key:
                        item.title = title
                for row in self.playlist_list.get_children():
                    if getattr(row, 'playlist', None) and row.playlist.key == playlist.key:
                        row.playlist.title = title
                        row.get_child().set_text(title)
                if self.active_playlist and self.active_playlist.key == playlist.key:
                    self.active_playlist.title = title
                    self.songs_heading.set_text(title)
            else:
                active = self.active_playlist and self.active_playlist.key == playlist.key
                self.playlists = [item for item in self.playlists if item.key != playlist.key]
                for key in list(self.song_view_cache):
                    if len(key) > 2 and key[0] is client and key[2] == playlist.key:
                        del self.song_view_cache[key]
                for row in self.playlist_list.get_children():
                    if getattr(row, 'playlist', None) and row.playlist.key == playlist.key:
                        row.destroy()
                if active:
                    if self.playlist_list.get_selected_row() is self.all_songs_row:
                        self.select_playlist(self.playlist_list, self.all_songs_row)
                    else:
                        self.playlist_list.select_row(self.all_songs_row)
        def failed():
            pending.discard(operation)
            if self.client is client:
                self.song_count.set_text('Could not ' + ('rename' if title is not None else 'delete') + ' playlist on Plex')
        self.async_work(work, finished, on_error=failed)

    def smart_playlist_row(self, definition):
        row = Gtk.ListBoxRow()
        row.definition = definition
        row.add(Gtk.Label(label=definition['name'], xalign=0, margin=8))
        self.smart_playlist_list.add(row)
        row.show_all()
        return row

    def load_smart_playlist_definitions(self):
        section = self.library.get_active_id()
        self.active_smart_playlist = None
        if self.client and section:
            self.smart_playlists = load_for_scope(self.remote_server_machine,
                                                  self.client.address, section)
        else:
            self.smart_playlists = []
        self.refresh_smart_playlist_rows()

    def refresh_smart_playlist_rows(self, selected_id=None):
        self.smart_list_rebuilding = True
        for row in self.smart_playlist_list.get_children():
            row.destroy()
        selected_row = None
        for definition in self.smart_playlists:
            row = self.smart_playlist_row(definition)
            if definition['id'] == selected_id:
                selected_row = row
        self.smart_list_rebuilding = False
        if selected_row:
            self.smart_playlist_list.select_row(selected_row)

    def save_smart_playlist_definitions(self):
        if not self.client or not self.library.get_active_id():
            return False
        try:
            save_for_scope(self.remote_server_machine, self.client.address,
                           self.library.get_active_id(), self.smart_playlists)
        except (OSError, ValueError):
            self.song_count.set_text('Could not save smart playlists on this device')
            return False
        return True

    def create_smart_playlist_dialog(self, *_):
        if not self.client or not self.library.get_active_id():
            self.song_count.set_text('Connect to Plex to create a smart playlist')
            return
        definition = SmartPlaylistDialog(self, checked_label='Only loved songs').run()
        if definition is None:
            return
        self.smart_playlists.append(definition)
        if self.save_smart_playlist_definitions():
            self.refresh_smart_playlist_rows(definition['id'])
        else:
            self.smart_playlists.pop()

    def edit_smart_playlist_dialog(self, definition):
        edited = SmartPlaylistDialog(self, definition,
                                     checked_label='Only loved songs').run()
        if edited is None:
            return
        index = next((i for i, item in enumerate(self.smart_playlists)
                      if item['id'] == definition['id']), None)
        if index is None:
            return
        self.smart_playlists[index] = edited
        if self.save_smart_playlist_definitions():
            self.song_view_cache.clear()
            self.refresh_smart_playlist_rows(edited['id'])
        else:
            self.smart_playlists[index] = definition

    def delete_smart_playlist(self, definition):
        old = self.smart_playlists
        self.smart_playlists = [item for item in old if item['id'] != definition['id']]
        if self.save_smart_playlist_definitions():
            self.song_view_cache.clear()
            self.active_smart_playlist = None
            self.refresh_smart_playlist_rows()
            self.playlist_list.select_row(self.all_songs_row)
        else:
            self.smart_playlists = old

    def smart_playlist_pressed(self, row, event):
        if event.button != 3:
            return False
        self.smart_playlist_list.select_row(row)
        menu = Gtk.Menu()
        menu.set_name('apistat-context-menu')
        menu.attach_to_widget(self, None)
        for label, action in (
                ('Edit smart playlist…', lambda: self.edit_smart_playlist_dialog(row.definition)),
                ('Delete smart playlist', lambda: self.delete_smart_playlist(row.definition))):
            item = Gtk.MenuItem.new_with_label(label)
            item.connect('activate', lambda _item, callback=action: callback())
            menu.append(item)
        menu.connect('selection-done', lambda selected: selected.destroy())
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def select_smart_playlist(self, _list, row):
        if row is None or getattr(self, 'smart_list_rebuilding', False):
            return
        self.playlist_list.unselect_all()
        self.invalidate_song_catalog()
        self.active_playlist = None
        self.active_smart_playlist = row.definition
        self.library_album_filter = None
        self.library_tag_filter = None
        self.update_full_library_selection()
        self.library_back_button.hide()
        self.songs_heading.set_text(row.definition['name'])
        self.apply_library_layout()
        self.load_songs()

    def show_full_music_library(self, *_):
        if self.playlist_list.get_selected_row() is self.all_songs_row:
            self.select_playlist(self.playlist_list, self.all_songs_row)
        else:
            self.playlist_list.select_row(self.all_songs_row)
        self.show_view('library')

    def update_full_library_selection(self):
        active = (self.active_playlist is None and
                  self.active_smart_playlist is None and
                  self.library_album_filter is None and
                  self.library_tag_filter is None)
        context = self.full_library_button.get_style_context()
        if active:
            context.add_class('active')
        else:
            context.remove_class('active')

    def create_playlist_dialog(self, *_):
        if not self.client:
            self.song_count.set_text('Connect to Plex to create a playlist')
            return
        section = self.library.get_active_id()
        songs = (LocalCache(self.client).read_song_index(section) if section else None) or \
            self.song_catalog or self.songs
        if not songs:
            self.song_count.set_text('Load songs before creating a playlist')
            return
        dialog = Gtk.Dialog(title='New Plex playlist', transient_for=self, modal=True)
        dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
        create = dialog.add_button('Create', Gtk.ResponseType.OK)
        create.get_style_context().add_class('suggested-action')
        create.set_sensitive(False)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=16)
        entry = Gtk.Entry(placeholder_text='Playlist name')
        content.pack_start(entry, False, False, 0)
        content.pack_start(Gtk.Label(label='Choose the first song for this playlist', xalign=0),
                           False, False, 0)
        song_search = Gtk.SearchEntry(placeholder_text='Find a song')
        content.pack_start(song_search, False, False, 0)
        choices = Gtk.ListBox()
        choices.set_selection_mode(Gtk.SelectionMode.SINGLE)
        song_scroll = self.scroll(choices)
        song_scroll.set_size_request(420, 210)
        content.pack_start(song_scroll, True, True, 0)
        dialog.get_content_area().add(content)
        def fill_choices(*_args):
            for old in choices.get_children():
                old.destroy()
            words = song_search.get_text().casefold().split()
            matches = (song for song in songs if all(
                word in f'{song.title} {song.artist} {song.album}'.casefold()
                for word in words))
            for song in list(matches)[:60]:
                row = Gtk.ListBoxRow()
                row.track = song
                row.add(Gtk.Label(label=f'{song.title}  ·  {song.artist}', xalign=0,
                                  margin=5, ellipsize=Pango.EllipsizeMode.END))
                choices.add(row)
                row.show_all()
            create.set_sensitive(bool(entry.get_text().strip()) and
                                 choices.get_selected_row() is not None)
        song_search.connect('search-changed', fill_choices)
        entry.connect('changed', lambda *_args: create.set_sensitive(
            bool(entry.get_text().strip()) and choices.get_selected_row() is not None))
        choices.connect('row-selected', lambda *_args: create.set_sensitive(
            bool(entry.get_text().strip()) and choices.get_selected_row() is not None))
        fill_choices()
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        title = entry.get_text().strip()
        selected = choices.get_selected_row()
        first_track = selected.track if selected else None
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        if not title or first_track is None:
            self.song_count.set_text('Enter a name and choose the first song')
            return
        client = self.client
        self.song_count.set_text(f'Creating playlist “{title}”…')
        def created(playlist):
            self.active_playlist = None
            self.playlist_restore_key = playlist.key
            self.song_count.set_text(f'Created playlist “{playlist.title}”')
            self.load_playlists()
        self.async_work(lambda: client.create_playlist(title, first_track), created,
                        lambda: client is self.client,
                        lambda: self.song_count.set_text(
                            'Could not create playlist. ' + self.status.get_text()))

    def selected_song_indices(self):
        _model, paths = self.song_view.get_selection().get_selected_rows()
        return [index for path in paths
                if 0 <= (index := path.get_indices()[0]) < len(self.songs)]

    @staticmethod
    def selected_track_indices(view, tracks):
        _model, paths = view.get_selection().get_selected_rows()
        return sorted(index for path in paths
                      if 0 <= (index := path.get_indices()[0]) < len(tracks))

    @staticmethod
    def track_drag_candidates(view, event, tracks):
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return []
        modifiers = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK
        if getattr(event, 'state', 0) & modifiers:
            return None  # GTK updates the selection after the press handler.
        index = hit[0].get_indices()[0]
        if not 0 <= index < len(tracks):
            return []
        return (Player.selected_track_indices(view, tracks)
                if view.get_selection().path_is_selected(hit[0]) else [index])

    @staticmethod
    def restore_drag_selection(view, indices):
        selection = view.get_selection()
        for index in indices:
            selection.select_path(Gtk.TreePath.new_from_indices([index]))

    def collection_drag_begin(self, view, context, source):
        tracks = self.tracks if source == 'album' else self.style_display_songs
        indices = getattr(self, f'{source}_drag_candidates', None)
        if indices is None:
            indices = Player.selected_track_indices(view, tracks)
        indices = [index for index in indices if 0 <= index < len(tracks)]
        setattr(self, f'{source}_drag_tracks', tuple(tracks[index] for index in indices))
        setattr(self, f'{source}_drag_client', self.client)
        if indices:
            Player.restore_drag_selection(view, indices)
            self.set_track_drag_icon(context, tracks, indices, view)

    def collection_drag_end(self, _view, _context, source):
        setattr(self, f'{source}_drag_candidates', None)
        setattr(self, f'{source}_drag_tracks', None)
        setattr(self, f'{source}_drag_client', None)

    def set_track_drag_icon(self, context, tracks, indices, view=None):
        if isinstance(view, Gtk.TreeView):
            surface = view.create_row_drag_icon(Gtk.TreePath.new_from_indices([indices[0]]))
            if surface is not None:
                Gtk.drag_set_icon_surface(context, normalize_surface_origin(surface))
                return
        icon = Gtk.Label(label=self.song_drag_description(tracks, indices))
        icon.set_name('song-drag-ghost')
        icon.set_max_width_chars(36)
        icon.set_ellipsize(Pango.EllipsizeMode.END)
        icon.show()
        Gtk.drag_set_icon_widget(context, icon, 10, 10)

    def song_drag_begin(self, view, context):
        indices = getattr(self, 'song_drag_candidate_indices', None)
        if indices is None:
            indices = self.selected_song_indices()
        indices = [index for index in indices if 0 <= index < len(self.songs)]
        self.song_drag_indices = indices
        self.song_drag_tracks = tuple(self.songs[index] for index in indices)
        self.song_drag_client = self.client
        if not indices:
            return
        Player.restore_drag_selection(view, indices)
        self.set_track_drag_icon(context, self.songs, indices, view)

    def song_drag_end(self, _view, _context):
        Player.set_playlist_drop_target(self, None)
        self.song_drag_indices = []
        self.song_drag_candidate_indices = None
        self.song_drag_tracks = None
        self.song_drag_client = None

    def song_drag_data_get(self, _view, _context, selection, info, _time):
        tracks = getattr(self, 'song_drag_tracks', None)
        if tracks is None:
            indices = getattr(self, 'song_drag_indices', None) or self.selected_song_indices()
            tracks = [self.songs[index] for index in indices if 0 <= index < len(self.songs)]
        data = encode_track_keys([track.key for track in tracks])
        if data:
            selection.set(selection.get_target(), 8, data)

    def playlist_pointer_mode(self):
        return bool(getattr(self, 'library_view_mode', 'songs') != 'albums' and
                    self.active_playlist and not self.active_playlist.smart and
                    not self.active_smart_playlist and
                    self.library_album_filter is None and
                    not self.library_search.get_text().strip() and
                    self.effective_library_sort() is None)

    def update_song_drag_mode(self):
        if self.song_native_drag_enabled:
            self.song_view.unset_rows_drag_source()
            self.song_native_drag_enabled = False

    def playlist_reorder_allowed(self):
        return bool(self.client and self.playlist_pointer_mode() and
                    len(self.songs) == self.song_total and
                    not getattr(self, 'playlist_reorder_pending', False) and
                    all(song.playlist_item_id > 0 for song in self.songs))

    def song_drop_position(self, x, y, show_marker=False):
        hit = self.song_view.get_path_at_pos(int(x), int(y))
        if hit:
            path = hit[0]
            area = self.song_view.get_background_area(path, None)
            after = y >= area.y + area.height / 2
            if show_marker:
                self.song_view.set_drag_dest_row(
                    path, Gtk.TreeViewDropPosition.AFTER if after
                    else Gtk.TreeViewDropPosition.BEFORE)
                self.show_song_drop_line(
                    self.song_view, area.y + (area.height if after else 0))
            return path.get_indices()[0] + int(after)
        if show_marker and self.songs:
            path = Gtk.TreePath.new_from_indices([len(self.songs) - 1])
            self.song_view.set_drag_dest_row(path, Gtk.TreeViewDropPosition.AFTER)
            area = self.song_view.get_background_area(path, None)
            self.show_song_drop_line(self.song_view, area.y + area.height)
        return len(self.songs)

    def song_pointer_motion(self, view, event):
        drag = getattr(self, 'song_pointer_drag', None)
        if not drag or not (event.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        if not drag['active']:
            if abs(event.x - drag['x']) < 5 and abs(event.y - drag['y']) < 5:
                return False
            drag['active'] = True
            Player.prepare_song_drag_ghost(self, view, drag)
            if hasattr(view, 'get_selection'):
                Player.restore_drag_selection(view, drag['indices'])
        self.show_song_drag_ghost(view, event, self.songs, drag['indices'])
        if Player.update_playlist_drop_target(self, event):
            self.hide_song_drop_line()
            view.set_drag_dest_row(None, Gtk.TreeViewDropPosition.BEFORE)
        elif self.playlist_reorder_allowed():
            self.song_drop_position(event.x, event.y, show_marker=True)
        return True

    def pointer_position_in(self, widget, event):
        if not hasattr(event, 'x_root') or not widget.get_mapped():
            return None
        origin = self.get_window().get_origin()[-2:]
        translated = widget.translate_coordinates(self, 0, 0)
        if not translated:
            return None
        offset_x, offset_y = translated[-2:]
        x = event.x_root - origin[0] - offset_x
        y = event.y_root - origin[1] - offset_y
        if 0 <= x < widget.get_allocated_width() and 0 <= y < widget.get_allocated_height():
            return x, y
        return None

    def song_pointer_release(self, view, event):
        if event.button != 1:
            return False
        drag = getattr(self, 'song_pointer_drag', None)
        self.song_pointer_drag = None
        self.hide_song_drag_ghost()
        self.hide_song_drop_line()
        Player.set_playlist_drop_target(self, None)
        view.set_drag_dest_row(None, Gtk.TreeViewDropPosition.BEFORE)
        if not drag or not drag['active']:
            return False
        if self.pointer_position_in(self.queue_nav, event) is not None:
            self.enqueue_tracks([self.songs[index] for index in drag['indices']])
            return True
        playlist_position = self.pointer_position_in(self.playlist_list, event)
        if playlist_position is not None:
            row = self.playlist_list.get_row_at_y(int(playlist_position[1]))
            if row is not None and row.playlist is not None and not row.playlist.smart:
                self.add_tracks_to_playlist(
                    row.playlist, [self.songs[index] for index in drag['indices']])
                return True
        if self.pointer_position_in(view, event) is None:
            return True
        if self.playlist_reorder_allowed():
            return self.move_playlist_rows(drag['indices'],
                                           self.song_drop_position(event.x, event.y))
        return True

    def move_playlist_rows(self, indices, destination):
        try:
            updated, moves = playlist_move_plan(self.songs, indices, destination)
        except ValueError:
            return False
        if not moves:
            return False
        Player.note_song_cache_edit(self)
        playlist = self.active_playlist
        client = self.client
        section = self.library.get_active_id()
        old_positions = {song.playlist_item_id: index for index, song in enumerate(self.songs)}
        self.song_store.reorder([old_positions[song.playlist_item_id] for song in updated])
        self.songs[:] = updated
        self.song_results = list(updated)
        cached = self.song_view_cache.get(self.song_view_key)
        if cached is not None:
            cached['results'] = list(updated)
        for key in list(self.song_view_cache):
            if key[2] == playlist.key and key != self.song_view_key:
                del self.song_view_cache[key]
        if self.song_catalog_source == (client, section, playlist.key, None):
            self.song_catalog = list(updated)
        self.playlist_reorder_pending = True
        self.song_count.set_text(f'Saving order in {playlist.title}…')
        def work():
            for item_id, after_id in moves:
                client.move_playlist_item(playlist, item_id, after_id)
            LocalCache(client).save_song_index(section, updated, playlist.key)
        def saved(_result):
            self.playlist_reorder_pending = False
            if client is self.client and self.active_playlist is playlist:
                self.song_count.set_text(f'{len(updated)} of {len(updated)} songs • Playlist order')
        def failed():
            self.playlist_reorder_pending = False
            try:
                LocalCache(client).song_index_path(section, playlist.key).unlink(missing_ok=True)
            except OSError:
                pass
            for key in list(self.song_view_cache):
                if key[2] == playlist.key:
                    del self.song_view_cache[key]
            if client is self.client and self.active_playlist and self.active_playlist.key == playlist.key:
                self.invalidate_song_catalog()
                self.load_songs()
                self.status.set_text('Could not save playlist order on Plex')
        self.async_work(work, saved, lambda: True, failed)
        return True

    def drag_media_key(self, _widget, _context, selection, _info, _time, key):
        selection.set(selection.get_target(), 8, key.encode('utf-8'))

    def album_drag_begin(self, _widget, context, album, image):
        self.dragged_album = (self.client, album)
        pixbuf = image.get_pixbuf()
        if pixbuf is not None:
            width, height = pixbuf.get_width(), pixbuf.get_height()
            scale = min(1.0, 96 / max(width, height))
            if scale < 1:
                pixbuf = pixbuf.scale_simple(max(1, round(width * scale)),
                                            max(1, round(height * scale)),
                                            GdkPixbuf.InterpType.BILINEAR)
            Gtk.drag_set_icon_pixbuf(context, pixbuf, 8, 8)

    def album_drag_end(self, _widget, _context):
        self.dragged_album = None

    def dragged_album_for_selection(self, selection):
        key = bytes(selection.get_data() or b'').decode('utf-8', errors='replace')
        source = getattr(self, 'dragged_album', None)
        if source:
            return source[1] if source[0] is self.client and source[1].key == key else None
        return next((album for album in getattr(self, 'albums', ()) if album.key == key), None)

    def resolve_loaded_tracks(self, keys):
        if not keys:
            return []
        wanted = set(keys)
        found = {}
        client = getattr(self, 'client', None)
        collections = [getattr(self, f'{source}_drag_tracks', None)
                       for source in ('song', 'album', 'style', 'time')
                       if getattr(self, f'{source}_drag_client', None) is client]
        collections.extend(getattr(self, name, None) for name in
                           ('songs', 'song_catalog', 'tracks'))
        if getattr(self, 'queue_client', client) is client:
            collections.extend((getattr(self, 'queue', None), getattr(self, 'play_history', None)))
        style_source = getattr(self, 'style_result_source', None)
        if style_source and style_source[0] is client:
            collections.extend((getattr(self, 'style_display_songs', None),
                                getattr(self, 'style_result_songs', None)))
        grid = getattr(self, 'grid', None)
        if grid is not None:
            collections.extend(child.get_child().tracks for child in grid.get_children())
        for collection in collections:
            for track in collection or ():
                if track.key in wanted and track.key not in found:
                    found[track.key] = track
                    if len(found) == len(wanted):
                        return [found[key] for key in keys]
        return []

    def find_loaded_track(self, key):
        tracks = self.resolve_loaded_tracks([key])
        return tracks[0] if tracks else None

    def queue_drop_received(self, _button, context, _x, _y, selection, info, event_time):
        if info == 2:
            return
        action = None
        if info == 0:
            keys = decode_track_keys(selection.get_data())
            tracks = self.resolve_loaded_tracks(keys)
            if tracks and self.client:
                action = lambda: self.enqueue_tracks(tracks)
        elif info == 1:
            album = Player.dragged_album_for_selection(self, selection)
            if album is not None and self.client:
                action = lambda: self.enqueue_album(album)
        Gtk.drag_finish(context, action is not None, False, event_time)
        if action:
            action()

    def enqueue_album(self, album, play_next=False):
        client = self.client
        if client is None:
            return
        self.status.set_text(f'Loading tracks from {album.title}…')
        self.async_work(lambda: client.tracks(album),
                        lambda tracks: self.enqueue_tracks(tracks, play_next),
                        lambda: client is self.client)

    def enqueue_similar_songs(self, song):
        client = self.client
        if client is None:
            return
        section = self.library.get_active_id()
        self.status.set_text('Finding similar songs…')
        session = getattr(self, 'lastfm_session', None)
        credentials = lastfm.application_credentials() or (
            (session['api_key'], session['secret']) if session else None)
        excluded = {item.key for item in getattr(self, 'queue', [])}
        excluded.update(item.key for item in getattr(self, 'play_history', []))
        def work():
            try:
                online = lastfm_similar_tracks(client, section, song, credentials, excluded)
            except (lastfm.LastFMError, OSError):
                online = []
            if getattr(client, 'is_local', False) or len(online) >= 10:
                return online
            try:
                candidates = client.nearest_tracks(song, limit=50)
            except HTTPError as error:
                if error.code == 404 or online:
                    candidates = []
                else:
                    raise
            if section:
                try:
                    candidates.extend(client.metadata_similar_tracks(song, section, limit=50))
                except (HTTPError, OSError):
                    if not online:
                        raise
            return online + [track for track in candidates if track.key not in excluded]
        def ready(candidates):
            chosen = select_similar_tracks(song, candidates, limit=10)
            if not chosen:
                self.status.set_text('No similar songs found in this library (no sonic matches or tracks with matching genre or artist).')
                return
            self.enqueue_tracks(chosen)
            self.status.set_text(f'Added {len(chosen)} similar songs to queue')
        self.async_work(work, ready, lambda: client is self.client)

    def enqueue_tracks(self, tracks, play_next=False):
        if not tracks or not self.client:
            return
        Player.clear_remote_queue(self)
        self.queue, self.index, position = insert_items(
            self.queue, self.index, tracks, play_next)
        if self.queue_album and any(track.album != self.queue_album.title for track in tracks):
            self.queue_album = None
        self.queue_client = self.client
        self.pulse_queue_icon()
        if play_next and self.shuffle.get_active():
            self.shuffle.set_active(False)
        if not (self.stream_open or self.remote_opening):
            self.index = position
            self.start_track()
        else:
            self.refresh_queue_view()
            self.mpris.changed()
            self.persist_session(force=True)
            self.status.set_text(f'Added {len(tracks)} track{"s" if len(tracks) != 1 else ""} to queue')

    def pulse_queue_icon(self):
        self.queue_pulse_started = time.monotonic()
        if not self.queue_pulse_source:
            self.queue_pulse_source = GLib.timeout_add(33, self.animate_queue_pulse)

    def animate_queue_pulse(self):
        elapsed = time.monotonic() - self.queue_pulse_started
        image = self.queue_nav.get_image()
        if elapsed >= 1.1 or self.closed:
            image.set_pixel_size(24)
            self.queue_nav.get_style_context().remove_class('queue-pulse')
            self.queue_pulse_source = 0
            return False
        strength = max(0.0, math.sin(elapsed * math.pi * 4)) * math.exp(-elapsed * 1.5)
        image.set_pixel_size(24 + round(8 * strength))
        self.queue_nav.get_style_context().add_class('queue-pulse')
        return True

    def playlist_drop_received(self, row, context, _x, _y, selection, info, event_time):
        if info == 3:
            album = Player.dragged_album_for_selection(self, selection)
            playlist = row.playlist
            client = self.client
            valid = bool(album and client and playlist and not getattr(playlist, 'smart', False))
            Gtk.drag_finish(context, valid, False, event_time)
            if valid:
                self.song_count.set_text(f'Loading tracks from {album.title}…')
                self.async_work(lambda: client.tracks(album),
                                lambda tracks: Player.add_tracks_to_playlist(self, playlist, tracks),
                                lambda: client is self.client)
            return
        keys = decode_track_keys(selection.get_data())
        tracks = self.resolve_loaded_tracks(keys)
        playlist = row.playlist
        if not tracks or playlist is None or getattr(playlist, 'smart', False) or not self.client:
            Gtk.drag_finish(context, False, False, event_time)
            return
        Gtk.drag_finish(context, True, False, event_time)
        Player.add_tracks_to_playlist(self, playlist, tracks)

    def add_tracks_to_playlist(self, playlist, tracks):
        if not self.client or not tracks or getattr(playlist, 'smart', False):
            return
        Player.note_song_cache_edit(self)
        client = self.client
        sections = tuple(section for section, _name in getattr(self, 'sections', ()))
        self.song_count.set_text(f'Adding {len(tracks)} track(s) to {playlist.title}…')
        def work():
            try:
                for track in tracks:
                    client.add_playlist_item(playlist, track)
            finally:
                for section in sections:
                    try:
                        LocalCache(client).song_index_path(section, playlist.key).unlink(missing_ok=True)
                    except OSError:
                        pass
        def added(_result):
            self.song_count.set_text(f'Added {len(tracks)} track(s) to {playlist.title}')
            for key in list(self.song_view_cache):
                if key[2] == playlist.key:
                    del self.song_view_cache[key]
            if self.active_playlist and self.active_playlist.key == playlist.key:
                self.invalidate_song_catalog()
                self.load_songs()
        def failed():
            for key in list(self.song_view_cache):
                if key[2] == playlist.key:
                    del self.song_view_cache[key]
            if self.active_playlist and self.active_playlist.key == playlist.key:
                self.invalidate_song_catalog()
                self.load_songs()
            self.song_count.set_text('Could not add every selected track to ' + playlist.title)
        self.async_work(work, added, lambda: client is self.client, failed)

    @staticmethod
    def library_list_lines_icon():
        icon = Gtk.DrawingArea()
        icon.set_has_window(False)
        icon.set_size_request(20, 20)
        def draw(widget, context):
            parent = widget.get_parent()
            style = (parent or widget).get_style_context()
            Gdk.cairo_set_source_rgba(context, style.get_color(style.get_state()))
            context.set_line_width(2)
            context.set_line_cap(cairo.LINE_CAP_ROUND)
            width = widget.get_allocated_width()
            for y in (4.5, 9.5, 14.5):
                context.move_to(3, y)
                context.line_to(max(3, width - 3), y)
            context.stroke()
            return False
        icon.connect('draw', draw)
        return icon

    @staticmethod
    def apply_library_row_alignment(player):
        alignment = 0.0 if getattr(player, 'library_view_mode', 'songs') == 'albums' else 0.5
        for _column, renderer, _text in getattr(player, 'song_cell_attributes', ()):
            renderer.set_property('yalign', alignment)

    def album_gutter_row_size(self, _column, cell, model, row, _data=None):
        overlay = getattr(self, 'album_group_overlay', None)
        index = model.get_path(row).get_indices()[0]
        count = (overlay.group_ends.get(index) if overlay is not None and
                 getattr(self, 'library_view_mode', 'songs') == 'albums' else None)
        cell.set_fixed_size(-1, album_group_row_height(count, self.text_size) if count else -1)

    def library_view_mode_changed(self, _button, mode):
        if mode not in ('songs', 'albums') or getattr(self, '_changing_library_view_mode', False):
            return
        changed = self.library_view_mode != mode
        self._changing_library_view_mode = True
        try:
            self.library_view_mode = mode
            self.library_list_mode_button.set_active(mode == 'songs')
            self.library_album_mode_button.set_active(mode == 'albums')
        finally:
            self._changing_library_view_mode = False
        if not changed:
            return
        self.album_gutter_column.set_visible(mode == 'albums')
        self.album_group_overlay.set_visible(mode == 'albums')
        Player.apply_library_row_alignment(self)
        try:
            save_library_view_mode(mode)
        except OSError:
            self.status.set_text('Could not save library view setting.')
        self.load_songs()

    def library_search_changed(self, *_):
        if self.library_search_timeout:
            GLib.source_remove(self.library_search_timeout)
        self.library_search_timeout = GLib.timeout_add(180, self.apply_library_search)

    def apply_library_search(self):
        self.library_search_timeout = 0
        self.load_songs()
        return False

    def configure_song_column(self, column, field):
        column.set_clickable(True)
        column.set_resizable(True)
        column.set_reorderable(True)
        column.set_expand(False)
        column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        column.set_fixed_width({'title': 280, 'artist': 170, 'album': 190,
                                'duration': 75}.get(field, 120))
        column.connect('clicked', self.song_column_clicked, field)
        column.connect('notify::width', self.library_columns_changed)
        column.connect('notify::fixed-width', self.library_columns_changed)
        header = Gtk.EventBox()
        header.set_visible_window(False)
        header.set_name('library-sort-header')
        header.set_size_request(max(1, column.get_fixed_width() - 8), -1)
        header_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5,
                                 margin=3)
        header_content.set_hexpand(True)
        title = Gtk.Label(label=column.get_title(), xalign=0)
        title.set_hexpand(True)
        header_content.pack_start(title, True, True, 0)
        arrow = Gtk.Label()
        arrow.get_style_context().add_class('sort-arrow')
        arrow.set_no_show_all(True)
        arrow.hide()
        arrow.set_margin_end(4)
        header_content.pack_start(arrow, False, False, 0)
        header.add(header_content)
        header.connect('map', self.attach_song_header_button, column, field)
        column.connect('notify::width', self.song_header_width_changed, header)
        header.show_all()
        column.set_widget(header)
        column.sort_arrow = arrow
        column.sort_header = header
        self.song_columns[field] = column

    def song_header_width_changed(self, column, _property, header):
        width = max(1, column.get_width() - 8)
        if getattr(header, 'requested_width', None) != width:
            header.requested_width = width
            header.set_size_request(width, -1)

    @staticmethod
    def bind_song_cell_backgrounds(player):
        # Let GTK paint alternating rows and selections natively. Rebinding a
        # column for a theme change avoids updating every row in large models.
        color_column = len(LIBRARY_COLUMNS) + {'dark': 1, 'light': 2, 'black': 3}.get(
            player.theme, 1)
        for column, cell, text_column in getattr(player, 'song_cell_attributes', ()):
            column.clear_attributes(cell)
            if text_column is not None:
                column.add_attribute(cell, 'text', text_column)
            column.add_attribute(cell, 'cell-background', color_column)

    def library_playing_marker(self, column, cell, model, row, _data=None):
        index = model.get_path(row).get_indices()[0]
        marker = (Player.current_track_marker(self, self.songs[index].key)
                  if index < len(self.songs) else '')
        # A renderer is reused for every row. Most rows have no marker, so
        # avoid rebuilding the same Pango style on every cell and every frame.
        if getattr(cell, '_library_marker', None) != marker:
            cell.set_property('text', marker)
            Player.style_playback_cell(cell, marker)
            if getattr(self, 'library_view_mode', 'songs') == 'albums':
                cell.set_property('yalign', 0.0)
            cell._library_marker = marker
        color = (self.current_art_bright if self.art_accent_enabled and
                 self.current_art_bright else self.accent_color)
        if getattr(cell, '_library_marker_color', None) != color:
            cell.set_property('foreground', color)
            cell._library_marker_color = color

    def queue_marker_cell(self, _column, cell, model, row, _data=None):
        marker = model.get_value(row, 1)
        active = marker in ('▶', PAUSE_MARKER)
        Player.style_playback_cell(cell, marker if active else '')
        cell.set_property('foreground',
                          (self.current_art_bright if self.art_accent_enabled and
                           self.current_art_bright else self.accent_color)
                          if active else model.get_value(row, 10))

    @staticmethod
    def style_playback_cell(cell, marker):
        paused = marker == PAUSE_MARKER
        cell.set_property('scale', 0.72 if paused else 1.0)
        if paused:
            spacing = Pango.attr_letter_spacing_new(-2 * Pango.SCALE)
            spacing.start_index = 0
            spacing.end_index = len(PAUSE_MARKER.encode('utf-8'))
            attributes = Pango.AttrList()
            attributes.insert(spacing)
            cell.set_property('attributes', attributes)
        else:
            cell.set_property('attributes', None)
        cell.set_property('rise', Pango.SCALE if paused else 0)
        cell.set_property('yalign', 0.5)

    @staticmethod
    def song_column_value(song, field):
        if field == 'duration':
            return clock(song.duration / 1000)
        if field in ('added_at', 'last_played_at'):
            value = getattr(song, field)
            return time.strftime('%Y-%m-%d', time.localtime(value)) if value else ''
        if field == 'user_rating':
            return star_text(song.user_rating)
        if field == 'bitrate':
            return f'{song.bitrate} kb/s' if song.bitrate else ''
        if field in ('disc', 'track_number', 'play_count'):
            value = getattr(song, field)
            return str(value) if value else ''
        return str(getattr(song, field))

    def library_layout_key(self):
        section = self.library.get_active_id()
        if not self.client or not section:
            return None
        smart = getattr(self, 'active_smart_playlist', None)
        source = (smart['id'] if smart else
                  self.active_playlist.key if self.active_playlist else
                  self.library_album_filter.key if self.library_album_filter else
                  self.library_tag_filter.cache_key if self.library_tag_filter else 'all')
        parts = (self.client.address, self.client.token, section, source)
        return hashlib.sha256('\0'.join(parts).encode('utf-8')).hexdigest()

    def library_columns_changed(self, *_):
        if getattr(self, 'library_layout_restoring', False) or getattr(self, 'current_library_layout_key', None) is None:
            return
        if self.library_layout_save_timeout:
            GLib.source_remove(self.library_layout_save_timeout)
        self.library_layout_save_timeout = GLib.timeout_add(400, self.save_library_layout_now)

    def save_library_layout_now(self):
        self.library_layout_save_timeout = 0
        key = self.current_library_layout_key
        if key is None or self.library_layout_restoring:
            return False
        order = [field for column in self.song_view.get_columns()
                 for field, candidate in self.song_columns.items() if candidate is column]
        widths = {field: max(50, min(1200, column.get_fixed_width() or column.get_width()))
                  for field, column in self.song_columns.items()}
        gutter = getattr(self, 'album_gutter_column', None)
        art_width = (gutter.get_width() or gutter.get_fixed_width()) if gutter is not None else AlbumGroupOverlay.GUTTER
        layout = {'order': order, 'widths': widths, 'album_art_width': art_width, 'rating_column_available': True,
                  'visible': [field for field, column in self.song_columns.items()
                              if column.get_visible() or
                              (field == 'user_rating' and
                               getattr(self, 'rating_column_preferred', False))],
                  'sort': list(self.column_sort) if self.column_sort else None}
        try:
            save_library_layout(key, layout)
        except OSError:
            pass
        return False

    def apply_library_layout(self):
        key = self.library_layout_key()
        if key is None or key == self.current_library_layout_key:
            return
        if self.library_layout_save_timeout:
            GLib.source_remove(self.library_layout_save_timeout)
            self.library_layout_save_timeout = 0
        self.save_library_layout_now()
        self.library_layout_restoring = True
        layout = load_library_layout(key) or {}
        fields = {field for _name, field in LIBRARY_COLUMNS}
        legacy = {name for name in load_library_sort_buttons()}
        default_visible = set(BASE_LIBRARY_FIELDS) | {
            field for name, field in LIBRARY_COLUMNS if name in legacy}
        visible = layout.get('visible')
        visible = ({value for value in visible if isinstance(value, str) and value in fields}
                   if isinstance(visible, list) else default_visible)
        if not layout.get('rating_column_available'):
            visible.add('user_rating')
        self.rating_column_preferred = 'user_rating' in visible
        gutter = getattr(self, 'album_gutter_column', None)
        if gutter is not None:
            art_width = layout.get('album_art_width')
            if type(art_width) is not int or not AlbumGroupOverlay.MIN_GUTTER <= art_width <= AlbumGroupOverlay.MAX_GUTTER:
                art_width = AlbumGroupOverlay.GUTTER
            gutter.set_fixed_width(art_width)
        widths = layout.get('widths') if isinstance(layout.get('widths'), dict) else {}
        for field, column in self.song_columns.items():
            column.set_visible((field in BASE_LIBRARY_FIELDS or field in visible) and
                               (field != 'user_rating' or not getattr(
                                   self, 'star_ratings_hidden', False)))
            width = widths.get(field)
            if type(width) is not int or not 50 <= width <= 1200:
                width = {'title': 280, 'artist': 170, 'album': 190,
                         'duration': 75}.get(field, 120)
            column.set_fixed_width(width)
        order = layout.get('order') if isinstance(layout.get('order'), list) else []
        ordered = list(dict.fromkeys(field for field in order
                                     if isinstance(field, str) and field in fields))
        ordered.extend(field for _name, field in LIBRARY_COLUMNS if field not in ordered)
        previous = getattr(self, 'album_gutter_column', None)
        for field in ordered:
            column = self.song_columns[field]
            self.song_view.move_column_after(column, previous)
            previous = column
        sort = layout.get('sort')
        if (isinstance(sort, list) and len(sort) == 2 and
                isinstance(sort[0], str) and sort[0] in fields
                and type(sort[1]) is bool and self.song_columns[sort[0]].get_visible()):
            self.column_sort = sort[0], sort[1]
        else:
            self.column_sort = None
        self.song_sort = 'addedAt:desc'
        self.update_song_sort_headers()
        self.current_library_layout_key = key
        self.library_layout_restoring = False

    def update_song_sort_headers(self):
        sort = self.column_sort
        if sort is None:
            sort = {'addedAt:desc': ('added_at', True),
                    'titleSort': ('title', False),
                    'artist.titleSort,titleSort': ('artist', False)}.get(
                        getattr(self, 'song_sort', None))
        for field, column in self.song_columns.items():
            selected = sort is not None and field == sort[0]
            column.set_sort_indicator(False)
            arrow = getattr(column, 'sort_arrow', None)
            if arrow is not None:
                arrow.set_text('▼' if selected and sort[1] else '▲')
                arrow.set_visible(selected)
            for widget in (getattr(column, 'sort_header', None),
                           getattr(column, 'header_button', None)):
                if widget is not None:
                    context = widget.get_style_context()
                    if selected:
                        context.add_class('sorted')
                    else:
                        context.remove_class('sorted')

    def attach_song_header_button(self, header, column, field):
        if getattr(header, '_sort_context_attached', False):
            return
        parent = header.get_parent()
        while parent is not None and not isinstance(parent, Gtk.Button):
            parent = parent.get_parent()
        if parent is not None:
            parent.connect('button-press-event', self.song_header_pressed, column, field)
            column.header_button = parent
            self.update_song_sort_headers()
            header._sort_context_attached = True

    def song_column_clicked(self, _column, field):
        descending = (not self.column_sort[1]
                      if self.column_sort and self.column_sort[0] == field else False)
        self.choose_library_sort(field, descending)

    def song_header_pressed(self, _header, event, column, field):
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        menu.set_name('apistat-context-menu')
        menu.attach_to_widget(self, None)
        recent = Gtk.MenuItem.new_with_label('Recently added (original order)')
        recent.connect('activate', lambda *_: self.reset_library_sort())
        menu.append(recent)
        menu.append(Gtk.SeparatorMenuItem())
        columns_item = Gtk.MenuItem.new_with_label('Show columns')
        columns_menu = Gtk.Menu()
        columns_menu.set_name('apistat-context-menu')
        for name, optional_field in LIBRARY_COLUMNS[4:]:
            if optional_field == 'user_rating' and self.star_ratings_hidden:
                continue
            item = Gtk.CheckMenuItem.new_with_label(f'Show {name} column')
            item.set_active(self.song_columns[optional_field].get_visible())
            item.connect('toggled', lambda selected, key=optional_field:
                         self.set_library_column_visible(key, selected.get_active()))
            columns_menu.append(item)
        columns_item.set_submenu(columns_menu)
        menu.append(columns_item)
        self.sort_context_menu = menu
        menu.connect('selection-done', lambda selected: selected.destroy())
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def set_library_column_visible(self, field, visible):
        if field == 'user_rating':
            self.rating_column_preferred = visible
            visible = visible and not self.star_ratings_hidden
        self.song_columns[field].set_visible(visible)
        self.library_columns_changed()
        if not visible and self.column_sort and self.column_sort[0] == field:
            self.reset_library_sort()

    def reset_library_sort(self):
        self.column_sort = None
        self.song_sort = 'addedAt:desc'
        self.update_song_sort_headers()
        self.library_columns_changed()
        self.load_songs()

    def choose_library_sort(self, field, descending):
        self.column_sort = field, descending
        self.update_song_sort_headers()
        self.library_columns_changed()
        self.load_songs()

    def effective_library_sort(self):
        if self.column_sort:
            return self.column_sort
        if self.song_sort == 'titleSort':
            return 'title', False
        if self.song_sort == 'artist.titleSort,titleSort':
            return 'artist', False
        return None

    def invalidate_song_catalog(self):
        self.song_catalog_generation += 1
        self.song_catalog_source = None
        self.song_catalog = None
        self.song_catalog_loading = False

    @staticmethod
    def note_song_cache_edit(player):
        def increment():
            player.song_cache_edit_generation = getattr(player, 'song_cache_edit_generation', 0) + 1
        lock = getattr(player, 'song_cache_edit_lock', None)
        if lock is None:
            increment()
        else:
            with lock:
                increment()

    def start_song_catalog(self, client, section, playlist, album_filter, facet=None):
        source = (client, section, playlist.key if playlist else None,
                  album_filter.key if album_filter else None)
        if facet is not None:
            source += (facet,)
        if self.song_catalog_source != source:
            self.invalidate_song_catalog()
            self.song_catalog_source = source
        if self.song_catalog_loading:
            return
        self.song_catalog_generation += 1
        generation = self.song_catalog_generation
        self.song_catalog_loading = True
        cache = LocalCache(client)
        playlist_key = facet.cache_key if facet is not None else (
            playlist.key if playlist else None)
        self.song_count.set_text('Loading songs…')
        valid = lambda: (generation == self.song_catalog_generation and
                         self.song_catalog_source == source and client is self.client)
        def fetch_catalog(still_valid=valid):
            return (client.music_facet_tracks(section, facet, still_valid) if facet is not None
                    else build_song_catalog(client, section, playlist, still_valid))
        def work():
            if album_filter:
                return client.tracks(album_filter), False
            if getattr(client, 'is_local', False):
                return fetch_catalog(), False
            entry = cache.read_song_index_entry(section, playlist_key)
            if entry is not None:
                cached, built_at = entry
                stale = time.time() - built_at > 3600
                # Playlists and facets retain their existing foreground refresh:
                # their mutable membership must not race local playlist edits.
                if playlist_key is None or not stale:
                    return cached, stale
            if not valid():
                return None, False
            catalog = fetch_catalog()
            if catalog is not None and valid():
                try:
                    cache.save_song_index(section, catalog, playlist_key)
                except OSError:
                    pass
            return catalog, False
        def refresh_stale(cached):
            pending_ratings = any(
                state['latest'] > state['confirmed_revision'] and
                state.get('failed_revision') != state['latest']
                for state in getattr(self, 'rating_requests', {}).values())
            if pending_ratings or getattr(self, 'playlist_reorder_pending', False):
                return
            edit_generation = getattr(self, 'song_cache_edit_generation', 0)
            refresh_valid = lambda: (valid() and
                                     getattr(self, 'song_cache_edit_generation', 0) == edit_generation)
            def refresh_work():
                try:
                    if not refresh_valid():
                        return None
                    catalog = fetch_catalog(refresh_valid)
                    if catalog is None or not refresh_valid():
                        return None
                    try:
                        saved = cache.save_song_index(
                            section, catalog, playlist_key, still_current=refresh_valid,
                            commit_lock=getattr(self, 'song_cache_edit_lock', None))
                        if saved is False:
                            return None
                    except OSError:
                        pass
                    return catalog if catalog != cached else None
                except Exception:
                    # Keep serving the cached library if Plex is unavailable.
                    return None
            def refreshed(catalog):
                if catalog is not None:
                    self.song_catalog = catalog
                    self.song_view_cache.clear()
                    self.load_songs()
            self.async_work(refresh_work, refreshed, refresh_valid)
        def loaded(result):
            self.song_catalog_loading = False
            catalog, stale = result
            if catalog is not None:
                self.song_catalog = catalog
                self.load_songs()
                if stale and valid():
                    refresh_stale(catalog)
        def failed():
            self.song_catalog_loading = False
            if self.song_catalog is None:
                self.song_count.set_text('Could not load songs')
        self.async_work(work, loaded, valid, failed)

    def select_playlist(self, _list, row):
        if row is None or getattr(self, 'playlist_list_rebuilding', False):
            return
        self.smart_playlist_list.unselect_all()
        self.active_smart_playlist = None
        self.invalidate_song_catalog()
        self.library_album_filter = None
        self.library_tag_filter = None
        self.library_back_button.hide()
        self.active_playlist = row.playlist
        self.songs_heading.set_text(row.playlist.title if row.playlist else
                                    'Full music library')
        self.update_full_library_selection()
        self.apply_library_layout()
        self.load_songs()

    def activate_song(self, _view, path, _column):
        self.play_song(path.get_indices()[0])

    def play_song(self, index):
        if 0 <= index < len(self.songs):
            Player.clear_remote_queue(self)
            if self.active_playlist:
                self.remote_container = self.active_playlist.key
            self.queue = list(self.song_results if self.song_results is not None else self.songs)
            self.queue_client = self.client
            self.queue_album = None
            self.index = index
            self.start_track()

    def library_changed(self, *_):
        self.song_generation = getattr(self, 'song_generation', 0) + 1
        self.auto_style_facet = None
        self.auto_style_keys.clear()
        if self.style_autoplay_pending:
            waiting = self.style_autoplay_waiting
            self.style_autoplay_generation += 1
            self.style_autoplay_pending = False
            self.style_autoplay_waiting = False
            self.style_autoplay_exhausted = True
            if waiting:
                self.stop()
        if ((self.stream_open or self.remote_opening) and
                self.index == len(self.queue) - 1):
            self.style_autoplay_exhausted = True
        self.album_prefetch_generation += 1
        self.album_prefetch_pending = True
        self.invalidate_song_catalog()
        self.artist_filter = None
        self.artist_catalog = None
        self.artist_filter_bar.hide()
        self.library_album_filter = None
        self.library_tag_filter = None
        self.styles_source = None
        self.styles_facets = None
        self.styles_generation += 1
        self.style_queue_generation += 1
        self.style_result_generation += 1
        self.style_render_generation += 1
        self.style_result_source = None
        self.style_result_songs = None
        self.style_result_facet = None
        self.styles_stack.set_visible_child_name('browser')
        self.library_back_button.hide()
        self.load_smart_playlist_definitions()
        self.apply_library_layout()
        self.ensure_search_index()
        self.load_albums()
        if self.active_playlist is None:
            self.load_songs()
        if self.content_views.get_visible_child_name() == 'styles':
            self.load_styles_browser()

    def prefetch_album_sort_pages(self):
        section = self.library.get_active_id()
        client = self.client
        if not client or not section or getattr(client, 'is_local', False):
            return
        generation = self.album_prefetch_generation
        active_sort = self.album_sort if not self.search.get_text().strip() else None
        cache = LocalCache(client)
        def valid():
            return (not self.closed and self.client is client and
                    generation == self.album_prefetch_generation)
        def worker():
            pages = []
            for _label, sort in ALBUM_SORT_OPTIONS:
                if not valid() or sort == active_sort:
                    continue
                try:
                    page = cached_album_page(cache, client, section, sort)
                except (OSError, ValueError, URLError):
                    continue
                pages.append(page[0])
            for albums in pages:
                for album in albums:
                    if not valid():
                        return
                    if not album.thumb or cache.read_art(album.thumb, ALBUM_SIZE_RANGE[1]):
                        continue
                    try:
                        data = client.get('/photo/:/transcode', width=ALBUM_SIZE_RANGE[1],
                                          height=ALBUM_SIZE_RANGE[1], minSize=1, upscale=1,
                                          url=album.thumb)
                        cache.save_art(album.thumb, ALBUM_SIZE_RANGE[1], data)
                    except (OSError, ValueError, URLError):
                        continue
        self.album_prefetch_thread = threading.Thread(target=worker, daemon=True)
        self.album_prefetch_thread.start()

    def clear_wall(self):
        self.art_epoch += 1
        self.gpu_rebuild_generation = getattr(self, 'gpu_rebuild_generation', 0) + 1
        self.gpu_rebuild_pending = False
        if getattr(self, 'gpu_wall', None):
            self.gpu_wall.set_albums(self.client, [], reset=True)
        if getattr(self, 'album_canvas', None):
            self.album_canvas.set_albums(None, [], reset=True)
        self.canvas_catalog = None
        self.canvas_catalog_identity = None
        self.last_flipped_tile = None
        self.pending_flipped_tile = None
        for child in self.grid.get_children():
            child.destroy()
        self.views.set_visible_child_name('wall')

    def load_art(self, client, album, image, size, valid, on_pixbuf=None):
        if not album.thumb:
            return
        cache = LocalCache(client)
        def fetch(force_remote=False):
            if self.closed or not valid():
                return
            data = None if force_remote else cache.read_art(album.thumb, size)
            cached_size = size
            if data is None and not force_remote and size <= 56:
                data = cache.read_art(album.thumb, NOW_SIZE_RANGE[1])
                if data is not None:
                    cached_size = NOW_SIZE_RANGE[1]
            from_cache = data is not None
            try:
                if data is None:
                    data = client.get('/photo/:/transcode', width=size, height=size,
                                      minSize=1, upscale=1, url=album.thumb)
                    try:
                        cache.save_art(album.thumb, size, data)
                    except OSError:
                        pass
            except Exception:
                return  # Missing artwork retains the placeholder.
            try:
                # Decoding large or compressed artwork can take noticeable time.
                # Pixbufs are data objects; only the widget update belongs on GTK.
                loader = GdkPixbuf.PixbufLoader()
                loader.set_size(size, size)
                loader.write(data)
                loader.close()
                pixbuf = loader.get_pixbuf()
            except GLib.Error:
                if from_cache:
                    try:
                        cache.art_path(album.thumb, cached_size).unlink(missing_ok=True)
                    except OSError:
                        pass
                    fetch(True)
                return
            def show():
                if self.closed or not valid():
                    return False
                image.art_source = pixbuf
                image.placeholder_art = False
                if hasattr(image, 'art_display_size'):
                    self.set_art_size(image, image.art_display_size)
                else:
                    image.set_from_pixbuf(pixbuf)
                if on_pixbuf:
                    on_pixbuf(pixbuf)
                return False
            GLib.idle_add(show)
        def submit_fetch(force_remote=False):
            future = self.art_workers.submit(fetch, force_remote)
            self.busy.begin()
            future.add_done_callback(lambda _completed: GLib.idle_add(self.busy.end))
        submit_fetch()

    def add_album_tile(self, album, grid=None, on_album=None):
        grid = grid if grid is not None else self.grid
        tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        tile.album_grid = grid
        tile.open_album = on_album or self.select_album
        tile.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        tile.connect('button-press-event',
                     lambda _widget, event: self.album_context_menu_pressed(tile, event))
        front = Gtk.Button()
        album_target = [Gtk.TargetEntry.new('application/x-plex-album-key',
                                            Gtk.TargetFlags.SAME_APP, 1)]
        front.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, album_target,
                              Gdk.DragAction.COPY)
        front.connect('drag-data-get', self.drag_media_key, album.key)
        front.connect('button-press-event',
                      lambda _widget, event: self.album_context_menu_pressed(tile, event))
        age = added_age_label(album.added_at)
        self.set_tooltip(front, f'{album.title}\n{album.artist}\n{age}')
        front.get_accessible().set_name(f'Flip {album.title} by {album.artist} to show tracks')
        image = Gtk.Image()
        self.set_placeholder_art(image, self.album_art_size,
                                 SMALL_PLACEHOLDER_LOGO_RATIO)
        front.add(image)
        front.connect('drag-begin', self.album_drag_begin, album, image)
        front.connect('drag-end', self.album_drag_end)
        metadata = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        metadata.set_size_request(self.album_art_size, -1)
        tile.pack_end(metadata, False, False, 0)
        for index, (value, name) in enumerate(((album.title, 'album-title'),
                                               (album.artist, 'album-meta'),
                                               (album_info_label(album, self.album_sort), 'album-meta'))):
            label = Gtk.Label(label=value, xalign=0.5)
            label.set_name(name)
            label.set_opacity((1., .78, .55)[index])
            if index == 2:
                attributes = Pango.AttrList()
                attributes.insert(Pango.attr_scale_new(.88))
                label.set_attributes(attributes)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_max_width_chars(1)
            if index == 1:
                artist_click = Gtk.EventBox()
                artist_click.set_visible_window(False)
                artist_click.add(label)
                artist_click.connect('button-press-event', self.artist_name_pressed,
                                     lambda artist=album.artist: artist)
                metadata.pack_start(artist_click, False, False, 0)
            else:
                metadata.pack_start(label, False, False, 0)
            if index == 2:
                age_label = label
        back = Gtk.Overlay()
        background = DitheredGradient()
        background.set_colors(('#292238', '#111e2b'))
        back.add(background)
        back_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, margin=5)
        back_content.set_name('album-card-back')
        back.add_overlay(back_content)
        tracks_scroll = Gtk.ScrolledWindow()
        tracks_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        tracks_scroll.set_min_content_width(1)
        tracks_scroll.set_min_content_height(1)
        tracks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        tracks_box.set_valign(Gtk.Align.CENTER)
        loading = Gtk.Label(label='Loading tracks…')
        loading.set_ellipsize(Pango.EllipsizeMode.END)
        loading.set_max_width_chars(1)
        tracks_box.pack_start(loading, False, False, 0)
        tracks_scroll.add(tracks_box)
        self.attach_smooth_scroll(tracks_scroll)
        back_content.pack_start(tracks_scroll, True, True, 0)
        footer = Gtk.Box(spacing=5)
        footer.set_homogeneous(True)
        cover_button = Gtk.Button(label='‹' if self.album_art_size < 100 else '‹ Cover')
        cover_button.set_name('album-cover-button')
        cover_button.get_child().set_valign(Gtk.Align.CENTER)
        self.set_tooltip(cover_button, 'Flip back to album art')
        footer.pack_start(cover_button, True, True, 0)
        explore_button = Gtk.Button()
        explore_button.set_name('album-explore-button')
        explore_button.set_size_request(1, -1)
        explore_label = Gtk.Label(label='Explore Related')
        explore_label.set_valign(Gtk.Align.CENTER)
        explore_label.set_ellipsize(Pango.EllipsizeMode.END)
        explore_label.set_max_width_chars(16)
        explore_button.add(explore_label)
        explore_button.get_accessible().set_name('Explore related albums')
        self.set_tooltip(explore_button, 'Explore related albums')
        explore_button.connect('clicked', lambda *_: self.open_album_web(album))
        explore_button.connect('button-press-event',
                               lambda _widget, event: self.album_context_menu_pressed(tile, event))
        footer.pack_end(explore_button, True, True, 0)
        back_content.pack_end(footer, False, False, 0)
        flip_card = FlipCard(front, back, self.album_art_size)
        tile.pack_start(flip_card, False, False, 0)
        tile.album = album
        tile.art_image = image
        tile.metadata_box = metadata
        tile.age_label = age_label
        tile.age_album = album
        tile.tracks_box = tracks_box
        tile.tracks = None
        tile.track_buttons = []
        tile.tracks_loading = False
        tile.pending_tracks = None
        tile.pending_tracks_error = False
        tile.flip_card = flip_card
        flip_card.on_side_shown = lambda side: self.album_side_shown(tile, side)
        tile.cover_button = cover_button
        tile.back_gradient = background
        background.set_fallback_color('#f5f5f3' if self.theme == 'light' else '#000000')
        front.connect('clicked', lambda *_: self.flip_album_card(tile))
        front.connect('enter-notify-event', lambda *_: flip_card.prepare())
        if len(grid.get_children()) < 16:
            flip_card.connect('map', lambda card: GLib.idle_add(
                card.prepare, priority=GLib.PRIORITY_LOW))
        cover_button.connect('clicked', lambda *_: self.flip_album_card(tile))
        grid.add(tile)
        epoch = self.art_epoch
        def show_back_colors(pixbuf):
            tile.back_art_colors = self.cached_art_colors(self.client, album, pixbuf)[0]
            background.set_colors(theme_gradient_colors(tile.back_art_colors, self.theme))
        self.load_art(self.client, album, image, ALBUM_SIZE_RANGE[1],
                      lambda: epoch == self.art_epoch, show_back_colors)
        tile.show_all()
        metadata.set_visible(self.show_album_details)

    def flip_album_card(self, tile):
        flip = tile.flip_card
        target = 'front' if (flip.target if flip.animating else flip.side) == 'back' else 'back'
        if target == 'back':
            self.pending_flipped_tile = tile
            self.load_card_tracks(tile)
        elif self.pending_flipped_tile is tile:
            self.pending_flipped_tile = None
        flip.show_side(target)

    def album_side_shown(self, tile, side):
        if side == 'front':
            if self.last_flipped_tile is tile:
                self.last_flipped_tile = None
            return
        if self.single_flip_enabled and self.pending_flipped_tile is not tile:
            return
        if self.single_flip_enabled:
            for child in getattr(tile, 'album_grid', self.grid).get_children():
                other = child.get_child()
                if other is not tile:
                    other.flip_card.show_side('front')
        self.last_flipped_tile = tile
        if self.pending_flipped_tile is tile:
            self.pending_flipped_tile = None
        if getattr(tile, 'pending_tracks', None) is not None:
            tracks = tile.pending_tracks
            tile.pending_tracks = None
            self.show_card_tracks(tile, tracks)
        elif getattr(tile, 'pending_tracks_error', False):
            tile.pending_tracks_error = False
            self.show_card_track_error(tile)

    def request_album_card_tracks(self, client, album, done, valid, failed):
        """Share album track requests and keep successful results for this session."""
        cache = getattr(self, '_album_card_tracks', None)
        if cache is None:
            cache = self._album_card_tracks = {}
            self._album_card_pending = {}
        key = (client, album.key)
        if key in cache:
            if valid():
                done(cache[key])
            return
        pending = self._album_card_pending
        if key in pending:
            pending[key].append((done, valid, failed))
            return
        pending[key] = [(done, valid, failed)]
        def loaded(tracks):
            cache[key] = tracks
            for callback, still_valid, _failed in pending.pop(key, []):
                if still_valid():
                    callback(tracks)
        def error():
            for _callback, still_valid, on_error in pending.pop(key, []):
                if still_valid():
                    on_error()
        self.async_work(lambda: client.tracks(album), loaded,
                        lambda: not getattr(self, 'closed', False), error)

    def load_card_tracks(self, card):
        if card.tracks is not None or card.tracks_loading or not self.client:
            return
        card.tracks_loading = True
        album = card.album
        client = self.client
        epoch = self.art_epoch
        def loaded(tracks):
            if card.flip_card.animating:
                card.pending_tracks = tracks
            else:
                self.show_card_tracks(card, tracks)
        def failed():
            if card.flip_card.animating:
                card.pending_tracks_error = True
            else:
                self.show_card_track_error(card)
        Player.request_album_card_tracks(
            self, client, album, loaded,
            lambda: epoch == self.art_epoch and client is self.client, failed)

    def show_card_tracks(self, card, tracks):
        card.tracks_loading = False
        card.tracks = tracks
        card.track_buttons = []
        for child in card.tracks_box.get_children():
            child.destroy()
        if not tracks:
            card.tracks_box.pack_start(Gtk.Label(label='No tracks found'), False, False, 0)
        highlights = track_highlights(tracks)
        for index, track in enumerate(tracks):
            button = Gtk.Button()
            song_target = [Gtk.TargetEntry.new('application/x-plex-song-key',
                                               Gtk.TargetFlags.SAME_APP, 0)]
            button.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, song_target,
                                   Gdk.DragAction.COPY)
            button.connect('drag-data-get', self.drag_media_key, track.key)
            def track_menu(_button, event, selected=index, song=track):
                if event.button != 3:
                    return False
                self.show_song_context_menu(
                    event, song, selected,
                    lambda: self.play_card_track(card, selected))
                return True
            button.connect('button-press-event', track_menu)
            row = Gtk.Box(spacing=6)
            play_marker = Gtk.Label(label='', xalign=0.5)
            play_marker.set_name('playing-marker')
            play_marker.set_size_request(22, -1)
            play_marker.set_yalign(0.5)
            number = Gtk.Label(label=f'{index + 1}.')
            number.set_name('album-track-number')
            title = Gtk.Label(label=track.title, xalign=0)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_max_width_chars(1)
            title.set_hexpand(True)
            duration = Gtk.Label(label=clock(track.duration / 1000), xalign=1)
            duration.set_no_show_all(True)
            duration.set_visible(show_track_duration(self.album_art_size))
            row.pack_start(play_marker, False, False, 0)
            row.pack_start(number, False, False, 0)
            row.pack_start(title, True, True, 0)
            right_spacer = Gtk.Label(label=highlights.get(track.key, ''))
            right_spacer.set_size_request(22, -1)
            row.pack_end(right_spacer, False, False, 0)
            row.pack_end(duration, False, False, 0)
            button.add(row)
            button.play_marker = play_marker
            button.highlight_marker = right_spacer
            button.duration_label = duration
            button.connect('drag-begin', self.album_track_drag_begin, track.title)
            self.set_tooltip(button, track.title)
            button.connect('clicked', lambda _button, selected=index: self.play_card_track(card, selected))
            card.tracks_box.pack_start(button, False, False, 0)
            card.track_buttons.append(button)
        card.tracks_box.show_all()
        self.refresh_playing_highlight()

    def show_card_track_error(self, card):
        card.tracks_loading = False
        for child in card.tracks_box.get_children():
            child.destroy()
        card.tracks_box.pack_start(Gtk.Label(label='Could not load tracks'), False, False, 0)
        card.tracks_box.show_all()

    def play_card_track(self, card, index):
        if card.tracks is None or not 0 <= index < len(card.tracks):
            return
        Player.clear_remote_queue(self)
        self.queue_album = card.album
        self.queue = list(card.tracks)
        self.queue_client = self.client
        self.index = index
        self.start_track()

    def refresh_playing_highlight(self):
        time_wall = getattr(getattr(self, 'time_machine', None), 'gpu_wall', None)
        if time_wall is not None:
            time_wall.refresh_flip()
        if getattr(self, 'gpu_wall_enabled', False) and getattr(self, 'gpu_wall', None):
            self.gpu_wall.refresh_flip()
        for grid in (self.grid, getattr(self, 'style_album_grid', None)):
            if grid is None:
                continue
            for child in grid.get_children():
                tile = child.get_child()
                for track, button in zip(tile.tracks or [], tile.track_buttons):
                    context = button.get_style_context()
                    marker = Player.current_track_marker(self, track.key)
                    active = bool(marker)
                    if hasattr(button, 'play_marker'):
                        if marker == PAUSE_MARKER:
                            button.play_marker.set_markup(
                                f'<span letter_spacing="-2048" rise="1024">{PAUSE_MARKER}</span>')
                            button.play_marker.get_style_context().add_class('paused')
                        else:
                            button.play_marker.set_text(marker)
                            button.play_marker.get_style_context().remove_class('paused')
                    if active:
                        context.add_class('playing-track')
                    else:
                        context.remove_class('playing-track')
        if hasattr(self, 'track_view'):
            self.track_view.queue_draw()

    def current_track_marker(self, key):
        if not 0 <= self.index < len(self.queue) or self.queue[self.index].key != key:
            return ''
        if self.stream_open:
            return '▶' if getattr(self, 'playing', True) else PAUSE_MARKER
        return '▶' if getattr(self, 'remote_opening', False) else ''

    def album_detail_playing_marker(self, _column, cell, model, row, _data=None):
        index = model.get_path(row).get_indices()[0]
        marker = (Player.current_track_marker(self, self.tracks[index].key)
                  if index < len(self.tracks) else '')
        cell.set_property('text', marker)
        Player.style_playback_cell(cell, marker)
        cell.set_property('foreground', self.current_art_bright
                          if self.art_accent_enabled and self.current_art_bright
                          else self.accent_color)

    def album_track_drag_begin(self, button, context, title):
        width, height = button.get_allocated_width(), button.get_allocated_height()
        if button.get_mapped() and width > 0 and height > 0:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            draw_allocated(button, cairo.Context(surface))
            Gtk.drag_set_icon_surface(context, surface)
            return
        ghost = Gtk.Label(label=title)
        ghost.set_name('song-drag-ghost')
        ghost.show()
        Gtk.drag_set_icon_widget(context, ghost, 8, 8)

    def refresh_album_ages(self):
        if self.closed:
            return False
        for grid in (self.grid, getattr(self, 'style_album_grid', None)):
            if grid is None:
                continue
            for child in grid.get_children():
                tile = child.get_child()
                tile.age_label.set_text(album_info_label(tile.age_album, self.album_sort))
        return True

    def button(self, text, callback):
        button = Gtk.Button(label=text)
        button.connect('clicked', callback)
        return button

    def icon_button(self, icon, name, callback):
        button = Gtk.Button()
        button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
        self.set_tooltip(button, name)
        button.get_accessible().set_name(name)
        button.connect('clicked', callback)
        return button

    def icon_toggle(self, icon, name):
        button = Gtk.ToggleButton()
        button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
        self.set_tooltip(button, name)
        button.get_accessible().set_name(name)
        return button

    def set_play_button_state(self, playing):
        button = getattr(self, 'nav_buttons', {}).get('now')
        image = button.get_image() if button is not None else None
        if isinstance(image, SidebarIcon):
            image.set_playing(playing and getattr(self, 'sidebar_note_animation_enabled', True))
        name = 'Pause' if playing else 'Play'
        icon = 'media-playback-pause-symbolic' if playing else 'media-playback-start-symbolic'
        image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
        image.set_pixel_size(38)
        self.play_button.set_image(image)
        self.set_tooltip(self.play_button, name)
        self.play_button.get_accessible().set_name(name)

    def scroll(self, child, *, overlay_scrolling=None):
        scroll = Gtk.ScrolledWindow()
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        if overlay_scrolling is not None:
            scroll.set_overlay_scrolling(overlay_scrolling)
        scroll.add(child)
        return self.attach_smooth_scroll(scroll)

    @staticmethod
    def stable_library_scrollbar(scroll, auto_hide=False):
        """Keep the library scrollbar outside the redrawn scrolled window."""
        horizontal, _vertical = scroll.get_policy()
        scroll.set_policy(horizontal, Gtk.PolicyType.EXTERNAL)
        scroll.set_overlay_scrolling(False)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row.pack_start(scroll, True, True, 0)
        scrollbar = Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL,
                                  adjustment=scroll.get_vadjustment())
        scrollbar.set_name('library-stable-scrollbar')
        row.pack_start(scrollbar, False, False, 0)
        if auto_hide:
            scrollbar.set_no_show_all(True)
            pending = [0]
            def update_visibility(adjustment):
                if pending[0]:
                    return
                def apply_visibility():
                    pending[0] = 0
                    if not scrollbar.in_destruction():
                        scrollbar.set_visible(adjustment.get_upper() - adjustment.get_lower() >
                                              adjustment.get_page_size() + 0.5)
                    return False
                pending[0] = GLib.idle_add(apply_visibility)
            def cancel_visibility(*_args):
                if pending[0]:
                    GLib.source_remove(pending[0])
                    pending[0] = 0
            scroll.connect('destroy', cancel_visibility)
            scroll.get_vadjustment().connect('changed', update_visibility)
            update_visibility(scroll.get_vadjustment())
        return row

    def attach_smooth_scroll(self, scroll):
        attach_background_drag(scroll)
        controller = SmoothScroller(scroll, self.smooth_scrolling_enabled)
        self.smooth_scrollers.add(controller)
        return scroll

    def table(self, store, titles):
        view = Gtk.TreeView(model=store)
        for i, title in enumerate(titles):
            renderer = Gtk.CellRendererText()
            renderer.set_property('ellipsize', 3)
            column = Gtk.TreeViewColumn(title, renderer, text=i)
            column.set_resizable(True)
            column.set_expand(i == (1 if titles[0] == '#' else 0))
            column.set_min_width(50)
            view.append_column(column)
        return view

    def async_work(self, work, done, valid=lambda: True, on_error=None):
        self.busy.begin()
        def worker():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, exc
            def deliver():
                try:
                    if self.closed or not valid():
                        return False
                    if error:
                        if isinstance(error, HTTPError):
                            message = f'Plex returned HTTP {error.code}. Check the address, token and library access.'
                        elif isinstance(error, (URLError, TimeoutError)):
                            message = 'Cannot reach Plex. Check the address, network and server certificate.'
                        else:
                            message = 'Request failed. Check server access and media availability.'
                        self.status.set_text(message)  # Never display URLs or tokens in errors.
                        if on_error:
                            on_error()
                    else:
                        done(result)
                    return False
                finally:
                    self.busy.end()
            GLib.idle_add(deliver, priority=GLib.PRIORITY_HIGH_IDLE)
        threading.Thread(target=worker, daemon=True).start()

    def connect_dialog(self, *_):
        self.finish_startup_loading()
        dialog = Gtk.Dialog(title='Connect to Plex', transient_for=self, modal=True)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Connect', Gtk.ResponseType.OK)
        account_response = 1001
        dialog.add_button('Choose from Plex account…', account_response)
        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_border_width(18)
        box.pack_start(Gtk.Label(label='Server URL (HTTPS for remote servers)', xalign=0), False, False, 0)
        address = Gtk.Entry(placeholder_text='http://192.168.1.10:32400')
        current = ((self.client.address, self.client.token) if self.client and
                   not getattr(self.client, 'is_local', False) else self.restored_credentials)
        if current:
            address.set_text(current[0])
        box.pack_start(address, False, False, 0)
        token_store = 'Windows Credential Manager' if os.name == 'nt' else ('macOS Keychain' if sys.platform == 'darwin' else 'desktop keyring')
        box.pack_start(Gtk.Label(label=f'X-Plex-Token (saved in {token_store})', xalign=0), False, False, 0)
        token = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
        if current:
            token.set_text(current[1])
        box.pack_start(token, False, False, 0)
        help_link = Gtk.LinkButton.new_with_label('https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/', 'How to find a temporary Plex token')
        box.pack_start(help_link, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        url, secret = address.get_text(), token.get_text()
        dialog.destroy()
        if response == account_response:
            self.choose_server_from_account()
            return False
        if response != Gtk.ResponseType.OK:
            self.populate_source_selector()
            return False
        self.connect_to_server(url, secret, remember=True)
        return False

    def connect_to_server(self, url, secret, remember=False, automatic=False, source=None):
        try:
            client = source or PlexClient(url, secret, self.remote_config['identifier'],
                                          self.remote_config['name'])
        except ValueError as exc:
            self.status.set_text(str(exc))
            if automatic:
                self.connect_dialog()
            return False
        self.connection_generation += 1
        generation = self.connection_generation
        self.generation += 1
        self.loading_albums = False
        self.stop()
        self.status.set_text('Connecting…')
        def work():
            sections = client.sections()
            try:
                machine = '' if getattr(client, 'is_local', False) else client.xml('/').get('machineIdentifier', '')
            except Exception:
                machine = ''
            saved = True
            if remember:
                try:
                    save_credentials(client.address, client.token)
                except Exception:
                    saved = False
            return sections, saved, machine
        def connected(result):
            sections, saved, machine = result
            self.client = client
            self.new_playlist_button.set_sensitive(not getattr(client, 'is_local', False))
            self.keep_style_playing.set_sensitive(not getattr(client, 'is_local', False))
            self.song_view_cache.clear()
            self.song_view_key = None
            self.remote_server_machine = machine
            self.clear_remote_queue()
            if self.remote_receiver:
                self.remote_receiver.set_server(None if getattr(client, 'is_local', False) else client, machine)
            if hasattr(self, 'source_config'):
                self.source_config['active'] = ('local:' + client.source['id']
                                                if getattr(client, 'is_local', False) else 'plex:current')
                try:
                    save_sources(self.source_config)
                except OSError:
                    self.status.set_text('Could not save selected library source.')
                self.populate_source_selector()
            self.update_remote_status()
            self.index_generation += 1
            self.index_cache = None
            self.indexed_albums = None
            self.index_section = None
            self.index_building = False
            self.index_refresh.set_sensitive(self.search_index_enabled)
            self.index_status.set_text('Choose a music library to build the index'
                                       if self.search_index_enabled else 'Index is off')
            self.restored_credentials = None
            self.play_history.clear()
            self.current_played_track = None
            store = 'Windows Credential Manager' if os.name == 'nt' else ('macOS Keychain' if sys.platform == 'darwin' else 'desktop keyring')
            self.credential_warning = '' if saved else f'{store} could not save this login.'
            self.sections = sections
            self.library.remove_all()
            self.clear_wall()
            self.track_store.clear()
            self.albums, self.tracks, self.queue = [], [], []
            self.refresh_queue_view()
            self.songs = []
            self.playlists = []
            self.song_store.clear()
            self.song_total = 0
            self.song_count.set_text('No music library available')
            self.index = -1
            self.selected_album = self.queue_album = None
            self.lyrics_generation += 1
            self.lyrics_request_key = None
            if self.content_views.get_visible_child_name() == 'lyrics':
                self.load_current_lyrics()
            self.now_title.set_text('Nothing playing')
            self.now_artist.set_text('')
            self.set_placeholder_art(self.now_cover, 48)
            self.set_placeholder_art(self.hero_cover,
                                     getattr(self, 'now_display_art_size', self.now_art_size))
            self.current_art_colors = None
            self.current_art_key = None
            self.current_art_bright = None
            self.current_wave_colors = None
            self.render_gradient()
            self.apply_accent()
            self.hero_title.set_text('Nothing playing')
            self.hero_artist.set_text('Choose an album or song to start listening')
            self.hero_album.set_text('')
            self.server_label.set_text(client.source['path'] if getattr(client, 'is_local', False) else client.address)
            self.album_generation += 1
            self.song_generation += 1
            self.playlist_generation += 1
            for row in self.playlist_list.get_children():
                if row is not self.all_songs_row:
                    row.destroy()
            self.active_playlist = None
            self.playlist_restore_key = (self.saved_session.get('playlist')
                                         if self.saved_session.get('server') == client.address else None)
            self.playlist_list.select_row(self.all_songs_row)
            self.library.set_sensitive(True)
            for key, name in sections:
                self.library.append(key, name)
            if sections:
                saved_section = (self.saved_session.get('section')
                                 if self.saved_session.get('server') == client.address else None)
                first_section = (None if getattr(client, 'is_local', False)
                                 else self.choose_initial_library(sections))
                if getattr(client, 'is_local', False):
                    self.first_run_setup = False
                selection = first_section or saved_section
                if not selection or not self.library.set_active_id(selection):
                    self.library.set_active(0)
                self.load_playlists()
            else:
                self.status.set_text('Connected, but no music libraries are available to this token.')
                self.finish_startup_loading()
            if self.credential_warning:
                self.status.set_text(self.credential_warning)
            self.restore_saved_session()
            self.mpris.changed()
            if getattr(client, 'is_local', False):
                self.rescan_local_source(force=False)
        self.async_work(work, connected, lambda: generation == self.connection_generation,
                        self.connect_dialog if automatic else None)
        return False

    def load_albums(self, more=False, force_refresh=False):
        section = self.library.get_active_id()
        if not self.client or not section:
            return
        if getattr(self, 'canvas_enabled', False):
            if not more:
                self.load_canvas_albums(force_refresh)
            return
        if more and self.loading_albums:
            return
        self.loading_albums = True
        self.generation += 1
        generation = self.generation
        client = self.client
        start = len(self.albums) if more else 0
        title = self.search.get_text().strip()
        artist = self.artist_filter
        if artist or title:
            self.artist_filter_label.set_text(
                f'Albums by {artist}' if artist else f'Search results for “{title}”')
            self.artist_filter_bar.set_no_show_all(False)
            self.artist_filter_bar.show_all()
        else:
            self.artist_filter_bar.hide()
        if not more:
            self.album_generation += 1
            self.albums, self.tracks = [], []
            self.clear_wall()
            self.track_store.clear()
            self.album_label.set_text('Choose an album')
            self.album_artist.set_text('')
            self.album_year.set_text('')
            self.set_placeholder_art(self.cover, 160)
        self.status.set_text('Loading albums…')
        def loaded(result):
            albums, total, catalog = result
            if catalog is not None:
                if artist:
                    self.artist_catalog = catalog
                elif title:
                    self.album_search_catalog = (client, section, title, catalog)
            self.total = total
            offset = 0
            self.busy.begin()
            def append_batch():
                nonlocal offset
                if self.closed or generation != self.generation:
                    self.busy.end()
                    return False
                deadline = time.monotonic() + 0.006
                while offset < len(albums):
                    album = albums[offset]
                    if getattr(self, 'gpu_wall_enabled', False) and getattr(self, 'gpu_wall', None):
                        self.gpu_wall.set_albums(client, [album])
                    elif not getattr(self, 'gpu_rebuild_pending', False):
                        self.add_album_tile(album)
                    self.albums.append(album)
                    offset += 1
                    if time.monotonic() >= deadline:
                        break
                if offset < len(albums):
                    return True
                self.busy.end()
                self.loading_albums = False
                if getattr(self, 'gpu_wall_enabled', False) and getattr(self, 'gpu_wall', None):
                    GLib.idle_add(self.gpu_load_more_albums)
                if self.album_prefetch_pending:
                    self.album_prefetch_pending = False
                    self.prefetch_album_sort_pages()
                message = (f'{len(self.albums)} of {total} albums by {artist}' if artist else
                           f'{len(self.albums)} of {total} albums • Click a cover to open')
                self.status.set_text(f'{self.credential_warning} • {message}' if self.credential_warning else message)
                self.finish_startup_loading()
                return False
            GLib.idle_add(append_batch)
        def failed():
            self.loading_albums = False
            self.finish_startup_loading()
        indexed = (self.indexed_albums if not force_refresh and not getattr(client, 'is_local', False) and self.search_index_enabled and
                   self.index_section == section else None)
        if artist:
            existing_catalog = self.artist_catalog
            sort = self.album_sort
            def artist_work():
                catalog = existing_catalog
                if catalog is None:
                    # The persistent search index can be older than the server.
                    # Query Plex's album-artist filter and collect every page.
                    catalog = []
                    offset = 0
                    while generation == self.generation and client is self.client and self.artist_filter == artist:
                        page, total = client.albums(section, offset, sort=sort, artist=artist)
                        catalog.extend(album for album in page
                                       if album.artist.strip().casefold() == artist.strip().casefold())
                        offset += len(page)
                        if not page or offset >= total:
                            break
                    else:
                        return [], 0, None
                catalog = sort_albums(catalog, sort)
                return catalog[start:start + 100], len(catalog), catalog
            work = artist_work
        elif title:
            sort = self.album_sort
            saved = None if force_refresh else getattr(self, 'album_search_catalog', None)
            def search_work():
                source = (saved[3] if start and saved and
                          saved[:3] == (client, section, title) else indexed)
                if source is None and saved and saved[:3] == (client, section, title):
                    source = saved[3]
                if source is None:
                    source = build_album_index(
                        client, section, lambda: generation == self.generation and
                        client is self.client)
                    if source is None:
                        return [], 0, None
                return *search_albums(sort_albums(source, sort), title, start), source
            work = search_work
        else:
            sort = self.album_sort
            def page_work():
                cache = LocalCache(client)
                if start == 0 and not title and not force_refresh and not getattr(client, 'is_local', False):
                    page = cached_album_page(cache, client, section, sort)
                else:
                    page = client.albums(section, start, title, sort)
                    if start == 0 and force_refresh:
                        try:
                            cache.save_album_page(section, sort, *page)
                        except OSError:
                            pass
                return *page, None
            work = page_work
        self.async_work(work, loaded,
                        lambda: generation == self.generation, failed)

    def load_playlists(self):
        if not self.client:
            return
        self.playlist_generation += 1
        generation = self.playlist_generation
        client = self.client
        def loaded(playlists):
            order = load_playlist_order(client.address, client.token)
            ranks = {key: index for index, key in enumerate(order)}
            playlists.sort(key=lambda playlist: ranks.get(playlist.key, len(ranks)))
            selected = self.active_playlist.key if self.active_playlist else self.playlist_restore_key
            self.playlist_restore_key = None
            for row in self.playlist_list.get_children():
                if row is not self.all_songs_row:
                    row.destroy()
            self.playlists = playlists
            selected_row = self.all_songs_row
            for playlist in playlists:
                row = self.playlist_row(playlist.title, playlist)
                if playlist.key == selected:
                    selected_row = row
            self.playlist_list.select_row(selected_row)
        self.async_work(client.playlists, loaded,
                        lambda: generation == self.playlist_generation and client is self.client)

    def restore_saved_session(self):
        if self.session_applied:
            return
        if self.saved_session.get('server') != self.client.address:
            return
        self.session_applied = True
        if not hasattr(self, 'play_history'):
            self.play_history = deque(maxlen=QUEUE_HISTORY_LIMIT)
        self.play_history.extend(self.saved_session.get('history', []))
        sort = self.saved_session.get('song_sort')
        if sort == 'titleSort':
            self.choose_library_sort('title', False)
        elif sort == 'artist.titleSort,titleSort':
            self.choose_library_sort('artist', False)
        album = self.saved_session.get('album_detail')
        if album:
            self.select_album(album)
        playback = self.saved_session.get('playback')
        if playback:
            self.queue = list(playback['queue'])
            self.queue_client = self.client
            self.queue_album = playback['album']
            self.index = playback['index']
            self.shuffle.set_active(playback['shuffle'])
            self.repeat.set_active(playback['repeat'])
            self.start_track(resume_paused=True,
                             resume_position_ms=playback['position_ms'])

    def load_songs(self):
        if (hasattr(self, 'content_views') and
                self.content_views.get_visible_child_name() != 'library'):
            self.song_generation = getattr(self, 'song_generation', 0) + 1
            self.song_load_pending = True
            return
        self.song_load_pending = False
        self.update_song_drag_mode()
        section = self.library.get_active_id()
        if not self.client or not section:
            self.song_count.set_text('Connect to a server to browse songs')
            return
        self.song_generation += 1
        generation = self.song_generation
        client = self.client
        playlist = self.active_playlist
        smart = getattr(self, 'active_smart_playlist', None)
        album_filter = self.library_album_filter
        tag_filter = getattr(self, 'library_tag_filter', None)
        query = self.library_search.get_text().strip()
        source = (client, section, playlist.key if playlist else None,
                  album_filter.key if album_filter else None)
        if tag_filter is not None:
            source += (tag_filter,)
        sort = self.effective_library_sort()
        view_key = ((*source, smart['id'], tag_filter, query, sort) if smart
                    else (*source, tag_filter, query, sort))
        if getattr(self, 'library_view_mode', 'songs') == 'albums':
            view_key += ('album-groups',)
        cached_view = self.song_view_cache.get(view_key)
        if cached_view is not None and time.monotonic() - cached_view.get('built_at', 0) >= 3600:
            del self.song_view_cache[view_key]
            cached_view = None
            if self.song_catalog_source == source:
                self.invalidate_song_catalog()
        if cached_view is None:
            cached_view = {'store': Gtk.ListStore(*([str] * (len(LIBRARY_COLUMNS) + 4))),
                           'rows': [], 'results': None, 'total': 0, 'message': '',
                           'built_at': time.monotonic()}
            self.song_view_cache[view_key] = cached_view
            while len(self.song_view_cache) > 3:
                self.song_view_cache.popitem(last=False)
        else:
            self.song_view_cache.move_to_end(view_key)
        self.song_view_key = view_key
        previous_store = self.song_store
        self.song_store = cached_view['store']
        if self.song_store is not previous_store:
            self.song_view.set_model(self.song_store)
        self.songs = cached_view['rows']
        self.song_results = cached_view['results']
        overlay = getattr(self, 'album_group_overlay', None)
        if overlay is not None:
            overlay.set_results(self.song_results if self.song_results is not None and
                                getattr(self, 'library_view_mode', 'songs') == 'albums' else ())
        if self.song_results is not None:
            self.song_total = cached_view['total']
            if len(self.songs) == self.song_total:
                self.song_count.set_text(cached_view['message'])
            else:
                self.display_song_page(self.song_results, self.song_total,
                                       playlist, album_filter, query)
            return
        if self.song_catalog_source != source or self.song_catalog is None:
            self.start_song_catalog(client, section, playlist, album_filter, tag_filter)
            return
        catalog = self.song_catalog
        def ready(results):
            self.song_results = results
            self.display_song_page(results, len(results), playlist, album_filter, query)
        def filtered():
            loved = (song.key for song in catalog if song.user_rating >= 9.5)
            # Keep random membership stable while the user searches this smart list.
            selected = (apply_definition(catalog, smart, loved,
                                         random.Random(smart['id'])) if smart else catalog)
            result = filter_sort_songs(selected, query, sort)
            return (group_songs_by_album(result) if getattr(self, 'library_view_mode', 'songs') == 'albums'
                    else result)
        if len(catalog) > 2000:
            self.song_count.set_text('Sorting songs…')
            self.async_work(filtered, ready,
                            lambda: generation == self.song_generation and client is self.client)
        else:
            ready(filtered())

    def display_song_page(self, songs, total, playlist, album_filter, query):
        self.song_total = total
        overlay = getattr(self, 'album_group_overlay', None)
        if overlay is not None and getattr(self, 'library_view_mode', 'songs') == 'albums':
            overlay.set_results(songs)
        if album_filter:
            message = f'{total} of {total} tracks in {album_filter.title}'
        elif getattr(self, 'library_tag_filter', None):
            message = f'{total} of {total} songs in {self.library_tag_filter.title}'
        elif query:
            message = f'{total} of {total} matching songs'
        elif getattr(self, 'active_smart_playlist', None):
            message = f'{total} of {total} songs in {self.active_smart_playlist["name"]}'
        else:
            message = (f'{total} of {total} songs' +
                       (' • Playlist order' if playlist and
                        self.effective_library_sort() is None else ''))
        cached_view = getattr(self, 'song_view_cache', {}).get(
            getattr(self, 'song_view_key', None))
        if cached_view is not None:
            cached_view.update(results=songs, total=total, message=message)
        generation = self.song_generation
        offset = len(self.songs)
        building = offset < total
        if building:
            self._song_row_builds = getattr(self, '_song_row_builds', 0) + 1
            busy = getattr(self, 'busy', None)
            if busy is not None:
                busy.begin()
        def finish_build():
            nonlocal building
            if not building:
                return
            building = False
            self._song_row_builds = max(0, self._song_row_builds - 1)
            busy = getattr(self, 'busy', None)
            if busy is not None:
                busy.end()
            if not self._song_row_builds:
                bar = getattr(self, 'player_bar', None)
                if bar is not None:
                    bar.queue_draw()
                header = getattr(self, 'library_header', None)
                if header is not None:
                    header.queue_draw()
        def resume_after_resize():
            if generation != self.song_generation or self.closed:
                finish_build()
                return False
            if Player.window_resize_recent(self):
                return True
            GLib.idle_add(append_batch)
            return False
        def append_batch():
            nonlocal offset
            if generation != self.song_generation or self.closed:
                finish_build()
                return False
            if Player.window_resize_recent(self):
                GLib.timeout_add(100, resume_after_resize)
                return False
            limit = min(total, offset + 200)
            deadline = time.monotonic() + 0.006
            try:
                while offset < limit:
                    song = songs[offset]
                    self.songs.append(song)
                    self.song_store.append([self.song_column_value(song, field)
                                            for _name, field in LIBRARY_COLUMNS] +
                                           ['♥' if song.user_rating >= 9.5 else '',
                                            ('#181818', '#111111')[offset % 2],
                                            ('#f3f3f1', '#ffffff')[offset % 2],
                                            '#000000'])
                    offset += 1
                    if time.monotonic() >= deadline:
                        break
            except Exception:
                finish_build()
                raise
            self.song_count.set_text(message if offset >= total else
                                     f'Preparing {offset} of {total} songs…')
            if offset >= total:
                finish_build()
                self.mpris.changed()
                return False
            return True
        if total > 200:
            GLib.idle_add(append_batch)
        else:
            if append_batch():
                GLib.idle_add(append_batch)

    def select_album(self, album):
        self.selected_album = album
        self.views.set_visible_child_name('detail')
        self.album_generation += 1
        generation = self.album_generation
        client = self.client
        self.tracks = []
        self.track_store.clear()
        self.album_label.set_text(album.title)
        self.album_artist.set_text(album.artist)
        self.album_year.set_text(album.year)
        self.set_placeholder_art(self.cover, 160)
        def loaded(tracks):
            self.tracks = tracks
            for track in tracks:
                self.track_store.append([str(track.number), track.title,
                                         clock(track.duration / 1000),
                                         star_text(track.user_rating)])
            self.mpris.changed()
        valid = lambda: generation == self.album_generation
        self.async_work(lambda: client.tracks(album), loaded, valid)
        self.load_art(client, album, self.cover, 160, valid)

    def activate_track(self, view, path, column):
        self.play_album(path.get_indices()[0])

    def album_track_drag_data_get(self, _view, _context, selection, _info, _time):
        tracks = getattr(self, 'album_drag_tracks', None)
        if tracks is None:
            tracks = [self.tracks[index] for index in
                      Player.selected_track_indices(self.track_view, self.tracks)]
        data = encode_track_keys([track.key for track in tracks])
        if data:
            selection.set(selection.get_target(), 8, data)

    def album_track_pressed(self, view, event):
        if event.button == 1:
            hit = view.get_path_at_pos(int(event.x), int(event.y))
            if hit and hit[1] is view.get_columns()[3]:
                index = hit[0].get_indices()[0]
                if 0 <= index < len(self.tracks):
                    song = self.tracks[index]
                    self.set_song_rating(song, stars_from_click(hit[2], song.user_rating))
                    return True
            self.album_drag_candidates = Player.track_drag_candidates(view, event, self.tracks)
        if event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        index = hit[0].get_indices()[0]
        if not 0 <= index < len(self.tracks):
            return False
        view.get_selection().select_path(hit[0])
        self.show_song_context_menu(event, self.tracks[index], index,
                                    lambda: self.play_album(index))
        return True

    def play_album(self, index):
        if not self.tracks:
            return
        Player.clear_remote_queue(self)
        self.queue_album = self.selected_album
        self.queue = list(self.tracks)
        self.queue_client = self.client
        self.index = index
        self.start_track()

    def source_setup(self, pipeline, source):
        if source.find_property('extra-headers') and self.queue_client and self.queue_client.token:
            headers = Gst.Structure.new_empty('headers')
            headers.set_value('X-Plex-Token', self.queue_client.token)
            source.set_property('extra-headers', headers)
        if source.find_property('automatic-redirect'):
            source.set_property('automatic-redirect', False)
        if source.find_property('timeout'):
            source.set_property('timeout', 15)

    def playback_transition_failed(self):
        if not self.closed:
            self.status.set_text('Playback failed. Check server access and installed GStreamer codecs.')
        return False

    @staticmethod
    def pipeline_transitioning(player):
        controller = getattr(player, 'playback_controller', None)
        return bool(controller and controller.busy())

    @staticmethod
    def set_pipeline_state(player, state):
        controller = getattr(player, 'playback_controller', None)
        if controller is None:
            player.pipeline.set_state(state)
        elif state == Gst.State.NULL:
            controller.set_state(state)
        else:
            generation = player.play_generation
            controller.set_state(state, lambda: not player.closed and player.play_generation == generation)

    def stop(self, remember=True):
        self.lastfm_tracker = None
        self.style_autoplay_generation += 1
        self.style_autoplay_pending = False
        self.style_autoplay_waiting = False
        self.style_autoplay_exhausted = False
        if remember and self.current_played_track is not None:
            self.play_history.append(self.current_played_track)
            self.current_played_track = None
        self.waveform_generation += 1
        self.next_prefetch_target = None
        for future in (getattr(self, 'next_art_prefetch_future', None),
                       getattr(self, 'next_wave_prefetch_future', None)):
            if future is not None:
                future.cancel()
        self.next_art_prefetch_future = None
        self.next_wave_prefetch_future = None
        self.current_stream_uri = ''
        self.instrument_analysis = None
        self.instrument_pending = None
        self.wave_timeline.set_peaks(None)
        self.wave_timeline.set_sensitive(False)
        if self.buffering_busy:
            self.buffering_busy = False
            self.busy.end()
        self.play_generation += 1
        if self.timeline_seek_source:
            GLib.source_remove(self.timeline_seek_source)
            self.timeline_seek_source = 0
        self.pending_timeline_seek = None
        self.remote_opening = False
        Player.set_pipeline_state(self, Gst.State.NULL)
        self.playing = False
        self.stream_open = False
        self.refresh_live_waveform()
        self.playback_position_ms = 0
        self.pending_resume_seek_ms = 0
        self.timeline_base_position = 0.0
        self.timeline_base_time = time.monotonic()
        self.timeline_duration = 0.0
        self.seek.set_value(0)
        self.set_play_button_state(False)
        self.seek.set_sensitive(False)
        self.refresh_playing_highlight()
        self.refresh_queue_view()
        self.refresh_now_rating()
        if hasattr(self, 'song_view'):
            self.song_view.queue_draw()
        self.mpris.changed()

    def start_track(self, resume_paused=False, resume_position_ms=0):
        previous_track = self.current_played_track
        self.stop(remember=False)
        self.current_played_track = None
        if not 0 <= self.index < len(self.queue):
            return
        self.remote_opening = True
        self.playback_position_ms = max(0, resume_position_ms)
        track = self.queue[self.index]
        if previous_track is not None:
            self.play_history.append(previous_track)
        self.refresh_queue_view()
        self.timeline_base_position = self.playback_position_ms / 1000
        self.timeline_base_time = time.monotonic()
        self.timeline_duration = track.duration / 1000 if track.duration else 0.0
        client = self.queue_client
        generation = self.play_generation
        self.now_title.set_text(track.title)
        self.now_artist.set_text(track.artist +
                                 (f' · {self.queue_album.title}' if self.queue_album else ''))
        self.hero_title.set_text(track.title)
        self.hero_artist.set_text(track.artist)
        self.hero_album.set_text(self.queue_album.title if self.queue_album else track.album)
        if (hasattr(self, 'info_revealer') and self.info_revealer.get_reveal_child() and
                getattr(self, 'info_target', None) is None and
                getattr(self, 'info_mode', 'track') == 'track'):
            self.load_current_info()
        if hasattr(self, 'lyrics_text'):
            self.lyrics_generation += 1
            self.lyrics_request_key = None
            if self.content_views.get_visible_child_name() == 'lyrics':
                self.load_current_lyrics()
        self.refresh_now_rating()
        art_item = self.queue_album if self.queue_album and self.queue_album.thumb else track
        art_key = (client, art_item.thumb) if art_item.thumb else None
        same_art = art_key is not None and art_key == self.current_art_key
        self.current_art_key = art_key
        if not same_art:
            self.set_placeholder_art(self.now_cover, 48)
            self.set_placeholder_art(self.hero_cover,
                                     getattr(self, 'now_display_art_size', self.now_art_size))
            palette = LocalCache(client).read_palette(art_item.thumb) if art_key else None
            self.current_wave_colors = None
            if palette is not None:
                self.current_art_colors, wave = palette
                self.current_art_bright = wave[0]
                self.current_wave_colors = wave
                self.render_gradient()
                self.apply_accent()
            elif art_key is None:
                self.current_art_colors = None
                self.current_art_bright = None
                self.current_wave_colors = None
                self.render_gradient()
                self.apply_accent()
            else:
                self.apply_accent()
        valid_art = lambda: generation == self.play_generation
        if not same_art or not getattr(self.now_cover, 'art_source', None):
            self.load_art(client, art_item, self.now_cover, 56, valid_art)
        if not same_art or not getattr(self.hero_cover, 'art_source', None):
            self.load_art(client, art_item, self.hero_cover, NOW_SIZE_RANGE[1], valid_art,
                          lambda pixbuf: self.update_art_gradient(client, art_item, pixbuf))
        self.status.set_text('Opening stream…')
        self.mpris.changed()
        def ready(uri):
            self.current_stream_uri = uri
            self.remote_opening = False
            self.stream_open = True
            self.current_played_track = track
            self.lastfm_tracker = lastfm.PlaybackTracker(track)
            self.playing = not resume_paused
            self.refresh_live_waveform()
            if self.instrument_visualizer_enabled:
                self.prepare_instrument_analysis(client, track, uri, generation)
            self.pending_resume_seek_ms = self.playback_position_ms
            state = Gst.State.PAUSED if resume_paused else Gst.State.PLAYING
            controller = getattr(self, 'playback_controller', None)
            if controller is None:
                self.pipeline.set_property('uri', uri)
                self.pipeline.set_state(state)
            else:
                controller.open(uri, state, lambda: not self.closed and generation == self.play_generation)
            if self.timeline_waveform_enabled:
                # Give the playback stream time to buffer before requesting a
                # second copy of the track for waveform analysis.
                self.prepare_track_waveform(client, track, uri, generation, delay_ms=750)
            self.set_play_button_state(not resume_paused)
            self.status.set_text(f'Queue • {self.index + 1} / {len(self.queue)}' +
                                 (' • Ready to resume' if resume_paused else ''))
            self.refresh_playing_highlight()
            self.refresh_queue_view()
            self.song_view.queue_draw()
            self.mpris.changed()
            self.persist_session(force=True)
            if self.playing:
                self.maybe_prefetch_same_style()
        self.persist_session(force=True)
        self.async_work(lambda: client.stream(track), ready,
                        lambda: generation == self.play_generation)

    def toggle(self, *_):
        if not self.stream_open:
            if self.queue:
                self.start_track()
            elif self.songs:
                self.play_song(0)
            else:
                self.play_album(0)
            return
        if getattr(self, 'lastfm_tracker', None):
            self.lastfm_tracker.previous = None
        self.playing = not self.playing
        Player.set_pipeline_state(self, Gst.State.PLAYING if self.playing else Gst.State.PAUSED)
        self.refresh_live_waveform()
        if not self.playing:
            if getattr(self, 'timeline_duration', 0) > 0:
                elapsed = (0. if getattr(self, 'buffering_busy', False) else
                           max(0., time.monotonic() - self.timeline_base_time))
                self.playback_position_ms = round(min(self.timeline_duration,
                                                       self.timeline_base_position + elapsed) * 1000)
        self.timeline_base_position = self.playback_position_ms / 1000
        self.timeline_base_time = time.monotonic()
        self.set_play_button_state(self.playing)
        self.refresh_playing_highlight()
        self.refresh_queue_view()
        self.song_view.queue_draw()
        self.mpris.changed()
        self.persist_session(force=True)
        if self.playing:
            self.maybe_prefetch_same_style()

    def play(self):
        if not self.playing:
            self.toggle()

    def pause(self):
        if self.playing:
            self.toggle()

    def previous(self, *_):
        if self.queue and self.index > 0:
            self.index -= 1
            self.start_track()

    def advance(self):
        if not self.queue:
            return
        if self.shuffle.get_active() and len(self.queue) > 1:
            self.index = random.choice([i for i in range(len(self.queue)) if i != self.index])
        elif self.index + 1 < len(self.queue):
            self.index += 1
        elif self.repeat.get_active():
            self.index = 0
        elif self.keep_style_playing_enabled:
            if self.style_autoplay_exhausted:
                self.stop()
                self.status.set_text('No more similar songs found in this library')
                return
            self.style_autoplay_waiting = True
            if not self.style_autoplay_pending:
                self.extend_queue_same_style()
            return
        else:
            self.stop()
            self.status.set_text('Album finished')
            return
        self.start_track()

    def maybe_prefetch_same_style(self):
        if (self.keep_style_playing_enabled and self.playing and self.queue and
                self.index == len(self.queue) - 1 and
                not self.repeat.get_active() and
                not (self.shuffle.get_active() and len(self.queue) > 1) and
                not self.style_autoplay_pending and
                not self.style_autoplay_exhausted):
            self.extend_queue_same_style()

    def extend_queue_same_style(self):
        if (self.style_autoplay_pending or not self.client or
                not 0 <= self.index < len(self.queue)):
            return
        section = self.library.get_active_id()
        if not section:
            self.style_autoplay_exhausted = True
            if self.style_autoplay_waiting:
                self.stop()
            return
        client = self.queue_client
        if client is not self.client:
            self.style_autoplay_exhausted = True
            if self.style_autoplay_waiting:
                self.stop()
            return
        current = self.queue[self.index]
        preferred = (self.auto_style_facet if current.key in self.auto_style_keys
                     else None)
        if preferred is None:
            self.auto_style_facet = None
            self.auto_style_keys.clear()
        excluded = {item.key for item in self.queue}
        excluded.update(item.key for item in self.play_history)
        generation = self.play_generation
        request = self.style_autoplay_generation + 1
        self.style_autoplay_generation = request
        index = self.index
        self.style_autoplay_pending = True
        self.status.set_text('Finding more similar songs…')
        session = getattr(self, 'lastfm_session', None)
        credentials = lastfm.application_credentials() or (
            (session['api_key'], session['secret']) if session else None)
        def work():
            try:
                online = lastfm_similar_tracks(client, section, current, credentials, excluded)
            except (lastfm.LastFMError, OSError):
                online = []
            if online or getattr(client, 'is_local', False):
                return None, online
            cache = LocalCache(client)
            facets = cache.read_music_facets(section)
            if facets is None:
                facets = client.music_facets(section)
                try:
                    cache.save_music_facets(section, facets)
                except OSError:
                    pass
            return client.more_tracks_same_mood(section, current, facets,
                                                excluded, preferred=preferred)
        valid = lambda: (request == self.style_autoplay_generation and
                         generation == self.play_generation and
                         self.queue_client is client and self.client is client and
                         index == self.index and self.keep_style_playing_enabled and
                         section == self.library.get_active_id())
        def ready(result):
            self.style_autoplay_pending = False
            waiting = self.style_autoplay_waiting
            self.style_autoplay_waiting = False
            facet, tracks = result
            if self.index + 1 < len(self.queue):
                if waiting:
                    self.advance()
                return
            if not tracks:
                self.style_autoplay_exhausted = True
                if waiting:
                    self.stop()
                self.status.set_text('No more similar songs found in this library')
                return
            self.auto_style_facet = facet
            self.auto_style_keys = {track.key for track in tracks}
            Player.clear_remote_queue(self)
            self.queue_album = None
            self.queue.extend(tracks)
            self.pulse_queue_icon()
            self.refresh_queue_view()
            self.mpris.changed()
            self.persist_session(force=True)
            if waiting:
                self.index += 1
                self.start_track()
            else:
                self.status.set_text(f'Queued {len(tracks)} similar songs')
        def failed():
            self.style_autoplay_pending = False
            waiting = self.style_autoplay_waiting
            self.style_autoplay_waiting = False
            self.style_autoplay_exhausted = True
            if waiting:
                self.stop()
            self.status.set_text('Could not find more similar songs')
        self.async_work(work, ready, valid, failed)

    def message(self, bus, message):
        if message.type == Gst.MessageType.ELEMENT:
            if self.live_waveform_tap is not None:
                levels = self.live_waveform_tap.read_message(message)
                if levels is not None:
                    analysis = getattr(self, 'instrument_analysis', None)
                    if analysis is not None and getattr(self, 'instrument_visualizer_enabled', False):
                        elapsed = (max(0., time.monotonic() - self.timeline_base_time)
                                   if self.playing and not self.buffering_busy else 0.)
                        position_ms = (self.timeline_base_position + elapsed) * 1000
                        instruments = sample_analysis(analysis, position_ms)
                        if instruments is not None:
                            levels = tuple(levels[:3]) + instruments
                    self.hero_waveform.set_audio(levels)
                    self.background_visualizer.set_audio(levels)
        elif message.type == Gst.MessageType.EOS:
            self.advance()
        elif message.type == Gst.MessageType.ERROR:
            self.stop()
            self.status.set_text('Playback failed. Check server access and installed GStreamer codecs.')
        elif message.type == Gst.MessageType.ASYNC_DONE:
            self.apply_pending_resume_seek()
        elif message.type == Gst.MessageType.BUFFERING:
            percent = message.parse_buffering()
            buffering = percent < 100
            if buffering != self.buffering_busy:
                self.buffering_busy = buffering
                self.busy.begin() if buffering else self.busy.end()
                if self.playing:
                    Player.set_pipeline_state(self, Gst.State.PAUSED if buffering else Gst.State.PLAYING)
            self.status.set_text(f'Buffering {percent}%' if percent < 100 else 'Streaming from Plex')

    def seek_to(self, scale, scroll, value):
        scale.set_value(value)
        self.pending_timeline_seek = value
        if not self.timeline_seek_source:
            self.timeline_seek_source = GLib.timeout_add(30, self.flush_timeline_seek)
        return True

    def flush_timeline_seek(self):
        self.timeline_seek_source = 0
        value = self.pending_timeline_seek
        self.pending_timeline_seek = None
        if value is not None:
            self.seek_mpris(int(value * 1000000))
        return False

    def timeline_motion(self, widget, event):
        width = widget.get_allocated_width()
        self.timeline_hover_x = max(0, min(width - 1, event.x)) if width > 0 else None
        widget.get_style_context().add_class('hovering')
        widget.queue_draw()
        return False

    def timeline_value_changed(self, scale):
        upper = scale.get_adjustment().get_upper()
        self.wave_timeline.set_progress(scale.get_value() / upper if upper > 0 else 0)
        if (hasattr(self, 'lyrics_lines') and
                self.content_views.get_visible_child_name() == 'lyrics'):
            self.update_lyrics_position(scale.get_value())

    def wave_timeline_scrub(self, widget, x):
        if not self.seek.get_sensitive():
            return
        width = max(1, widget.get_allocated_width())
        upper = self.seek.get_adjustment().get_upper()
        value = max(0.0, min(upper, x / width * upper))
        self.seek_to(self.seek, None, value)

    def wave_timeline_pressed(self, widget, event):
        if event.button != 1 or not self.seek.get_sensitive():
            return False
        self.timeline_pressed(widget, event)
        self.wave_timeline_scrub(widget, event.x)
        return True

    def wave_timeline_motion(self, widget, event):
        self.timeline_motion(widget, event)
        if self.timeline_dragging:
            self.wave_timeline_scrub(widget, event.x)
        return True

    def wave_timeline_released(self, widget, event):
        if event.button != 1 or not self.timeline_dragging:
            return False
        self.wave_timeline_scrub(widget, event.x)
        self.timeline_released(widget, event)
        return True

    def timeline_leave(self, widget, _event):
        self.timeline_hover_x = None
        widget.get_style_context().remove_class('hovering')
        widget.queue_draw()
        return False

    def draw_timeline_marker(self, widget, context):
        if self.timeline_hover_x is None:
            return False
        x = self.timeline_hover_x
        height = widget.get_allocated_height()
        context.set_source_rgba(0, 0, 0, 0.55)
        context.rectangle(x - 2, (height - 14) / 2, 4, 14)
        context.fill()
        return False

    def timeline_pressed(self, _widget, event):
        if event.button == 1:
            self.timeline_dragging = True
        return False

    def timeline_released(self, _widget, event):
        if event.button == 1:
            if self.timeline_seek_source:
                GLib.source_remove(self.timeline_seek_source)
                self.timeline_seek_source = 0
            self.flush_timeline_seek()
            self.timeline_dragging = False
            self.timeline_base_position = self.seek.get_value()
            self.timeline_base_time = time.monotonic()
        return False

    def seek_mpris(self, position):
        if self.timeline_seek_source:
            GLib.source_remove(self.timeline_seek_source)
            self.timeline_seek_source = 0
            self.pending_timeline_seek = None
        if not self.seek.get_sensitive() or not self.queue:
            return
        if Player.pipeline_transitioning(self):
            self.pending_timeline_seek = position / 1000000
            self.timeline_seek_source = GLib.timeout_add(50, self.flush_timeline_seek)
            return
        track = self.queue[self.index]
        position = max(0, min(position, track.duration * 1000)) if track.duration else max(0, position)
        if getattr(self, 'lastfm_tracker', None):
            self.lastfm_tracker.previous = None
        if self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                     int(position * 1000)):
            self.playback_position_ms = position // 1000
            self.timeline_base_position = position / 1000000
            self.timeline_base_time = time.monotonic()
            self.mpris.seeked(position)
            self.persist_session(force=True)

    def apply_pending_resume_seek(self):
        if not self.stream_open or not self.pending_resume_seek_ms or Player.pipeline_transitioning(self):
            return
        track = self.queue[self.index]
        position = min(self.pending_resume_seek_ms, track.duration) if track.duration else self.pending_resume_seek_ms
        if self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                     position * Gst.MSECOND):
            self.pending_resume_seek_ms = 0
            self.playback_position_ms = position
            self.timeline_base_position = position / 1000
            self.timeline_base_time = time.monotonic()
            self.mpris.seeked(position * 1000)

    def tick(self):
        if self.closed:
            return False
        if Player.pipeline_transitioning(self):
            return True
        self.apply_pending_resume_seek()
        if self.playback_poll_future is None and self.stream_open:
            generation = self.play_generation
            base_time = self.timeline_base_time
            def poll():
                ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
                pos_ok, position = self.pipeline.query_position(Gst.Format.TIME)
                _result, state, _pending = self.pipeline.get_state(0)
                return ok, duration, pos_ok, position, state
            future = self.playback_poll_workers.submit(poll)
            self.playback_poll_future = future
            future.add_done_callback(lambda completed: GLib.idle_add(
                self.finish_playback_poll, generation, base_time, completed))
        if self.stream_open and self.queue:
            self.persist_session()
        if self.remote_receiver:
            self.remote_receiver.publish(self.remote_snapshot())
            if self.remote_receiver.last_request:
                path, code = self.remote_receiver.last_request
                self.remote_request_status.set_text(f'Last remote request: {path} → HTTP {code}')
        return True

    def finish_playback_poll(self, generation, base_time, future):
        if self.playback_poll_future is future:
            self.playback_poll_future = None
        if (self.closed or generation != self.play_generation or
                base_time != self.timeline_base_time or Player.pipeline_transitioning(self)):
            return False
        try:
            ok, duration, pos_ok, position, state = future.result()
        except Exception:
            return False
        if getattr(self, 'lastfm_tracker', None):
            if self.lastfm_tracker.duration <= 0 and ok and duration > 0:
                self.lastfm_tracker.duration = duration / Gst.SECOND
            self.update_lastfm_playback(position / Gst.SECOND if pos_ok else None,
                                        self.stream_open and self.playing and
                                        not self.buffering_busy and state == Gst.State.PLAYING)
        if ok and pos_ok and duration > 0:
            self.playback_position_ms = position // Gst.MSECOND
            self.seek.set_range(0, duration / Gst.SECOND)
            self.timeline_base_position = position / Gst.SECOND
            self.timeline_base_time = time.monotonic()
            self.timeline_duration = duration / Gst.SECOND
            if not self.seek.get_sensitive():
                self.seek.set_sensitive(True)
                self.wave_timeline.set_sensitive(True)
                self.mpris.changed()
            self.time.set_text(f'{clock(position / Gst.SECOND)} / {clock(duration / Gst.SECOND)}')
        return False

    def animate_timeline(self):
        if self.closed:
            return False
        if self.stream_open and self.timeline_duration > 0 and not self.timeline_dragging:
            elapsed = max(0.0, time.monotonic() - self.timeline_base_time) if self.playing else 0.0
            self.seek.set_value(min(self.timeline_duration,
                                    self.timeline_base_position + elapsed))
        return True

    def persist_session(self, force=False):
        if not self.client or not self.queue:
            return
        now = time.monotonic()
        if not force and now - self.last_session_save < 15:
            return
        if Player.queue_session_save(self):
            self.last_session_save = now

    @staticmethod
    def queue_session_save(player):
        workers = getattr(player, 'session_save_workers', None)
        if workers is None:
            try:
                save_session(player.session_snapshot())
                return True
            except OSError:
                return False
        snapshot = player.session_snapshot(defer_items=True)
        previous = getattr(player, 'session_save_future', None)
        if previous is not None:
            previous.cancel()
        def save():
            try:
                save_session(serialize_snapshot(snapshot))
            except OSError:
                pass
        try:
            player.session_save_future = workers.submit(save)
            return True
        except RuntimeError:
            return False

    def session_snapshot(self, defer_items=False):
        encode = (lambda item: item) if defer_items else item_to_data
        maximized = self.is_maximized()
        width, height = self.normal_size
        data = {
            'version': 1,
            'window': {'width': width, 'height': height, 'maximized': maximized},
            'panel': self.content_views.get_visible_child_name(),
            'settings_page': ('shortcuts' if self.settings_tabs.get_current_page() == 3
                              else 'main'),
            'settings_tab': self.settings_tabs.get_current_page(),
        }
        machine = getattr(self, 'time_machine', None)
        if machine:
            try:
                start, end = machine.selected_dates()
                data['time_machine_dates'] = {'from': start.isoformat(), 'to': end.isoformat()}
            except (ValueError, OverflowError):
                previous = self.saved_session.get('time_machine_dates')
                if previous:
                    data['time_machine_dates'] = {key: value.isoformat() for key, value in previous.items()}
        if self.client:
            data['server'] = self.client.address
            data['history'] = [encode(track)
                               for track in getattr(self, 'play_history', ())]
            data['section'] = self.library.get_active_id()
            data['playlist'] = self.active_playlist.key if self.active_playlist else None
            data['song_sort'] = self.song_sort
            if self.selected_album and self.views.get_visible_child_name() == 'detail':
                data['album_detail'] = encode(self.selected_album)
            if self.queue and 0 <= self.index < len(self.queue):
                position = self.playback_position_ms
                if (not defer_items and self.stream_open and self.playing and not self.pending_resume_seek_ms and
                        not Player.pipeline_transitioning(self)):
                    ok, current = self.pipeline.query_position(Gst.Format.TIME)
                    if ok:
                        position = current // Gst.MSECOND
                elif (defer_items and self.stream_open and self.playing and
                      not self.pending_resume_seek_ms and self.timeline_duration > 0):
                    elapsed = 0. if self.buffering_busy else max(0., time.monotonic() - self.timeline_base_time)
                    position = round(min(self.timeline_duration, self.timeline_base_position + elapsed) * 1000)
                data['playback'] = {
                    'queue': [encode(track) for track in self.queue],
                    'index': self.index,
                    'position_ms': max(0, position),
                    'album': encode(self.queue_album) if self.queue_album else None,
                    'shuffle': self.shuffle.get_active(),
                    'repeat': self.repeat.get_active(),
                }
        else:
            for name in ('server', 'section', 'playlist', 'song_sort'):
                if name in self.saved_session:
                    data[name] = self.saved_session[name]
            if self.saved_session.get('history'):
                data['history'] = [encode(track)
                                   for track in self.saved_session['history']]
            if self.saved_session.get('album_detail'):
                data['album_detail'] = encode(self.saved_session['album_detail'])
            old = self.saved_session.get('playback')
            if old:
                data['playback'] = {
                    'queue': [encode(track) for track in old['queue']],
                    'index': old['index'],
                    'position_ms': old['position_ms'],
                    'album': encode(old['album']) if old['album'] else None,
                    'shuffle': old['shuffle'], 'repeat': old['repeat'],
                }
        return data

    def close(self, *_):
        if getattr(self, 'album_web_wall', None):
            self.album_web_wall.shutdown()
        if getattr(self, 'album_canvas', None):
            self.album_canvas.shutdown()
        if getattr(self, 'canvas_search_source', 0):
            GLib.source_remove(self.canvas_search_source)
            self.canvas_search_source = 0
        if getattr(self, 'gpu_wall', None):
            self.gpu_wall.shutdown()
        if self._window_shape_resume_source:
            GLib.source_remove(self._window_shape_resume_source)
            self._window_shape_resume_source = 0
        self.lyrics_client.close()
        self.frosted_bar.set_enabled(False)
        for _widget, effect in self.top_frosted_bars:
            effect.set_enabled(False)
        if self.live_waveform_tap is not None:
            self.live_waveform_tap.set_enabled(False)
        if self.background_prefetch_source:
            GLib.source_remove(self.background_prefetch_source)
            self.background_prefetch_source = 0
        self.waveform_generation += 1
        self.instrument_generation += 1
        self.instrument_pending = None
        self.instrument_workers.shutdown(wait=False, cancel_futures=True)
        self.waveform_workers.shutdown(wait=False, cancel_futures=True)
        self.next_art_workers.shutdown(wait=False, cancel_futures=True)
        self.next_waveform_workers.shutdown(wait=False, cancel_futures=True)
        self.style_tile_art_workers.shutdown(wait=False, cancel_futures=True)
        self.rating_executor.shutdown(wait=False, cancel_futures=True)
        Player.cancel_queue_render(self)
        self.busy.close()
        if self.sidebar_volume_timeout:
            GLib.source_remove(self.sidebar_volume_timeout)
            self.sidebar_volume_timeout = 0
        if self.sidebar_volume_tick:
            self.sidebar_volume_indicator.remove_tick_callback(self.sidebar_volume_tick)
            self.sidebar_volume_tick = 0
        if self.queue_pulse_source:
            GLib.source_remove(self.queue_pulse_source)
            self.queue_pulse_source = 0
        if self.timeline_seek_source:
            GLib.source_remove(self.timeline_seek_source)
            self.timeline_seek_source = 0
        self.remote_pin_generation += 1
        if self.remote_receiver:
            self.remote_receiver.stop()
            self.remote_receiver = None
        if self.remote_stop_thread:
            self.remote_stop_thread.join(timeout=5)
        if self.library_layout_save_timeout:
            GLib.source_remove(self.library_layout_save_timeout)
        self.save_library_layout_now()
        Player.queue_session_save(self)
        self.session_save_workers.shutdown(wait=False)
        self.closed = True
        self.album_prefetch_generation += 1
        if self.album_prefetch_thread:
            self.album_prefetch_thread.join(timeout=0.2)
        Gtk.Settings.get_default().set_property('gtk-enable-tooltips',
                                                self.desktop_tooltips_enabled)
        self.mpris.close()
        if self.portal_shortcuts:
            self.portal_shortcuts.close()
        self.art_workers.shutdown(wait=False, cancel_futures=True)
        self.playback_controller.shutdown(Gst.State.NULL)
        self.playback_poll_workers.shutdown(wait=False, cancel_futures=True)
        Gtk.main_quit()


def runtime_self_test():
    """Check bundled GTK/GStreamer imports and the media elements used by playback."""
    if os.environ.get('APISTAT_REQUIRE_LASTFM_BUILD') == '1' and not lastfm.application_credentials():
        raise RuntimeError('Last.fm application credentials are missing from the build')
    required = ('playbin', 'appsink', 'audioconvert', 'audioresample', 'level',
                'souphttpsrc', 'autoaudiosink')
    missing = [name for name in required if Gst.ElementFactory.find(name) is None]
    if os.name == 'nt':
        for decoder in ('flacdec', 'mpg123audiodec', 'faad'):
            if Gst.ElementFactory.find(decoder) is None:
                missing.append(decoder)
        if not any(Gst.ElementFactory.find(name) for name in
                   ('wasapi2sink', 'wasapisink', 'directsoundsink')):
            missing.append('Windows audio sink')
    if missing:
        raise RuntimeError('Missing GStreamer elements: ' + ', '.join(missing))
    if sys.platform == 'darwin':
        if Gst.ElementFactory.find('osxaudiosink') is None:
            raise RuntimeError('Missing GStreamer macOS audio sink')
        from keyring.backends.macOS import Keyring
        Keyring.priority  # Check the underlying Security API, not just the module.
        if getattr(sys, 'frozen', False):
            from gi.repository import Gio
            if not Gio.TlsBackend.get_default().supports_tls():
                raise RuntimeError('Missing GLib TLS backend for HTTPS streaming')
            from macos_runtime import configure_bundled_icons
            theme = Gtk.IconTheme.get_default()
            settings = Gtk.Settings.get_default()
            if theme is None or settings is None or not configure_bundled_icons(settings, theme, sys._MEIPASS):
                raise RuntimeError('Bundled Adwaita icon theme is missing')
            for icon in ('emblem-system-symbolic', 'audio-volume-high-symbolic',
                         'media-playback-start-symbolic', 'list-add-symbolic'):
                if not theme.has_icon(icon):
                    raise RuntimeError('Bundled icon not found: ' + icon)
                if theme.load_icon(icon, 24, Gtk.IconLookupFlags.FORCE_SIZE) is None:
                    raise RuntimeError('Bundled icon could not be loaded: ' + icon)
    if (os.name == 'nt' or sys.platform == 'darwin') and getattr(sys, 'frozen', False):
        from app_font import font_path
        from mutagen.id3 import ID3
        if not font_path().is_file():
            raise RuntimeError('Bundled font is missing')
        app_icon()  # Also checks that the bundled icon can be decoded.
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        # Verify the optional GPU wall modules were included in Windows bundles.
        import gpu_album_wall
        import gpu_wgl
        import gi
        gi.require_version('PangoCairo', '1.0')
        from gi.repository import PangoCairo
        if not register_bundled_font():
            raise RuntimeError('Bundled font could not be registered with Pango')
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 80)
        cr = cairo.Context(surface)
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription.from_string('Nunito 12'))
        layout.set_text('Apistat ★ ♥ 🎵', -1)
        if layout.get_unknown_glyphs_count():
            raise RuntimeError('Pango could not find fonts for the text and symbols test')
        PangoCairo.show_layout(cr, layout)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Apistat music player')
    parser.add_argument('--self-test', action='store_true', help='check GTK and GStreamer dependencies')
    parser.add_argument('--playback-test-dir', metavar='DIR',
                        help='check local and HTTP audio decoding using test fixtures')
    parser.add_argument('--resize-log', metavar='FILE',
                        help='append opt-in window resize diagnostics as JSON lines')
    args = parser.parse_args()
    if args.self_test:
        try:
            runtime_self_test()
            if args.playback_test_dir:
                from playback_self_test import verify_playback
                verify_playback(args.playback_test_dir)
        except Exception:
            if os.name == 'nt' and getattr(sys, 'frozen', False):
                # A windowed executable has no console. Avoid a modal error
                # dialog during CI and write diagnostics only when requested.
                report = os.environ.get('APISTAT_SELF_TEST_REPORT')
                if report:
                    import traceback
                    try:
                        with open(report, 'w', encoding='utf-8') as stream:
                            traceback.print_exc(file=stream)
                    except OSError:
                        pass
                raise SystemExit(1)
            raise
    else:
        stream = None
        if args.resize_log:
            try:
                stream = open(args.resize_log, 'a', encoding='utf-8')
            except OSError as error:
                parser.error(f'Cannot open resize log: {error}')
        try:
            player = Player(mpris_enabled=sys.platform.startswith('linux'))
            diagnostics = None
            if stream is not None:
                from resize_diagnostics import ResizeDiagnostics
                diagnostics = ResizeDiagnostics(player, stream)
                print(f'Resize diagnostics are being written to {args.resize_log}', flush=True)
            try:
                Gtk.main()
            finally:
                if diagnostics is not None and not diagnostics.closed:
                    diagnostics.close()
        finally:
            if stream is not None and not stream.closed:
                stream.close()
