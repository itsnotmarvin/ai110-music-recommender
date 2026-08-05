"""Private, local-first recommendations from an Apple Music XML export.

The module reads metadata only. It does not upload audio, call Apple services, or
persist a listener's library. The scoring rule is deliberately transparent so a
listener can see how play counts, skips, ratings, recency, and genre affected a
pick.
"""

from __future__ import annotations

import math
import plistlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional


MAX_LIBRARY_BYTES = 50 * 1024 * 1024
RECOMMENDATION_MODES = ("Rediscover", "Comfort pick", "Deep cut")


class AppleMusicImportError(ValueError):
    """Raised when an Apple Music export cannot be read safely."""


@dataclass(frozen=True)
class LibraryTrack:
    """The small metadata subset Threadline needs for one library track."""

    library_id: str
    title: str
    artist: str
    album: str
    genre: str
    play_count: int = 0
    skip_count: int = 0
    rating: int = 0
    date_added: Optional[datetime] = None
    last_played: Optional[datetime] = None
    source_id: str = ""


@dataclass(frozen=True)
class LibraryPlaylist:
    """One named playlist and the source track IDs it contains, in order."""

    persistent_id: str
    name: str
    track_ids: tuple[str, ...]


@dataclass(frozen=True)
class AppleMusicExport:
    """Music metadata plus user playlists parsed from one Apple XML export."""

    tracks: tuple[LibraryTrack, ...]
    playlists: tuple[LibraryPlaylist, ...]

    def tracks_for(self, playlist: LibraryPlaylist) -> list[LibraryTrack]:
        by_source_id = {track.source_id: track for track in self.tracks}
        return [
            by_source_id[track_id]
            for track_id in playlist.track_ids
            if track_id in by_source_id
        ]


@dataclass(frozen=True)
class LibraryProfile:
    """Aggregate, inspectable signals inferred from an imported library."""

    track_count: int
    artist_count: int
    genre_count: int
    top_artists: tuple[tuple[str, float], ...]
    top_genres: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class LibraryRecommendation:
    """A recommended library track with a score and human-readable reasons."""

    track: LibraryTrack
    score: float
    reasons: tuple[str, ...]
    breakdown: Mapping[str, float]


def _clean_text(value: object, fallback: str) -> str:
    clean = " ".join(str(value or "").split())
    return clean or fallback


def _non_negative_int(value: object, maximum: Optional[int] = None) -> int:
    try:
        number = max(0, int(value or 0))
    except (TypeError, ValueError):
        number = 0
    return min(number, maximum) if maximum is not None else number


def _as_utc(value: object) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_plist(payload: bytes) -> dict:
    if not payload:
        raise AppleMusicImportError("The selected Apple Music export is empty.")
    if len(payload) > MAX_LIBRARY_BYTES:
        raise AppleMusicImportError("The export is larger than the 50 MB import limit.")

    try:
        library = plistlib.loads(payload)
    except Exception as exc:  # plistlib exposes several parser-specific exceptions
        raise AppleMusicImportError(
            "This does not look like an Apple Music XML library or playlist export."
        ) from exc

    if not isinstance(library, dict):
        raise AppleMusicImportError("The Apple Music export has an unsupported structure.")
    return library


