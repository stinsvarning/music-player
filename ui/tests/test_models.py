import unittest

from datetime import date

from music_player.models import (
    BrowseState,
    SeekGate,
    Track,
    can_autoselect_playlist,
    default_queue_playlist_name,
    format_time,
    is_library_stale_error,
    is_login_error,
    lyric_lines,
    login_status_text,
    LIBRARY_STALE_NOTICE,
    page_done,
    parse_playlists,
    parse_status,
    parse_track,
    playback_word,
    playlist_is_editable,
    playlist_menu_actions,
    should_apply_engine_rating,
    song_menu_actions,
    tracks_caption,
)


class SeekGateTests(unittest.TestCase):
    def test_release_emits_absolute_seconds(self):
        gate = SeekGate()
        gate.drag(12.0, now=1.0)
        gate.drag(90.0, now=1.1)
        self.assertAlmostEqual(gate.release(current=10.0, now=1.2), 90.0)
        self.assertIsNone(gate.release(now=1.3))

    def test_take_settled_waits_then_commits(self):
        gate = SeekGate(settle_s=0.12, ignore_s=0.45)
        gate.drag(40.0, now=10.0)
        self.assertIsNone(gate.take_settled(now=10.05))
        self.assertAlmostEqual(gate.take_settled(now=10.13), 40.0)
        self.assertIsNone(gate.take_settled(now=10.20))

    def test_status_ignored_while_dragging_and_just_after_commit(self):
        gate = SeekGate(settle_s=0.12, ignore_s=0.45)
        self.assertTrue(gate.follow_status(now=0.0))
        gate.drag(30.0, now=1.0)
        self.assertFalse(gate.follow_status(now=1.05))
        gate.release(now=1.2)
        self.assertFalse(gate.follow_status(now=1.3))
        self.assertTrue(gate.follow_status(now=1.66))


class LoginErrorTests(unittest.TestCase):
    def test_detects_login_required(self):
        self.assertTrue(is_login_error("LOGIN_REQUIRED: log in to YouTube Music"))
        self.assertTrue(is_login_error("no YouTube cookies — open Zen"))
        self.assertFalse(is_login_error("playlist is empty"))
        self.assertFalse(is_login_error(""))
        self.assertTrue(is_library_stale_error("LOGIN_REQUIRED: expired"))
        self.assertTrue(is_library_stale_error("status code 401"))
        self.assertFalse(is_library_stale_error("playlist is empty"))
        self.assertEqual(LIBRARY_STALE_NOTICE, "session expired — refreshing…")

    def test_login_status_shows_engine_hint(self):
        self.assertIn(
            "yt-dlp",
            login_status_text(
                {"logged_in": False, "error": "LOGIN_REQUIRED: Install yt-dlp to read Chromium cookies."},
            ),
        )
        self.assertEqual(
            login_status_text({"logged_in": False, "error": "LOGIN_REQUIRED"}),
            "Still signed out. Finish Google sign-in in the browser.",
        )


