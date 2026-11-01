#!/usr/bin/env python3
import random
import hmac
import hashlib
import hashlib
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import Future
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, Gst, GLib, GdkPixbuf, Gdk, Pango
from plex_client import PlexClient
from credentials import load_credentials, save_credentials
from mpris import Mpris
from appearance import (ALBUM_SIZE_RANGE, ALBUM_COLUMN_RANGE, NOW_SIZE_RANGE,
                        DitheredGradient, added_age_label, album_cover_size, gradient_colors,
                        load_accent_color, load_album_columns, load_album_details_enabled,
                        load_art_accent_enabled, load_art_sizes, load_tooltips_hidden,
                        load_custom_font, load_gradient_enabled, load_search_index_enabled,
                        load_album_margins, save_album_margins,
                        load_library_layout, save_library_layout,
                        load_library_sort_buttons,
                        load_single_flip_enabled,
                        load_text_size, load_title_bar_hidden,
                        save_accent_color, save_album_columns, save_album_details_enabled,
                        save_art_accent_enabled, save_custom_font, save_tooltips_hidden,
                        save_gradient_enabled, save_now_art_size,
                        save_search_index_enabled,
                        save_single_flip_enabled, save_text_size,
                        save_title_bar_hidden, waveform_colors)
from local_cache import LocalCache, build_album_index, search_albums
from library_catalog import build_song_catalog, filter_sort_songs
from waveform import Waveform, spectrum_values
from album_card import FlipCard
from session import load_session, save_session, item_to_data
import shortcuts
from companion import CompanionReceiver, local_ip
from companion_account import (PlexAccount, load_device_token, save_device_token,
                               clear_device_token)
from companion_config import load_config, save_config

Gst.init(None)


def clock(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}:{seconds % 60:02}'


LIBRARY_COLUMNS = (
    ('Song', 'title'), ('Artist', 'artist'), ('Album', 'album'),
    ('Time', 'duration'), ('Genre', 'genre'), ('Year', 'year'),
    ('Added', 'added_at'), ('Mood', 'mood'), ('Label', 'label'),
    ('Album artist', 'album_artist'), ('Release date', 'release_date'),
    ('Disc', 'disc'), ('Track', 'track_number'), ('Last played', 'last_played_at'),
    ('Plays', 'play_count'), ('Rating', 'user_rating'), ('Bitrate', 'bitrate'),
    ('Codec', 'codec'),
)
BASE_LIBRARY_FIELDS = ('title', 'artist', 'album', 'duration')


class InactiveMpris:
    def changed(self):
        pass

    def seeked(self, _position):
        pass

    def close(self):
        pass


