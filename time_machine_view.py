"""Listening-history browser for the current Last.fm account and library."""
from datetime import date
import math
import random
import sys
from pathlib import Path

import cairo

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, GObject, Gtk

import lastfm
from frosted_bar import FrostedBar
from drag_payload import encode_track_keys
from library_album_view import AlbumGroupOverlay, album_group_row_height, group_songs_by_album
from library_catalog import build_song_catalog
from local_cache import LocalCache
from time_machine import albums_for_history, partition_history, timestamps


_ASSET_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets' / 'time-machine'


def _texture(name):
    try:
        return cairo.ImageSurface.create_from_png(str(_ASSET_DIR / name))
    except (OSError, cairo.Error):
        return None


_LCD_TEXTURE = _texture('lcd.png')
_MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')
_FUTURE_ERRORS = ('Future not found.', 'Paradox continuum corruption detected.',
                  'Temporal coordinates unavailable — the future has not happened yet.',
                  'Flux capacitor cannot locate memories from the future.',
                  'Causality error: destination lies beyond the present.')


def _paint_texture(cr, surface, width, height, alpha=1):
    if surface is None:
        return
    cr.save()
    cr.scale(width / surface.get_width(), height / surface.get_height())
    cr.set_source_surface(surface, 0, 0)
    cr.paint_with_alpha(alpha)
    cr.restore()


class LcdDigits(Gtk.DrawingArea):
    """Textured luminous digits over an accessible, editable spin button."""
    def __init__(self, spin, digits, style, month=False):
        super().__init__()
        self.spin, self.digits, self.style, self.month = spin, digits, style, month
        self.set_size_request(digits * 30 + 10, 58)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.CENTER)
        self.connect('draw', self.draw_digits)
        spin.connect('changed', lambda *_: self.queue_draw())
        spin.connect('notify::selection-bound', lambda *_: self.queue_draw())
        spin.connect('notify::cursor-position', lambda *_: self.queue_draw())

    def draw_digits(self, _widget, cr):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        raw = self.spin.get_text()
        text = (_MONTHS[self.spin.get_value_as_int() - 1] if self.month else
                raw[-self.digits:] if raw.isdigit() else '')
        rgb = (1.0, .19, .055) if self.style == 'dial-start' else (.16, 1.0, .25)
        patterns = ('ab cdef'.replace(' ', ''), 'bc', 'abged', 'abgcd',
                    'fgbc', 'afgcd', 'afgecd', 'abc', 'abcdefg', 'abfgcd')
        letters = {'J': 'bcde', 'A': 'abcefg', 'N': 'bcef', 'F': 'aefg',
                   'E': 'adefg', 'B': 'cdefg', 'M': 'bcef', 'R': 'eg',
                   'P': 'abefg', 'Y': 'bcdfg', 'U': 'bcdef', 'L': 'def',
                   'G': 'acdefg', 'S': 'acdfg', 'O': 'abcdef', 'C': 'adef',
                   'T': 'defg', 'V': '', 'D': 'bcdeg'}
        if not self.is_sensitive():
            rgb = (.22, .21, .19)
        # Seven clipped, chamfered phosphor segments per digit, including the
        # faint unlit segments visible behind a real LED display.
        segments = {
            'a': ((5, 0), (22, 0), (25, 3), (22, 6), (5, 6), (2, 3)),
            'g': ((5, 23), (22, 23), (25, 26), (22, 29), (5, 29), (2, 26)),
            'd': ((5, 46), (22, 46), (25, 49), (22, 52), (5, 52), (2, 49)),
            'f': ((1, 4), (4, 7), (4, 22), (1, 25), (-2, 22), (-2, 7)),
            'b': ((26, 4), (29, 7), (29, 22), (26, 25), (23, 22), (23, 7)),
            'e': ((1, 27), (4, 30), (4, 45), (1, 48), (-2, 45), (-2, 30)),
            'c': ((26, 27), (29, 30), (29, 45), (26, 48), (23, 45), (23, 30)),
        }
        def path(points):
            cr.move_to(*points[0])
            for point in points[1:]:
                cr.line_to(*point)
            cr.close_path()

        cr.save()
        cr.translate((width - len(text) * 29.6) / 2 + 2.4, (height - 41.6) / 2)
        cr.scale(.8, .8)
        selection = self.spin.get_selection_bounds() if self.spin.is_focus() else ()
        if selection:
            start, end = selection
            cr.set_source_rgba(*rgb, .17)
            cr.rectangle(start * 37 - 3, -4, (end - start) * 37, 60)
            cr.fill()
        for number in text:
            cr.save()
            cr.transform(cairo.Matrix(1, 0, -.10, 1, 4, 0))
            active = patterns[int(number)] if number.isdigit() else letters.get(number, '')
            for segment, points in segments.items():
                path(points)
                cr.set_source_rgba(*rgb, .11)
                cr.fill()
                if segment not in active:
                    continue
                for thickness, alpha in ((7, .04), (3, .12)):
                    path(points)
                    cr.set_line_width(thickness)
                    cr.set_source_rgba(*rgb, alpha)
                    cr.stroke()
                path(points)
                cr.save()
                cr.clip()
                cr.set_source_rgb(*rgb)
                cr.paint()
                cr.translate(-4, -(height - 52) / 2)
                _paint_texture(cr, _LCD_TEXTURE, width, height, .25)
                cr.restore()
            diagonals = {
                'M': (((4, 6), (8, 7), (14, 16), (13, 20), (10, 18), (4, 10)),
                      ((23, 6), (23, 10), (16, 18), (13, 20), (13, 16), (20, 7))),
                'N': (((4, 7), (8, 8), (14, 21), (13, 24), (10, 22), (4, 11)),
                      ((15, 28), (18, 30), (24, 42), (24, 46), (20, 45), (14, 31))),
                'V': (((1, 7), (5, 8), (12, 29), (11, 33), (8, 30), (1, 11)),
                      ((25, 7), (25, 11), (17, 30), (14, 33), (14, 29), (21, 8)),
                      ((9, 32), (12, 35), (14, 42), (16, 35), (19, 32), (15, 47), (12, 47))),
            }
            for points in diagonals.get(number, ()):
                for thickness, alpha in ((7, .04), (3, .12)):
                    path(points)
                    cr.set_line_width(thickness)
                    cr.set_source_rgba(*rgb, alpha)
                    cr.stroke()
                path(points)
                cr.save()
                cr.clip()
                cr.set_source_rgb(*rgb)
                cr.paint()
                cr.translate(-4, -(height - 52) / 2)
                _paint_texture(cr, _LCD_TEXTURE, width, height, .25)
                cr.restore()
            cr.restore()
            cr.translate(37, 0)
        cr.restore()
        return False


