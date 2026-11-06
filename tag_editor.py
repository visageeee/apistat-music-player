"""GTK editor for the fields explicitly selected by the user."""
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, GdkPixbuf

from local_cache import LocalCache
from plex_client import ALBUM_SORT_ARTIST, Item
from tag_edit import image_type, validate_changes

FIELDS = (('title', 'Title'), ('artist', 'Artist'), ('album', 'Album'),
          ('album_artist', 'Album artist'), ('year', 'Year'), ('genre', 'Genre'),
          ('track_number', 'Track number'), ('disc', 'Disc number'))


class TagEditor(Gtk.Box):
    def __init__(self, player):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.player = player
        self.client = None
        self.tracks = ()
        self.section = None
        self.artwork = None
        self.loading = False
        self.entries, self.checks, self.rows = {}, {}, {}
        self.intro = Gtk.Label(xalign=0)
        self.intro.set_name('info-section-title')
        self.intro.set_line_wrap(True)
        self.intro.set_width_chars(1)
        self.intro.set_max_width_chars(28)
        self.pack_start(self.intro, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        self.fields_scroll = scroll
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.source_heading = Gtk.Label(xalign=0)
        self.source_heading.set_name('info-section-title')
        content.pack_start(self.source_heading, False, False, 0)
        self.source_description = Gtk.Label(xalign=0)
        self.source_description.set_line_wrap(True)
        self.source_description.set_width_chars(1)
        self.source_description.set_max_width_chars(28)
        content.pack_start(self.source_description, False, False, 0)
        self.edit_instructions = Gtk.Label(xalign=0)
        self.edit_instructions.set_line_wrap(True)
        self.edit_instructions.set_width_chars(1)
        self.edit_instructions.set_max_width_chars(28)
        content.pack_start(self.edit_instructions, False, False, 0)
        for key, label in FIELDS:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            check = Gtk.CheckButton(label=label)
            entry = Gtk.Entry()
            entry.set_max_length(4096)
            entry.connect('changed', self.entry_changed, check)
            row.pack_start(check, False, False, 0)
            row.pack_start(entry, False, False, 0)
            content.pack_start(row, False, False, 0)
            self.entries[key], self.checks[key], self.rows[key] = entry, check, row
            # Keep hidden Plex-only rows hidden when the containing window calls show_all.
            row.show_all()
            row.set_no_show_all(True)
        content.pack_start(Gtk.Label(label='Album artwork', xalign=0), False, False, 0)
        self.art_preview = Gtk.Image()
        self.art_preview.set_halign(Gtk.Align.START)
        content.pack_start(self.art_preview, False, False, 0)
        art_buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        choose = Gtk.Button(label='Choose image…')
        choose.connect('clicked', self.choose_art)
        reset = Gtk.Button(label='Remove album art')
        reset.connect('clicked', self.remove_art)
        art_buttons.pack_start(choose, False, False, 0)
        art_buttons.pack_start(reset, False, False, 0)
        content.pack_start(art_buttons, False, False, 0)
        self.art_label = Gtk.Label(label='Artwork will remain unchanged.', xalign=0)
        self.art_label.set_line_wrap(True)
        self.art_label.set_width_chars(1)
        self.art_label.set_max_width_chars(28)
        content.pack_start(self.art_label, False, False, 0)
        scroll.add(content)
        self.pack_start(scroll, True, True, 0)
        self.message = Gtk.Label(xalign=0)
        self.message.set_line_wrap(True)
        self.message.set_width_chars(1)
        self.message.set_max_width_chars(28)
        self.message.set_selectable(True)
        self.pack_start(self.message, False, False, 0)
        self.buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.save_button = Gtk.Button(label='Save changes')
        self.save_button.connect('clicked', self.save)
        self.cancel_button = Gtk.Button(label='Cancel')
        self.cancel_button.connect('clicked', lambda *_: self.player.info_button.set_active(False))
        self.buttons.pack_start(self.save_button, False, False, 0)
        self.buttons.pack_start(self.cancel_button, False, False, 0)
        self.pack_start(self.buttons, False, False, 0)

    def entry_changed(self, _entry, check):
        if not self.loading:
            check.set_active(True)

    def load(self, client, section, tracks):
        self.client, self.section, self.tracks = client, section, tuple(tracks)
        self.loading = True
        local = getattr(client, 'is_local', False)
        count = len(self.tracks)
        noun = 'track' if count == 1 else 'tracks'
        self.intro.set_text(f'{count} {noun} selected')
        if local:
            self.source_heading.set_text('Local files')
            self.source_description.set_text('Changes are written to the selected music files.')
            self.edit_instructions.set_text(
                'Check the fields you want to change. A checked field left blank will be cleared.')
        else:
            self.source_heading.set_text('Plex library')
            self.source_description.set_text(
                'Changes are saved in Plex. The original music files are not changed.')
            self.edit_instructions.set_text(
                'Check Title and enter a name to apply it to every selected track. '
                'Choosing artwork updates each album containing a selected track.')
        for key, _label in FIELDS:
            values = {str(getattr(track, key, '') or '') for track in self.tracks}
            value = next(iter(values)) if len(values) == 1 else ''
            self.entries[key].set_text(value)
            self.entries[key].set_placeholder_text('Multiple values' if len(values) > 1 else '')
            supported = local or key == 'title'
            self.rows[key].set_visible(supported)
            self.entries[key].set_sensitive(supported)
            self.checks[key].set_sensitive(supported)
            self.checks[key].set_active(False)
        self.artwork = None
        self.art_preview.clear()
        self.art_label.set_text('Artwork will remain unchanged.')
        self.message.set_text('')
        self.save_button.set_sensitive(True)
        self.loading = False
        covers = {(track.album_key, track.album_thumb or track.thumb) for track in self.tracks}
        if len(covers) == 1 and hasattr(self.player, 'load_art'):
            album_key, thumb = next(iter(covers))
            if thumb:
                snapshot = self.tracks
                item = Item(album_key or snapshot[0].key, snapshot[0].album or 'Album', thumb=thumb)
                def valid():
                    return (not self.player.closed and self.client is client and self.tracks == snapshot
                            and self.artwork is None)
                def loaded(_pixbuf):
                    if valid():
                        self.art_label.set_text('Current artwork; no change selected.')
                self.player.load_art(client, item, self.art_preview, 96, valid, loaded)

    def clear_art(self, *_args):
        self.artwork = None
        self.art_preview.clear()
        self.art_label.set_text('Artwork will remain unchanged.')

    def remove_art(self, *_args):
        self.artwork = False
        self.art_preview.clear()
        if getattr(self.client, 'is_local', False):
            message = ('Embedded front covers will be removed from the selected files. '
                       'Other tracks or folder artwork may still supply a cover.')
        else:
            message = 'Plex will remove the artwork for each selected album.'
        self.art_label.set_text(message)

    def choose_art(self, *_args):
        dialog = Gtk.FileChooserDialog(title='Choose album artwork', transient_for=self.player,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Choose', Gtk.ResponseType.OK)
        image_filter = Gtk.FileFilter()
        image_filter.set_name('JPEG and PNG images')
        for mime in ('image/jpeg', 'image/png'):
            image_filter.add_mime_type(mime)
        dialog.add_filter(image_filter)
        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not filename:
            return
        client, tracks = self.client, self.tracks
        self.message.set_text('Loading artwork…')
        def work():
            with open(filename, 'rb') as file:
                data = file.read(16 * 1024 * 1024 + 1)
            image_type(data)
            loader = GdkPixbuf.PixbufLoader()
            loader.set_size(96, 96)
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            if pixbuf is None:
                raise ValueError('Could not decode artwork.')
            return data, pixbuf
        def done(result):
            self.artwork = result[0]
            self.art_preview.set_from_pixbuf(result[1])
            self.art_label.set_text('Selected: ' + Path(filename).name)
            self.message.set_text('')
        self.player.async_work(work, done,
                               lambda: not self.player.closed and self.client is client and self.tracks == tracks,
                               lambda: self.message.set_text('Could not load the image. Choose a valid JPEG or PNG under 16 MB.'))

    def save(self, *_args):
        client, section, tracks, artwork = self.client, self.section, self.tracks, self.artwork
        if not client or not tracks or client is not self.player.client:
            self.message.set_text('The library changed. Select tracks again.')
            return
        changes = {key: self.entries[key].get_text() for key, _label in FIELDS
                   if self.checks[key].get_sensitive() and self.checks[key].get_active()}
        try:
            changes = validate_changes(changes)
        except ValueError as error:
            self.message.set_text(str(error))
            return
        if not changes and artwork is None:
            self.message.set_text('Choose at least one field or image to change.')
            return
        self.save_button.set_sensitive(False)
        self.message.set_text('Saving changes…')
        self.player.note_song_cache_edit(self.player)
        playlists = tuple(getattr(self.player, 'playlists', ()))
        def work():
            result = client.edit_tracks(tracks, changes, artwork, section=section)
            if result[0]:
                try:
                    cache = LocalCache(client)
                    for key in [None] + [playlist.key for playlist in playlists]:
                        cache.song_index_path(section, key).unlink(missing_ok=True)
                    cache.index_path(section).unlink(missing_ok=True)
                    cache.music_facets_path(section).unlink(missing_ok=True)
                    for sort in ('addedAt:desc', 'year:desc', ALBUM_SORT_ARTIST, 'titleSort'):
                        cache.album_page_path(section, sort).unlink(missing_ok=True)
                except OSError:
                    result[1].append(('Cache', 'Changes were saved, but cached library data could not be cleared.'))
            return result
        def done(result):
            saved, failures = result
            if self.client is client and self.tracks == tracks:
                self.save_button.set_sensitive(True)
                details = '\n'.join(f'{name}: {message}' for name, message in failures[:4])
                self.message.set_text(f'Saved {saved} of {len({track.key for track in tracks})} tracks.' +
                                      ('\n' + details if details else ''))
                if not failures:
                    self.loading = True
                    for check in self.checks.values():
                        check.set_active(False)
                    self.loading = False
                    self.clear_art()
            if saved:
                self.player.invalidate_song_catalog()
                self.player.song_view_cache.clear()
                self.player.indexed_albums = None
                self.player.artist_catalog = None
                self.player.album_search_catalog = None
                getattr(self.player, '_album_card_tracks', {}).clear()
                self.player.load_songs()
                self.player.load_albums(force_refresh=True)
        def failed():
            if self.client is client and self.tracks == tracks:
                self.save_button.set_sensitive(True)
                self.message.set_text('Could not save the changes. Check file permissions or server access.')
        self.player.async_work(work, done, lambda: not self.player.closed and client is self.player.client, failed)