class Player(Gtk.Window):
    def __init__(self, mpris_enabled=False):
        super().__init__(title='Plex Music · Prototype')
        self.saved_session = load_session()
        self.session_applied = False
        self.previous_panel = 'albums'
        window = self.saved_session.get('window', {})
        self.normal_size = (window.get('width', 1080), window.get('height', 720))
        self.set_default_size(*self.normal_size)
        self.hide_title_bar = load_title_bar_hidden()
        self.set_decorated(not self.hide_title_bar)
        self.connect('size-allocate', self.window_allocated)
        self.client = None
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
        self.restored_credentials = None
        self.credential_warning = ''
        self.sections = []
        self.albums = []
        self.tracks = []
        self.queue = []
        self.index = -1
        self.generation = 0
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
        self.offset = 0
        self.total = 0
        self.pipeline = Gst.ElementFactory.make('playbin', None)
        if not self.pipeline:
            raise RuntimeError('Install gstreamer1.0-plugins-base and gstreamer1.0-plugins-good')
        self.pipeline.set_property('flags', 2)  # Audio only
        self.audio_spectrum = Gst.ElementFactory.make('spectrum')
        if self.audio_spectrum and self.pipeline.find_property('audio-filter'):
            self.audio_spectrum.set_property('bands', 512)
            self.audio_spectrum.set_property('interval', 30 * Gst.MSECOND)
            self.audio_spectrum.set_property('threshold', -90)
            self.audio_spectrum.set_property('post-messages', True)
            self.pipeline.set_property('audio-filter', self.audio_spectrum)
        else:
            self.audio_spectrum = None
        self.pipeline.connect('source-setup', self.source_setup)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self.message)
        self.connect('destroy', self.close)
        self.connect('key-press-event', self.global_key_pressed)
        self.connect('key-release-event', self.global_key_released)
        self.connect('focus-out-event', self.window_focus_out)
        self.connect('button-press-event', self.context_menu_pressed)
        self.space_held = False
        self.last_session_save = 0.0
        self.art_workers = ThreadPoolExecutor(max_workers=4)
        self.selected_album = None
        self.queue_album = None
        self.artist_filter = None
        self.artist_catalog = None
        self.library_album_filter = None
        self.column_sort = None
        self.song_catalog = None
        self.song_results = None
        self.song_catalog_source = None
        self.song_catalog_loading = False
        self.song_catalog_generation = 0
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
            #plex-player label { color: #eee; }
            #album-grid flowboxchild { padding: 0; margin: 0; border: 0; }
            #album-grid button { background: transparent; border: 0; padding: 0;
                border-radius: 0; box-shadow: none; }
            #album-grid button:hover { background: rgba(255, 255, 255, 0.12); }
            #album-load-more, #album-load-more:hover,
            #album-results-back, #album-results-back:hover { background: transparent;
                border: 0; box-shadow: none; }
            #album-grid #album-title { font-weight: bold; color: #fff; }
            #album-grid #album-meta { color: #ccc; font-size: 11px; }
            #album-card-back { background: transparent; border: 0; }
            #album-card-back button { color: #eee; }
            #album-card-back #album-back-title { font-weight: bold; }
            #album-card-back button.playing-track { background: rgba(255, 255, 255, 0.25);
                font-weight: bold; }
            #player-bar { background: #151515; }
            #player-bar button, #library-toolbar button { color: #eee;
                background: #252525; border-color: #444; box-shadow: none; }
            #player-bar button, #player-bar button:hover, #player-bar button:active,
            #player-bar button:checked { background: transparent; border: 0;
                border-radius: 0; box-shadow: none; }
            #player-bar button:checked image { color: #e7a641; }
            #player-bar #song-info-button { padding: 0; }
            #bar-track-title { font-weight: bold; }
            #bar-track-artist { color: #bbb; }
            #border-timeline { margin: 0; padding: 0; min-height: 8px; }
            #border-timeline trough { background: #383838; border: 0;
                border-radius: 0; min-height: 8px; }
            #border-timeline highlight { background: #e7a641; border: 0;
                border-radius: 0; min-height: 8px; }
            #border-timeline slider { background: transparent; border: 0;
                box-shadow: none; min-width: 0; min-height: 0; opacity: 0; }
            #plex-player *:focus { outline: none; box-shadow: none; }
            #side-nav { background: #101010; border-right: 1px solid #303030; }
            #side-nav button { background: transparent; border: 0; box-shadow: none;
                padding: 12px; border-radius: 8px; }
            #side-nav button.active { background: #35302a; }
            #side-nav image { color: #eee; }
            #playlist-panel { background: #181818; border-right: 1px solid #303030; }
            #playlist-panel row, #song-panel row { color: #eee; }
            #settings-panel, #song-panel { background: #000; }
            #startup-loading { background: #000; }
            #startup-loading label { font-size: 18px; font-weight: bold; }
            #now-scroll, #now-scroll viewport, #now-panel { background: transparent; }
            #song-panel button:checked { background: #514233; border-bottom: 2px solid #e7a641; }
            #now-title { font-size: 22px; font-weight: bold; }
            #art-toggle { background: transparent; border: 0; padding: 0;
                border-radius: 0; box-shadow: none; }
            #art-toggle:hover { background: transparent; }
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
        self.gradient_enabled = load_gradient_enabled()
        self.accent_color = load_accent_color()
        self.art_accent_enabled = load_art_accent_enabled()
        self.current_art_bright = None
        self.tooltips_hidden = load_tooltips_hidden()
        self.tooltip_texts = weakref.WeakKeyDictionary()
        self.desktop_tooltips_enabled = Gtk.Settings.get_default().get_property('gtk-enable-tooltips')
        self.apply_tooltip_setting()
        self.apply_accent()
        self.show_album_details = load_album_details_enabled()
        self.single_flip_enabled = load_single_flip_enabled()
        self.search_index_enabled = load_search_index_enabled()
        self.last_flipped_tile = None
        self.pending_flipped_tile = None
        self.text_size = load_text_size()
        self.custom_font = load_custom_font()
        self.album_art_size, self.now_art_size = load_art_sizes()
        self.album_columns = load_album_columns()
        self.album_margin, self.album_spacing = load_album_margins()
        self.album_art_size = album_cover_size(self.normal_size[0] - 70,
                                               self.album_columns, self.album_margin,
                                               self.album_spacing)
        self.zoom_remainder = {'albums': 0.0, 'now': 0.0}
        self.current_art_colors = None
        self.current_art_key = None
        layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(layout)
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                               margin=8)
        self.sidebar.connect('button-press-event', self.context_menu_pressed)
        self.sidebar.set_name('side-nav')
        self.sidebar.set_size_request(70, -1)
        layout.pack_start(self.sidebar, False, False, 0)
        self.window_grip = Gtk.EventBox()
        self.window_grip.add(Gtk.Label(label='⋮⋮'))
        self.set_tooltip(self.window_grip, 'Drag to move window')
        self.window_grip.connect('button-press-event', self.window_grip_pressed)
        self.sidebar.pack_start(self.window_grip, False, False, 0)
        self.nav_buttons = {}
        self.add_nav_button('now', 'Now playing', 'media-playback-start-symbolic')
        self.add_nav_button('albums', 'Albums', 'media-optical-symbolic')
        self.add_nav_button('library', 'Library', 'audio-x-generic-symbolic')
        self.add_nav_button('settings', 'Settings', 'emblem-system-symbolic', bottom=True)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        layout.pack_start(main, True, True, 0)
        self.content_views = Gtk.Stack()
        self.content_views.connect('button-press-event', self.context_menu_pressed)
        self.content_overlay = Gtk.Overlay()
        self.content_overlay.add(self.content_views)
        main.pack_start(self.content_overlay, True, True, 0)
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
        self.album_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.content_views.add_named(self.album_panel, 'albums')
        toolbar = Gtk.Box(spacing=12, margin=12)
        toolbar.set_name('library-toolbar')
        toolbar.set_no_show_all(True)
        self.album_toolbar = toolbar
        toolbar.pack_start(Gtk.Label(label='Recently added'), False, False, 0)
        self.library = Gtk.ComboBoxText()
        self.library.connect('changed', self.library_changed)
        toolbar.pack_start(self.library, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text='Search albums; press Enter')
        self.search.connect('activate', self.search_album_titles)
        toolbar.pack_start(self.search, True, True, 0)
        self.album_panel.pack_start(toolbar, False, False, 0)
        self.views = Gtk.Stack()
        self.album_panel.pack_start(self.views, True, True, 0)
        wall = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=self.album_spacing,
                       margin=self.album_margin)
        self.album_wall = wall
        self.artist_filter_bar = Gtk.Box(spacing=10)
        self.artist_filter_bar.set_no_show_all(True)
        self.album_results_back = Gtk.Button(label='◀')
        self.album_results_back.set_name('album-results-back')
        self.set_tooltip(self.album_results_back, 'Back to all albums')
        self.album_results_back.get_accessible().set_name('Back to all albums')
        self.album_results_back.connect('clicked', self.show_all_albums)
        self.artist_filter_bar.pack_start(self.album_results_back, False, False, 0)
        self.artist_filter_label = Gtk.Label(xalign=0)
        self.artist_filter_bar.pack_start(self.artist_filter_label, True, True, 0)
        wall.pack_start(self.artist_filter_bar, False, False, 0)
        self.grid = Gtk.FlowBox()
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
        self.more = self.button('Load more albums', lambda *_: self.load_albums(True))
        self.more.set_name('album-load-more')
        self.more.set_no_show_all(True)
        self.more.set_sensitive(False)
        wall.pack_start(self.more, False, False, 0)
        wall_scroll = self.scroll(wall)
        wall_scroll.set_name('library-wall')
        wall_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_tooltip(wall_scroll, 'Hold Ctrl and scroll to resize album covers')
        wall_scroll.connect('scroll-event', self.zoom_art, 'albums')
        wall_scroll.connect('size-allocate', self.album_wall_allocated)
        self.wall_scroll = wall_scroll
        wall_overlay = Gtk.Overlay()
        self.albums_background = DitheredGradient()
        wall_overlay.add(self.albums_background)
        wall_overlay.add_overlay(wall_scroll)
        self.views.add_named(wall_overlay, 'wall')
        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=16)
        detail.pack_start(self.button('‹ All albums', lambda *_: self.views.set_visible_child_name('wall')), False, False, 0)
        album_header = Gtk.Box(spacing=18)
        self.cover = Gtk.Image.new_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        self.cover.set_size_request(160, 160)
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
        self.track_store = Gtk.ListStore(str, str, str)
        self.track_view = self.table(self.track_store, ['#', 'Track', 'Time'])
        self.track_view.connect('row-activated', self.activate_track)
        detail.pack_start(self.scroll(self.track_view), True, True, 0)
        self.views.add_named(detail, 'detail')
        self.views.set_visible_child_name('wall')
        self.build_now_view()
        self.build_library_view()
        self.build_settings_view()
        self.render_gradient()
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar.set_name('player-bar')
        self.player_bar = bar
        bar.connect('button-press-event', self.context_menu_pressed)
        main.pack_end(bar, False, False, 0)
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.01)
        self.seek.set_name('border-timeline')
        self.seek.set_draw_value(False)
        self.seek.set_digits(2)
        self.seek.connect('change-value', self.seek_to)
        self.seek.connect('button-press-event', self.timeline_pressed)
        self.seek.connect('button-release-event', self.timeline_released)
        self.seek.set_sensitive(False)
        bar.pack_start(self.seek, False, False, 0)
        controls = Gtk.Overlay()
        bar.pack_start(controls, False, False, 0)
        sides = Gtk.Box(spacing=10, margin=10)
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
        self.now_cover = Gtk.Image.new_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        self.now_cover.set_size_request(48, 48)
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
        playback_buttons.pack_start(
            self.icon_button('media-skip-backward-symbolic', 'Previous', self.previous),
            False, False, 0)
        self.play_button = self.icon_button('media-playback-start-symbolic', 'Play', self.toggle)
        playback_buttons.pack_start(self.play_button, False, False, 0)
        playback_buttons.pack_start(
            self.icon_button('media-skip-forward-symbolic', 'Next', lambda *_: self.advance()),
            False, False, 0)
        utilities = Gtk.Box(spacing=6)
        utilities.set_size_request(205, -1)
        utilities.set_hexpand(True)
        utilities.set_halign(Gtk.Align.END)
        sides.pack_end(utilities, True, True, 0)
        self.time = Gtk.Label(label='0:00 / 0:00')
        utilities.pack_start(self.time, False, False, 0)
        self.shuffle = self.icon_toggle('media-playlist-shuffle-symbolic', 'Shuffle')
        self.repeat = self.icon_toggle('media-playlist-repeat-symbolic', 'Repeat')
        self.shuffle.connect('toggled', self.playback_options_changed)
        self.repeat.connect('toggled', self.playback_options_changed)
        utilities.pack_start(self.shuffle, False, False, 0)
        utilities.pack_start(self.repeat, False, False, 0)
        volume = Gtk.VolumeButton()
        self.volume = volume
        volume.set_value(0.8)
        self.pipeline.set_property('volume', 0.8)
        volume.connect('value-changed', self.volume_changed)
        utilities.pack_start(volume, False, False, 0)
        self.search_button = self.icon_button('system-search-symbolic', 'Search albums',
                                              self.toggle_album_search)
        utilities.pack_start(self.search_button, False, False, 0)
        self.status = Gtk.Label(label='Connect to your Plex server')
        self.status.connect('notify::label', self.status_changed)
        self.status_changed()
        self.show_all()
        self.content_views.set_sensitive(False)
        self.sidebar.set_sensitive(False)
        self.player_bar.set_sensitive(False)
        self.loading_spinner.start()
        self.apply_tooltip_setting()
        self.album_toolbar.hide()
        self.artist_filter_bar.hide()
        self.more.hide()
        self.library_back_button.hide()
        self.window_grip.set_visible(self.hide_title_bar)
        self.apply_text_size()
        self.show_view(self.saved_session.get('panel', 'albums'))
        if self.saved_session.get('settings_page') == 'shortcuts':
            self.shortcut_scroll.show_all()
            self.settings_stack.set_visible_child_name('shortcuts')
        if window.get('maximized'):
            self.maximize()
        self.mpris = Mpris(self) if mpris_enabled else InactiveMpris()
        GLib.timeout_add(500, self.tick)
        GLib.timeout_add(33, self.animate_timeline)
        GLib.timeout_add_seconds(3600, self.refresh_album_ages)
        GLib.timeout_add_seconds(30, self.refresh_remote_connection)
        GLib.idle_add(self.restore_connection)
        GLib.idle_add(self.initialize_remote)

    def playback_options_changed(self, *_):
        if hasattr(self, 'mpris'):
            self.mpris.changed()

    def volume_changed(self, _button, value):
        self.pipeline.set_property('volume', value)
        if hasattr(self, 'mpris'):
            self.mpris.changed()

    def set_volume(self, value):
        self.volume.set_value(value)

    def apply_text_size(self):
        size = self.text_size
        font = self.custom_font.replace('\\', '\\\\').replace('"', '\\"')
        family = f' font-family: "{font}";' if font else ''
        self.text_provider.load_from_data(
            f'#plex-player {{ font-size: {size}px;{family} }} '
            f'#now-title {{ font-size: {round(size * 1.55)}px; }} '
            f'#album-grid #album-meta {{ font-size: {round(size * 0.8)}px; }}'.encode())

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
        self.accent_provider.load_from_data(f'''
            #border-timeline highlight {{ background: {color}; }}
            #player-bar button:checked image, #side-nav button.active image {{ color: {color}; }}
            #side-nav button.active, #song-panel button:checked {{ background: {wash}; }}
            #song-panel button:checked {{ border-bottom: 2px solid {color}; }}
            #album-card-back button.playing-track {{ background: {wash}; }}
        '''.encode())

    def window_grip_pressed(self, _widget, event):
        if event.button == 1 and self.hide_title_bar:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
            return True
        return False

    def global_key_pressed(self, _window, event):
        if getattr(self, 'startup_loading', False):
            return True
        modified = event.state & (Gdk.ModifierType.CONTROL_MASK |
                                  Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SUPER_MASK)
        focus = self.get_focus()
        editing = isinstance(focus, (Gtk.Entry, Gtk.TextView)) or (
            isinstance(focus, Gtk.Editable))
        if event.keyval == Gdk.KEY_space and not modified:
            if editing:
                return False
            if not self.space_held:
                self.space_held = True
                self.toggle()
            return True
        if (not modified and not editing and event.keyval in
                (Gdk.KEY_1, Gdk.KEY_2, Gdk.KEY_3, Gdk.KEY_4)):
            self.show_view({Gdk.KEY_1: 'now', Gdk.KEY_2: 'albums',
                            Gdk.KEY_3: 'library', Gdk.KEY_4: 'settings'}[event.keyval])
            return True
        if event.keyval != Gdk.KEY_f or modified:
            return False
        if editing:
            return False
        visible = self.sidebar.get_visible()
        self.sidebar.set_visible(not visible)
        self.player_bar.set_visible(not visible)
        return True

    def global_key_released(self, _window, event):
        if getattr(self, 'startup_loading', False):
            return True
        if event.keyval == Gdk.KEY_space:
            self.space_held = False
            return not isinstance(self.get_focus(), (Gtk.Entry, Gtk.TextView, Gtk.Editable))
        return False

    def window_focus_out(self, *_):
        self.space_held = False
        return False

    def album_wall_allocated(self, _widget, allocation):
        if getattr(self, '_album_wall_width', None) == allocation.width:
            return
        self._album_wall_width = allocation.width
        if not getattr(self, '_album_layout_pending', False):
            self._album_layout_pending = True
            GLib.idle_add(self.apply_album_grid_layout)

    def apply_album_grid_layout(self):
        self._album_layout_pending = False
        size = album_cover_size(self.wall_scroll.get_allocated_width(), self.album_columns,
                                self.album_margin, self.album_spacing)
        self.grid.set_min_children_per_line(self.album_columns)
        self.grid.set_max_children_per_line(self.album_columns)
        if size == self.album_art_size:
            return False
        self.album_art_size = size
        for child in self.grid.get_children():
            tile = child.get_child()
            self.set_art_size(tile.art_image, size)
            tile.metadata_box.set_size_request(size, -1)
            tile.flip_card.resize_card(size)
            tile.heading_button.set_visible(size >= 100)
            tile.cover_button.set_label('‹' if size < 100 else '‹ Cover')
        self.grid.queue_resize()
        return False

    def window_allocated(self, _window, allocation):
        if not self.is_maximized() and allocation.width >= 640 and allocation.height >= 480:
            self.normal_size = allocation.width, allocation.height

    def restore_connection(self):
        self.status.set_text('Looking for saved server login…')
        def restored(credentials):
            if credentials:
                self.restored_credentials = credentials
                self.connect_to_server(*credentials, remember=False, automatic=True)
            else:
                self.connect_dialog()
        self.async_work(load_credentials, restored, on_error=self.connect_dialog)
        return False

    def remote_work(self, work, done, failed):
        def run():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, exc
            def deliver():
                if not self.closed:
                    failed(error) if error else done(result)
                return False
            GLib.idle_add(deliver)
        threading.Thread(target=run, daemon=True).start()

    def initialize_remote(self):
        def load():
            token = load_device_token(self.remote_config['identifier'])
            if token and self.remote_config['enabled']:
                try:
                    return token, self.remote_account.user_id(token)
                except Exception:
                    return token, None
            return None, None
        def ready(result):
            self.remote_link_token, self.remote_link_user = result
            if self.remote_receiver:
                self.remote_receiver.set_link(*result)
            if self.remote_config['enabled']:
                self.start_remote_receiver()
                self.refresh_remote_connection()
            else:
                self.update_remote_status()
            if self.remote_link_token and not self.remote_link_user:
                self.update_remote_status('Plex link could not be verified; reconnect or relink.')
        def failed(_error):
            self.remote_keyring_available = False
            if self.remote_config['enabled']:
                self.start_remote_receiver()
            self.update_remote_status()
        self.remote_work(load, ready, failed)
        return False

    def update_remote_status(self, detail=None):
        if detail:
            self.remote_status.set_text(detail)
        elif not self.remote_config['enabled']:
            self.remote_status.set_text('Remote control is off')
        elif self.remote_receiver:
            link = ('linked to Plex' if self.remote_link_user else
                    'keyring unavailable; linking disabled' if not self.remote_keyring_available
                    else 'not linked to Plex')
            self.remote_status.set_text(
                f'Listening at http://{local_ip()}:{self.remote_receiver.port} • {link}' +
                (' • Plex server identity unavailable' if self.client and
                 not self.remote_server_machine else '') +
                (' • GDM unavailable (UDP 32412)' if not self.remote_receiver.gdm else ''))
        else:
            self.remote_status.set_text('Starting local receiver…')
        self.remote_link_button.set_sensitive(self.remote_keyring_available and
                                              self.remote_config['enabled'] and
                                              self.remote_receiver is not None)
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
        name = self.remote_name_entry.get_text().strip() or 'Plex Music on Linux'
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
        if self.client:
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

    def start_remote_link(self, *_):
        if not self.remote_receiver or not self.remote_keyring_available:
            return
        self.remote_pin_generation += 1
        generation = self.remote_pin_generation
        self.update_remote_status('Requesting Plex link code…')
        def ready(result):
            if generation != self.remote_pin_generation:
                return
            pin_id, code = result
            dialog = Gtk.Dialog(title='Link Plex Music to Plex', transient_for=self)
            dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
            box = dialog.get_content_area()
            box.set_spacing(10)
            box.set_border_width(18)
            box.pack_start(Gtk.Label(label=f'Enter code {code} at plex.tv/link'), False, False, 0)
            box.pack_start(Gtk.LinkButton.new_with_label('https://plex.tv/link',
                                                         'Open plex.tv/link'), False, False, 0)
            dialog.connect('response', lambda window, *_: (setattr(
                self, 'remote_pin_generation', self.remote_pin_generation + 1), window.destroy()))
            dialog.show_all()
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
                        self.update_remote_status('Plex link code expired or could not be checked.')
                self.remote_work(lambda: self.remote_account.check_pin(pin_id), linked, failed)
                return True
            GLib.timeout_add_seconds(3, poll)
        self.remote_work(self.remote_account.create_pin, ready,
                         lambda _error: self.update_remote_status('Could not request a Plex link code.'))

    def finish_remote_link(self, token):
        def work():
            user = self.remote_account.user_id(token)
            save_device_token(self.remote_config['identifier'], token)
            return user
        def ready(user):
            self.remote_link_token, self.remote_link_user = token, user
            with self.remote_token_lock:
                self.remote_token_cache.clear()
            if self.remote_receiver:
                self.remote_receiver.set_link(token, user)
            self.update_remote_status()
            self.refresh_remote_connection()
        self.remote_work(work, ready, lambda _error: self.update_remote_status(
            'Could not save Plex link in the desktop keyring; no plaintext fallback is used.'))

    def unlink_remote(self, *_):
        token = self.remote_link_token
        if not token:
            return
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
        self.loading_spinner.stop()
        self.loading_overlay.hide()
        self.content_views.set_sensitive(True)
        self.sidebar.set_sensitive(True)
        self.player_bar.set_sensitive(True)

    def add_nav_button(self, view, label, icon, bottom=False):
        button = Gtk.Button()
        button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR))
        self.set_tooltip(button, label)
        button.get_accessible().set_name(label)
        button.connect('clicked', lambda *_: self.show_view(view))
        self.sidebar.pack_end(button, False, False, 0) if bottom else self.sidebar.pack_start(button, False, False, 0)
        self.nav_buttons[view] = button

    def show_view(self, view, preserve=False):
        if view != 'now':
            self.previous_panel = view
        if view == 'albums' and not preserve:
            self.views.set_visible_child_name('wall')
        elif view == 'settings' and not preserve:
            self.settings_stack.set_visible_child_name('main')
        self.content_views.set_visible_child_name(view)
        for name, button in self.nav_buttons.items():
            context = button.get_style_context()
            if name == view:
                context.add_class('active')
            else:
                context.remove_class('active')
        if hasattr(self, 'status'):
            self.status_changed()

    def toggle_now_panel(self, *_):
        current = self.content_views.get_visible_child_name()
        self.show_view(self.previous_panel if current == 'now' else 'now',
                       preserve=current == 'now')

    def toggle_album_search(self, *_):
        if self.content_views.get_visible_child_name() != 'albums':
            self.show_view('albums')
            self.album_toolbar.set_no_show_all(False)
            self.album_toolbar.show_all()
            self.search.grab_focus()
        elif self.album_toolbar.get_visible():
            self.album_toolbar.hide()
            self.search_button.grab_focus()
        else:
            self.views.set_visible_child_name('wall')
            self.album_toolbar.set_no_show_all(False)
            self.album_toolbar.show_all()
            self.search.grab_focus()

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

    def show_context_menu(self, event, tile=None):
        menu = Gtk.Menu()
        menu.attach_to_widget(self, None)
        def item(label, callback):
            entry = Gtk.MenuItem.new_with_label(label)
            entry.connect('activate', lambda *_: callback())
            menu.append(entry)
        def separator():
            menu.append(Gtk.SeparatorMenuItem())
        if tile is not None:
            item('Show cover' if tile.flip_card.side == 'back' else 'Flip album',
                 lambda: self.flip_album_card(tile))
            item('Open album', lambda: self.select_album(tile.album))
            item('Show Artist Albums', lambda: self.show_artist_albums(tile.album.artist))
            item('Show in library', lambda: self.show_in_library(tile.album))
            separator()
        elif self.queue_album is not None:
            item('Show Artist Albums',
                 lambda: self.show_artist_albums(self.queue_album.artist))
            item('Show in library', lambda: self.show_in_library(self.queue_album))
            separator()
        item('Pause' if self.playing else 'Play', self.toggle)
        item('Previous', self.previous)
        item('Next', self.advance)
        separator()
        item('Now Playing', lambda: self.show_view('now'))
        item('Albums', lambda: self.show_view('albums'))
        item('Library', lambda: self.show_view('library'))
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

    def library_artist_pressed(self, view, event):
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if event.button == 3 and hit:
            index = hit[0].get_indices()[0]
            if 0 <= index < len(self.songs):
                view.get_selection().select_path(hit[0])
                self.show_song_context_menu(event, self.songs[index], index)
                return True
            return False
        if event.button != 1:
            return False
        if hit and hit[1].get_title() == 'Artist':
            index = hit[0].get_indices()[0]
            if 0 <= index < len(self.songs) and self.songs[index].artist:
                self.show_artist_albums(self.songs[index].artist)
                return True
        return False

    def show_song_context_menu(self, event, song, index):
        menu = Gtk.Menu()
        menu.attach_to_widget(self, None)
        def item(label, action):
            entry = Gtk.MenuItem.new_with_label(label)
            entry.connect('activate', lambda *_: action())
            menu.append(entry)
        item('Play Song', lambda: self.play_song(index))
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
        client = self.client
        if client is None:
            return
        section = self.library.get_active_id()
        def updated(_response):
            rating = 10.0 if loved else 0.0
            for collection in (self.song_catalog, self.songs, self.queue):
                if collection:
                    for candidate in collection:
                        if candidate.key == song.key:
                            candidate.user_rating = rating
            if section:
                cache = LocalCache(client)
                playlist_keys = [None]
                if self.active_playlist:
                    playlist_keys.append(self.active_playlist.key)
                for playlist_key in playlist_keys:
                    if (playlist_key is None and self.active_playlist is None and
                            self.library_album_filter is None and self.song_catalog is not None):
                        catalog = self.song_catalog
                    else:
                        catalog = cache.read_song_index(section, playlist_key)
                    if catalog is None:
                        continue
                    changed = False
                    for candidate in catalog:
                        if candidate.key == song.key:
                            candidate.user_rating = rating
                            changed = True
                    if changed:
                        try:
                            cache.save_song_index(section, catalog, playlist_key)
                        except OSError:
                            pass
            self.load_songs()
            self.status.set_text(('Loved ' if loved else 'Removed love from ') + song.title)
        self.async_work(lambda: client.rate_track(song, loved), updated,
                        lambda: client is self.client,
                        lambda: self.status.set_text('Could not update song rating on Plex.'))

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
        self.album_toolbar.hide()
        self.search.set_text('')
        self.show_view('albums')
        self.load_albums()

    def search_album_titles(self, *_):
        self.artist_filter = None
        self.artist_catalog = None
        self.artist_filter_bar.hide()
        self.load_albums()

    def show_in_library(self, album):
        if not self.client:
            return
        self.invalidate_song_catalog()
        self.library_album_filter = None
        self.playlist_list.select_row(self.all_songs_row)
        self.active_playlist = None
        self.library_album_filter = album
        self.library_back_button.set_no_show_all(False)
        self.library_back_button.show()
        self.songs_heading.set_text(f'{album.title} · {album.artist}')
        self.apply_library_layout()
        self.show_view('library')
        self.load_songs()

    def clear_library_album_filter(self, *_):
        self.invalidate_song_catalog()
        self.library_album_filter = None
        self.library_back_button.hide()
        self.apply_library_layout()
        if self.playlist_list.get_selected_row() is self.all_songs_row:
            self.songs_heading.set_text('Songs')
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
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        panel.set_name('now-panel')
        self.now_panel = panel
        panel.connect('scroll-event', self.zoom_art, 'now')
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=32)
        group.set_hexpand(True)
        group.set_valign(Gtk.Align.CENTER)
        panel.pack_start(group, True, True, 0)
        self.hero_cover = Gtk.Image.new_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        self.hero_cover.set_halign(Gtk.Align.CENTER)
        self.hero_cover.set_valign(Gtk.Align.CENTER)
        self.set_art_size(self.hero_cover, self.now_art_size)
        self.waveform = Waveform()
        self.waveform.set_size_request(-1, 320)
        self.waveform.set_hexpand(True)
        self.waveform.set_vexpand(True)
        cover_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        cover_page.set_halign(Gtk.Align.FILL)
        cover_page.set_valign(Gtk.Align.FILL)
        cover_page.pack_start(self.hero_cover, True, False, 0)
        self.art_stack = Gtk.Stack()
        self.art_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.art_stack.set_transition_duration(180)
        self.art_stack.set_hexpand(True)
        self.art_stack.set_vexpand(True)
        self.art_stack.set_vhomogeneous(False)
        self.art_stack.add_named(cover_page, 'cover')
        self.art_stack.add_named(self.waveform, 'waveform')
        self.art_stack.set_visible_child_name('cover')
        self.art_button = Gtk.Button()
        self.art_button.set_name('art-toggle')
        self.art_button.set_hexpand(True)
        self.art_button.set_vexpand(False)
        self.art_button.add(self.art_stack)
        self.set_tooltip(self.art_button, 'Click for layered waves • Ctrl+scroll to resize artwork')
        self.art_button.get_accessible().set_name('Show waveform visualizer')
        self.art_button.connect('clicked', self.toggle_art_visualizer)
        self.art_button.connect('scroll-event', self.zoom_art, 'now')
        group.pack_start(self.art_button, False, False, 0)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        group.pack_start(info, False, False, 0)
        self.hero_title = Gtk.Label(label='Nothing playing')
        self.hero_title.set_name('now-title')
        self.hero_title.set_justify(Gtk.Justification.CENTER)
        self.hero_title.set_line_wrap(True)
        info.pack_start(self.hero_title, False, False, 0)
        self.hero_artist = Gtk.Label(label='Choose an album or song to start listening')
        hero_artist_click = Gtk.EventBox()
        hero_artist_click.set_visible_window(False)
        hero_artist_click.add(self.hero_artist)
        hero_artist_click.connect('button-press-event', self.artist_name_pressed,
                                  lambda: self.queue[self.index].artist
                                  if 0 <= self.index < len(self.queue) else '')
        info.pack_start(hero_artist_click, False, False, 0)
        self.hero_album = Gtk.Label()
        info.pack_start(self.hero_album, False, False, 0)
        now_scroll = self.scroll(panel)
        now_scroll.set_name('now-scroll')
        now_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        now_scroll.connect('scroll-event', self.zoom_art, 'now')
        now_overlay = Gtk.Overlay()
        self.now_background = DitheredGradient()
        now_overlay.add(self.now_background)
        now_overlay.add_overlay(now_scroll)
        self.content_views.add_named(now_overlay, 'now')

    def set_art_size(self, image, size):
        image.art_display_size = size
        image.set_size_request(size, size)
        source = getattr(image, 'art_source', None)
        if source:
            pixbuf = source if source.get_width() == size and source.get_height() == size else \
                source.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
            image.set_from_pixbuf(pixbuf)
        elif image.get_storage_type() == Gtk.ImageType.ICON_NAME:
            image.set_pixel_size(min(size // 3, 96))

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
            low, high = ALBUM_COLUMN_RANGE
            columns = max(low, min(high, self.album_columns - steps))
            if columns == self.album_columns:
                return True
            self.album_columns = columns
            self.apply_album_grid_layout()
            try:
                save_album_columns(columns)
            except OSError:
                self.status.set_text('Could not save album grid zoom.')
        else:
            low, high = NOW_SIZE_RANGE
            size = max(low, min(high, self.now_art_size + 40 * steps))
            if size == self.now_art_size:
                return True
            self.now_art_size = size
            self.set_art_size(self.hero_cover, size)
            try:
                save_now_art_size(size)
            except OSError:
                self.status.set_text('Could not save artwork size.')
        return True

    def toggle_art_visualizer(self, *_):
        if not self.audio_spectrum:
            self.status.set_text('The GStreamer spectrum plugin is needed for the waveform visualizer.')
            return
        showing_waveform = self.art_stack.get_visible_child_name() == 'waveform'
        self.art_stack.set_visible_child_name('cover' if showing_waveform else 'waveform')
        self.set_tooltip(self.art_button,
            'Click for layered waves • Ctrl+scroll to resize artwork' if showing_waveform
            else 'Click for album art')
        self.art_button.get_accessible().set_name(
            'Show waveform visualizer' if showing_waveform else 'Show album artwork')
        if not showing_waveform:
            self.waveform.queue_draw()

    def build_library_view(self):
        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_position(225)
        playlists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        playlists.set_name('playlist-panel')
        playlists.set_size_request(170, -1)
        playlist_header = Gtk.Box(spacing=4)
        playlist_header.pack_start(Gtk.Label(label='PLAYLISTS', xalign=0), True, True, 0)
        self.new_playlist_button = Gtk.Button.new_from_icon_name('list-add-symbolic', Gtk.IconSize.BUTTON)
        self.set_tooltip(self.new_playlist_button, 'Create playlist on Plex')
        self.new_playlist_button.get_accessible().set_name('Create playlist')
        self.new_playlist_button.connect('clicked', self.create_playlist_dialog)
        playlist_header.pack_end(self.new_playlist_button, False, False, 0)
        playlists.pack_start(playlist_header, False, False, 0)
        self.playlist_list = Gtk.ListBox()
        self.playlist_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.playlist_list.connect('row-selected', self.select_playlist)
        playlists.pack_start(self.scroll(self.playlist_list), True, True, 0)
        self.all_songs_row = self.playlist_row('All songs', None)
        split.pack1(playlists, False, False)

        songs_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=16)
        songs_panel.set_name('song-panel')
        self.songs_heading = Gtk.Label(label='Songs', xalign=0)
        self.songs_heading.set_name('now-title')
        songs_panel.pack_start(self.songs_heading, False, False, 0)
        self.library_back_button = self.button('‹ All songs', self.clear_library_album_filter)
        self.library_back_button.set_no_show_all(True)
        self.library_back_button.set_halign(Gtk.Align.START)
        songs_panel.pack_start(self.library_back_button, False, False, 0)
        self.library_search = Gtk.SearchEntry(
            placeholder_text='Filter songs, artists, albums')
        self.library_search.connect('search-changed', self.library_search_changed)
        songs_panel.pack_start(self.library_search, False, False, 0)
        self.song_sort = 'addedAt:desc'
        self.song_store = Gtk.ListStore(*([str] * (len(LIBRARY_COLUMNS) + 1)))
        self.song_view = self.table(self.song_store, ['Song', 'Artist', 'Album', 'Time'])
        self.song_columns = {}
        for column, field in zip(self.song_view.get_columns(),
                                 BASE_LIBRARY_FIELDS):
            self.configure_song_column(column, field)
        for index, (label, field) in enumerate(LIBRARY_COLUMNS[4:], 4):
            column = Gtk.TreeViewColumn(label, Gtk.CellRendererText(), text=index)
            self.song_view.append_column(column)
            self.configure_song_column(column, field)
            column.set_visible(False)
        heart = Gtk.CellRendererText()
        heart.set_property('foreground', '#e84b5a')
        heart.set_property('scale', 0.82)
        title_column = self.song_columns['title']
        title_column.pack_start(heart, False)
        title_column.add_attribute(heart, 'text', len(LIBRARY_COLUMNS))
        title_column.reorder(heart, 0)
        for column in self.song_view.get_columns():
            for renderer in column.get_cells():
                column.set_cell_data_func(renderer, self.song_row_background)
        self.song_view.connect('columns-changed', self.library_columns_changed)
        self.song_view.connect('row-activated', self.activate_song)
        self.song_view.connect('button-press-event', self.library_artist_pressed)
        song_target = [Gtk.TargetEntry.new('application/x-plex-song-key',
                                           Gtk.TargetFlags.SAME_APP, 0)]
        self.song_view.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK,
                                                 song_target, Gdk.DragAction.COPY)
        self.song_view.connect('drag-data-get', self.song_drag_data_get)
        songs_panel.pack_start(self.scroll(self.song_view), True, True, 0)
        self.song_count = Gtk.Label(label='Connect to a server to browse songs', xalign=0)
        songs_panel.pack_start(self.song_count, False, False, 0)
        split.pack2(songs_panel, True, False)
        self.content_views.add_named(split, 'library')
        self.playlists = []
        self.active_playlist = None
        self.playlist_restore_key = None
        self.songs = []
        self.song_total = 0
        self.song_generation = 0
        self.playlist_generation = 0
        self.current_library_layout_key = None
        self.library_layout_restoring = False
        self.library_layout_save_timeout = 0
        self.playlist_list.select_row(self.all_songs_row)

    def build_settings_view(self):
        self.settings_stack = Gtk.Stack()
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin=24)
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
        info = Gtk.Label(label='Server login is stored in your desktop keyring after a successful connection.', xalign=0)
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
        remote_actions = Gtk.Box(spacing=12)
        self.remote_link_button = self.button('Link Plex account…', self.start_remote_link)
        self.remote_unlink_button = self.button('Unlink', self.unlink_remote)
        remote_actions.pack_start(self.remote_link_button, False, False, 0)
        remote_actions.pack_start(self.remote_unlink_button, False, False, 0)
        self.remote_unlink_button.set_sensitive(False)
        panel.pack_start(remote_actions, False, False, 0)
        panel.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        panel.pack_start(Gtk.Label(label='Appearance', xalign=0), False, False, 0)
        self.gradient_toggle = Gtk.CheckButton(label='Use album art colors behind Now Playing and Albums')
        self.gradient_toggle.set_active(self.gradient_enabled)
        self.gradient_toggle.connect('toggled', self.gradient_changed)
        panel.pack_start(self.gradient_toggle, False, False, 0)
        accent_row = Gtk.Box(spacing=12)
        accent_row.pack_start(Gtk.Label(label='Pick accent color', xalign=0), False, False, 0)
        self.accent_color_button = Gtk.ColorButton()
        self.accent_color_button.set_title('Pick accent color')
        self.accent_color_button.set_use_alpha(False)
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
        self.tooltips_toggle = Gtk.CheckButton(label='Hide all tooltips')
        self.tooltips_toggle.set_active(self.tooltips_hidden)
        self.tooltips_toggle.connect('toggled', self.tooltips_changed)
        panel.pack_start(self.tooltips_toggle, False, False, 0)
        self.album_details_toggle = Gtk.CheckButton(label='Show artist, album title and days since added on album covers')
        self.album_details_toggle.set_active(self.show_album_details)
        self.album_details_toggle.connect('toggled', self.album_details_changed)
        panel.pack_start(self.album_details_toggle, False, False, 0)
        panel.pack_start(Gtk.Label(label='Album grid outer margin', xalign=0), False, False, 0)
        self.album_outer_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 64, 2)
        self.album_outer_scale.set_value(self.album_margin)
        self.album_outer_scale.set_digits(0)
        self.album_outer_scale.connect('value-changed', self.album_margins_changed)
        panel.pack_start(self.album_outer_scale, False, False, 0)
        panel.pack_start(Gtk.Label(label='Space between album covers', xalign=0), False, False, 0)
        self.album_gap_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 36, 2)
        self.album_gap_scale.set_value(self.album_spacing)
        self.album_gap_scale.set_digits(0)
        self.album_gap_scale.connect('value-changed', self.album_margins_changed)
        panel.pack_start(self.album_gap_scale, False, False, 0)
        self.single_flip_toggle = Gtk.CheckButton(label='Only one album flipped at a time')
        self.single_flip_toggle.set_active(self.single_flip_enabled)
        self.single_flip_toggle.connect('toggled', self.single_flip_changed)
        panel.pack_start(self.single_flip_toggle, False, False, 0)
        self.title_bar_toggle = Gtk.CheckButton(label='Hide window title bar')
        self.title_bar_toggle.set_active(self.hide_title_bar)
        self.title_bar_toggle.connect('toggled', self.title_bar_changed)
        panel.pack_start(self.title_bar_toggle, False, False, 0)
        panel.pack_start(Gtk.Label(label='Text size', xalign=0), False, False, 0)
        self.text_size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 24, 1)
        self.text_size_scale.set_value(self.text_size)
        self.text_size_scale.set_digits(0)
        self.text_size_scale.connect('value-changed', self.text_size_changed)
        panel.pack_start(self.text_size_scale, False, False, 0)
        self.font_toggle = Gtk.CheckButton(label='Use custom font')
        self.font_toggle.set_active(bool(self.custom_font))
        self.font_toggle.connect('toggled', self.custom_font_toggled)
        panel.pack_start(self.font_toggle, False, False, 0)
        self.font_button = Gtk.FontButton()
        self.font_button.set_show_size(False)
        self.font_button.set_font_name(self.custom_font or 'Sans')
        self.font_button.set_sensitive(bool(self.custom_font))
        self.font_button.connect('font-set', self.custom_font_changed)
        panel.pack_start(self.font_button, False, False, 0)
        panel.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        panel.pack_start(Gtk.Label(label='Search', xalign=0), False, False, 0)
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
        panel.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        shortcuts_button = self.button('Global keyboard shortcuts…', self.show_shortcuts_page)
        shortcuts_button.set_halign(Gtk.Align.START)
        panel.pack_start(shortcuts_button, False, False, 0)
        self.settings_stack.add_named(self.scroll(panel), 'main')

        shortcut_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin=24)
        shortcut_page.set_name('settings-panel')
        back = self.button('‹ Settings', lambda *_: self.settings_stack.set_visible_child_name('main'))
        back.set_halign(Gtk.Align.START)
        shortcut_page.pack_start(back, False, False, 0)
        heading = Gtk.Label(label='Global keyboard shortcuts', xalign=0)
        heading.set_name('now-title')
        shortcut_page.pack_start(heading, False, False, 0)
        description = Gtk.Label(label='These Xfce shortcuts control Plex Music while it is running.', xalign=0)
        description.set_line_wrap(True)
        shortcut_page.pack_start(description, False, False, 0)
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
        self.shortcut_scroll = self.scroll(shortcut_page)
        self.settings_stack.add_named(self.shortcut_scroll, 'shortcuts')
        self.content_views.add_named(self.settings_stack, 'settings')

    def show_shortcuts_page(self, *_):
        self.show_view('settings')
        self.shortcut_scroll.show_all()
        self.settings_stack.set_visible_child_name('shortcuts')
        self.refresh_shortcuts()

    def refresh_shortcuts(self):
        if not shortcuts.available():
            self.shortcut_status.set_text('Shortcut editing requires an Xfce desktop with xfconf-query and gdbus.')
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
        self.render_gradient()
        try:
            save_gradient_enabled(self.gradient_enabled)
        except OSError:
            self.status.set_text('Could not save the appearance setting.')

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
        for side in ('start', 'end', 'top', 'bottom'):
            getattr(self.album_wall, f'set_margin_{side}')(self.album_margin)
        self.album_wall.set_spacing(self.album_spacing)
        self.grid.set_row_spacing(self.album_spacing)
        self.grid.set_column_spacing(self.album_spacing)
        self.apply_album_grid_layout()
        try:
            save_album_margins(self.album_margin, self.album_spacing)
        except OSError:
            self.status.set_text('Could not save album margins.')

    def single_flip_changed(self, button):
        self.single_flip_enabled = button.get_active()
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
        self.window_grip.set_visible(self.hide_title_bar)
        try:
            save_title_bar_hidden(self.hide_title_bar)
        except OSError:
            self.status.set_text('Could not save title bar setting.')

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
        description = Pango.FontDescription.from_string(self.font_button.get_font_name())
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
        self.index_refresh.set_sensitive(True)
        if self.index_section == section and (self.indexed_albums is not None or
                                              self.index_building):
            return
        self.index_generation += 1
        self.index_section = section
        self.index_cache = LocalCache(self.client)
        self.indexed_albums = self.index_cache.read_index(section)
        self.index_building = False
        if self.indexed_albums is None:
            self.start_search_index_build()
        else:
            self.index_status.set_text(f'{len(self.indexed_albums)} albums indexed • Refresh to update')

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
        colors = self.current_art_colors if self.gradient_enabled else None
        self.now_background.set_colors(colors)
        self.albums_background.set_colors(colors)

    def cached_art_colors(self, client, item, pixbuf):
        cache = LocalCache(client)
        try:
            palette = cache.read_palette(item.thumb)
        except OSError:
            palette = None
        if palette is not None:
            return palette
        gradient, wave = gradient_colors(pixbuf), waveform_colors(pixbuf)
        if gradient:
            try:
                cache.save_palette(item.thumb, gradient, wave)
            except OSError:
                pass
        return gradient, wave

    def update_art_gradient(self, client, item, pixbuf):
        try:
            self.current_art_colors, wave = self.cached_art_colors(client, item, pixbuf)
            self.waveform.set_colors(*wave)
            self.current_art_bright = wave[0]
        except Exception:
            self.current_art_colors = None
            self.current_art_key = None
            self.current_art_bright = None
            self.waveform.set_colors('#d080dc', '#e7a641')
        self.render_gradient()
        self.apply_accent()

    def playlist_row(self, title, playlist):
        row = Gtk.ListBoxRow()
        row.playlist = playlist
        row.add(Gtk.Label(label=title, xalign=0, margin=8))
        self.playlist_list.add(row)
        if playlist is not None:
            targets = [Gtk.TargetEntry.new('application/x-plex-song-key',
                                            Gtk.TargetFlags.SAME_APP, 0)]
            row.drag_dest_set(Gtk.DestDefaults.ALL, targets, Gdk.DragAction.COPY)
            row.connect('drag-data-received', self.playlist_drop_received)
        row.show_all()
        return row

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

    def song_drag_data_get(self, _view, _context, selection, _info, _time):
        model, selected = self.song_view.get_selection().get_selected()
        if selected is None:
            return
        index = model.get_path(selected).get_indices()[0]
        if 0 <= index < len(self.songs):
            selection.set(selection.get_target(), 8, self.songs[index].key.encode('utf-8'))

    def playlist_drop_received(self, row, context, _x, _y, selection, _info, event_time):
        key = bytes(selection.get_data() or b'').decode('utf-8', errors='ignore')
        track = next((song for song in self.songs if song.key == key), None)
        playlist = row.playlist
        if track is None or playlist is None or not self.client:
            Gtk.drag_finish(context, False, False, event_time)
            return
        Gtk.drag_finish(context, True, False, event_time)
        client = self.client
        self.song_count.set_text(f'Adding “{track.title}” to {playlist.title}…')
        def added(_result):
            self.song_count.set_text(f'Added “{track.title}” to {playlist.title}')
            if self.active_playlist and self.active_playlist.key == playlist.key:
                source = (client, self.library.get_active_id(), playlist.key, None)
                if self.song_catalog_source == source and self.song_catalog is not None:
                    self.song_catalog.append(track)
                    try:
                        LocalCache(client).save_song_index(source[1], self.song_catalog,
                                                           playlist.key)
                    except OSError:
                        pass
                else:
                    self.invalidate_song_catalog()
                self.load_songs()
        self.async_work(lambda: client.add_playlist_item(playlist, track), added,
                        lambda: client is self.client,
                        lambda: self.song_count.set_text(
                            f'Could not add “{track.title}” to {playlist.title}. ' +
                            self.status.get_text()))

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
        header.add(Gtk.Label(label=column.get_title(), margin=3))
        header.connect('map', self.attach_song_header_button, column, field)
        header.show_all()
        column.set_widget(header)
        self.song_columns[field] = column

    def song_row_background(self, _column, cell, model, row, _data=None):
        path = model.get_path(row)
        selected = self.song_view.get_selection().path_is_selected(path)
        cell.set_property('cell-background-set', not selected)
        if not selected:
            cell.set_property('cell-background',
                              '#181818' if path.get_indices()[0] % 2 else '#111111')

    @staticmethod
    def song_column_value(song, field):
        if field == 'duration':
            return clock(song.duration / 1000)
        if field in ('added_at', 'last_played_at'):
            value = getattr(song, field)
            return time.strftime('%Y-%m-%d', time.localtime(value)) if value else ''
        if field == 'user_rating':
            return f'{song.user_rating / 2:g} ★' if song.user_rating else ''
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
        source = (self.active_playlist.key if self.active_playlist else
                  self.library_album_filter.key if self.library_album_filter else 'all')
        parts = (self.client.address, self.client.token, section, source)
        return hashlib.sha256('\0'.join(parts).encode('utf-8')).hexdigest()

    def library_columns_changed(self, *_):
        if self.library_layout_restoring or self.current_library_layout_key is None:
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
        layout = {'order': order, 'widths': widths,
                  'visible': [field for field, column in self.song_columns.items()
                              if column.get_visible()],
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
        widths = layout.get('widths') if isinstance(layout.get('widths'), dict) else {}
        for field, column in self.song_columns.items():
            column.set_visible(field in BASE_LIBRARY_FIELDS or field in visible)
            width = widths.get(field)
            if type(width) is not int or not 50 <= width <= 1200:
                width = {'title': 280, 'artist': 170, 'album': 190,
                         'duration': 75}.get(field, 120)
            column.set_fixed_width(width)
        order = layout.get('order') if isinstance(layout.get('order'), list) else []
        ordered = list(dict.fromkeys(field for field in order
                                     if isinstance(field, str) and field in fields))
        ordered.extend(field for _name, field in LIBRARY_COLUMNS if field not in ordered)
        previous = None
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
        for field, column in self.song_columns.items():
            selected = self.column_sort is not None and field == self.column_sort[0]
            column.set_sort_indicator(selected)
            if selected:
                column.set_sort_order(Gtk.SortType.DESCENDING if self.column_sort[1]
                                      else Gtk.SortType.ASCENDING)
        self.current_library_layout_key = key
        self.library_layout_restoring = False

    def attach_song_header_button(self, header, column, field):
        if getattr(header, '_sort_context_attached', False):
            return
        parent = header.get_parent()
        while parent is not None and not isinstance(parent, Gtk.Button):
            parent = parent.get_parent()
        if parent is not None:
            parent.connect('button-press-event', self.song_header_pressed, column, field)
            header._sort_context_attached = True

    def song_column_clicked(self, _column, field):
        descending = (not self.column_sort[1]
                      if self.column_sort and self.column_sort[0] == field else False)
        self.choose_library_sort(field, descending)

    def song_header_pressed(self, _header, event, column, field):
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        menu.attach_to_widget(self, None)
        recent = Gtk.MenuItem.new_with_label('Recently added (original order)')
        recent.connect('activate', lambda *_: self.reset_library_sort())
        menu.append(recent)
        menu.append(Gtk.SeparatorMenuItem())
        columns_item = Gtk.MenuItem.new_with_label('Show columns')
        columns_menu = Gtk.Menu()
        for name, optional_field in LIBRARY_COLUMNS[4:]:
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
        self.song_columns[field].set_visible(visible)
        self.library_columns_changed()
        if not visible and self.column_sort and self.column_sort[0] == field:
            self.reset_library_sort()

    def reset_library_sort(self):
        self.column_sort = None
        self.song_sort = 'addedAt:desc'
        for column in self.song_columns.values():
            column.set_sort_indicator(False)
        self.library_columns_changed()
        self.load_songs()

    def choose_library_sort(self, field, descending):
        self.column_sort = field, descending
        for key, column in self.song_columns.items():
            selected = key == field
            column.set_sort_indicator(selected)
            if selected:
                column.set_sort_order(Gtk.SortType.DESCENDING if descending
                                      else Gtk.SortType.ASCENDING)
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

    def start_song_catalog(self, client, section, playlist, album_filter):
        source = (client, section, playlist.key if playlist else None,
                  album_filter.key if album_filter else None)
        if self.song_catalog_source != source:
            self.invalidate_song_catalog()
            self.song_catalog_source = source
        if self.song_catalog_loading:
            return
        self.song_catalog_generation += 1
        generation = self.song_catalog_generation
        self.song_catalog_loading = True
        cache = LocalCache(client)
        playlist_key = playlist.key if playlist else None
        if not album_filter:
            self.song_catalog = cache.read_song_index(section, playlist_key)
        if self.song_catalog is None:
            self.song_count.set_text('Loading songs…')
        else:
            self.load_songs()
        valid = lambda: (generation == self.song_catalog_generation and
                         self.song_catalog_source == source and client is self.client)
        def work():
            if album_filter:
                return client.tracks(album_filter)
            catalog = build_song_catalog(client, section, playlist, valid)
            if catalog is not None and valid():
                try:
                    cache.save_song_index(section, catalog, playlist_key)
                except OSError:
                    pass
            return catalog
        def loaded(catalog):
            self.song_catalog_loading = False
            if catalog is not None:
                self.song_catalog = catalog
                self.load_songs()
        def failed():
            self.song_catalog_loading = False
            if self.song_catalog is None:
                self.song_count.set_text('Could not load songs')
        self.async_work(work, loaded, valid, failed)

    def select_playlist(self, _list, row):
        if row is None:
            return
        self.invalidate_song_catalog()
        self.library_album_filter = None
        self.library_back_button.hide()
        self.active_playlist = row.playlist
        self.songs_heading.set_text(row.playlist.title if row.playlist else 'Songs')
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
        self.invalidate_song_catalog()
        self.artist_filter = None
        self.artist_catalog = None
        self.artist_filter_bar.hide()
        self.library_album_filter = None
        self.library_back_button.hide()
        self.apply_library_layout()
        self.ensure_search_index()
        self.load_albums()
        if self.active_playlist is None:
            self.load_songs()

    def clear_wall(self):
        self.art_epoch += 1
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
            def show():
                if self.closed or not valid():
                    return False
                try:
                    loader = GdkPixbuf.PixbufLoader()
                    loader.set_size(size, size)
                    loader.write(data)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    image.art_source = pixbuf
                    if hasattr(image, 'art_display_size'):
                        self.set_art_size(image, image.art_display_size)
                    else:
                        image.set_from_pixbuf(pixbuf)
                    if on_pixbuf:
                        on_pixbuf(pixbuf)
                except GLib.Error:
                    if from_cache:
                        try:
                            cache.art_path(album.thumb, size).unlink(missing_ok=True)
                        except OSError:
                            pass
                        self.art_workers.submit(fetch, True)
                return False
            GLib.idle_add(show)
        self.art_workers.submit(fetch)

    def add_album_tile(self, album):
        tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        tile.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        tile.connect('button-press-event',
                     lambda _widget, event: self.album_context_menu_pressed(tile, event))
        front = Gtk.Button()
        front.connect('button-press-event',
                      lambda _widget, event: self.album_context_menu_pressed(tile, event))
        age = added_age_label(album.added_at)
        self.set_tooltip(front, f'{album.title}\n{album.artist}\n{age}')
        front.get_accessible().set_name(f'Flip {album.title} by {album.artist} to show tracks')
        image = Gtk.Image.new_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        self.set_art_size(image, self.album_art_size)
        front.add(image)
        metadata = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        metadata.set_size_request(self.album_art_size, -1)
        tile.pack_end(metadata, False, False, 0)
        for index, (value, name) in enumerate(((album.title, 'album-title'),
                                               (album.artist, 'album-meta'),
                                               (age, 'album-meta'))):
            label = Gtk.Label(label=value, xalign=0.5)
            label.set_name(name)
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
        heading = Gtk.Label(label=album.title, xalign=0.5)
        heading.set_name('album-back-title')
        heading.set_ellipsize(Pango.EllipsizeMode.END)
        heading.set_max_width_chars(1)
        heading_button = Gtk.Button()
        heading_button.add(heading)
        self.set_tooltip(heading_button, 'Open full album view')
        heading_button.connect('clicked', lambda *_: self.select_album(album))
        back_content.pack_start(heading_button, False, False, 0)
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
        back_content.pack_start(tracks_scroll, True, True, 0)
        cover_button = Gtk.Button(label='‹' if self.album_art_size < 100 else '‹ Cover')
        self.set_tooltip(cover_button, 'Flip back to album art')
        back_content.pack_end(cover_button, False, False, 0)
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
        tile.flip_card = flip_card
        flip_card.on_side_shown = lambda side: self.album_side_shown(tile, side)
        tile.heading_button = heading_button
        tile.cover_button = cover_button
        tile.back_gradient = background
        front.connect('clicked', lambda *_: self.flip_album_card(tile))
        cover_button.connect('clicked', lambda *_: self.flip_album_card(tile))
        self.grid.add(tile)
        epoch = self.art_epoch
        self.load_art(self.client, album, image, ALBUM_SIZE_RANGE[1],
                      lambda: epoch == self.art_epoch,
                      lambda pixbuf: background.set_colors(
                          self.cached_art_colors(self.client, album, pixbuf)[0]))
        tile.show_all()
        metadata.set_visible(self.show_album_details)
        heading_button.set_visible(self.album_art_size >= 100)

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
            for child in self.grid.get_children():
                other = child.get_child()
                if other is not tile:
                    other.flip_card.show_side('front')
        self.last_flipped_tile = tile
        if self.pending_flipped_tile is tile:
            self.pending_flipped_tile = None

    def load_card_tracks(self, card):
        if card.tracks is not None or card.tracks_loading or not self.client:
            return
        card.tracks_loading = True
        album = card.album
        client = self.client
        epoch = self.art_epoch
        def loaded(tracks):
            card.tracks_loading = False
            card.tracks = tracks
            card.track_buttons = []
            for child in card.tracks_box.get_children():
                child.destroy()
            if not tracks:
                card.tracks_box.pack_start(Gtk.Label(label='No tracks found'), False, False, 0)
            for index, track in enumerate(tracks):
                button = Gtk.Button()
                label = Gtk.Label(label=f'{index + 1}. {track.title}  ·  {clock(track.duration / 1000)}',
                                  xalign=0)
                label.set_ellipsize(Pango.EllipsizeMode.END)
                label.set_max_width_chars(1)
                button.add(label)
                self.set_tooltip(button, track.title)
                button.connect('clicked', lambda _button, selected=index: self.play_card_track(card, selected))
                card.tracks_box.pack_start(button, False, False, 0)
                card.track_buttons.append(button)
            card.tracks_box.show_all()
            self.refresh_playing_highlight()
        def failed():
            card.tracks_loading = False
            for child in card.tracks_box.get_children():
                child.destroy()
            card.tracks_box.pack_start(Gtk.Label(label='Could not load tracks'), False, False, 0)
            card.tracks_box.show_all()
        self.async_work(lambda: client.tracks(album), loaded,
                        lambda: epoch == self.art_epoch and client is self.client, failed)

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
        current = (self.queue[self.index].key if self.stream_open and
                   0 <= self.index < len(self.queue) else None)
        album_key = self.queue_album.key if self.queue_album else None
        for child in self.grid.get_children():
            tile = child.get_child()
            for track, button in zip(tile.tracks or [], tile.track_buttons):
                context = button.get_style_context()
                if current and tile.album.key == album_key and track.key == current:
                    context.add_class('playing-track')
                else:
                    context.remove_class('playing-track')

    def refresh_album_ages(self):
        if self.closed:
            return False
        for child in self.grid.get_children():
            tile = child.get_child()
            tile.age_label.set_text(added_age_label(tile.age_album.added_at))
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
        name = 'Pause' if playing else 'Play'
        icon = 'media-playback-pause-symbolic' if playing else 'media-playback-start-symbolic'
        self.play_button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
        self.set_tooltip(self.play_button, name)
        self.play_button.get_accessible().set_name(name)

    def scroll(self, child):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(child)
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
        def worker():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, exc
            def deliver():
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
            GLib.idle_add(deliver)
        threading.Thread(target=worker, daemon=True).start()

    def connect_dialog(self, *_):
        self.finish_startup_loading()
        dialog = Gtk.Dialog(title='Connect to Plex', transient_for=self, modal=True)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Connect', Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_border_width(18)
        box.pack_start(Gtk.Label(label='Server URL (HTTPS for remote servers)', xalign=0), False, False, 0)
        address = Gtk.Entry(placeholder_text='http://192.168.1.10:32400')
        current = (self.client.address, self.client.token) if self.client else self.restored_credentials
        if current:
            address.set_text(current[0])
        box.pack_start(address, False, False, 0)
        box.pack_start(Gtk.Label(label='X-Plex-Token (saved in desktop keyring)', xalign=0), False, False, 0)
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
        if response != Gtk.ResponseType.OK:
            return False
        self.connect_to_server(url, secret, remember=True)
        return False

    def connect_to_server(self, url, secret, remember=False, automatic=False):
        try:
            client = PlexClient(url, secret, self.remote_config['identifier'],
                                self.remote_config['name'])
        except ValueError as exc:
            self.status.set_text(str(exc))
            if automatic:
                self.connect_dialog()
            return False
        self.generation += 1
        generation = self.generation
        self.stop()
        self.status.set_text('Connecting…')
        def work():
            sections = client.sections()
            try:
                machine = client.xml('/').get('machineIdentifier', '')
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
            self.remote_server_machine = machine
            self.clear_remote_queue()
            if self.remote_receiver:
                self.remote_receiver.set_server(client, machine)
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
            self.credential_warning = '' if saved else 'Desktop keyring could not save this login.'
            self.sections = sections
            self.library.remove_all()
            self.clear_wall()
            self.track_store.clear()
            self.albums, self.tracks, self.queue = [], [], []
            self.songs = []
            self.playlists = []
            self.song_store.clear()
            self.song_total = 0
            self.song_count.set_text('No music library available')
            self.index = -1
            self.selected_album = self.queue_album = None
            self.now_title.set_text('Nothing playing')
            self.now_artist.set_text('')
            self.now_cover.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
            self.hero_cover.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
            self.hero_cover.art_source = None
            self.set_art_size(self.hero_cover, self.now_art_size)
            self.current_art_colors = None
            self.current_art_key = None
            self.current_art_bright = None
            self.waveform.clear()
            self.waveform.set_colors('#d080dc', '#e7a641')
            self.art_stack.set_visible_child_name('cover')
            self.render_gradient()
            self.apply_accent()
            self.hero_title.set_text('Nothing playing')
            self.hero_artist.set_text('Choose an album or song to start listening')
            self.hero_album.set_text('')
            self.server_label.set_text(client.address)
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
                if not saved_section or not self.library.set_active_id(saved_section):
                    self.library.set_active(0)
                self.load_playlists()
            else:
                self.status.set_text('Connected, but no music libraries are available to this token.')
                self.finish_startup_loading()
            if self.credential_warning:
                self.status.set_text(self.credential_warning)
            self.restore_saved_session()
            self.mpris.changed()
        self.async_work(work, connected, lambda: generation == self.generation,
                        self.connect_dialog if automatic else None)
        return False

    def load_albums(self, more=False):
        section = self.library.get_active_id()
        if not self.client or not section:
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
            self.cover.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        self.more.set_sensitive(False)
        self.more.hide()
        self.status.set_text('Loading recently added albums…')
        def loaded(result):
            self.loading_albums = False
            albums, total, catalog = result
            if catalog is not None:
                self.artist_catalog = catalog
            self.albums.extend(albums)
            for album in albums:
                self.add_album_tile(album)
            self.total = total
            has_more = bool(albums) and len(self.albums) < total
            self.more.set_sensitive(has_more)
            self.more.set_visible(has_more)
            message = (f'{len(self.albums)} of {total} albums by {artist}' if artist else
                       f'{len(self.albums)} of {total} albums • Newest first • Click a cover to open')
            self.status.set_text(f'{self.credential_warning} • {message}' if self.credential_warning else message)
            self.finish_startup_loading()
        def failed():
            self.loading_albums = False
            has_more = more and bool(self.albums) and len(self.albums) < self.total
            self.more.set_sensitive(has_more)
            self.more.set_visible(has_more)
            self.finish_startup_loading()
        indexed = (self.indexed_albums if self.search_index_enabled and
                   self.index_section == section else None)
        if artist:
            existing_catalog = self.artist_catalog
            def artist_work():
                catalog = existing_catalog
                if catalog is None:
                    source = indexed if indexed is not None else build_album_index(
                        client, section, lambda: generation == self.generation and
                        client is self.client and self.artist_filter == artist)
                    if source is None:
                        return [], 0, None
                    catalog = [album for album in source
                               if album.artist.casefold() == artist.casefold()]
                return catalog[start:start + 100], len(catalog), catalog
            work = artist_work
        elif title and indexed is not None:
            work = lambda: (*search_albums(indexed, title, start), None)
        else:
            work = lambda: (*client.albums(section, start, title), None)
        self.async_work(work, loaded,
                        lambda: generation == self.generation, failed)

    def load_playlists(self):
        if not self.client:
            return
        self.playlist_generation += 1
        generation = self.playlist_generation
        client = self.client
        def loaded(playlists):
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
        sort = self.saved_session.get('song_sort')
        if sort == 'titleSort':
            self.choose_library_sort('title', False)
        elif sort == 'artist.titleSort,titleSort':
            self.choose_library_sort('artist', False)
        album = self.saved_session.get('album_detail')
        if album:
            self.select_album(album)
        if self.saved_session.get('art_mode') == 'waveform' and self.audio_spectrum:
            self.toggle_art_visualizer()
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
        section = self.library.get_active_id()
        if not self.client or not section:
            self.song_count.set_text('Connect to a server to browse songs')
            return
        self.song_generation += 1
        client = self.client
        playlist = self.active_playlist
        album_filter = self.library_album_filter
        query = self.library_search.get_text().strip()
        self.songs = []
        self.song_store.clear()
        source = (client, section, playlist.key if playlist else None,
                  album_filter.key if album_filter else None)
        if self.song_catalog_source != source or self.song_catalog is None:
            self.start_song_catalog(client, section, playlist, album_filter)
            return
        self.song_results = filter_sort_songs(
            self.song_catalog, query, self.effective_library_sort())
        self.display_song_page(self.song_results, len(self.song_results),
                               playlist, album_filter, query)

    def display_song_page(self, songs, total, playlist, album_filter, query):
        self.songs.extend(songs)
        for song in songs:
            self.song_store.append([self.song_column_value(song, field)
                                    for _name, field in LIBRARY_COLUMNS] +
                                   ['♥' if song.user_rating >= 9.5 else ''])
        self.song_total = total
        if album_filter:
            message = f'{len(self.songs)} of {total} tracks in {album_filter.title}'
        elif query:
            message = f'{len(self.songs)} of {total} matching songs'
        else:
            message = (f'{len(self.songs)} of {total} songs' +
                       (' • Playlist order' if playlist and
                        self.effective_library_sort() is None else ''))
        self.song_count.set_text(message)
        self.mpris.changed()

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
        self.cover.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        def loaded(tracks):
            self.tracks = tracks
            for track in tracks:
                self.track_store.append([track.number, track.title, clock(track.duration / 1000)])
            self.mpris.changed()
        valid = lambda: generation == self.album_generation
        self.async_work(lambda: client.tracks(album), loaded, valid)
        self.load_art(client, album, self.cover, 160, valid)

    def activate_track(self, view, path, column):
        self.play_album(path.get_indices()[0])

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
        if source.find_property('extra-headers'):
            headers = Gst.Structure.new_empty('headers')
            headers.set_value('X-Plex-Token', self.queue_client.token)
            source.set_property('extra-headers', headers)
        if source.find_property('automatic-redirect'):
            source.set_property('automatic-redirect', False)
        if source.find_property('timeout'):
            source.set_property('timeout', 15)

    def stop(self):
        self.play_generation += 1
        self.remote_opening = False
        self.pipeline.set_state(Gst.State.NULL)
        self.playing = False
        self.stream_open = False
        self.playback_position_ms = 0
        self.pending_resume_seek_ms = 0
        self.timeline_base_position = 0.0
        self.timeline_base_time = time.monotonic()
        self.timeline_duration = 0.0
        self.seek.set_value(0)
        self.set_play_button_state(False)
        self.seek.set_sensitive(False)
        self.waveform.clear()
        self.refresh_playing_highlight()
        self.mpris.changed()

    def start_track(self, resume_paused=False, resume_position_ms=0):
        self.stop()
        if not 0 <= self.index < len(self.queue):
            return
        self.remote_opening = True
        self.playback_position_ms = max(0, resume_position_ms)
        track = self.queue[self.index]
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
        art_item = self.queue_album if self.queue_album and self.queue_album.thumb else track
        art_key = (client, art_item.thumb) if art_item.thumb else None
        same_art = art_key is not None and art_key == self.current_art_key
        self.current_art_key = art_key
        if not same_art:
            self.now_cover.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
            self.hero_cover.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
            self.hero_cover.art_source = None
            self.set_art_size(self.hero_cover, self.now_art_size)
            self.current_art_colors = None
            self.current_art_bright = None
            self.waveform.set_colors('#d080dc', '#e7a641')
            self.render_gradient()
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
            self.pipeline.set_property('uri', uri)
            self.remote_opening = False
            self.stream_open = True
            self.playing = not resume_paused
            self.pending_resume_seek_ms = self.playback_position_ms
            self.pipeline.set_state(Gst.State.PAUSED if resume_paused else Gst.State.PLAYING)
            self.set_play_button_state(not resume_paused)
            self.status.set_text(f'Queue • {self.index + 1} / {len(self.queue)}' +
                                 (' • Ready to resume' if resume_paused else ''))
            self.refresh_playing_highlight()
            self.mpris.changed()
            self.persist_session(force=True)
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
        self.playing = not self.playing
        self.pipeline.set_state(Gst.State.PLAYING if self.playing else Gst.State.PAUSED)
        if not self.playing:
            ok, position = self.pipeline.query_position(Gst.Format.TIME)
            if ok and (position > 0 or self.playback_position_ms == 0):
                self.playback_position_ms = position // Gst.MSECOND
            self.waveform.pause()
        self.timeline_base_position = self.playback_position_ms / 1000
        self.timeline_base_time = time.monotonic()
        self.set_play_button_state(self.playing)
        self.mpris.changed()
        self.persist_session(force=True)

    def play(self):
        if not self.playing:
            self.toggle()

    def pause(self):
        if self.playing:
            self.toggle()

    def previous(self, *_):
        if self.queue:
            self.index = max(0, self.index - 1)
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
        else:
            self.stop()
            self.status.set_text('Album finished')
            return
        self.start_track()

    def message(self, bus, message):
        if message.type == Gst.MessageType.ELEMENT:
            structure = message.get_structure()
            if self.stream_open and structure and structure.get_name() == 'spectrum':
                caps = self.audio_spectrum.get_static_pad('sink').get_current_caps()
                rate = caps.get_structure(0).get_int('rate')[1] if caps else 44100
                self.waveform.push_spectrum(spectrum_values(structure), rate)
        elif message.type == Gst.MessageType.EOS:
            self.advance()
        elif message.type == Gst.MessageType.ERROR:
            self.stop()
            self.status.set_text('Playback failed. Check server access and installed GStreamer codecs.')
        elif message.type == Gst.MessageType.ASYNC_DONE:
            self.apply_pending_resume_seek()
        elif message.type == Gst.MessageType.BUFFERING:
            percent = message.parse_buffering()
            if self.playing:
                self.pipeline.set_state(Gst.State.PAUSED if percent < 100 else Gst.State.PLAYING)
            self.status.set_text(f'Buffering {percent}%' if percent < 100 else 'Streaming from Plex')

    def seek_to(self, scale, scroll, value):
        self.seek_mpris(int(value * 1000000))
        return True

    def timeline_pressed(self, _widget, event):
        if event.button == 1:
            self.timeline_dragging = True
        return False

    def timeline_released(self, _widget, event):
        if event.button == 1:
            self.timeline_dragging = False
            self.timeline_base_position = self.seek.get_value()
            self.timeline_base_time = time.monotonic()
        return False

    def seek_mpris(self, position):
        if not self.seek.get_sensitive() or not self.queue:
            return
        track = self.queue[self.index]
        position = max(0, min(position, track.duration * 1000)) if track.duration else max(0, position)
        if self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                     int(position * 1000)):
            self.playback_position_ms = position // 1000
            self.timeline_base_position = position / 1000000
            self.timeline_base_time = time.monotonic()
            self.mpris.seeked(position)
            self.persist_session(force=True)

    def apply_pending_resume_seek(self):
        if not self.stream_open or not self.pending_resume_seek_ms:
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
        self.apply_pending_resume_seek()
        ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
        pos_ok, position = self.pipeline.query_position(Gst.Format.TIME)
        if ok and pos_ok and duration > 0:
            self.playback_position_ms = position // Gst.MSECOND
            self.seek.set_range(0, duration / Gst.SECOND)
            self.timeline_base_position = position / Gst.SECOND
            self.timeline_base_time = time.monotonic()
            self.timeline_duration = duration / Gst.SECOND
            if not self.seek.get_sensitive():
                self.seek.set_sensitive(True)
                self.mpris.changed()
            self.time.set_text(f'{clock(position / Gst.SECOND)} / {clock(duration / Gst.SECOND)}')
        if self.stream_open and self.queue:
            self.persist_session()
        if self.remote_receiver:
            self.remote_receiver.publish(self.remote_snapshot())
            if self.remote_receiver.last_request:
                path, code = self.remote_receiver.last_request
                self.remote_request_status.set_text(f'Last remote request: {path} → HTTP {code}')
        return True

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
        try:
            save_session(self.session_snapshot())
        except OSError:
            return
        self.last_session_save = now

    def session_snapshot(self):
        maximized = self.is_maximized()
        width, height = self.normal_size
        data = {
            'version': 1,
            'window': {'width': width, 'height': height, 'maximized': maximized},
            'panel': self.content_views.get_visible_child_name(),
            'settings_page': self.settings_stack.get_visible_child_name(),
            'art_mode': self.art_stack.get_visible_child_name(),
        }
        if self.client:
            data['server'] = self.client.address
            data['section'] = self.library.get_active_id()
            data['playlist'] = self.active_playlist.key if self.active_playlist else None
            data['song_sort'] = self.song_sort
            if self.selected_album and self.views.get_visible_child_name() == 'detail':
                data['album_detail'] = item_to_data(self.selected_album)
            if self.queue and 0 <= self.index < len(self.queue):
                position = self.playback_position_ms
                if self.stream_open and self.playing and not self.pending_resume_seek_ms:
                    ok, current = self.pipeline.query_position(Gst.Format.TIME)
                    if ok:
                        position = current // Gst.MSECOND
                data['playback'] = {
                    'queue': [item_to_data(track) for track in self.queue],
                    'index': self.index,
                    'position_ms': max(0, position),
                    'album': item_to_data(self.queue_album) if self.queue_album else None,
                    'shuffle': self.shuffle.get_active(),
                    'repeat': self.repeat.get_active(),
                }
        else:
            for name in ('server', 'section', 'playlist', 'song_sort'):
                if name in self.saved_session:
                    data[name] = self.saved_session[name]
            if self.saved_session.get('album_detail'):
                data['album_detail'] = item_to_data(self.saved_session['album_detail'])
            old = self.saved_session.get('playback')
            if old:
                data['playback'] = {
                    'queue': [item_to_data(track) for track in old['queue']],
                    'index': old['index'],
                    'position_ms': old['position_ms'],
                    'album': item_to_data(old['album']) if old['album'] else None,
                    'shuffle': old['shuffle'], 'repeat': old['repeat'],
                }
        return data

    def close(self, *_):
        self.remote_pin_generation += 1
        if self.remote_receiver:
            self.remote_receiver.stop()
            self.remote_receiver = None
        if self.remote_stop_thread:
            self.remote_stop_thread.join(timeout=5)
        if self.library_layout_save_timeout:
            GLib.source_remove(self.library_layout_save_timeout)
        self.save_library_layout_now()
        try:
            save_session(self.session_snapshot())
        except OSError:
            pass
        self.closed = True
        Gtk.Settings.get_default().set_property('gtk-enable-tooltips',
                                                self.desktop_tooltips_enabled)
        self.mpris.close()
        self.art_workers.shutdown(wait=False, cancel_futures=True)
        self.pipeline.set_state(Gst.State.NULL)
        Gtk.main_quit()


if __name__ == '__main__':
    Player(mpris_enabled=True)
    Gtk.main()