class DateField(Gtk.Entry):
    """A keyboard-editable date field whose display is drawn separately."""
    __gsignals__ = {'value-changed': (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, minimum, maximum, value, digits):
        super().__init__()
        self.minimum, self.maximum, self.digits = minimum, maximum, digits
        self.value_number = value
        self._wheel_time = 0
        self.set_name('time-dial-value')
        self.set_width_chars(digits)
        self.set_max_length(digits)
        self.set_size_request(digits * 30 + 10, 58)
        self.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self.set_text(f'{value:0{digits}d}')
        self.connect('changed', self.text_changed)
        self.connect('focus-out-event', self.finish_edit)
        self.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)

    def text_changed(self, _entry):
        text = self.get_text()
        if text.isdigit():
            value = int(text)
            if self.minimum <= value <= self.maximum and value != self.value_number:
                self.value_number = value
                self.emit('value-changed')

    def finish_edit(self, *_args):
        self.update()
        return False

    def update(self):
        text = self.get_text()
        self.set_value(int(text) if text.isdigit() else self.value_number)

    def set_value(self, value):
        value = max(self.minimum, min(self.maximum, int(value)))
        previous = self.value_number
        self.value_number = value
        self.set_text(f'{value:0{self.digits}d}')
        if value != previous:
            self.emit('value-changed')

    def get_value_as_int(self):
        return self.value_number

    def scroll_delta(self, dy):
        event_time = Gtk.get_current_event_time()
        if event_time and event_time == self._wheel_time:
            return True
        self._wheel_time = event_time
        if dy:
            self.set_value(self.value_number + (1 if dy < 0 else -1))
        return True

    def scroll_value(self, _widget, event):
        if getattr(event, 'time', 0) and event.time == self._wheel_time:
            return True
        if event.direction == Gdk.ScrollDirection.UP:
            step = 1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            step = -1
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            _valid, _dx, dy = event.get_scroll_deltas()
            step = 1 if dy < 0 else -1 if dy > 0 else 0
        else:
            return False
        if step:
            self.set_value(self.value_number + step)
        return True


class DateDial(Gtk.Box):
    """An accessible row of month, day and year controls."""
    def __init__(self, title, value, style, changed):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.set_name('time-dial')
        self.get_style_context().add_class(style)
        heading = Gtk.Label(label=title, xalign=0)
        heading.set_name('time-dial-title')
        self.pack_start(heading, False, False, 0)
        row = Gtk.Box(spacing=6)
        self.fields = {}
        self.scroll_controllers = []
        for name, maximum, current, width in (('MONTH', 12, value.month, 2),
                                               ('DAY', 31, value.day, 2),
                                               ('YEAR', 9998, value.year, 4)):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            label = Gtk.Label(label=name)
            label.set_name('time-dial-label')
            column.pack_start(label, False, False, 0)
            spin = DateField(1970 if name == 'YEAR' else 1, maximum, current, width)
            display_width = 3 if name == 'MONTH' else width
            spin.set_size_request(display_width * 30 + 10, 58)
            spin.get_accessible().set_name(f'{title.title()} {name.lower()}')
            spin.connect('value-changed', changed)
            overlay = Gtk.Overlay()
            overlay.add(spin)
            digits = LcdDigits(spin, display_width, style, month=name == 'MONTH')
            overlay.add_overlay(digits)
            overlay.set_overlay_pass_through(digits, True)
            field_row = Gtk.Box(spacing=2)
            # An above-child event window receives wheel events reliably even
            # when the drawing overlay or entry owns the pointer window.
            hit = Gtk.EventBox()
            hit.set_visible_window(False)
            hit.set_above_child(True)
            hit.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK |
                           Gdk.EventMask.BUTTON_PRESS_MASK)
            hit.connect('scroll-event', spin.scroll_value)
            hit.connect('button-press-event', lambda _box, _event, field=spin: field.grab_focus() or True)
            hit.add(overlay)
            field_row.pack_start(hit, False, False, 0)
            arrows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            for symbol, step in (('▲', 1), ('▼', -1)):
                button = Gtk.Button(label=symbol)
                button.set_name('time-dial-step')
                button.set_can_focus(False)
                button.get_accessible().set_name(f'{"Increase" if step > 0 else "Decrease"} {name.lower()}')
                button.connect('clicked', lambda _button, field=spin, delta=step:
                               field.set_value(field.get_value_as_int() + delta))
                arrows.pack_start(button, True, True, 0)
            field_row.pack_start(arrows, False, False, 0)
            # Capture scroll before GTK's entry/flow-box handlers consume it.
            controller = Gtk.EventControllerScroll.new(field_row, Gtk.EventControllerScrollFlags.VERTICAL)
            controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            controller.connect('scroll', lambda _controller, _dx, dy, field=spin:
                               field.scroll_delta(dy))
            self.scroll_controllers.append(controller)
            column.pack_start(field_row, False, False, 0)
            spin.hit_region = column
            row.pack_start(column, False, False, 0)
            self.fields[name] = spin
        self.pack_start(row, False, False, 0)

    def value(self):
        return date(self.fields['YEAR'].get_value_as_int(),
                    self.fields['MONTH'].get_value_as_int(),
                    self.fields['DAY'].get_value_as_int())


