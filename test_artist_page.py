import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from xml.etree import ElementTree

from artist_page import (artist_library, popular_tracks, plex_artist_profile,
                         plex_album_description, short_description, full_description)
from artist_album_canvas import ArtistAlbumCanvas, artist_album_slots
import cairo
from plex_client import Item
from player import Player
from gi.repository import Gdk, Gtk


class ArtistPageTests(unittest.TestCase):
    def setUp(self):
        self.albums = [Item('/a', 'Early', artist='Artist', year='1980'),
                       Item('/b', 'Later', artist='ARTIST', year='2000'),
                       Item('/c', 'Unknown', artist='Artist'),
                       Item('/d', 'Other', artist='Other', year='2020')]
        self.songs = [Item('/1', 'First', artist='Artist', play_count=1),
                      Item('/2', 'Popular', artist='artist', play_count=8),
                      Item('/3', 'Other', artist='Other', play_count=50)]

    def test_artist_catalog_is_filtered_and_sorted_by_year(self):
        albums, songs = artist_library('artist', self.albums, self.songs)
        self.assertEqual([album.title for album in albums], ['Later', 'Early', 'Unknown'])
        self.assertEqual([song.title for song in songs], ['Popular', 'First'])

    def test_popular_tracks_match_library_in_lastfm_order(self):
        result = {'toptracks': {'track': [{'name': 'missing'}, {'name': 'First'},
                                          {'name': 'POPULAR'}, {'name': 'First'}]}}
        self.assertEqual([song.key for song in popular_tracks(self.songs[:2], result)], ['/1', '/2'])
        self.assertEqual(popular_tracks(self.songs, {}), [])

    def test_album_slots_leave_space_for_descriptions_and_group_years(self):
        albums = [self.albums[1], self.albums[0], self.albums[2]]
        slots, indices, markers = artist_album_slots(albums, 4)
        for index, slot in enumerate(indices):
            self.assertEqual(slots[slot], index)
            self.assertIsNone(slots[slot + 1])
        self.assertEqual([marker[1] for marker in markers], ['2000', '1980', 'Unknown year'])

    def test_album_description_uses_valid_plex_metadata_and_sanitizes_html(self):
        album = Item('/library/metadata/4/children', 'Album')
        xml = ElementTree.fromstring('<MediaContainer><Directory summary="A record."/></MediaContainer>')
        client = SimpleNamespace(xml=Mock(return_value=xml))
        self.assertEqual(plex_album_description(client, album), 'A record.')
        client.xml.assert_called_once_with('/library/metadata/4')
        self.assertEqual(short_description('A &amp; B <a href="https://example.com">more</a>'), 'A & B')
        long_text = 'A long record. ' * 80
        self.assertEqual(full_description(long_text), long_text.strip())

    def test_read_more_is_only_drawn_for_clipped_descriptions(self):
        album = self.albums[0]
        player = SimpleNamespace(theme='dark', text_size=18, show_album_details=True,
                                 search_escape_pressed=Mock(), shared_background=None,
                                 background_visualizer=None, show_album_description=Mock())
        with patch('gpu_album_wall.load_gl', return_value=Mock()):
            wall = ArtistAlbumCanvas(player, Mock(), Mock())
        wall.canvas_player.zoom = 1.25
        wall.albums = [album]
        wall.descriptions = {album.key: 'Short description.'}
        wall.visible = lambda: [(0, 5, 5)]
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 500, 230)
        try:
            with patch('experimental_album_canvas.ExperimentalAlbumCanvas.draw_labels', return_value=False):
                wall.draw_labels(wall.labels, cairo.Context(surface))
                self.assertEqual(wall.read_more_hits, [])
                wall.descriptions[album.key] = 'This is a much longer description. ' * 50
                wall.draw_labels(wall.labels, cairo.Context(surface))
                self.assertEqual(len(wall.read_more_hits), 1)
                left, top, width, height, target = wall.read_more_hits[0]
                self.assertIs(target, album)
                self.assertGreater(width * height, 0)
                self.assertIs(ArtistAlbumCanvas.read_more_at(wall, left + 1, top + 1)[4], album)
                press = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
                press.button, press.x, press.y = 1, left + 1, top + 1
                release = Gdk.Event.new(Gdk.EventType.BUTTON_RELEASE)
                release.button, release.x, release.y = 1, left + 1, top + 1
                self.assertTrue(wall.input_surface.emit('button-press-event', press))
                self.assertTrue(wall.input_surface.emit('button-release-event', release))
                self.assertEqual(player.show_album_description.call_args.args[:2],
                                 (album, wall.descriptions[album.key]))
        finally:
            wall.shutdown()
            wall.destroy()

    def test_plex_artist_profile_validates_artist_and_metadata_path(self):
        track = Item('/library/metadata/1', 'Track', artist='Artist')
        track_xml = ElementTree.fromstring('<MediaContainer><Track grandparentTitle="Artist" '
                                          'grandparentKey="/library/metadata/2"/></MediaContainer>')
        artist_xml = ElementTree.fromstring('<MediaContainer><Directory summary="Biography" '
                                           'thumb="/library/metadata/2/thumb/1"/></MediaContainer>')
        client = SimpleNamespace(xml=Mock(side_effect=[track_xml, artist_xml]))
        summary, image = plex_artist_profile(client, track, 'Artist')
        self.assertEqual(summary, 'Biography')
        self.assertEqual(image.thumb, '/library/metadata/2/thumb/1')
        client.xml = Mock(return_value=track_xml)
        self.assertEqual(plex_artist_profile(client, track, 'Other'), ('', None))
        client.xml.assert_called_once()

    def test_artist_name_opens_page_only_on_left_click(self):
        player = SimpleNamespace(show_artist_page=Mock())
        self.assertFalse(Player.artist_name_pressed(player, None, SimpleNamespace(button=3), lambda: 'Artist'))
        self.assertTrue(Player.artist_name_pressed(player, None, SimpleNamespace(button=1), lambda: 'Artist'))
        player.show_artist_page.assert_called_once_with('Artist')

    def test_artist_page_builds_with_a_back_button_and_album_grid(self):
        stack = Gtk.Stack()
        def scroll(child):
            widget = Gtk.ScrolledWindow()
            widget.add(child)
            return widget
        player = SimpleNamespace(views=stack, album_spacing=20, album_margin=20,
                                 artist_page_back=Mock(), artist_page_fallback_zoom=Mock(),
                                 artist_page_header_allocated=Mock(),
                                 set_placeholder_art=Mock(), scroll=scroll,
                                 button=lambda label, callback: Gtk.Button(label=label))
        try:
            with patch('player.sys.platform', 'darwin'):
                Player.ensure_artist_page(player)
            self.assertIs(stack.get_child_by_name('artist'), player.artist_page)
            self.assertIsInstance(player.artist_page, Gtk.Overlay)
            self.assertIsInstance(player.artist_page_grid, Gtk.FlowBox)
            self.assertIsInstance(player.artist_page_songs, Gtk.Box)
        finally:
            stack.destroy()

    def test_artist_page_loads_library_and_plays_selected_song(self):
        client = object()
        stack = Gtk.Stack()
        stack.add_named(Gtk.Box(), 'wall')
        state = {'panel': 'now'}
        def scroll(child):
            widget = Gtk.ScrolledWindow()
            widget.add(child)
            return widget
        player = SimpleNamespace(
            client=client, library=SimpleNamespace(get_active_id=lambda: 'music'),
            views=stack, content_views=SimpleNamespace(get_visible_child_name=lambda: state['panel']),
            album_spacing=20, album_margin=20, album_art_size=180, artist_page_back=Mock(),
            artist_page_fallback_zoom=Mock(), artist_page_header_allocated=Mock(),
            set_placeholder_art=Mock(),
            scroll=scroll, button=lambda label, callback: Gtk.Button(label=label),
            canvas_catalog=self.albums, canvas_catalog_identity=(client, 'music'),
            closed=False, load_art=Mock(), artist_page_load_profile=Mock(),
            artist_page_load_descriptions=Mock(), play_artist_song=Mock())
        def ensure():
            with patch('player.sys.platform', 'darwin'):
                Player.ensure_artist_page(player)
        player.ensure_artist_page = ensure
        player.show_view = lambda name: state.__setitem__('panel', name)
        player.async_work = lambda work, ready, valid, failed: ready(work()) if valid() else None
        player.artist_page_set_songs = lambda songs, title: Player.artist_page_set_songs(player, songs, title)
        player.artist_page_song_menu = Mock()
        player.artist_page_populate_fallback = lambda: Player.artist_page_populate_fallback(player)
        def add_album(album, grid, show_description=False):
            tile = Gtk.Box()
            tile.age_label = Gtk.Label()
            tile.album_description = Gtk.Label()
            grid.add(tile)
        player.add_album_tile = add_album
        try:
            with patch('similar_recommendations.library_catalog', return_value=self.songs):
                Player.show_artist_page(player, 'Artist')
            self.assertEqual(stack.get_visible_child_name(), 'artist')
            self.assertEqual(player.artist_page_title.get_text(), 'Artist')
            self.assertEqual([child.get_child().age_label.get_text()
                              for child in player.artist_page_grid.get_children()], ['2000', '1980', ''])
            player.artist_page_songs.get_children()[0].emit('clicked')
            self.assertEqual(player.play_artist_song.call_args.args[1], 0)
            self.assertEqual(player.play_artist_song.call_args.args[0][0].title, 'Popular')
        finally:
            stack.destroy()

    def test_popular_list_is_limited_to_five(self):
        player = SimpleNamespace(artist_page_songs_title=Gtk.Label(), artist_page_songs=Gtk.Box(),
                                 play_artist_song=Mock(), artist_page_song_menu=Mock())
        songs = [Item('/' + str(i), 'Song ' + str(i)) for i in range(9)]
        try:
            Player.artist_page_set_songs(player, songs, 'Popular songs')
            self.assertEqual(len(player.artist_page_songs.get_children()), 5)
            player.artist_page_songs.get_children()[0].emit('clicked')
            self.assertEqual(len(player.play_artist_song.call_args.args[0]), 5)
        finally:
            player.artist_page_songs.destroy()

    def test_artist_page_uses_canvas_and_preserves_album_interactions(self):
        stack = Gtk.Stack()
        canvas = Gtk.Box()
        canvas.render_surface = Gtk.Box()
        canvas.scrollbar = Gtk.Scrollbar()
        canvas.toggle_album = Mock()
        player = SimpleNamespace(views=stack, album_spacing=20, album_margin=20,
                                 artist_page_back=Mock(), artist_page_fallback_zoom=Mock(),
                                 artist_page_header_allocated=Mock(),
                                 artist_page_canvas_failed=Mock(), show_context_menu=Mock(),
                                 set_placeholder_art=Mock(), button=Mock(),
                                 artist_page_canvas_pressed=Mock())
        def scroll(child):
            widget = Gtk.ScrolledWindow()
            widget.add(child)
            return widget
        player.scroll = scroll
        try:
            with patch('player.sys.platform', 'linux'), \
                 patch('artist_album_canvas.ArtistAlbumCanvas', return_value=canvas):
                Player.ensure_artist_page(player)
            self.assertIs(player.artist_page_canvas, canvas)
            self.assertEqual(player.artist_page_walls.get_visible_child_name(), 'canvas')
            Player.artist_page_canvas_pressed(player, self.albums[0], SimpleNamespace(button=1), 0, 0)
            canvas.toggle_album.assert_called_once_with(self.albums[0])
            Player.artist_page_canvas_pressed(player, self.albums[0], SimpleNamespace(button=3), 0, 0)
            player.show_context_menu.assert_called_once()
        finally:
            stack.destroy()


if __name__ == '__main__':
    unittest.main()
