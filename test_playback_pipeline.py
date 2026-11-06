import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from concurrent.futures import Future, ThreadPoolExecutor

from playback_pipeline import PlaybackPipeline
from player import Player


class PlaybackPipelineTests(unittest.TestCase):
    def test_blocking_stop_does_not_block_caller_and_open_follows_it(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        def set_state(state):
            calls.append(('state', state))
            if state == 'stop':
                entered.set()
                release.wait(timeout=2)
        pipeline = SimpleNamespace(set_state=set_state,
                                   set_property=lambda name, value: calls.append((name, value)))
        controller = PlaybackPipeline(pipeline)
        try:
            self.assertTrue(controller.set_state('stop'))
            self.assertTrue(entered.wait(timeout=1))
            self.assertTrue(controller.busy())
            self.assertTrue(controller.open('track', 'play'))
            self.assertEqual(calls, [('state', 'stop')])
            release.set()
            controller.executor.submit(lambda: None).result(timeout=2)
            self.assertEqual(calls, [('state', 'stop'), ('uri', 'track'), ('state', 'play')])
            self.assertFalse(controller.busy())
        finally:
            release.set()
            controller.shutdown('stop')

    def test_stale_open_is_skipped_before_a_new_track(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def stop(state):
            calls.append(state)
            if state == 'block':
                entered.set()
                release.wait(timeout=2)
        pipeline = SimpleNamespace(set_state=stop, set_property=lambda _name, value: calls.append(value))
        controller = PlaybackPipeline(pipeline)
        try:
            controller.set_state('block')
            self.assertTrue(entered.wait(timeout=1))
            controller.open('old', 'play-old', valid=lambda: False)
            controller.open('new', 'play-new')
            release.set()
            controller.executor.submit(lambda: None).result(timeout=2)
            self.assertEqual(calls, ['block', 'new', 'play-new'])
        finally:
            release.set()
            controller.shutdown('stop')

    def test_tick_does_not_query_pipeline_during_transition(self):
        pipeline = Mock()
        player = SimpleNamespace(closed=False, playback_controller=SimpleNamespace(busy=lambda: True),
                                 pipeline=pipeline, apply_pending_resume_seek=Mock())
        self.assertTrue(Player.tick(player))
        pipeline.query_position.assert_not_called()
        pipeline.query_duration.assert_not_called()
        player.apply_pending_resume_seek.assert_not_called()

    def test_tick_does_not_wait_for_blocked_pipeline_query(self):
        entered, release = threading.Event(), threading.Event()
        def query(_format):
            entered.set()
            release.wait(timeout=2)
            return False, 0
        pipeline = SimpleNamespace(query_duration=query, query_position=query,
                                   get_state=lambda _timeout: (None, None, None))
        with ThreadPoolExecutor(max_workers=1) as workers:
            player = SimpleNamespace(closed=False, playback_controller=SimpleNamespace(busy=lambda: False),
                                     pipeline=pipeline, apply_pending_resume_seek=Mock(),
                                     playback_poll_workers=workers, playback_poll_future=None,
                                     stream_open=True, play_generation=1, timeline_base_time=1.,
                                     queue=[], remote_receiver=None,
                                     finish_playback_poll=Mock())
            with patch('player.GLib.idle_add'):
                try:
                    self.assertTrue(Player.tick(player))
                    self.assertTrue(entered.wait(timeout=1))
                    self.assertTrue(Player.tick(player))
                finally:
                    release.set()
                    player.playback_poll_future.result(timeout=2)
                    workers.submit(lambda: None).result(timeout=2)

    def test_late_poll_does_not_overwrite_new_track_or_seek(self):
        future = Future()
        future.set_result((True, 120, True, 10, None))
        player = SimpleNamespace(playback_poll_future=future, closed=False,
                                 play_generation=2, timeline_base_time=20.,
                                 playback_controller=SimpleNamespace(busy=lambda: False))
        self.assertFalse(Player.finish_playback_poll(player, 1, 20., future))
        self.assertIsNone(player.playback_poll_future)
        player.playback_poll_future = future
        self.assertFalse(Player.finish_playback_poll(player, 2, 10., future))
        self.assertIsNone(player.playback_poll_future)

    def test_transition_errors_do_not_leave_controller_busy(self):
        failed = threading.Event()
        pipeline = SimpleNamespace(set_state=Mock(side_effect=RuntimeError('device error')))
        controller = PlaybackPipeline(pipeline, on_error=failed.set)
        try:
            self.assertTrue(controller.set_state('play'))
            self.assertTrue(failed.wait(timeout=1))
            controller.executor.submit(lambda: None).result(timeout=2)
            self.assertFalse(controller.busy())
        finally:
            controller.shutdown('stop')


if __name__ == '__main__':
    unittest.main()
