import io
import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cairo

from next_track_preload import preload_next_art, preload_next_waveform
from player import Player
from plex_client import Item


def png_art():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
    context = cairo.Context(surface)
    context.set_source_rgb(0.8, 0.2, 0.4)
    context.paint()
    output = io.BytesIO()
    surface.write_to_png(output)
    return output.getvalue()


class NextTrackPreloadTests(unittest.TestCase):
    def test_next_art_palette_and_background_are_cached_before_track_switch(self):
        data = png_art()
        cache = SimpleNamespace(
            read_palette=Mock(return_value=None),
            read_art=Mock(return_value=None),
            save_art=Mock(), save_palette=Mock())
        client = SimpleNamespace(get=Mock(return_value=data))
        with patch('next_track_preload.LocalCache', return_value=cache), \
                patch('next_track_preload.cached_gradient') as gradient:
            preload_next_art(client, '/art/next', 'dark', True, (900, 600))
        cache.save_art.assert_called_once_with('/art/next', 1000, data)
        cache.save_palette.assert_called_once()
        self.assertEqual(cache.save_palette.call_args.args[0], '/art/next')
        gradient.assert_called_once()
        self.assertEqual(gradient.call_args.args[:2], (900, 600))

    def test_cached_next_art_and_palette_do_not_fetch_again(self):
        palette = (('#112233', '#334455'), ('#aabbcc', '#ddeeff'))
        cache = SimpleNamespace(
            read_palette=Mock(return_value=palette),
            read_art=Mock(return_value=png_art()),
            save_art=Mock(), save_palette=Mock())
        client = SimpleNamespace(get=Mock())
        with patch('next_track_preload.LocalCache', return_value=cache), \
                patch('next_track_preload.cached_gradient') as gradient:
            preload_next_art(client, '/art/next', 'dark', True, (900, 600))
        client.get.assert_not_called()
        cache.save_art.assert_not_called()
        cache.save_palette.assert_not_called()
        gradient.assert_called_once_with(900, 600, palette[0])

    def test_next_waveform_is_analyzed_only_when_missing(self):
        track = Item('/library/metadata/2', 'Next', duration=120000)
        cache = SimpleNamespace(read_waveform=Mock(return_value=None),
                                save_waveform=Mock())
        client = SimpleNamespace(address='https://plex.example:32400', token='secret',
                                 stream=Mock(return_value='https://plex.example:32400/music'))
        peaks = [0.5] * 512
        with patch('next_track_preload.LocalCache', return_value=cache), \
                patch('next_track_preload.analyze_track_waveform', return_value=peaks) as analyze:
            preload_next_waveform(client, track)
            cache.read_waveform.return_value = peaks
            preload_next_waveform(client, track)
        client.stream.assert_called_once_with(track)
        analyze.assert_called_once()
        cache.save_waveform.assert_called_once_with(track.key, track.duration, peaks)

    def test_next_waveform_uses_server_loudness_before_streaming_audio(self):
        track = Item('/library/metadata/2', 'Next', duration=120000)
        peaks = [.5] * 512
        cache = SimpleNamespace(read_waveform=Mock(return_value=None), save_waveform=Mock())
        client = SimpleNamespace(loudness_waveform=Mock(return_value=peaks), stream=Mock())
        with patch('next_track_preload.LocalCache', return_value=cache), \
                patch('next_track_preload.analyze_track_waveform') as analyze:
            preload_next_waveform(client, track)
        client.loudness_waveform.assert_called_once_with(track)
        client.stream.assert_not_called()
        analyze.assert_not_called()
        cache.save_waveform.assert_called_once_with(track.key, track.duration, peaks)

    def test_queue_change_cancels_old_next_track_work(self):
        current = Item('/library/metadata/1', 'Current')
        next_track = Item('/library/metadata/2', 'Next', duration=120000,
                          thumb='/art/next')
        replacement = Item('/library/metadata/3', 'Replacement')
        jobs = []
        def submit(*args):
            jobs.append(args)
            return Future()
        client = object()
        subject = SimpleNamespace(
            stream_open=True, queue_client=client, queue=[current, next_track],
            index=0, queue_album=None, theme='dark', gradient_enabled=True,
            timeline_waveform_enabled=True, play_generation=4, closed=False,
            shared_background=SimpleNamespace(get_allocated_width=lambda: 900,
                                               get_allocated_height=lambda: 600),
            next_prefetch_target=None, next_art_prefetch_future=None,
            next_wave_prefetch_future=None,
            next_art_workers=SimpleNamespace(submit=submit),
            next_waveform_workers=SimpleNamespace(submit=submit))
        Player.prefetch_next_track(subject)
        self.assertEqual(len(jobs), 2)
        self.assertFalse(jobs[0][-1]())
        subject.queue[1] = replacement
        self.assertTrue(jobs[0][-1]())
        Player.prefetch_next_track(subject)
        self.assertTrue(subject.next_art_prefetch_future is not None)
        self.assertEqual(len(jobs), 4)

    def test_resize_warms_new_gradient_without_restarting_waveform_analysis(self):
        current = Item('/library/metadata/1', 'Current')
        next_track = Item('/library/metadata/2', 'Next', duration=120000,
                          thumb='/art/next')
        jobs = []
        def submit(*args):
            jobs.append(args)
            return Future()
        background = SimpleNamespace(get_allocated_width=lambda: 900,
                                     get_allocated_height=lambda: 600)
        subject = SimpleNamespace(
            stream_open=True, queue_client=object(), queue=[current, next_track],
            index=0, queue_album=None, theme='dark', gradient_enabled=True,
            timeline_waveform_enabled=True, play_generation=4, closed=False,
            shared_background=background, next_prefetch_target=None,
            next_art_prefetch_future=None, next_wave_prefetch_future=None,
            next_art_workers=SimpleNamespace(submit=submit),
            next_waveform_workers=SimpleNamespace(submit=submit))
        Player.prefetch_next_track(subject)
        wave_future = subject.next_wave_prefetch_future
        old_art_cancelled = jobs[0][-1]
        background.get_allocated_width = lambda: 1200
        Player.prefetch_next_track(subject)
        self.assertEqual(len(jobs), 3)
        self.assertIs(subject.next_wave_prefetch_future, wave_future)
        self.assertTrue(old_art_cancelled())
        self.assertEqual(jobs[-1][5], (1200, 600))


if __name__ == '__main__':
    unittest.main()
