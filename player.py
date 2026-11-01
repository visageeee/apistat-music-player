#!/usr/bin/env python3
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, Gst, GLib, GdkPixbuf, Gdk
from plex_client import PlexClient

Gst.init(None)


def clock(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}:{seconds % 60:02}'


class Player(Gtk.Window):
    def __init__(self):
        super().__init__(title='Plex Music · Prototype')
        self.set_default_size(1080, 720)
        self.client = None
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
        self.updating = False
        self.offset = 0
        self.total = 0
        self.pipeline = Gst.ElementFactory.make('playbin', None)
        if not self.pipeline:
            raise RuntimeError('Install gstreamer1.0-plugins-base and gstreamer1.0-plugins-good')
        self.pipeline.set_property('flags', 2)  # Audio only
        self.pipeline.connect('source-setup', self.source_setup)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self.message)
        self.connect('destroy', self.close)
        self.art_workers = ThreadPoolExecutor(max_workers=4)
        self.selected_album = None
        self.queue_album = None
        self.art_epoch = 0
        self.loading_albums = False
        self.set_name('plex-player')
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            #plex-player, #library-wall, #library-wall viewport,
            #album-grid, #album-grid flowboxchild { background: #000; color: #eee; }
            #plex-player label { color: #eee; }
            #album-grid flowboxchild { padding: 0; margin: 0; border: 0; }
            #album-grid button { background: #000; border: 0; padding: 0;
                border-radius: 0; box-shadow: none; }
            #album-grid button:hover { background: #252525; }
            #player-bar { background: #151515; border-top: 1px solid #303030; }
            #player-bar button, #library-toolbar button { color: #eee;
                background: #252525; border-color: #444; box-shadow: none; }
            #player-bar scale trough { background: #383838; }
            #player-bar scale highlight { background: #e7a641; }
        """)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)
        self.library_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.pack_start(self.library_panel, True, True, 0)
        toolbar = Gtk.Box(spacing=12, margin=12)
        toolbar.set_name('library-toolbar')
        toolbar.pack_start(Gtk.Label(label='Recently added'), False, False, 0)
        self.library = Gtk.ComboBoxText()
        self.library.connect('changed', lambda *_: self.load_albums())
        toolbar.pack_start(self.library, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text='Search albums; press Enter')
        self.search.connect('activate', lambda *_: self.load_albums())
        toolbar.pack_start(self.search, True, True, 0)
        toolbar.pack_end(self.button('Connection…', self.connect_dialog), False, False, 0)
        self.library_panel.pack_start(toolbar, False, False, 0)
        self.views = Gtk.Stack()
        self.library_panel.pack_start(self.views, True, True, 0)
        wall = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=12)
        self.grid = Gtk.FlowBox()
        self.grid.set_name('album-grid')
        self.grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.grid.set_homogeneous(True)
        self.grid.set_min_children_per_line(1)
        self.grid.set_max_children_per_line(20)
        self.grid.set_row_spacing(8)
        self.grid.set_column_spacing(8)
        self.grid.set_valign(Gtk.Align.START)
        wall.pack_start(self.grid, False, False, 0)
        self.more = self.button('Load more albums', lambda *_: self.load_albums(True))
        self.more.set_sensitive(False)
        wall.pack_start(self.more, False, False, 0)
        wall_scroll = self.scroll(wall)
        wall_scroll.set_name('library-wall')
        wall_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.views.add_named(wall_scroll, 'wall')
        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=16)
        detail.pack_start(self.button('‹ All albums', lambda *_: self.views.set_visible_child_name('wall')), False, False, 0)
        album_header = Gtk.Box(spacing=18)
        self.cover = Gtk.Image.new_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        self.cover.set_size_request(160, 160)
        album_header.pack_start(self.cover, False, False, 0)
        self.album_label = Gtk.Label(label='Choose an album', xalign=0)
        self.album_label.set_line_wrap(True)
        album_header.pack_start(self.album_label, True, True, 0)
        album_header.pack_end(self.button('Play album', lambda *_: self.play_album(0)), False, False, 0)
        detail.pack_start(album_header, False, False, 0)
        self.track_store = Gtk.ListStore(str, str, str)
        self.track_view = self.table(self.track_store, ['#', 'Track', 'Time'])
        self.track_view.connect('row-activated', self.activate_track)
        detail.pack_start(self.scroll(self.track_view), True, True, 0)
        self.views.add_named(detail, 'detail')
        self.views.set_visible_child_name('wall')
        self.idle_space = Gtk.Box()
        root.pack_start(self.idle_space, True, True, 0)
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=0)
        bar.set_name('player-bar')
        root.pack_end(bar, False, False, 0)
        controls = Gtk.Box(spacing=12, margin=12)
        self.now_cover = Gtk.Image.new_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        self.now_cover.set_size_request(56, 56)
        controls.pack_start(self.now_cover, False, False, 0)
        self.now = Gtk.Label(label='Nothing playing', xalign=0)
        self.now.set_ellipsize(3)
        self.now.set_hexpand(True)
        controls.pack_start(self.now, True, True, 0)
        controls.pack_start(self.button('Previous', self.previous), False, False, 0)
        self.play_button = self.button('Play', self.toggle)
        controls.pack_start(self.play_button, False, False, 0)
        controls.pack_start(self.button('Next', lambda *_: self.advance()), False, False, 0)
        volume = Gtk.VolumeButton()
        volume.set_value(0.8)
        self.pipeline.set_property('volume', 0.8)
        volume.connect('value-changed', lambda _, value: self.pipeline.set_property('volume', value))
        controls.pack_start(volume, False, False, 0)
        self.library_toggle = self.button('Hide library', self.toggle_library)
        controls.pack_end(self.library_toggle, False, False, 0)
        bar.pack_start(controls, False, False, 0)
        progress = Gtk.Box(spacing=10, margin_start=12, margin_end=12)
        self.shuffle = Gtk.CheckButton(label='Shuffle')
        self.repeat = Gtk.CheckButton(label='Repeat')
        progress.pack_start(self.shuffle, False, False, 0)
        progress.pack_start(self.repeat, False, False, 0)
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.seek.set_draw_value(False)
        self.seek.connect('change-value', self.seek_to)
        self.seek.set_sensitive(False)
        progress.pack_start(self.seek, True, True, 0)
        self.time = Gtk.Label(label='0:00 / 0:00')
        progress.pack_end(self.time, False, False, 0)
        bar.pack_start(progress, False, False, 0)
        self.status = Gtk.Label(label='Connect to your Plex server', xalign=0,
                                margin_start=12, margin_end=12, margin_bottom=8)
        self.status.set_ellipsize(3)
        bar.pack_start(self.status, False, False, 0)
        self.show_all()
        self.idle_space.hide()
        GLib.timeout_add(500, self.tick)
        GLib.idle_add(self.connect_dialog)

    def toggle_library(self, *_):
        visible = not self.library_panel.get_visible()
        self.library_panel.set_visible(visible)
        self.idle_space.set_visible(not visible)
        self.library_toggle.set_label('Hide library' if visible else 'Show library')

    def clear_wall(self):
        self.art_epoch += 1
        for child in self.grid.get_children():
            child.destroy()
        self.views.set_visible_child_name('wall')

    def load_art(self, client, album, image, size, valid):
        if not album.thumb:
            return
        def fetch():
            if self.closed or not valid():
                return
            try:
                data = client.get('/photo/:/transcode', width=size, height=size,
                                  minSize=1, upscale=1, url=album.thumb)
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
                    image.set_from_pixbuf(loader.get_pixbuf())
                except GLib.Error:
                    pass
                return False
            GLib.idle_add(show)
        self.art_workers.submit(fetch)

    def add_album_tile(self, album):
        tile = self.button('', lambda *_: self.select_album(album))
        tile.set_tooltip_text(f'{album.title}\n{album.artist}\n{album.year}')
        tile.get_accessible().set_name(f'{album.title} by {album.artist}')
        image = Gtk.Image.new_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        image.set_size_request(160, 160)
        tile.set_image(image)
        tile.set_always_show_image(True)
        self.grid.add(tile)
        epoch = self.art_epoch
        self.load_art(self.client, album, image, 160, lambda: epoch == self.art_epoch)
        tile.show_all()

    def button(self, text, callback):
        button = Gtk.Button(label=text)
        button.connect('clicked', callback)
        return button

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
                    if on_error:
                        on_error()
                    if isinstance(error, HTTPError):
                        message = f'Plex returned HTTP {error.code}. Check the address, token and library access.'
                    elif isinstance(error, (URLError, TimeoutError)):
                        message = 'Cannot reach Plex. Check the address, network and server certificate.'
                    else:
                        message = 'Request failed. Check server access and media availability.'
                    self.status.set_text(message)  # Never display URLs or tokens in errors.
                else:
                    done(result)
                return False
            GLib.idle_add(deliver)
        threading.Thread(target=worker, daemon=True).start()

    def connect_dialog(self, *_):
        dialog = Gtk.Dialog(title='Connect to Plex', transient_for=self, modal=True)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Connect', Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_border_width(18)
        box.pack_start(Gtk.Label(label='Server URL (HTTPS for remote servers)', xalign=0), False, False, 0)
        address = Gtk.Entry(placeholder_text='http://192.168.1.10:32400')
        if self.client:
            address.set_text(self.client.address)
        box.pack_start(address, False, False, 0)
        box.pack_start(Gtk.Label(label='X-Plex-Token (not saved)', xalign=0), False, False, 0)
        token = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
        box.pack_start(token, False, False, 0)
        help_link = Gtk.LinkButton.new_with_label('https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/', 'How to find a temporary Plex token')
        box.pack_start(help_link, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        url, secret = address.get_text(), token.get_text()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return False
        try:
            client = PlexClient(url, secret)
        except ValueError as exc:
            self.status.set_text(str(exc))
            return False
        self.generation += 1
        generation = self.generation
        self.stop()
        self.status.set_text('Connecting…')
        def connected(sections):
            self.client = client
            self.sections = sections
            self.library.remove_all()
            self.clear_wall()
            self.track_store.clear()
            self.albums, self.tracks, self.queue = [], [], []
            self.selected_album = self.queue_album = None
            self.now.set_text('Nothing playing')
            self.now_cover.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
            self.album_generation += 1
            self.library.set_sensitive(True)
            for key, name in sections:
                self.library.append(key, name)
            if sections:
                self.library.set_active(0)
            else:
                self.status.set_text('Connected, but no music libraries are available to this token.')
        self.async_work(client.sections, connected, lambda: generation == self.generation)
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
        if not more:
            self.album_generation += 1
            self.albums, self.tracks = [], []
            self.clear_wall()
            self.track_store.clear()
            self.album_label.set_text('Choose an album')
            self.cover.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        self.more.set_sensitive(False)
        self.status.set_text('Loading recently added albums…')
        def loaded(result):
            self.loading_albums = False
            albums, total = result
            self.albums.extend(albums)
            for album in albums:
                self.add_album_tile(album)
            self.total = total
            self.more.set_sensitive(bool(albums) and len(self.albums) < total)
            self.status.set_text(f'{len(self.albums)} of {total} albums • Newest first • Click a cover to open')
        def failed():
            self.loading_albums = False
            self.more.set_sensitive(True)
        self.async_work(lambda: client.albums(section, start, title), loaded,
                        lambda: generation == self.generation, failed)

    def select_album(self, album):
        self.selected_album = album
        self.views.set_visible_child_name('detail')
        self.album_generation += 1
        generation = self.album_generation
        client = self.client
        self.tracks = []
        self.track_store.clear()
        self.album_label.set_text(f'{album.title}\n{album.artist}\n{album.year}')
        self.cover.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        def loaded(tracks):
            self.tracks = tracks
            for track in tracks:
                self.track_store.append([track.number, track.title, clock(track.duration / 1000)])
        valid = lambda: generation == self.album_generation
        self.async_work(lambda: client.tracks(album), loaded, valid)
        self.load_art(client, album, self.cover, 160, valid)

    def activate_track(self, view, path, column):
        self.play_album(path.get_indices()[0])

    def play_album(self, index):
        if not self.tracks:
            return
        self.queue_album = self.selected_album
        self.now_cover.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        album = self.queue_album
        if album:
            self.load_art(self.client, album, self.now_cover, 56,
                          lambda: self.queue_album is album)
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
        self.pipeline.set_state(Gst.State.NULL)
        self.playing = False
        self.play_button.set_label('Play')
        self.seek.set_sensitive(False)

    def start_track(self):
        self.stop()
        if not 0 <= self.index < len(self.queue):
            return
        track = self.queue[self.index]
        client = self.queue_client
        generation = self.play_generation
        self.now.set_text(f'{track.title}\n{track.artist}' + (f' · {self.queue_album.title}' if self.queue_album else ''))
        self.status.set_text('Opening stream…')
        def ready(uri):
            self.pipeline.set_property('uri', uri)
            self.playing = True
            self.pipeline.set_state(Gst.State.PLAYING)
            self.play_button.set_label('Pause')
            self.status.set_text(f'Album queue • {self.index + 1} / {len(self.queue)}')
        self.async_work(lambda: client.stream(track), ready,
                        lambda: generation == self.play_generation)

    def toggle(self, *_):
        if self.pipeline.get_property('uri') is None or self.pipeline.get_state(0)[1] == Gst.State.NULL:
            if self.queue:
                self.start_track()
            else:
                self.play_album(0)
            return
        self.playing = not self.playing
        self.pipeline.set_state(Gst.State.PLAYING if self.playing else Gst.State.PAUSED)
        self.play_button.set_label('Pause' if self.playing else 'Play')

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
        if message.type == Gst.MessageType.EOS:
            self.advance()
        elif message.type == Gst.MessageType.ERROR:
            self.stop()
            self.status.set_text('Playback failed. Check server access and installed GStreamer codecs.')
        elif message.type == Gst.MessageType.BUFFERING:
            percent = message.parse_buffering()
            if self.playing:
                self.pipeline.set_state(Gst.State.PAUSED if percent < 100 else Gst.State.PLAYING)
            self.status.set_text(f'Buffering {percent}%' if percent < 100 else 'Streaming from Plex')

    def seek_to(self, scale, scroll, value):
        self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                  int(value * Gst.SECOND))
        return True

    def tick(self):
        if self.closed:
            return False
        ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
        pos_ok, position = self.pipeline.query_position(Gst.Format.TIME)
        if ok and pos_ok and duration > 0:
            self.seek.set_range(0, duration / Gst.SECOND)
            self.seek.set_value(position / Gst.SECOND)
            self.seek.set_sensitive(True)
            self.time.set_text(f'{clock(position / Gst.SECOND)} / {clock(duration / Gst.SECOND)}')
        return True

    def close(self, *_):
        self.closed = True
        self.art_workers.shutdown(wait=False, cancel_futures=True)
        self.pipeline.set_state(Gst.State.NULL)
        Gtk.main_quit()


if __name__ == '__main__':
    Player()
    Gtk.main()
