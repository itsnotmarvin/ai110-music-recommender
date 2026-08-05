import json
from urllib.parse import parse_qs, urlparse

from src.apple_music import LibraryTrack
from src.demo_data import DemoSimilarityClient, demo_apple_music_export
from src.playlist_recommender import (
    CandidateSignals,
    HybridPlaylistRecommender,
    LastfmClient,
    SimilarTrack,
    rank_playlist_candidates,
    select_diverse_seeds,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_lastfm_adapter_parses_listening_similarity_and_tags():
    def opener(request, timeout):
        assert timeout == 10.0
        method = parse_qs(urlparse(request.full_url).query)["method"][0]
        if method == "track.getSimilar":
            return FakeResponse(
                {
                    "similartracks": {
                        "track": [
                            {
                                "name": "Candidate Song",
                                "artist": {"name": "Candidate Artist"},
                                "match": "0.87",
                                "url": "https://www.last.fm/music/candidate",
                            }
                        ]
                    }
                }
            )
        return FakeResponse(
            {"toptags": {"tag": [{"name": "sad"}, {"name": "indie"}]}}
        )

    client = LastfmClient("test-key", opener=opener)

    similar = client.similar_tracks("Seed Artist", "Seed Song")
    tags = client.top_tags("Seed Artist", "Seed Song")

    assert similar == [
        SimilarTrack(
            "Candidate Song",
            "Candidate Artist",
            0.87,
            "https://www.last.fm/music/candidate",
        )
    ]
    assert tags == ["sad", "indie"]


def test_seed_selection_prefers_distinct_artists():
    tracks = [
        LibraryTrack("1", "A1", "Artist A", "Album", "Pop"),
        LibraryTrack("2", "A2", "Artist A", "Album", "Pop"),
        LibraryTrack("3", "B1", "Artist B", "Album", "Pop"),
    ]

    seeds = select_diverse_seeds(tracks, limit=2)

    assert [track.artist for track in seeds] == ["Artist A", "Artist B"]


def test_playlist_ranker_uses_mood_and_multiple_seed_support():
    playlist = [
        LibraryTrack("1", "Blue One", "Artist A", "Album", "Indie"),
        LibraryTrack("2", "Blue Two", "Artist B", "Album", "Indie"),
    ]
    candidates = [
        CandidateSignals(
            "Melancholy",
            "Artist C",
            "https://example.com/c",
            {"Blue One — Artist A": 0.8, "Blue Two — Artist B": 0.7},
            ("sad", "indie"),
        ),
        CandidateSignals(
            "Dancefloor",
            "Artist D",
            "https://example.com/d",
            {"Blue One — Artist A": 0.9},
            ("dance", "party"),
        ),
    ]

    ranked = rank_playlist_candidates(
        candidates,
        playlist_name="Sad Hours",
        playlist_tracks=playlist,
        library_tracks=playlist,
        seed_tags=["sad", "melancholy", "indie"],
        limit=2,
    )

    assert ranked[0].title == "Melancholy"
    assert ranked[0].confidence == "high"
    assert ranked[0].breakdown["mood/category fit"] > 0
    assert ranked[0].breakdown["multi-seed support"] > ranked[1].breakdown[
        "multi-seed support"
    ]


def test_playlist_ranker_excludes_tracks_already_in_playlist():
    playlist = [LibraryTrack("1", "Existing", "Artist A", "Album", "Rock")]
    candidate = CandidateSignals(
        "Existing",
        "Artist A",
        "https://example.com/existing",
        {"Existing — Artist A": 1.0},
        ("rock",),
    )

    assert not rank_playlist_candidates(
        [candidate],
        playlist_name="Rock",
        playlist_tracks=playlist,
        library_tracks=playlist,
    )


def test_hybrid_recommender_aggregates_the_same_candidate_across_seeds():
    class FakeClient:
        def similar_tracks(self, artist, title, limit=12):
            return [
                SimilarTrack(
                    "Shared Candidate",
                    "New Artist",
                    0.8,
                    "https://example.com/shared",
                )
            ]

        def top_tags(self, artist, title, limit=8):
            return ["sad", "indie"]

    playlist = [
        LibraryTrack("1", "Seed One", "Artist A", "Album", "Indie"),
        LibraryTrack("2", "Seed Two", "Artist B", "Album", "Indie"),
    ]

    results = HybridPlaylistRecommender(FakeClient()).recommend(
        "Sad Hours", playlist, playlist, limit=1
    )

    assert results[0].title == "Shared Candidate"
    assert len(results[0].supporting_seeds) == 2
    assert "sad" in results[0].tags


def test_stakeholder_demo_runs_the_real_hybrid_ranker_without_a_key():
    export = demo_apple_music_export()
    playlist = export.playlists[0]

    results = HybridPlaylistRecommender(DemoSimilarityClient()).recommend(
        playlist.name,
        export.tracks_for(playlist),
        export.tracks,
        limit=5,
    )

    assert len(results) == 5
    assert results[0].title == "Japanese Denim"
    assert len(results[0].supporting_seeds) >= 2
    assert results[0].breakdown["mood/category fit"] > 0
