import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from resize_diagnostics import ResizeDiagnostics, timing_summary


class FakeWidget:
    def connect(self, *_args):
        pass

    def connect_after(self, *_args):
        pass

    def get_allocated_width(self):
        return 800

    def get_allocated_height(self):
        return 600


class FakePlayer(FakeWidget):
    def __init__(self):
        for name in ('content_views', 'grid', 'song_view', 'now_panel', 'player_bar',
                     'seek', 'wave_timeline', 'shared_background'):
            setattr(self, name, FakeWidget())
        self.add_tick_callback = Mock(return_value=17)
        self.remove_tick_callback = Mock()
        self.frosted_bar = SimpleNamespace(refresh=Mock(return_value=True))
        self.refresh_window_shape = Mock(return_value=False)
        self.content_views.get_child_by_name = lambda _name: FakeWidget()
        self.rounded_corners_enabled = True
        self.get_decorated = lambda: False
        self.song_store = []


class ResizeDiagnosticsTests(unittest.TestCase):
    def test_logs_separate_gestures_with_frame_and_draw_samples(self):
        now = [10.0]
        stream = io.StringIO()
        player = FakePlayer()
        with patch.object(ResizeDiagnostics, 'context', return_value={'panel': 'albums'}), \
                patch('resize_diagnostics.GLib.timeout_add', return_value=42), \
                patch('resize_diagnostics.GLib.source_remove') as remove:
            log = ResizeDiagnostics(player, stream, clock=lambda: now[0])
            log.configure(player, SimpleNamespace(width=700, height=600))
            log.draw_begin(player.grid, None, 'album_grid')
            now[0] = 10.004
            log.draw_end(player.grid, None, 'album_grid')
            log.frame(player, None)
            now[0] = 10.024
            log.frame(player, None)
            now[0] = 10.030
            log.configure(player, SimpleNamespace(width=650, height=600))
            now[0] = 10.630
            log.finish()
            record = json.loads(stream.getvalue())
            self.assertEqual(record['start_size'], [800, 600])
            self.assertEqual(record['end_size'], [650, 600])
            self.assertEqual(record['events'], [[0.0, 700, 600], [30.0, 650, 600]])
            self.assertAlmostEqual(record['draw_summary']['album_grid']['max_ms'], 4.0)
            self.assertAlmostEqual(record['frame_gap_summary']['max_ms'], 20.0)
            self.assertEqual(record['context_end'], {'panel': 'albums'})
            self.assertNotIn('started_monotonic', record)
            remove.assert_called_with(42)
            player.remove_tick_callback.assert_called_once_with(17)
            log.close()

    def test_move_without_resize_does_not_start_logging(self):
        player = FakePlayer()
        log = ResizeDiagnostics(player, io.StringIO())
        self.assertFalse(log.configure(player, SimpleNamespace(width=800, height=600)))
        self.assertIsNone(log.session)
        player.add_tick_callback.assert_not_called()
        log.close()

    def test_close_flushes_unfinished_gesture(self):
        stream = Mock()
        player = FakePlayer()
        with patch.object(ResizeDiagnostics, 'context', return_value={}), \
                patch('resize_diagnostics.GLib.timeout_add', return_value=42), \
                patch('resize_diagnostics.GLib.source_remove'):
            log = ResizeDiagnostics(player, stream, clock=lambda: 10)
            log.configure(player, SimpleNamespace(width=700, height=600))
            log.close()
        record = json.loads(stream.write.call_args.args[0])
        self.assertEqual(record['duration_ms'], 0)
        stream.close.assert_called_once()

    def test_timing_summary_uses_nearest_rank_p95(self):
        self.assertEqual(timing_summary([]), {'count': 0})
        summary = timing_summary(list(range(1, 21)))
        self.assertEqual((summary['count'], summary['p95_ms'], summary['max_ms']), (20, 19, 20))

    def test_context_uses_counts_and_never_reads_track_or_credentials(self):
        player = FakePlayer()
        player.content_views.get_visible_child_name = lambda: 'albums'
        player.timeline_stack = SimpleNamespace(get_visible_child_name=lambda: 'waveform')
        player.frosted_player_bar = True
        player.theme = 'dark'
        player.grid.get_children = lambda: [object(), object()]
        player.song_store = ['private track title']
        player.client = SimpleNamespace(address='private server', token='private token')
        log = ResizeDiagnostics(player, io.StringIO())
        result = json.dumps(log.context())
        self.assertNotIn('private', result)
        self.assertEqual(json.loads(result)['album_tiles'], 2)
        self.assertEqual(json.loads(result)['library_rows'], 1)
        log.close()

    def test_frosted_refresh_is_measured_and_restored(self):
        player = FakePlayer()
        original = player.frosted_bar.refresh
        now = [10.0]
        with patch.object(ResizeDiagnostics, 'context', return_value={}), \
                patch('resize_diagnostics.GLib.timeout_add', return_value=42), \
                patch('resize_diagnostics.GLib.source_remove'):
            stream = io.StringIO()
            log = ResizeDiagnostics(player, stream, clock=lambda: now[0])
            log.configure(player, SimpleNamespace(width=700, height=600))
            self.assertTrue(player.frosted_bar.refresh())
            now[0] = 10.7
            log.finish()
            self.assertEqual(json.loads(stream.getvalue())['draw_summary']['frosted_refresh']['count'], 1)
            log.close()
        self.assertIs(player.frosted_bar.refresh, original)

    def test_heartbeat_records_loop_delays_and_row_counts(self):
        player = FakePlayer()
        now = [10.0]
        player.song_store = [object(), object()]
        with patch.object(ResizeDiagnostics, 'context', return_value={}), \
                patch('resize_diagnostics.GLib.timeout_add', return_value=42), \
                patch('resize_diagnostics.GLib.source_remove'):
            stream = io.StringIO()
            log = ResizeDiagnostics(player, stream, clock=lambda: now[0])
            log.configure(player, SimpleNamespace(width=700, height=600))
            now[0] = 10.120
            self.assertTrue(log.heartbeat())
            log.configure(player, SimpleNamespace(width=650, height=600))
            log.finish()
            record = json.loads(stream.getvalue())
            self.assertEqual(record['heartbeat'], [[120.0, 120.0, 700, 600, 2]])
            self.assertEqual(record['heartbeat_gap_summary']['max_ms'], 120.0)
            log.close()


if __name__ == '__main__':
    unittest.main()
