import plistlib
from datetime import datetime, timezone

import pytest

from src.apple_music import (
    AppleMusicImportError,
    LibraryTrack,
    analyze_library,
    parse_apple_music_export,
    parse_apple_music_xml,
    recommend_from_library,
)
from src.demo_data import DEMO_PLAYLIST_NAME, demo_apple_music_export


def test_demo_export_exercises_personalization_and_playlist_continuation():
    export = demo_apple_music_export()

    assert len(export.tracks) == 6
    assert [playlist.name for playlist in export.playlists] == [DEMO_PLAYLIST_NAME]
    assert len(export.tracks_for(export.playlists[0])) == 6
    assert analyze_library(export.tracks).top_artists[0][0] == "Frank Ocean"


def test_parse_apple_music_xml_keeps_only_needed_music_metadata():
    payload = plistlib.dumps(
        {
            "Major Version": 1,
            "Music Folder": "file:///Users/private/Music/",
            "Tracks": {
                "1": {
                    "Track ID": 1,
                    "Persistent ID": "ABC123",
                    "Name": "Old Favorite",
                    "Artist": "Example Artist",
                    "Album": "Example Album",
                    "Genre": "Alternative",
                    "Kind": "Apple Music AAC audio file",
                    "Play Count": 18,
                    "Skip Count": 1,
                    "Rating": 80,
                    "Date Added": datetime(2022, 1, 1),
                    "Play Date UTC": datetime(2025, 1, 10),
                    "Location": "file:///Users/private/Music/song.m4a",
                },
                "2": {
                    "Track ID": 2,
                    "Name": "A Music Video",
                    "Artist": "Example Artist",
                    "Kind": "MPEG-4 video file",
                },
            },
            "Playlists": [
                {
                    "Name": "Sad Hours",
                    "Playlist Persistent ID": "PLAYLIST1",
                    "Playlist Items": [{"Track ID": 1}, {"Track ID": 2}],
                },
                {
                    "Name": "Library",
                    "Master": True,
                    "Playlist Items": [{"Track ID": 1}],
                },
            ],
        }
    )

    export = parse_apple_music_export(payload)
    tracks = parse_apple_music_xml(payload)

    assert len(tracks) == 1
    assert tracks[0].library_id == "ABC123"
    assert tracks[0].title == "Old Favorite"
    assert tracks[0].play_count == 18
    assert tracks[0].last_played == datetime(2025, 1, 10, tzinfo=timezone.utc)
    assert not hasattr(tracks[0], "location")
    assert [playlist.name for playlist in export.playlists] == ["Sad Hours"]
    assert [track.title for track in export.tracks_for(export.playlists[0])] == [
        "Old Favorite"
    ]


def test_parse_apple_music_xml_rejects_non_library_documents():
    with pytest.raises(AppleMusicImportError, match="Tracks"):
        parse_apple_music_xml(plistlib.dumps({"Playlists": []}))


def test_analyze_library_uses_play_and_rating_history():
    tracks = [
        LibraryTrack("1", "One", "Artist A", "Album", "Soul", play_count=20),
        LibraryTrack("2", "Two", "Artist B", "Album", "Rock", play_count=2),
        LibraryTrack("3", "Three", "Artist A", "Album", "Soul", rating=100),
    ]

    profile = analyze_library(tracks)

    assert profile.track_count == 3
    assert profile.artist_count == 2
    assert profile.top_artists[0][0] == "Artist A"
    assert profile.top_genres[0][0] == "Soul"


def test_rediscover_prefers_a_familiar_track_with_more_time_away():
    tracks = [
        LibraryTrack(
            "old",
            "Old Favorite",
            "Artist A",
            "Album",
            "Soul",
            play_count=12,
            last_played=datetime(2023, 1, 1, tzinfo=timezone.utc),
        ),
        LibraryTrack(
            "new",
            "Yesterday's Song",
            "Artist A",
            "Album",
            "Soul",
            play_count=14,
            last_played=datetime(2025, 12, 31, tzinfo=timezone.utc),
        ),
    ]

    result = recommend_from_library(
        tracks,
        mode="Rediscover",
        limit=1,
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert result[0].track.title == "Old Favorite"
    assert "days" in " ".join(result[0].reasons)


def test_comfort_and_deep_cut_modes_rank_different_tracks():
    tracks = [
        LibraryTrack("favorite", "Favorite", "Artist", "Album", "Pop", play_count=50),
        LibraryTrack("deep", "Deep Cut", "Artist", "Album", "Pop", play_count=1),
    ]

    comfort = recommend_from_library(tracks, mode="Comfort pick", limit=1)
    deep_cut = recommend_from_library(tracks, mode="Deep cut", limit=1)

    assert comfort[0].track.title == "Favorite"
    assert deep_cut[0].track.title == "Deep Cut"


def test_recommendation_can_be_limited_to_one_library_genre():
    tracks = [
        LibraryTrack("1", "One", "Artist", "Album", "Jazz", play_count=5),
        LibraryTrack("2", "Two", "Artist", "Album", "Rock", play_count=100),
    ]

    result = recommend_from_library(tracks, genre="Jazz", limit=3)

    assert [item.track.genre for item in result] == ["Jazz"]
