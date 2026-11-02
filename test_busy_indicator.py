import unittest
from unittest.mock import Mock, patch

from busy_indicator import BusyIndicator


class BusyIndicatorTests(unittest.TestCase):
    @patch('busy_indicator.GLib.source_remove')
    @patch('busy_indicator.GLib.timeout_add', return_value=17)
    def test_short_work_never_shows_spinner(self, timer, remove):
        spinner = Mock()
        indicator = BusyIndicator(spinner)
        indicator.begin()
        timer.assert_called_once_with(2000, indicator._reveal)
        indicator.end()
        remove.assert_called_once_with(17)
        spinner.show.assert_not_called()
        spinner.start.assert_not_called()

    @patch('busy_indicator.GLib.timeout_add', return_value=17)
    def test_overlapping_work_keeps_spinner_until_all_complete(self, timer):
        spinner = Mock()
        indicator = BusyIndicator(spinner)
        indicator.begin()
        indicator.begin()
        timer.assert_called_once()
        indicator._reveal()
        spinner.show.assert_called_once()
        indicator.end()
        spinner.hide.assert_not_called()
        indicator.end()
        spinner.stop.assert_called_once()
        spinner.hide.assert_called_once()

    @patch('busy_indicator.GLib.source_remove')
    @patch('busy_indicator.GLib.timeout_add', return_value=17)
    def test_close_cancels_pending_timer(self, _timer, remove):
        spinner = Mock()
        indicator = BusyIndicator(spinner)
        indicator.begin()
        indicator.close()
        remove.assert_called_once_with(17)
        indicator._reveal()
        spinner.show.assert_not_called()


if __name__ == '__main__':
    unittest.main()