class BrowseStateTests(unittest.TestCase):
    def test_selecting_a_playlist_clears_search_results(self):
        pane = BrowseState()
        pane.finish_search(pane.begin_search(), [Track(id="s1", title="search hit")])
        self.assertEqual(pane.visible()[0].id, "s1")
        gen = pane.select_playlist()
        self.assertIsNone(pane.search_tracks)
        pane.finish_playlist(gen, [Track(id="p1", title="playlist song")])
        self.assertEqual(pane.visible()[0].id, "p1")

    def test_stale_search_cannot_overwrite_a_later_playlist(self):
        pane = BrowseState()
        stale = pane.begin_search()
        live = pane.select_playlist()
        self.assertFalse(pane.finish_search(stale, [Track(id="s1", title="late")]))
        self.assertTrue(pane.finish_playlist(live, [Track(id="p1", title="ok")]))
        self.assertEqual(pane.visible()[0].id, "p1")

    def test_finish_playlist_can_append_a_later_page(self):
        pane = BrowseState()
        gen = pane.select_playlist()
        self.assertTrue(pane.finish_playlist(gen, [Track(id="a", title="One")]))
        self.assertTrue(pane.finish_playlist(gen, [Track(id="b", title="Two")], append=True))
        self.assertEqual([t.id for t in pane.visible()], ["a", "b"])

    def test_finish_search_can_append_a_later_page(self):
        pane = BrowseState()
        gen = pane.begin_search()
        self.assertTrue(pane.finish_search(gen, [Track(id="s1", title="One")]))
        self.assertTrue(pane.finish_search(gen, [Track(id="s2", title="Two")], append=True))
        self.assertEqual([t.id for t in pane.visible()], ["s1", "s2"])

    def test_open_playlist_drops_search_hits_immediately(self):
        pane = BrowseState()
        pane.finish_search(pane.begin_search(), [Track(id="s1", title="hit")])
        pane.lib_tracks = [Track(id="old", title="stale")]
        pane.open_playlist()
        self.assertEqual(pane.visible(), [])
        self.assertIsNone(pane.search_tracks)

    def test_autoselect_skips_while_searching(self):
        self.assertTrue(can_autoselect_playlist(first=True, searching=False))
        self.assertFalse(can_autoselect_playlist(first=True, searching=True))
        self.assertFalse(can_autoselect_playlist(first=False, searching=False))

    def test_tracks_caption_restores_playlist_name(self):
        self.assertEqual(tracks_caption(query="hello"), "SEARCH · hello")
        self.assertEqual(tracks_caption(playlist_name="Liked Music"), "LIKED MUSIC")
        self.assertEqual(tracks_caption(), "TRACKS")


class QueueUpdateTests(unittest.TestCase):
    def test_same_ids_do_not_need_rebuild(self):
        from music_player.models import queue_needs_rebuild

        self.assertFalse(queue_needs_rebuild(["a", "b", "c"], ["a", "b", "c"]))
        self.assertTrue(queue_needs_rebuild(["a", "b"], ["a", "c"]))
        self.assertTrue(queue_needs_rebuild(["a"], ["a", "b"]))

    def test_default_queue_playlist_name_uses_the_date(self):
        self.assertEqual(default_queue_playlist_name(date(2026, 8, 15)), "Queue 2026-08-15")


class FormatTimeTests(unittest.TestCase):
    def test_minutes(self):
        self.assertEqual(format_time(205), "3:25")
        self.assertEqual(format_time(0), "0:00")
        self.assertEqual(format_time(None), "0:00")


class StatusParseTests(unittest.TestCase):
    def test_playing_status(self):
        st = parse_status(
            {
                "ok": True,
                "state": "playing",
                "position": 11.6,
                "duration": 205,
                "volume": 70,
                "index": 0,
                "total": 1,
                "shuffle": False,
                "repeat": "off",
                "eq_preset": "Warm",
                "eq_bands": [5, 4, 2, -1, -2, 2, 4, 5, 5, 5],
                "logged_in": True,
                "auth_source": "firefox:~/.config/zen",
                "track": {
                    "id": "abc",
                    "title": "My Name Is Jonas",
                    "artist": "Weezer",
                    "duration_secs": 205,
                },
            }
        )
        self.assertEqual(st.state, "playing")
        self.assertEqual(st.track.title, "My Name Is Jonas")
        self.assertEqual(st.track.id, "abc")
        self.assertEqual(len(st.eq_bands), 10)
        self.assertFalse(st.automix)
        self.assertTrue(st.logged_in)
        self.assertEqual(st.auth_source, "firefox:~/.config/zen")
        self.assertEqual(playback_word(st.state), "playing")
        self.assertEqual(playback_word("paused"), "paused")
        self.assertEqual(playback_word("stopped"), "stopped")
        self.assertEqual(playback_word(""), "stopped")

    def test_parse_track_keeps_playable_flag(self):
        self.assertTrue(parse_track({"id": "a", "title": "ok"}).playable)
        self.assertFalse(parse_track({"id": "b", "title": "no", "playable": False}).playable)

    def test_playlists(self):
        lists = parse_playlists(
            {"playlists": [{"id": "LM", "name": "Liked Music", "track_count": 12}]}
        )
        self.assertEqual(lists[0].id, "LM")
        self.assertEqual(lists[0].track_count, 12)

    def test_flattens_innertube_text_objects(self):
        lists = parse_playlists(
            {
                "playlists": [
                    {
                        "id": "VLLM",
                        "name": {"text": "Liked Music", "runs": [{"text": "Liked Music"}]},
                        "track_count": 3,
                    }
                ]
            }
        )
        self.assertEqual(lists[0].name, "Liked Music")