def parse_apple_music_export(payload: bytes) -> AppleMusicExport:
    """Parse tracks and playlist membership from an Apple Music XML export."""

    library = _load_plist(payload)
    raw_tracks = library.get("Tracks")
    if not isinstance(raw_tracks, dict):
        raise AppleMusicImportError(
            "No Tracks dictionary was found. Export the playlist or library as XML."
        )

    parsed: dict[str, LibraryTrack] = {}
    for fallback_id, raw in raw_tracks.items():
        if not isinstance(raw, dict):
            continue
        title = _clean_text(raw.get("Name"), "")
        artist = _clean_text(raw.get("Artist") or raw.get("Album Artist"), "")
        kind = _clean_text(raw.get("Kind"), "").casefold()
        if not title or not artist or "video" in kind:
            continue

        source_id = _clean_text(raw.get("Track ID") or fallback_id, str(fallback_id))
        library_id = _clean_text(
            raw.get("Persistent ID") or raw.get("Track ID") or fallback_id,
            str(fallback_id),
        )
        track = LibraryTrack(
            library_id=library_id,
            title=title,
            artist=artist,
            album=_clean_text(raw.get("Album"), "Unknown album"),
            genre=_clean_text(raw.get("Genre"), "Unknown genre"),
            play_count=_non_negative_int(raw.get("Play Count")),
            skip_count=_non_negative_int(raw.get("Skip Count")),
            rating=_non_negative_int(raw.get("Rating"), maximum=100),
            date_added=_as_utc(raw.get("Date Added")),
            last_played=_as_utc(raw.get("Play Date UTC") or raw.get("Last Played Date")),
            source_id=source_id,
        )
        parsed[source_id] = track

    if not parsed:
        raise AppleMusicImportError(
            "The export did not contain any music tracks with both a title and artist."
        )
    playlists: list[LibraryPlaylist] = []
    raw_playlists = library.get("Playlists", [])
    if isinstance(raw_playlists, list):
        for index, raw_playlist in enumerate(raw_playlists):
            if not isinstance(raw_playlist, dict):
                continue
            if raw_playlist.get("Master") or raw_playlist.get("Folder"):
                continue
            items = raw_playlist.get("Playlist Items")
            if not isinstance(items, list):
                continue
            track_ids = tuple(
                _clean_text(item.get("Track ID"), "")
                for item in items
                if isinstance(item, dict) and item.get("Track ID") is not None
            )
            track_ids = tuple(track_id for track_id in track_ids if track_id in parsed)
            name = _clean_text(raw_playlist.get("Name"), "")
            if not name or not track_ids:
                continue
            playlists.append(
                LibraryPlaylist(
                    persistent_id=_clean_text(
                        raw_playlist.get("Playlist Persistent ID"), f"playlist-{index}"
                    ),
                    name=name,
                    track_ids=track_ids,
                )
            )

    return AppleMusicExport(
        tracks=tuple(
            sorted(
                parsed.values(),
                key=lambda item: (item.artist.casefold(), item.title.casefold()),
            )
        ),
        playlists=tuple(sorted(playlists, key=lambda item: item.name.casefold())),
    )


def parse_apple_music_xml(payload: bytes) -> list[LibraryTrack]:
    """Parse music tracks from an Apple Music XML library or playlist export."""

    export = parse_apple_music_export(payload)
    deduplicated: dict[str, LibraryTrack] = {}
    for track in export.tracks:
        existing = deduplicated.get(track.library_id)
        if existing is None or (track.play_count, track.rating) > (
            existing.play_count,
            existing.rating,
        ):
            deduplicated[track.library_id] = track
    return sorted(
        deduplicated.values(),
        key=lambda item: (item.artist.casefold(), item.title.casefold()),
    )


def _listening_weight(track: LibraryTrack) -> float:
    """Give explicit plays the most weight while retaining unrated new tracks."""

    return 1.0 + track.play_count + (track.rating / 20.0)


def analyze_library(tracks: Iterable[LibraryTrack]) -> LibraryProfile:
    """Summarize the taste signals available in imported metadata."""

    materialized = list(tracks)
    artists: Counter[str] = Counter()
    genres: Counter[str] = Counter()
    for track in materialized:
        weight = _listening_weight(track)
        artists[track.artist] += weight
        genres[track.genre] += weight
    return LibraryProfile(
        track_count=len(materialized),
        artist_count=len(artists),
        genre_count=len(genres),
        top_artists=tuple((name, round(score, 2)) for name, score in artists.most_common(5)),
        top_genres=tuple((name, round(score, 2)) for name, score in genres.most_common(5)),
    )


def _days_since(value: Optional[datetime], as_of: datetime) -> Optional[int]:
    if value is None:
        return None
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return max(0, (as_of - normalized.astimezone(timezone.utc)).days)