class TimeMachineView:
    def __init__(self, player):
        self.player = player
        self.generation = 0
        self.render_generation = 0
        self.album_generation = 0
        self.tracks = []
        self.display_tracks = []
        self.lost_listens = []
        self.albums = []
        self.album_offset = 0
        self.source = None
        self.account = None
        self.album_filter = None
        self._changing_view = False
        self.widget = Gtk.Overlay()
        self.widget.set_name('time-machine-panel')
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.widget.add(self.body)
        self.header_surface = Gtk.EventBox()
        self.header_surface.set_visible_window(True)
        self.header_surface.set_app_paintable(True)
        self.header_surface.set_valign(Gtk.Align.START)
        self.header_surface.set_hexpand(True)
        self.header_surface.set_name('time-machine-glass')
        self.header_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.header_surface.add(self.header_content)
        self.widget.add_overlay(self.header_surface)
        self.header_height = 0
        self.header_surface.connect('size-allocate', self.header_allocated)
        self.header_surface.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.header_surface.connect('scroll-event', self.header_scroll)
        self.header_scroll_controller = Gtk.EventControllerScroll.new(
            self.header_surface, Gtk.EventControllerScrollFlags.VERTICAL)
        self.header_scroll_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.header_scroll_controller.connect('scroll', self.header_scroll_capture)
        header = Gtk.Box(spacing=12, margin_start=20, margin_end=20, margin_top=18)
        title = Gtk.Label(label='Time machine', xalign=0)
        title.set_name('now-title')
        title.set_hexpand(True)
        header.pack_start(title, True, True, 0)
        self.header_content.pack_start(header, False, False, 0)
        self.checked_range = None
        self.checked_dates = None
        self.result_dates = None
        today = date.today()
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                           margin_start=20, margin_end=20)
        controls.set_halign(Gtk.Align.FILL)
        controls.set_hexpand(True)
        self.status = Gtk.Label(label='Set a date range and press engage to go back in time', xalign=.5)
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(75)
        self.status.connect('activate-link', self.show_lost_listens)
        saved_dates = getattr(player, 'saved_session', {}).get('time_machine_dates', {})
        start_date = saved_dates.get('from', date(today.year, 1, 1))
        end_date = saved_dates.get('to', today)
        self.start_dial = DateDial('FROM', start_date, 'dial-start', self.date_changed)
        self.end_dial = DateDial('TO', end_date, 'dial-end', self.date_changed)
        self.start_dial.set_halign(Gtk.Align.END)
        self.end_dial.set_halign(Gtk.Align.START)
        self.dial_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.dial_panel.set_name('time-dial-panel')
        self.dials = Gtk.FlowBox()
        self.dials.set_selection_mode(Gtk.SelectionMode.NONE)
        self.dials.set_min_children_per_line(1)
        self.dials.set_max_children_per_line(2)
        self.dials.set_homogeneous(False)
        self.dials.set_row_spacing(8)
        self.dials.set_column_spacing(8)
        self.dials.set_halign(Gtk.Align.FILL)
        self.dials.connect('size-allocate', self.align_dials)
        self.dials.add(self.start_dial)
        self.dials.add(self.end_dial)
        self.dial_panel.pack_start(self.dials, False, False, 0)
        self.dial_panel.pack_start(self.status, False, False, 0)
        controls.pack_start(self.dial_panel, False, False, 0)
        buttons = Gtk.Box(spacing=10)
        buttons.set_halign(Gtk.Align.CENTER)
        self.pulse_tick_id = 0
        self.pulse_phase = 0.0
        self.go = Gtk.Button(label='ENGAGE')
        self.go.get_accessible().set_name('Engage')
        self.go.set_name('time-machine-engage')
        self.go.connect('clicked', self.engage_pressed)
        self.go.connect_after('draw', self.draw_engage_pulse)
        self.go.connect('notify::sensitive', lambda *_: self.update_engage_pulse())
        self.go.connect('notify::label', lambda *_: self.update_engage_pulse())
        for dial in (self.start_dial, self.end_dial):
            for field in dial.fields.values():
                field.connect('changed', lambda *_: self.update_engage_pulse())
        buttons.pack_start(self.go, False, False, 0)
        self.dial_panel.pack_start(buttons, False, False, 0)
        self.header_content.pack_start(controls, False, False, 0)
        self.settings_link = Gtk.LinkButton.new_with_label('apistat:settings', 'Open Last.fm settings')
        self.settings_link.set_halign(Gtk.Align.START)
        self.settings_link.set_margin_start(20)
        self.settings_link.set_no_show_all(True)
        self.settings_link.connect('activate-link', self.open_settings)
        self.header_content.pack_start(self.settings_link, False, False, 0)
        self.search_effect = Gtk.Label(xalign=.5)
        self.search_effect.set_name('time-machine-search-effect')
        self.search_effect.set_no_show_all(True)
        self.header_content.pack_start(self.search_effect, False, False, 0)
        self.search_timer = None
        self.search_step = 0
        self.widget.connect('destroy', lambda *_: self.stop_search_effect())
        self.action_banner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.action_banner.set_name('time-action-banner')
        actions = Gtk.Box(spacing=8, margin_start=20, margin_end=20)
        self.back = Gtk.Button(label='◀ All albums')
        self.back.set_name('time-action-button')
        self.back.set_no_show_all(True)
        self.back.connect('clicked', self.show_all_albums)
        actions.pack_start(self.back, False, False, 0)
        self.album_button = Gtk.ToggleButton(label='Albums')
        self.album_button.set_name('time-action-button')
        self.track_button = Gtk.ToggleButton(label='Tracks')
        self.track_button.set_name('time-action-button')
        self.album_button.set_active(True)
        self.album_button.connect('clicked', self.set_view, 'albums')
        self.track_button.connect('clicked', self.set_view, 'tracks')
        actions.pack_start(self.album_button, False, False, 0)
        actions.pack_start(self.track_button, False, False, 0)
        self.play = Gtk.Button(label='Play all')
        self.play.set_name('time-action-button')
        self.play.set_sensitive(False)
        self.play.set_no_show_all(True)
        self.play.connect('clicked', lambda *_: self.play_track(0))
        actions.pack_end(self.play, False, False, 0)
        self.save_playlist = Gtk.Button(label='Save as playlist')
        self.save_playlist.set_name('time-action-button')
        self.save_playlist.set_sensitive(False)
        self.save_playlist.set_no_show_all(True)
        self.save_playlist.connect('clicked', self.save_playlist_dialog)
        actions.pack_end(self.save_playlist, False, False, 0)
        self.queue_random = Gtk.Button(label='Add 50 songs to play queue')
        self.queue_random.set_name('time-action-button')
        self.queue_random.set_sensitive(False)
        self.queue_random.set_no_show_all(True)
        self.queue_random.connect('clicked', self.enqueue_random)
        actions.pack_end(self.queue_random, False, False, 0)
        self.action_banner.pack_start(actions, False, False, 0)
        self.track_sort_bar = Gtk.Box(spacing=0, margin_start=14, margin_end=14, margin_bottom=5)
        self.track_sort_bar.set_name('time-track-sort-bar')
        self.resize_state = None
        self.sort_gutter = Gtk.Box()
        gutter_space = Gtk.Box()
        self.sort_gutter.pack_start(gutter_space, True, True, 0)
        self.sort_gutter.pack_end(self.make_column_grip('gutter'), False, False, 0)
        self.sort_gutter.set_size_request(AlbumGroupOverlay.GUTTER, -1)
        self.track_sort_bar.pack_start(self.sort_gutter, False, False, 0)
        self.sort_buttons = {}
        self.sort_containers = {}
        for label, field in (('Name', 'title'), ('Artist', 'artist'), ('Year', 'year'), ('Time', 'duration')):
            button = Gtk.Button(label=label)
            button.set_name('time-track-sort-button')
            button.set_hexpand(field == 'title')
            button.connect('clicked', self.sort_tracks, field)
            self.sort_buttons[field] = (button, label)
            cell = Gtk.Box()
            cell.pack_start(button, True, True, 0)
            cell.pack_end(self.make_column_grip(field), False, False, 0)
            self.sort_containers[field] = cell
            self.track_sort_bar.pack_start(cell, field == 'title', field == 'title', 0)
        # Show the children before excluding their parent from show_all.
        self.track_sort_bar.show_all()
        self.track_sort_bar.hide()
        self.track_sort_bar.set_no_show_all(True)
        self.action_banner.pack_start(self.track_sort_bar, False, False, 0)
        self.header_content.pack_start(self.action_banner, False, False, 0)
        self.views = Gtk.Stack()
        self.views.set_hhomogeneous(False)
        self.body.pack_start(self.views, True, True, 0)
        self.grid = Gtk.FlowBox()
        self.grid.set_name('album-grid')
        self.grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.grid.set_min_children_per_line(1)
        self.grid.set_max_children_per_line(16)
        self.grid.set_halign(Gtk.Align.CENTER)
        self.grid.set_valign(Gtk.Align.START)
        self.grid.set_row_spacing(player.album_spacing)
        self.grid.set_column_spacing(player.album_spacing)
        wall = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=player.album_margin)
        self.wall = wall
        wall.pack_start(self.grid, False, False, 0)
        self.album_scroll = player.scroll(wall)
        self.album_scroll.set_name('library-wall')
        self.album_scroll.connect('size-allocate', self.resize_grid)
        self.album_scroll.connect('scroll-event', self.zoom)
        self.album_scroll.get_vadjustment().connect('value-changed', self.scroll_changed)
        self.album_stack = Gtk.Stack()
        self.album_stack.set_hhomogeneous(False)
        self.album_stack.add_named(self.album_scroll, 'gtk')
        self.gpu_wall = None
        self.gpu_unavailable = False
        self.views.add_named(self.album_stack, 'albums')
        self.widget.connect('destroy', self.shutdown_gpu)
        self.store = Gtk.ListStore(str, str, str, str)
        self.list = player.table(self.store, ['Name', 'Artist', 'Year', 'Time'])
        self.list.set_name('song-view')
        self.selection_provider = Gtk.CssProvider()
        self.list.get_style_context().add_provider(self.selection_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.refresh_selection_style()
        self.list.set_headers_visible(False)
        self.list.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.list.get_selection().set_select_function(
            lambda _selection, _model, path, _selected, _data: path.get_indices()[0] != 0, None)
        self.track_columns = dict(zip(('title', 'artist', 'year', 'duration'), self.list.get_columns()))
        for field, column in self.track_columns.items():
            column.set_clickable(True)
            if field != 'title':
                column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
                column.set_fixed_width({'artist': 120, 'year': 70, 'duration': 80}[field])
            column.connect('clicked', self.sort_tracks, field)
            column.connect('notify::width', self.update_sort_column, field)
            for cell in column.get_cells():
                cell.set_property('yalign', 0.0)
        gutter_cell = Gtk.CellRendererText()
        self.gutter = Gtk.TreeViewColumn('', gutter_cell)
        self.gutter.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        self.gutter.set_fixed_width(AlbumGroupOverlay.GUTTER)
        self.gutter.set_min_width(AlbumGroupOverlay.MIN_GUTTER)
        self.gutter.set_max_width(AlbumGroupOverlay.MAX_GUTTER)
        self.gutter.set_resizable(True)
        self.gutter.set_cell_data_func(gutter_cell, self.group_row_size)
        self.list.append_column(self.gutter)
        self.list.move_column_after(self.gutter, None)
        self.list.connect('row-activated', lambda _view, path, _column: self.play_track(path.get_indices()[0] - 1))
        self.list.connect('button-press-event', self.track_pressed)
        targets = [Gtk.TargetEntry.new('application/x-plex-song-key', Gtk.TargetFlags.SAME_APP, 0)]
        self.list.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, targets, Gdk.DragAction.COPY)
        self.list.connect('drag-begin', self.track_drag_begin)
        self.list.connect('drag-end', self.track_drag_end)
        self.list.connect('drag-data-get', self.track_drag_data)
        self.track_scroll = player.scroll(self.list)
        self.track_scroll.set_name('song-scroll')
        tracks_overlay = Gtk.Overlay()
        tracks_overlay.set_margin_start(14)
        tracks_overlay.set_margin_end(14)
        tracks_overlay.add(self.track_scroll)
        self.group_overlay = AlbumGroupOverlay(player, self.list, self.track_scroll, self.gutter, model_offset=1)
        tracks_overlay.add_overlay(self.group_overlay)
        tracks_overlay.set_overlay_pass_through(self.group_overlay, True)
        self.gutter.connect('notify::width', self.group_overlay.redraw)
        self.gutter.connect('notify::width', self.update_sort_gutter)
        self.views.add_named(tracks_overlay, 'tracks')
        self.track_sort = None
        self.track_sort_reverse = False
        self.header_frost = None
        background = getattr(player, 'shared_background', None)
        if background is not None:
            self.header_frost = FrostedBar(self.header_surface, self.views, background,
                                           lambda: player.theme, edge='top',
                                           capture_content=lambda: not (self.gpu_wall and self.gpu_wall.area.get_mapped()),
                                           gpu_surface=lambda: self.gpu_wall.glass_surfaces.get(id(self.header_surface)) if self.gpu_wall else None,
                                           retain_missing_gpu=lambda: bool(self.gpu_wall and not self.gpu_wall.glass_failed),
                                           cache_frames=True)
            self.header_frost.set_enabled(True)
            self.widget.connect('destroy', lambda *_: self.header_frost.stop())
        self.views.set_visible_child_name('albums')

    def start_search_effect(self):
        self.stop_search_effect()
        self.search_step = 0
        self.search_effect.show()
        self.advance_search_effect()
        self.search_timer = GLib.timeout_add(1200, self.advance_search_effect)

    def advance_search_effect(self):
        messages = ('SCANNING TEMPORAL FREQUENCIES', 'MEMORY STRANDS FOUND',
                    'TEMPORAL VIBE LOCALIZED', 'ALIGNING MUSICAL TIMELINES')
        self.search_effect.set_text('✦  ' + messages[self.search_step % len(messages)] + '  ✦')
        self.search_step += 1
        return True

    def stop_search_effect(self):
        if self.search_timer is not None:
            GLib.source_remove(self.search_timer)
            self.search_timer = None
        self.search_effect.hide()

    def open_settings(self, *_args):
        self.player.show_view('settings')
        self.player.settings_tabs.set_current_page(0)
        return True

    def on_show(self):
        account = (self.player.lastfm_session or {}).get('username')
        if self.source is not None and (self.source != (self.player.client, self.player.library.get_active_id())
                                        or self.account != account):
            self.source = None
            self.account = None
            self.tracks = []
            self.lost_listens = []
            self.albums = []
            self.album_filter = None
            self.render_albums()
            self.render_tracks()
            self.status.set_text('The library changed. Choose a period to explore it.')
        linked = bool(self.player.lastfm_session)
        was_offline = self.settings_link.get_visible()
        self.dial_panel.set_sensitive(linked)
        self.settings_link.set_visible(not linked)
        if not linked:
            self.status.set_text('Going back in time requires a last.fm account.')
        elif was_offline:
            self.status.set_text('Set a date range and press engage to go back in time')
        self.update_engage_pulse()

    def engage_ready(self):
        if (not self.player.lastfm_session or not self.go.is_sensitive() or
                self.checked_range is not None or self.go.get_label() != 'ENGAGE'):
            return False
        try:
            dates = []
            for dial in (self.start_dial, self.end_dial):
                values = []
                for name in ('YEAR', 'MONTH', 'DAY'):
                    text = dial.fields[name].get_text()
                    if not text.isdigit():
                        return False
                    values.append(int(text))
                dates.append(date(*values))
            return dates[0] <= dates[1] <= date.today() and dates[0].year >= 1970
        except (ValueError, OverflowError):
            return False

    def update_engage_pulse(self):
        if self.engage_ready() and not self.pulse_tick_id:
            self.pulse_tick_id = self.go.add_tick_callback(self.animate_engage)
        elif not self.engage_ready() and self.pulse_tick_id:
            self.go.remove_tick_callback(self.pulse_tick_id)
            self.pulse_tick_id = 0
        self.go.queue_draw()

    def animate_engage(self, _widget, clock):
        if not self.engage_ready():
            self.pulse_tick_id = 0
            self.go.queue_draw()
            return False
        self.pulse_phase = clock.get_frame_time() / 1000000.0
        self.go.queue_draw()
        return True

    def draw_engage_pulse(self, widget, cr):
        if not self.engage_ready():
            return False
        color = (getattr(self.player, 'current_art_bright', None)
                 if getattr(self.player, 'art_accent_enabled', False) else None)
        color = color or getattr(self.player, 'accent_color', '#78b7f0')
        rgba = Gdk.RGBA()
        if not rgba.parse(color):
            return False
        pulse = .5 + .5 * math.sin(self.pulse_phase * 2.4)
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, .06 + pulse * .12)
        cr.rectangle(0, 0, widget.get_allocated_width(), widget.get_allocated_height())
        cr.fill()
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, .35 + pulse * .65)
        cr.rectangle(0, max(0, widget.get_allocated_height() - 3), widget.get_allocated_width(), 3)
        cr.fill()
        return False

    def refresh_selection_style(self):
        color = (getattr(self.player, 'current_art_bright', None)
                 if getattr(self.player, 'art_accent_enabled', False) else None)
        color = color or getattr(self.player, 'accent_color', '#78b7f0')
        rgba = Gdk.RGBA()
        if not rgba.parse(color):
            rgba.parse('#78b7f0')
        text = '#202326' if getattr(self.player, 'theme', 'dark') == 'light' else '#ffffff'
        self.selection_provider.load_from_data(
            (f'#song-view.view:selected, #song-view.view:selected:backdrop {{ '
             f'background-color: rgba({round(rgba.red * 255)}, {round(rgba.green * 255)}, '
             f'{round(rgba.blue * 255)}, 0.42); color: {text}; }}').encode())
        self.list.queue_draw()

    def selected_dates(self):
        for dial in (self.start_dial, self.end_dial):
            for spin in dial.fields.values():
                spin.update()
        return self.start_dial.value(), self.end_dial.value()

    def align_dials(self, _flow, allocation):
        first_width = self.start_dial.get_preferred_width().minimum_width
        second_width = self.end_dial.get_preferred_width().minimum_width
        wrapped = allocation.width < first_width + second_width + self.dials.get_column_spacing()
        for dial, alignment in ((self.start_dial, Gtk.Align.CENTER if wrapped else Gtk.Align.END),
                                (self.end_dial, Gtk.Align.CENTER if wrapped else Gtk.Align.START)):
            if dial.get_halign() != alignment:
                dial.set_halign(alignment)

    def engage_pressed(self, *_args):
        if self.checked_range:
            self.show_listens()
        else:
            self.count_listens()

    def date_changed(self, *_args):
        if not hasattr(self, 'go'):
            return
        self.generation += 1
        self.stop_search_effect()
        self.checked_range = None
        self.checked_dates = None
        self.go.set_label('ENGAGE')
        self.go.set_sensitive(True)
        if hasattr(self, 'status') and self.source is None:
            self.status.set_text('Set a date range and press engage to go back in time')

    def count_listens(self, *_args):
        session = self.player.lastfm_session
        if not session:
            self.status.set_text('Going back in time requires a last.fm account.')
            return
        try:
            start_date, end_date = self.selected_dates()
            if start_date > date.today():
                self.status.set_text(random.choice(_FUTURE_ERRORS))
                return
            if end_date > date.today():
                self.status.set_text(random.choice(_FUTURE_ERRORS))
                return
            start, end = timestamps(start_date, end_date)
        except (ValueError, OverflowError):
            self.status.set_text('Choose valid dates, with FROM on or before TO.')
            return
        self.generation += 1
        generation = self.generation
        account_generation = self.player.lastfm_generation
        self.checked_range = None
        self.go.set_label('ENGAGE')
        self.go.set_sensitive(False)
        self.play.set_sensitive(False)
        self.save_playlist.set_sensitive(False)
        self.queue_random.set_sensitive(False)
        if self.source is not None:
            self.source = None
            self.account = None
            self.tracks = []
            self.lost_listens = []
            self.albums = []
            self.album_filter = None
            self.back.hide()
            self.render_albums()
            self.render_tracks()
        self.status.set_text('Counting listens on Last.fm…')
        self.start_search_effect()
        api = lastfm.LastFM(session['api_key'], session['secret'])
        def work():
            try:
                return api.listening_history_count(session['username'], start, end, session['session'])
            except lastfm.LastFMError as error:
                return str(error)
        def done(result):
            self.stop_search_effect()
            self.go.set_sensitive(True)
            if self.player.lastfm_generation != account_generation:
                self.status.set_text('The Last.fm account changed. Press ENGAGE to try again.')
            elif isinstance(result, str):
                self.status.set_text(result)
            elif result == 0:
                self.status.set_text('No listens found in this date range.')
            else:
                self.checked_range = (start, end, session['username'], account_generation)
                self.checked_dates = (start_date, end_date)
                noun = 'listen' if result == 1 else 'listens'
                self.status.set_text(f'Last.fm reports {result:,} {noun} in this date range.')
                self.go.set_label(f'SHOW {result:,} {noun.upper()}')
        def failed():
            self.stop_search_effect()
            self.go.set_sensitive(True)
            self.status.set_text('Could not count your Last.fm listens. Try again.')
        self.player.async_work(work, done, lambda: not self.player.closed and self.generation == generation, failed)

    def show_listens(self, *_args):
        session = self.player.lastfm_session
        client = self.player.client
        section = self.player.library.get_active_id()
        if not session or not self.checked_range:
            return
        start, end, username, account_generation = self.checked_range
        result_dates = self.checked_dates
        if username != session['username'] or account_generation != self.player.lastfm_generation:
            self.checked_range = None
            self.go.set_label('ENGAGE')
            self.status.set_text('The Last.fm account changed. Press ENGAGE to try again.')
            return
        if client is None or not section:
            self.status.set_text('Select a music library before showing these listens.')
            return
        self.generation += 1
        generation = self.generation
        catalog = (self.player.song_catalog if self.player.song_catalog_source ==
                   (client, section, None, None) else None)
        self.go.set_sensitive(False)
        self.play.set_sensitive(False)
        self.save_playlist.set_sensitive(False)
        self.queue_random.set_sensitive(False)
        self.status.set_text('Loading Last.fm history…')
        self.start_search_effect()
        self.source = None
        api = lastfm.LastFM(session['api_key'], session['secret'])
        valid = lambda: (not self.player.closed and self.generation == generation and
                         self.player.client is client and self.player.lastfm_generation == account_generation)
        def progress(page, pages, count):
            def update():
                if valid():
                    self.status.set_text(f'Loading listening history: page {page} of {pages} · {count} listens')
                return False
            GLib.idle_add(update)
        def work():
            try:
                history = api.listening_history(session['username'], start, end,
                                                session['session'], valid, progress)
                if history is None or not valid():
                    return None
                songs = catalog
                if songs is None and not getattr(client, 'is_local', False):
                    cached = LocalCache(client).read_song_index_entry(section)
                    songs = cached[0] if cached is not None else None
                if songs is None:
                    songs = build_song_catalog(client, section, valid=valid)
                    if songs is not None and valid() and not getattr(client, 'is_local', False):
                        try:
                            LocalCache(client).save_song_index(section, songs)
                        except OSError:
                            pass
                if songs is None or not valid():
                    return None
                tracks, missing = partition_history(history, songs)
                return tracks, len(history), missing
            except lastfm.LastFMError as error:
                return str(error)
        def done(result):
            self.stop_search_effect()
            self.go.set_sensitive(True)
            if self.player.library.get_active_id() != section:
                self.status.set_text('The library changed. Press ENGAGE to try again.')
                return
            if isinstance(result, str):
                self.status.set_text(result)
                return
            if result is None:
                self.status.set_text('The request was cancelled.')
                return
            self.checked_range = None
            self.go.set_label('ENGAGE')
            self.tracks, total, self.lost_listens = result
            self.result_dates = result_dates
            self.source = (client, section)
            self.account = session['username']
            self.albums = albums_for_history(self.tracks)
            self.album_filter = None
            self.back.hide()
            self.status.set_markup(f'{total:,} listens · {len(self.albums):,} albums · '
                                   f'<a href="apistat:lost">{len(self.lost_listens):,} lost to time</a> '
                                   '(not matched in library)')
            self.render_albums()
            self.render_tracks()
        def failed():
            self.stop_search_effect()
            self.go.set_sensitive(True)
            self.status.set_text('Could not load listening history or the music library. Try again.')
        # Always run the completion callback when the query is superseded so the
        # button cannot remain disabled; validity is checked inside the worker.
        self.player.async_work(work, done, lambda: not self.player.closed and self.generation == generation, failed)

    def show_lost_listens(self, _label, uri):
        if uri != 'apistat:lost':
            return False
        self.player.show_lost_time_info(self.lost_listens)
        return True

    def set_view(self, _button, name):
        if self._changing_view:
            return
        self._changing_view = True
        try:
            self.album_button.set_active(name == 'albums')
            self.track_button.set_active(name == 'tracks')
        finally:
            self._changing_view = False
        self.views.set_visible_child_name(name)
        self.track_sort_bar.set_visible(name == 'tracks')
        if name == 'albums':
            self.album_filter = None
            self.back.hide()
            self.render_tracks()
        self.play.set_sensitive(bool(self.display_tracks))
        self.save_playlist.set_sensitive(bool(self.display_tracks))

    def show_all_albums(self, *_args):
        self.album_filter = None
        self.back.hide()
        self.set_view(None, 'albums')

    def open_album(self, album):
        self.album_filter = album.key
        self.render_tracks()
        self.set_view(None, 'tracks')
        self.back.show()

    def render_tracks(self):
        self.render_generation += 1
        generation = self.render_generation
        tracks = [track for track in self.tracks
                  if self.album_filter is None or track.album_key == self.album_filter]
        if self.track_sort:
            tracks.sort(key=lambda track: (int(getattr(track, self.track_sort, 0) or 0)
                                            if str(getattr(track, self.track_sort, 0) or 0).isdigit() else 0)
                        if self.track_sort in ('duration', 'year') else
                        str(getattr(track, self.track_sort, '') or '').casefold(),
                        reverse=self.track_sort_reverse)
        self.display_tracks = group_songs_by_album(tracks)
        self.group_overlay.set_results(self.display_tracks)
        self.store.clear()
        # A virtual first row provides space under the glass without allocating
        # a full-height TreeView or sacrificing scrolling performance.
        self.store.append(['', '', '', ''])
        self.play.set_sensitive(bool(self.display_tracks))
        self.save_playlist.set_sensitive(bool(self.display_tracks))
        self.queue_random.set_sensitive(bool(self.tracks))
        for button in (self.play, self.save_playlist, self.queue_random):
            button.set_visible(bool(self.tracks))
        offset = 0
        def append():
            nonlocal offset
            if self.player.closed or generation != self.render_generation:
                return False
            for track in self.display_tracks[offset:offset + 150]:
                self.store.append([track.title, track.artist, str(track.year or ''),
                                   self.player.song_column_value(track, 'duration')])
            offset += 150
            return offset < len(self.display_tracks)
        if self.display_tracks:
            GLib.idle_add(append)

    def field_at_scroll_event(self, event):
        if event is None or not self.header_surface.get_mapped():
            return None
        try:
            valid, root_x, root_y = event.get_root_coords()
            if not valid:
                return None
            origin = self.header_surface.get_window().get_origin()
            x, y = root_x - origin[-2], root_y - origin[-1]
            for dial in (self.start_dial, self.end_dial):
                for field in dial.fields.values():
                    region = field.hit_region
                    position = region.translate_coordinates(self.header_surface, 0, 0)
                    if (position is not None and position[0] <= x < position[0] + region.get_allocated_width()
                            and position[1] <= y < position[1] + region.get_allocated_height()):
                        return field
        except (TypeError, AttributeError, IndexError):
            return None
        return None

    def header_scroll_capture(self, _controller, _dx, dy):
        field = self.field_at_scroll_event(Gtk.get_current_event())
        if field is not None:
            field.scroll_delta(dy)

    def header_scroll(self, _widget, event):
        field = self.field_at_scroll_event(event)
        return field.scroll_value(_widget, event) if field is not None else False

    def update_sort_column(self, column, _property, field):
        # The name column expands with the window; making its current width a
        # minimum would prevent the window from shrinking again.
        if field == 'title' and column.get_expand():
            return
        width = column.get_width()
        if width > 0:
            self.sort_containers[field].set_size_request(width, -1)

    def update_sort_gutter(self, column, *_args):
        width = column.get_width() or column.get_fixed_width()
        if width > 0:
            self.sort_gutter.set_size_request(width, -1)

    def make_column_grip(self, field):
        grip = Gtk.EventBox()
        grip.set_visible_window(False)
        grip.set_size_request(8, -1)
        grip.set_name('time-column-grip')
        grip.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK |
                        Gdk.EventMask.LEAVE_NOTIFY_MASK)
        grip.connect('button-press-event', self.start_column_resize, field)
        grip.connect('motion-notify-event', self.move_column_resize)
        grip.connect('button-release-event', self.finish_column_resize)
        grip.connect('enter-notify-event', self.column_grip_enter)
        grip.connect('leave-notify-event', self.column_grip_leave)
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_top=5, margin_bottom=5)
        grip.add(separator)
        return grip

    def column_grip_enter(self, grip, _event):
        window = grip.get_window()
        if window is not None:
            cursor = Gdk.Cursor.new_from_name(window.get_display(), 'col-resize')
            if cursor is not None:
                window.set_cursor(cursor)
        return False

    def column_grip_leave(self, grip, _event):
        window = grip.get_window()
        if window is not None:
            window.set_cursor(None)
        return False

    def start_column_resize(self, grip, event, field):
        if event.button != 1:
            return False
        column = self.gutter if field == 'gutter' else self.track_columns[field]
        width = column.get_width() or column.get_fixed_width()
        self.resize_state = (field, event.x_root, max(50, width))
        grip.grab_add()
        return True

    def move_column_resize(self, _grip, event):
        if self.resize_state is None:
            return False
        field, start, width = self.resize_state
        column = self.gutter if field == 'gutter' else self.track_columns[field]
        minimum = AlbumGroupOverlay.MIN_GUTTER if field == 'gutter' else 50
        maximum = AlbumGroupOverlay.MAX_GUTTER if field == 'gutter' else 1200
        target = max(minimum, min(maximum, round(width + event.x_root - start)))
        if field == 'title' and column.get_expand():
            column.set_expand(False)
            self.track_sort_bar.set_child_packing(self.sort_containers[field], False, False, 0, Gtk.PackType.START)
        column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        column.set_fixed_width(target)
        if field == 'gutter':
            self.sort_gutter.set_size_request(target, -1)
        else:
            self.sort_containers[field].set_size_request(target, -1)
        return True

    def finish_column_resize(self, grip, event):
        if event.button != 1 or self.resize_state is None:
            return False
        self.resize_state = None
        grip.grab_remove()
        return True

    def header_allocated(self, _widget, allocation):
        height = allocation.height
        if height == self.header_height:
            return
        self.header_height = height
        if hasattr(self, 'wall'):
            self.wall.set_margin_top(self.player.album_margin + height)
        if hasattr(self, 'list'):
            self.list.queue_resize()
        if self.gpu_wall is not None:
            self.gpu_wall.set_content_top_inset(height)

    def group_row_size(self, _column, cell, model, row, _data=None):
        index = model.get_path(row).get_indices()[0]
        if index == 0:
            cell.set_fixed_size(-1, max(1, self.header_height))
            return
        count = self.group_overlay.group_ends.get(index - 1)
        cell.set_fixed_size(-1, album_group_row_height(count, getattr(self.player, 'text_size', 18)) if count else -1)

    def sort_tracks(self, _column, field):
        self.track_sort_reverse = not self.track_sort_reverse if self.track_sort == field else False
        self.track_sort = field
        for name, (button, label) in self.sort_buttons.items():
            marker = (' ▼' if self.track_sort_reverse else ' ▲') if name == field else ''
            button.set_label(label + marker)
            context = button.get_style_context()
            (context.add_class if name == field else context.remove_class)('active')
        self.render_tracks()

    def track_pressed(self, view, event):
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if event.button == 1:
            if not hit or hit[0].get_indices()[0] == 0:
                self.player.time_drag_candidates = []
                return True
            modifiers = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK
            if getattr(event, 'state', 0) & modifiers:
                self.player.time_drag_candidates = None
            elif view.get_selection().path_is_selected(hit[0]):
                self.player.time_drag_candidates = self.selected_track_indices(view)
            else:
                self.player.time_drag_candidates = [hit[0].get_indices()[0] - 1]
        elif event.button == 3 and hit:
            index = hit[0].get_indices()[0] - 1
            if 0 <= index < len(self.display_tracks):
                selection = view.get_selection()
                if not selection.path_is_selected(hit[0]):
                    selection.unselect_all()
                    selection.select_path(hit[0])
                self.player.show_song_context_menu(event, self.display_tracks[index], index,
                                                   lambda: self.play_track(index))
                return True
        return False

    def selected_track_indices(self, view):
        _model, paths = view.get_selection().get_selected_rows()
        return sorted(index for path in paths
                      if 0 <= (index := path.get_indices()[0] - 1) < len(self.display_tracks))

    def track_drag_begin(self, view, context):
        indices = getattr(self.player, 'time_drag_candidates', None)
        if indices is None:
            indices = self.selected_track_indices(view)
        indices = [i for i in indices if 0 <= i < len(self.display_tracks)]
        self.player.time_drag_tracks = tuple(self.display_tracks[i] for i in indices)
        self.player.time_drag_client = self.player.client
        if indices:
            for index in indices:
                view.get_selection().select_path(Gtk.TreePath.new_from_indices([index + 1]))
            # Use the same row preview as Library, adjusted for the spacer row.
            surface = view.create_row_drag_icon(Gtk.TreePath.new_from_indices([indices[0] + 1]))
            if surface is not None:
                from gtk_snapshot import normalize_surface_origin
                Gtk.drag_set_icon_surface(context, normalize_surface_origin(surface))

    def track_drag_end(self, *_args):
        self.player.time_drag_candidates = None
        self.player.time_drag_tracks = None
        self.player.time_drag_client = None

    def track_drag_data(self, view, _context, selection, _info, _time):
        tracks = getattr(self.player, 'time_drag_tracks', None)
        if tracks is None:
            tracks = [self.display_tracks[i] for i in
                      self.selected_track_indices(view)]
        data = encode_track_keys([track.key for track in tracks])
        if data:
            selection.set(selection.get_target(), 8, data)

    def enqueue_random(self, *_args):
        client = self.player.client
        if (self.source != (client, self.player.library.get_active_id()) or
                self.account != (self.player.lastfm_session or {}).get('username')):
            return
        # Listening history may include the same song many times. Pick distinct
        # tracks so repeated scrobbles don't fill the queue with one song.
        unique = list({track.key: track for track in self.tracks}.values())
        if not unique:
            return
        chosen = random.sample(unique, min(50, len(unique)))
        self.player.enqueue_tracks(chosen)
        self.status.set_text(f'Added {len(chosen)} songs from this time to the play queue.')

    def playlist_default_name(self):
        if self.result_dates:
            start, end = self.result_dates
            return f'{start.isoformat()} – {end.isoformat()}'
        return 'Time machine'

    def save_playlist_dialog(self, *_args):
        client = self.player.client
        section = self.player.library.get_active_id()
        if (not self.display_tracks or self.source != (client, section) or
                self.account != (self.player.lastfm_session or {}).get('username')):
            return
        tracks = list(self.display_tracks)
        dialog = Gtk.Dialog(title='Save as playlist', transient_for=self.player, modal=True)
        dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
        save = dialog.add_button('Save', Gtk.ResponseType.OK)
        entry = Gtk.Entry(placeholder_text='Playlist name')
        entry.set_text(self.playlist_default_name())
        entry.set_margin_start(16); entry.set_margin_end(16)
        entry.set_margin_top(16); entry.set_margin_bottom(16)
        dialog.get_content_area().add(entry)
        entry.connect('changed', lambda field: save.set_sensitive(bool(field.get_text().strip())))
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry.set_activates_default(True)
        dialog.show_all()
        response = dialog.run()
        title = entry.get_text().strip()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not title:
            return
        self.save_playlist.set_sensitive(False)
        self.status.set_text(f'Saving {len(tracks):,} listens as a playlist…')
        def work():
            if getattr(client, 'is_local', False):
                return client.create_playlist_with_tracks(title, tracks), len(tracks), None
            playlist = client.create_playlist(title, tracks[0])
            count = 1
            try:
                for track in tracks[1:]:
                    client.add_playlist_item(playlist, track)
                    count += 1
            except Exception:
                return playlist, count, 'Some tracks could not be added.'
            return playlist, count, None
        def done(result):
            playlist, count, error = result
            self.save_playlist.set_sensitive(bool(self.display_tracks))
            self.status.set_text(f'Saved {count:,} of {len(tracks):,} listens to “{playlist.title}”.' +
                                 (f' {error}' if error else ''))
            self.player.load_playlists()
        def failed():
            self.save_playlist.set_sensitive(bool(self.display_tracks))
            self.status.set_text('Could not save the playlist. Please try again.')
        self.player.async_work(work, done, lambda: not self.player.closed and self.player.client is client, failed)

    def play_track(self, index):
        if (self.source != (self.player.client, self.player.library.get_active_id()) or
                self.account != (self.player.lastfm_session or {}).get('username') or
                not 0 <= index < len(self.display_tracks)):
            return
        self.player.clear_remote_queue()
        self.player.queue_album = None
        self.player.queue = list(self.display_tracks)
        self.player.queue_client = self.player.client
        self.player.index = index
        self.player.start_track()

    def shutdown_gpu(self, *_args):
        if self.gpu_wall is not None:
            self.gpu_wall.shutdown()

    def gpu_failed(self):
        self.gpu_unavailable = True
        self.album_stack.set_visible_child_name('gtk')
        self.status.set_text('GPU album wall unavailable; showing the regular album wall.')
        self.render_albums()
        return False

    def gpu_album_pressed(self, album, event, _x, _y):
        if event.button == 3:
            self.player.show_context_menu(event, gpu_album=album, gpu_wall=self.gpu_wall)
        else:
            self.gpu_wall.toggle_album(album)

    def render_albums(self):
        self.album_generation += 1
        for child in self.grid.get_children():
            child.destroy()
        self.album_offset = 0
        use_gpu = bool(self.albums and getattr(self.player, 'gpu_wall_enabled', False)
                       and not self.gpu_unavailable)
        if use_gpu:
            try:
                if self.gpu_wall is None:
                    from gpu_album_wall import GPUAlbumWall
                    self.gpu_wall = GPUAlbumWall(self.player, self.gpu_failed,
                                                album_pressed=self.gpu_album_pressed,
                                                load_more=False)
                    self.gpu_wall.render_surface.set_margin_top(0)
                    self.gpu_wall.scrollbar.set_margin_top(0)
                    self.gpu_wall.set_content_top_inset(self.header_height)
                    self.album_stack.add_named(self.gpu_wall, 'gpu')
                    self.gpu_wall.show_all()
                self.gpu_wall.set_albums(self.player.client, list(self.albums), reset=True)
                self.album_stack.set_visible_child_name('gpu')
                return
            except (OSError, ImportError, RuntimeError, AttributeError):
                self.gpu_unavailable = True
        if self.gpu_wall is not None:
            self.gpu_wall.set_albums(None, [], reset=True)
        self.album_stack.set_visible_child_name('gtk')
        self.add_albums()

    def add_albums(self):
        client = self.player.client
        generation = self.album_generation
        end = min(len(self.albums), self.album_offset + 40)
        for album in self.albums[self.album_offset:end]:
            button = Gtk.Button()
            button.set_name('time-machine-album')
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            image = Gtk.Image()
            self.player.set_placeholder_art(image, self.player.album_art_size)
            column.pack_start(image, False, False, 0)
            label = Gtk.Label(label=album.title, xalign=.5)
            label.set_ellipsize(3)
            label.set_max_width_chars(22)
            column.pack_start(label, False, False, 0)
            artist = Gtk.Label(label=album.artist, xalign=.5)
            artist.set_ellipsize(3)
            artist.set_max_width_chars(22)
            column.pack_start(artist, False, False, 0)
            button.add(column)
            button.time_art = image
            button.connect('clicked', lambda _button, value=album: self.open_album(value))
            self.grid.add(button)
            self.player.load_art(client, album, image, self.player.album_art_size,
                                 lambda: generation == self.album_generation and client is self.player.client)
        self.album_offset = end
        self.grid.show_all()
        self.resize_grid()

    def zoom(self, widget, event):
        handled = self.player.zoom_art(widget, event, 'albums')
        if handled:
            self.update_grid_settings()
        return handled

    def update_grid_settings(self):
        if self.gpu_wall is not None:
            self.gpu_wall.layout_changed()
        margin = self.player.album_margin
        for side in ('start', 'end', 'bottom'):
            getattr(self.wall, f'set_margin_{side}')(margin)
        self.wall.set_margin_top(margin + self.header_height)
        self.grid.set_row_spacing(self.player.album_spacing)
        self.grid.set_column_spacing(self.player.album_spacing)
        for child in self.grid.get_children():
            button = child.get_child()
            self.player.set_art_size(button.time_art, self.player.album_art_size)
        self.resize_grid()

    def resize_grid(self, *_args):
        width = self.album_scroll.get_allocated_width()
        size, gap, margin = self.player.album_art_size, self.player.album_spacing, self.player.album_margin
        columns = max(1, min(16, (max(0, width - 2 * margin - 18) + gap) // (size + gap)))
        self.grid.set_min_children_per_line(columns)
        self.grid.set_max_children_per_line(columns)

    def scroll_changed(self, adjustment):
        if (adjustment.get_upper() - adjustment.get_value() - adjustment.get_page_size() < 250 and
                self.album_offset < len(self.albums)):
            self.add_albums()
