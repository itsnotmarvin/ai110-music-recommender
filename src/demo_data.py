"""Public sample data used to demonstrate Threadline without personal uploads."""

from __future__ import annotations

from .apple_music import AppleMusicExport, LibraryPlaylist, LibraryTrack
from .playlist_recommender import SimilarTrack


DEMO_PLAYLIST_NAME = "Late Night: Alternative R&B"


def demo_apple_music_export() -> AppleMusicExport:
    """Return a synthetic listening profile for the stakeholder demo."""

    tracks = (
        LibraryTrack(
            "demo-1", "Pink + White", "Frank Ocean", "Blonde",
            "Alternative R&B", play_count=42, skip_count=1, rating=100,
            source_id="1",
        ),
        LibraryTrack(
            "demo-2", "Girl", "The Internet", "Ego Death",
            "R&B/Soul", play_count=38, skip_count=2, rating=100,
            source_id="2",
        ),
        LibraryTrack(
            "demo-3", "Boredom", "Tyler, the Creator", "Flower Boy",
            "Hip-Hop/Rap", play_count=34, skip_count=1, rating=100,
            source_id="3",
        ),
        LibraryTrack(
            "demo-4", "Body", "Syd", "Fin",
            "R&B/Soul", play_count=27, skip_count=2, rating=80,
            source_id="4",
        ),
        LibraryTrack(
            "demo-5", "Dark Red", "Steve Lacy", "Steve Lacy's Demo",
            "Alternative", play_count=31, skip_count=3, rating=100,
            source_id="5",
        ),
        LibraryTrack(
            "demo-6", "After the Storm", "Kali Uchis", "Isolation",
            "R&B/Soul", play_count=24, skip_count=1, rating=80,
            source_id="6",
        ),
    )
    playlist = LibraryPlaylist(
        persistent_id="threadline-live-demo",
        name=DEMO_PLAYLIST_NAME,
        track_ids=tuple(track.source_id for track in tracks),
    )
    return AppleMusicExport(tracks=tracks, playlists=(playlist,))


class DemoSimilarityClient:
    """Deterministic public sample evidence for demos without a provider key."""

    _candidates = {
        "pink + white": (
            ("Japanese Denim", "Daniel Caesar", 0.91),
            ("Get You", "Daniel Caesar", 0.87),
            ("Dead Man Walking", "Brent Faiyaz", 0.74),
        ),
        "girl": (
            ("Japanese Denim", "Daniel Caesar", 0.83),
            ("Tadow", "Masego & FKJ", 0.78),
            ("Focus", "H.E.R.", 0.71),
        ),
        "boredom": (
            ("Japanese Denim", "Daniel Caesar", 0.72),
            ("Come Through and Chill", "Miguel", 0.68),
            ("Tadow", "Masego & FKJ", 0.64),
        ),
        "body": (
            ("Focus", "H.E.R.", 0.84),
            ("Japanese Denim", "Daniel Caesar", 0.78),
            ("Dead Man Walking", "Brent Faiyaz", 0.70),
        ),
        "dark red": (
            ("Tadow", "Masego & FKJ", 0.82),
            ("Japanese Denim", "Daniel Caesar", 0.76),
            ("Come Through and Chill", "Miguel", 0.66),
        ),
        "after the storm": (
            ("Japanese Denim", "Daniel Caesar", 0.79),
            ("Get You", "Daniel Caesar", 0.75),
            ("Focus", "H.E.R.", 0.70),
        ),
    }
    _tags = {
        "japanese denim": ("alternative r&b", "neo soul", "chill"),
        "get you": ("r&b", "neo soul", "romantic"),
        "dead man walking": ("alternative r&b", "r&b", "late night"),
        "tadow": ("neo soul", "jazz", "chill"),
        "focus": ("r&b", "alternative r&b", "soul"),
        "come through and chill": ("r&b", "chill", "late night"),
    }
    _seed_tags = ("alternative r&b", "r&b", "neo soul", "chill", "late night")

    def similar_tracks(
        self, artist: str, title: str, *, limit: int = 12
    ) -> list[SimilarTrack]:
        del artist
        return [
            SimilarTrack(
                candidate_title,
                candidate_artist,
                match,
                "https://www.last.fm/search?q="
                + f"{candidate_artist} {candidate_title}".replace(" ", "+"),
            )
            for candidate_title, candidate_artist, match
            in self._candidates.get(title.casefold(), ())[:limit]
        ]

    def top_tags(self, artist: str, title: str, *, limit: int = 8) -> list[str]:
        del artist
        tags = self._tags.get(title.casefold(), self._seed_tags)
        return list(tags[:limit])
