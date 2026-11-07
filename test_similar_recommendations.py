import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import lastfm
from plex_client import Item
import similar_recommendations as similar
from player import Player


class SimilarRecommendationTests(unittest.TestCase):
    def setUp(self):
        similar._CACHE.clear()

    def test_lastfm_matches_only_library_and_excludes_played_tracks(self):
        seed = Item('1', 'Seed', artist='Seed Artist')
        songs = [Item('2', 'First', artist='Björk', album='One'),
                 Item('3', 'Second', artist='Other', album='Two'),
                 Item('4', 'Third', artist='Third', album='Three')]
        response = {'similartracks': {'track': [
            {'name': 'FIRST', 'artist': {'name': 'BJÖRK'}},
            {'name': 'Second', 'artist': {'name': 'Other'}},
            {'name': 'Missing', 'artist': {'name': 'Nobody'}},
            {'name': 'Third', 'artist': {'name': 'Third'}},
            {'name': 'Third', 'artist': {'name': 'Third'}}]}}
        api = SimpleNamespace(request=Mock(return_value=response))
        client = SimpleNamespace(is_local=True, recommendation_catalog=lambda: songs)
        with patch.object(similar.lastfm, 'LastFM', return_value=api):
            found = similar.similar_tracks(client, '1', seed, ('key', 'secret'), excluded={'3'})
            self.assertEqual([s.key for s in found], ['2', '4'])
            similar.similar_tracks(client, '1', seed, ('key', 'secret'))
        api.request.assert_called_once_with('track.getSimilar', {
            'artist': 'Seed Artist', 'track': 'Seed', 'autocorrect': 1, 'limit': 200})

    def test_missing_credentials_or_bad_response_does_not_fetch_catalog(self):
        seed = Item('1', 'Seed', artist='Artist')
        client = SimpleNamespace(is_local=True, recommendation_catalog=Mock())
        self.assertEqual(similar.similar_tracks(client, '1', seed, None), [])
        with patch.object(similar.lastfm, 'LastFM', return_value=SimpleNamespace(request=lambda *_: {})):
            self.assertEqual(similar.similar_tracks(client, '1', seed, ('key', 'secret')), [])
        client.recommendation_catalog.assert_not_called()

    def test_plex_catalog_reuses_cache_or_pages_server(self):
        client = SimpleNamespace(songs=Mock(side_effect=[([Item('a', 'A')], 2), ([Item('b', 'B')], 2)]))
        cache = SimpleNamespace(read_song_index=Mock(return_value=None))
        with patch.object(similar, 'LocalCache', return_value=cache):
            self.assertEqual([s.key for s in similar.library_catalog(client, '2')], ['a', 'b'])
        self.assertEqual(client.songs.call_count, 2)
        cache.read_song_index.return_value = [Item('c', 'C')]
        with patch.object(similar, 'LocalCache', return_value=cache):
            self.assertEqual(similar.library_catalog(client, '2')[0].key, 'c')
        self.assertEqual(client.songs.call_count, 2)

    def test_local_context_action_queues_online_matches(self):
        seed = Item('1', 'Seed', artist='A')
        match = Item('2', 'Match', artist='B')
        added = []
        client = SimpleNamespace(is_local=True)
        player = SimpleNamespace(client=client, library=SimpleNamespace(get_active_id=lambda: '1'),
                                 queue=[seed], status=SimpleNamespace(set_text=Mock()),
                                 async_work=lambda work, done, valid: done(work()) if valid() else None,
                                 enqueue_tracks=added.append)
        with patch('player.lastfm.application_credentials', return_value=('key', 'secret')), \
             patch('player.lastfm_similar_tracks', return_value=[match]):
            Player.enqueue_similar_songs(player, seed)
        self.assertEqual(added, [[match]])

    def test_local_queue_continuation_uses_online_results_and_excludes_history(self):
        seed = Item('1', 'Seed', artist='A')
        previous = Item('2', 'Previous', artist='C')
        match = Item('3', 'Match', artist='B')
        client = SimpleNamespace(is_local=True)
        player = SimpleNamespace(
            client=client, queue_client=client, library=SimpleNamespace(get_active_id=lambda: '1'),
            queue=[seed], index=0, play_history=[previous], play_generation=1,
            style_autoplay_pending=False, style_autoplay_waiting=False,
            style_autoplay_exhausted=False, style_autoplay_generation=0,
            keep_style_playing_enabled=True, auto_style_facet=None, auto_style_keys=set(),
            queue_album=None, remote_queue_id='', remote_container='', remote_queue_version='',
            remote_item_ids=(), async_work=lambda work, done, valid, _failed: done(work()) if valid() else None,
            pulse_queue_icon=Mock(), refresh_queue_view=Mock(), mpris=SimpleNamespace(changed=Mock()),
            persist_session=Mock(), status=SimpleNamespace(set_text=Mock()))
        with patch('player.lastfm.application_credentials', return_value=('key', 'secret')), \
             patch('player.lastfm_similar_tracks', return_value=[match]) as lookup:
            Player.extend_queue_same_style(player)
        self.assertEqual(player.queue, [seed, match])
        self.assertEqual(lookup.call_args.args[4], {'1', '2'})
        self.assertFalse(player.style_autoplay_pending)

    def test_lastfm_error_falls_back_to_plex(self):
        seed = Item('/library/metadata/1', 'Seed', artist='A')
        match = Item('/library/metadata/2', 'Match', artist='B')
        added = []
        client = SimpleNamespace(nearest_tracks=lambda *_args, **_kw: [match],
                                 metadata_similar_tracks=lambda *_args, **_kw: [])
        player = SimpleNamespace(client=client, library=SimpleNamespace(get_active_id=lambda: '2'),
                                 queue=[], status=SimpleNamespace(set_text=Mock()),
                                 async_work=lambda work, done, valid: done(work()), enqueue_tracks=added.append)
        with patch('player.lastfm.application_credentials', return_value=('key', 'secret')), \
             patch('player.lastfm_similar_tracks', side_effect=lastfm.LastFMError('offline')):
            Player.enqueue_similar_songs(player, seed)
        self.assertEqual(added, [[match]])


if __name__ == '__main__':
    unittest.main()