class PageDoneTests(unittest.TestCase):
    def test_missing_done_means_complete(self):
        self.assertTrue(page_done({"playlists": []}))
        self.assertTrue(page_done(None))

    def test_done_false_means_more_pages(self):
        self.assertFalse(page_done({"done": False, "playlists": []}))
        self.assertTrue(page_done({"done": True}))


class LyricLineTests(unittest.TestCase):
    def test_lines_are_plain_text_and_timing_is_ignored(self):
        payload = {
            "found": True,
            "text": "one\ntwo",
            "lines": [
                {"text": "one", "start": 1.5},
                {"text": "two", "start": 4},
            ],
        }
        self.assertEqual(lyric_lines(payload), ["one", "two"])

    def test_falls_back_to_the_text_block(self):
        self.assertEqual(lyric_lines({"text": "a\nb"}), ["a", "b"])
        self.assertEqual(lyric_lines(None), [])
        self.assertEqual(lyric_lines({"lines": ["x", {"text": "y"}]}), ["x", "y"])

    def test_blank_rows_stay_so_verse_gaps_remain(self):
        self.assertEqual(lyric_lines({"lines": [{"text": "verse"}, {"text": ""}, {"text": "chorus"}]}), ["verse", "", "chorus"])


class SongMenuTests(unittest.TestCase):
    def test_library_keeps_queue_actions(self):
        self.assertEqual(
            song_menu_actions("library"),
            ["Start mix", "Play next", "Add to queue", "Save this track…"],
        )

    def test_queue_drops_duplicate_queue_actions(self):
        self.assertEqual(
            song_menu_actions("queue"),
            ["Start mix", "Save this track…", "Save entire queue…", "Remove"],
        )


class PlaylistMenuTests(unittest.TestCase):
    def test_user_playlists_can_be_renamed(self):
        self.assertTrue(playlist_is_editable("PL123"))
        self.assertTrue(playlist_is_editable("VLPL123"))
        self.assertFalse(playlist_is_editable("LM"))
        self.assertFalse(playlist_is_editable("VLLM"))
        self.assertFalse(playlist_is_editable("RDAMPLPL123"))

    def test_system_playlists_only_start_a_mix(self):
        self.assertEqual(playlist_menu_actions("LM"), ["Start mix"])
        self.assertEqual(
            playlist_menu_actions("VLPL123"),
            ["Start mix", "Rename…", "Delete…"],
        )


class StatusRatingTests(unittest.TestCase):
    def test_parse_status_keeps_like_state(self):
        status = parse_status({"ok": True, "liked": True, "disliked": False, "track": {"id": "a"}})
        self.assertTrue(status.liked)
        self.assertFalse(status.disliked)
        self.assertTrue(status.track.liked)

    def test_parse_status_unknown_rating_stays_unset(self):
        status = parse_status({"ok": True, "track": {"id": "a"}})
        self.assertIsNone(status.liked)
        self.assertIsNone(status.disliked)

    def test_engine_rating_is_ignored_while_a_click_is_in_flight(self):
        self.assertFalse(should_apply_engine_rating(hold_until=10.0, now=9.5))
        self.assertTrue(should_apply_engine_rating(hold_until=10.0, now=10.0))
        self.assertTrue(should_apply_engine_rating(hold_until=0.0, now=1.0))


if __name__ == "__main__":
    unittest.main()


