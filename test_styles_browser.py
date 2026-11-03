import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk

from music_facets import MusicFacet
from player import Player


class StylesBrowserTests(unittest.TestCase):
    def test_browser_hides_category_count_when_facets_are_present(self):
        facet = MusicFacet('mood', 'Dreamy', (('track.mood', 7),))
        status = Gtk.Label(label='Loading')
        status.show()
        player = SimpleNamespace(
            style_grid=SimpleNamespace(get_children=lambda: []),
            style_mode_buttons={'mood': Gtk.Button(), 'style': Gtk.Button()},
            style_mode='mood', styles_facets=[facet],
            style_search=SimpleNamespace(get_text=lambda: ''),
            styles_rows_source=None, style_status=status, add_style_tiles=Mock())
        Player.render_styles_browser(player)
        self.assertFalse(status.get_visible())
        self.assertEqual(player.styles_visible_facets, [facet])
        player.add_style_tiles.assert_called_once_with()

    def test_tile_click_opens_album_grid_and_banner_has_no_buttons(self):
        facet = MusicFacet('mood', 'Dreamy', (('track.mood', 7),))
        player = SimpleNamespace(open_style_results=Mock(),
                                 draw_style_tile_art=Mock(return_value=False))
        player.style_facet_pressed = lambda widget, event, item: Player.style_facet_pressed(
            player, widget, event, item)
        tile = Player.make_style_tile(player, facet)
        overlay = tile.get_child()
        children = overlay.get_children()
        self.assertEqual(len(children), 2)
        banner = children[1]
        self.assertEqual(banner.get_name(), 'style-facet-banner')
        self.assertEqual(banner.get_halign(), Gtk.Align.FILL)
        self.assertEqual(banner.get_children()[0].get_text(), 'Dreamy')
        self.assertTrue(tile.get_above_child())
        window = Gtk.OffscreenWindow()
        window.add(tile)
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
        event.window = tile.get_window()
        event.send_event = True
        event.button = 1
        event.x = event.y = 112
        try:
            self.assertTrue(tile.event(event))
            player.open_style_results.assert_called_once_with(tile, facet, 'albums')
        finally:
            window.destroy()

    def test_category_title_identifies_kind_in_both_album_and_track_views(self):
        player = SimpleNamespace(style_result_facet=MusicFacet(
            'mood', 'Dreamy', (('track.mood', 7),)),
            style_result_songs=None, style_album_filter=None,
            style_result_title=Mock(), style_back_button=Mock())
        Player.render_style_results(player)
        player.style_result_title.set_text.assert_called_with('Dreamy Mood')
        player.style_result_facet = MusicFacet('style', 'Jazz', (('artist.style', 8),))
        player.style_album_filter = SimpleNamespace(title='Record')
        Player.render_style_results(player)
        player.style_result_title.set_text.assert_called_with('Jazz Style · Record')


if __name__ == '__main__':
    unittest.main()