def recommend_from_library(
    tracks: Iterable[LibraryTrack],
    *,
    mode: str = "Rediscover",
    genre: Optional[str] = None,
    limit: int = 3,
    as_of: Optional[datetime] = None,
) -> list[LibraryRecommendation]:
    """Rank tracks using one of three published, deterministic scoring recipes."""

    if mode not in RECOMMENDATION_MODES:
        raise ValueError(f"Unsupported recommendation mode: {mode}")
    if limit <= 0:
        return []

    materialized = list(tracks)
    if genre:
        materialized = [
            track for track in materialized if track.genre.casefold() == genre.casefold()
        ]
    if not materialized:
        return []

    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    genre_weights: Counter[str] = Counter()
    for track in materialized:
        genre_weights[track.genre] += _listening_weight(track)
    strongest_genre = max(genre_weights.values(), default=1.0)
    largest_play_count = max((track.play_count for track in materialized), default=0)

    mode_weights = {
        "Rediscover": {
            "genre affinity": 2.5,
            "time away": 3.0,
            "positive history": 1.5,
            "familiarity": 1.0,
            "rating": 1.0,
        },
        "Comfort pick": {
            "genre affinity": 2.5,
            "time away": 0.25,
            "positive history": 1.5,
            "familiarity": 3.0,
            "rating": 1.75,
        },
        "Deep cut": {
            "genre affinity": 3.0,
            "time away": 2.0,
            "positive history": 1.25,
            "novelty": 3.0,
            "rating": 0.75,
        },
    }[mode]

    recommendations: list[LibraryRecommendation] = []
    for track in materialized:
        familiarity = (
            math.log1p(track.play_count) / math.log1p(largest_play_count)
            if largest_play_count > 0
            else 0.0
        )
        days_away = _days_since(track.last_played, now)
        time_away = 1.0 if days_away is None else min(1.0, days_away / 365.0)
        interactions = track.play_count + track.skip_count
        positive_history = (
            (track.play_count + 1) / (track.play_count + (2 * track.skip_count) + 2)
            if interactions
            else 0.5
        )
        signals = {
            "genre affinity": genre_weights[track.genre] / strongest_genre,
            "time away": time_away,
            "positive history": positive_history,
            "familiarity": familiarity,
            "novelty": 1.0 - familiarity,
            "rating": (track.rating / 100.0) if track.rating else 0.5,
        }
        weighted = sum(signals[name] * weight for name, weight in mode_weights.items())
        score = 10.0 * weighted / sum(mode_weights.values())

        reasons: list[str] = []
        if signals["genre affinity"] >= 0.65:
            reasons.append(f"{track.genre} is one of your strongest library genres")
        if mode == "Comfort pick" and track.play_count:
            reasons.append(f"you have returned to it {track.play_count} times")
        elif mode == "Deep cut":
            reasons.append(
                "it is still relatively unexplored in your library"
                if track.play_count <= max(2, largest_play_count * 0.2)
                else "it sits beyond your most-played tracks"
            )
        elif days_away is None:
            reasons.append("your export has no recorded recent play for it")
        elif days_away >= 90:
            reasons.append(f"it has been about {days_away} days since the recorded play")
        else:
            reasons.append("it balances familiarity with some time away")
        if track.rating >= 80:
            reasons.append(f"you rated it {track.rating}/100")
        elif track.skip_count == 0 and track.play_count > 0:
            reasons.append("its history has plays without recorded skips")
        if len(reasons) < 2:
            reasons.append("its play and skip history fits this mode")

        recommendations.append(
            LibraryRecommendation(
                track=track,
                score=round(score, 2),
                reasons=tuple(reasons[:3]),
                breakdown={
                    name: round(signals[name], 3) for name in mode_weights
                },
            )
        )

    recommendations.sort(
        key=lambda item: (
            -item.score,
            item.track.artist.casefold(),
            item.track.title.casefold(),
        )
    )
    return recommendations[:limit]
