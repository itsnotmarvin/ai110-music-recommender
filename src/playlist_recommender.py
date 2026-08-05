"""Hybrid automatic playlist continuation using public listening signals.

Candidate tracks come from Last.fm's listening-data similarity endpoint. A
transparent second-stage ranker combines that signal with playlist tags,
multi-seed agreement, the listener's own library, and discovery value.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .apple_music import LibraryTrack


LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
_TITLE_STOP_WORDS = {
    "a", "and", "for", "mix", "music", "my", "of", "playlist", "songs", "the", "to",
}


class PlaylistRecommendationError(RuntimeError):
    """Raised when external candidate generation cannot produce a safe result."""


@dataclass(frozen=True)
class SimilarTrack:
    """One listening-similarity result returned for a seed track."""

    title: str
    artist: str
    match: float
    url: str


@dataclass(frozen=True)
class CandidateSignals:
    """Normalized evidence collected before final playlist ranking."""

    title: str
    artist: str
    url: str
    matches_by_seed: Mapping[str, float]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlaylistRecommendation:
    """A playlist-fit recommendation with inspectable scoring evidence."""

    title: str
    artist: str
    url: str
    score: float
    confidence: str
    reasons: tuple[str, ...]
    supporting_seeds: tuple[str, ...]
    tags: tuple[str, ...]
    breakdown: Mapping[str, float]


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _items(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _web_url(value: object) -> str:
    url = _clean(value)
    return url if url.startswith(("https://", "http://")) else ""


class LastfmClient:
    """Small read-only adapter for Last.fm similarity and community tags."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 10.0,
        opener: Callable = urlopen,
    ):
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.opener = opener
        if not self.api_key:
            raise ValueError("A Last.fm API key is required.")

    def _get(self, method: str, **params: object) -> dict:
        query = urlencode(
            {
                "method": method,
                "api_key": self.api_key,
                "format": "json",
                "autocorrect": 1,
                **params,
            }
        )
        request = Request(
            f"{LASTFM_API_URL}?{query}",
            headers={"User-Agent": "Threadline/0.2 playlist-research-prototype"},
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise PlaylistRecommendationError(
                "The listening-similarity provider could not be reached."
            ) from exc
        if not isinstance(payload, dict):
            raise PlaylistRecommendationError("The similarity provider returned invalid data.")
        if payload.get("error"):
            raise PlaylistRecommendationError(
                _clean(payload.get("message")) or "The similarity provider rejected the request."
            )
        return payload

    def similar_tracks(
        self, artist: str, title: str, *, limit: int = 12
    ) -> list[SimilarTrack]:
        payload = self._get(
            "track.getSimilar", artist=artist, track=title, limit=max(1, limit)
        )
        container = payload.get("similartracks")
        raw_tracks = _items(container.get("track")) if isinstance(container, dict) else []
        results: list[SimilarTrack] = []
        for raw in raw_tracks:
            candidate_artist = raw.get("artist", {})
            if isinstance(candidate_artist, dict):
                candidate_artist = candidate_artist.get("name")
            name = _clean(raw.get("name"))
            artist_name = _clean(candidate_artist)
            if not name or not artist_name:
                continue
            try:
                match = max(0.0, float(raw.get("match", 0.0)))
            except (TypeError, ValueError):
                match = 0.0
            results.append(
                SimilarTrack(
                    title=name,
                    artist=artist_name,
                    match=match,
                    url=_web_url(raw.get("url")),
                )
            )
        return results

    def top_tags(self, artist: str, title: str, *, limit: int = 8) -> list[str]:
        payload = self._get("track.getTopTags", artist=artist, track=title)
        container = payload.get("toptags")
        raw_tags = _items(container.get("tag")) if isinstance(container, dict) else []
        return [
            _clean(raw.get("name"))
            for raw in raw_tags
            if _clean(raw.get("name"))
        ][: max(1, limit)]


def select_diverse_seeds(
    tracks: Iterable[LibraryTrack], *, limit: int = 6
) -> list[LibraryTrack]:
    """Choose representative playlist tracks without letting one artist dominate."""

    materialized = list(tracks)
    if limit <= 0:
        return []
    selected: list[LibraryTrack] = []
    seen_artists: set[str] = set()
    for track in materialized:
        artist_key = track.artist.casefold()
        if artist_key in seen_artists:
            continue
        selected.append(track)
        seen_artists.add(artist_key)
        if len(selected) == limit:
            return selected
    selected_ids = {track.library_id for track in selected}
    for track in materialized:
        if track.library_id not in selected_ids:
            selected.append(track)
        if len(selected) == limit:
            break
    return selected


def _title_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1 and token not in _TITLE_STOP_WORDS
    }


def rank_playlist_candidates(
    candidates: Iterable[CandidateSignals],
    *,
    playlist_name: str,
    playlist_tracks: Iterable[LibraryTrack],
    library_tracks: Iterable[LibraryTrack],
    seed_tags: Iterable[str] = (),
    limit: int = 5,
) -> list[PlaylistRecommendation]:
    """Apply the researched second-stage hybrid scoring recipe."""

    if limit <= 0:
        return []
    candidate_list = list(candidates)
    playlist = list(playlist_tracks)
    library = list(library_tracks)
    playlist_keys = {(track.artist.casefold(), track.title.casefold()) for track in playlist}
    playlist_artists = {track.artist.casefold() for track in playlist}
    library_keys = {(track.artist.casefold(), track.title.casefold()) for track in library}

    artist_weights: Counter[str] = Counter()
    for track in library:
        artist_weights[track.artist.casefold()] += 1 + track.play_count + (track.rating / 20)
    strongest_artist = max(artist_weights.values(), default=1.0)

    playlist_tag_profile: Counter[str] = Counter()
    for token in _title_tokens(playlist_name):
        playlist_tag_profile[token] += 4.0
    for index, tag in enumerate(seed_tags):
        clean_tag = _clean(tag).casefold()
        if clean_tag:
            playlist_tag_profile[clean_tag] += 1.0 / (1 + (index * 0.12))

    seed_count = max(
        1,
        len({key for candidate in candidate_list for key in candidate.matches_by_seed}),
    )
    ranked: list[PlaylistRecommendation] = []
    for candidate in candidate_list:
        candidate_key = (candidate.artist.casefold(), candidate.title.casefold())
        if candidate_key in playlist_keys:
            continue
        matches = sorted(candidate.matches_by_seed.values(), reverse=True)
        if not matches:
            continue
        best_matches = matches[:3]
        listening_fit = (0.65 * best_matches[0]) + (
            0.35 * (sum(best_matches) / len(best_matches))
        )
        multi_seed = min(1.0, len(candidate.matches_by_seed) / min(3, seed_count))

        tag_weights = [1.0 / (index + 1) for index in range(len(candidate.tags))]
        matching_tag_weight = sum(
            weight
            for tag, weight in zip(candidate.tags, tag_weights)
            if tag.casefold() in playlist_tag_profile
            or bool(_title_tokens(tag) & set(playlist_tag_profile))
        )
        mood_fit = matching_tag_weight / sum(tag_weights) if tag_weights else 0.0
        personal_fit = artist_weights[candidate.artist.casefold()] / strongest_artist
        if not personal_fit:
            personal_fit = 0.25
        discovery = 1.0 if candidate_key not in library_keys else 0.25
        if candidate.artist.casefold() in playlist_artists:
            discovery *= 0.55

        breakdown = {
            "listening similarity": min(1.0, listening_fit),
            "mood/category fit": min(1.0, mood_fit),
            "multi-seed support": multi_seed,
            "personal affinity": min(1.0, personal_fit),
            "discovery value": discovery,
        }
        score = 10 * (
            (0.40 * breakdown["listening similarity"])
            + (0.25 * breakdown["mood/category fit"])
            + (0.15 * breakdown["multi-seed support"])
            + (0.10 * breakdown["personal affinity"])
            + (0.10 * breakdown["discovery value"])
        )

        supporting_seeds = tuple(candidate.matches_by_seed.keys())
        reasons = [
            f"listening data connects it to {supporting_seeds[0]}"
        ]
        if len(supporting_seeds) > 1:
            reasons.append(f"{len(supporting_seeds)} different playlist seeds support it")
        matching_tags = [
            tag
            for tag in candidate.tags
            if tag.casefold() in playlist_tag_profile
            or bool(_title_tokens(tag) & set(playlist_tag_profile))
        ]
        if matching_tags:
            reasons.append(
                "its community tags match " + ", ".join(matching_tags[:3])
            )
        elif discovery >= 0.9:
            reasons.append("it adds a new artist or track without leaving the listening neighborhood")
        else:
            reasons.append("it stays close to artists already present in your library")

        confidence = "high" if len(supporting_seeds) >= 2 and mood_fit > 0 else (
            "medium" if listening_fit >= 0.55 else "exploratory"
        )
        ranked.append(
            PlaylistRecommendation(
                title=candidate.title,
                artist=candidate.artist,
                url=candidate.url,
                score=round(score, 2),
                confidence=confidence,
                reasons=tuple(reasons),
                supporting_seeds=supporting_seeds,
                tags=candidate.tags,
                breakdown={name: round(value, 3) for name, value in breakdown.items()},
            )
        )

    ranked.sort(key=lambda item: (-item.score, item.artist.casefold(), item.title.casefold()))
    diversified: list[PlaylistRecommendation] = []
    artist_counts: Counter[str] = Counter()
    remaining = list(ranked)
    while remaining and len(diversified) < limit:
        remaining.sort(
            key=lambda item: (
                -(item.score - (1.2 * artist_counts[item.artist.casefold()])),
                item.artist.casefold(),
                item.title.casefold(),
            )
        )
        chosen = remaining.pop(0)
        diversified.append(chosen)
        artist_counts[chosen.artist.casefold()] += 1
    return diversified


class HybridPlaylistRecommender:
    """Generate listening-based candidates, enrich them, then rank playlist fit."""

    def __init__(self, client: LastfmClient):
        self.client = client

    def recommend(
        self,
        playlist_name: str,
        playlist_tracks: Iterable[LibraryTrack],
        library_tracks: Iterable[LibraryTrack],
        *,
        limit: int = 5,
    ) -> list[PlaylistRecommendation]:
        playlist = list(playlist_tracks)
        seeds = select_diverse_seeds(playlist)
        if not seeds:
            return []
        existing = {(track.artist.casefold(), track.title.casefold()) for track in playlist}
        aggregate: dict[tuple[str, str], dict] = {}
        seed_tags: list[str] = []
        successful_seed_requests = 0

        for seed in seeds:
            seed_label = f"{seed.title} — {seed.artist}"
            try:
                seed_tags.extend(self.client.top_tags(seed.artist, seed.title, limit=5))
            except PlaylistRecommendationError:
                pass
            try:
                similar = self.client.similar_tracks(seed.artist, seed.title, limit=12)
            except PlaylistRecommendationError:
                continue
            if not similar:
                continue
            successful_seed_requests += 1
            largest_match = max((item.match for item in similar), default=1.0) or 1.0
            for item in similar:
                key = (item.artist.casefold(), item.title.casefold())
                if key in existing:
                    continue
                record = aggregate.setdefault(
                    key,
                    {
                        "title": item.title,
                        "artist": item.artist,
                        "url": item.url,
                        "matches": {},
                    },
                )
                record["matches"][seed_label] = min(1.0, item.match / largest_match)

        if not aggregate:
            if not successful_seed_requests:
                raise PlaylistRecommendationError(
                    "No listening-similarity data was available for the selected playlist seeds."
                )
            return []

        likely = sorted(
            aggregate.values(),
            key=lambda item: (
                -len(item["matches"]),
                -sum(item["matches"].values()),
                item["artist"].casefold(),
            ),
        )[:24]
        candidates: list[CandidateSignals] = []
        for record in likely:
            try:
                tags = tuple(
                    self.client.top_tags(record["artist"], record["title"], limit=8)
                )
            except PlaylistRecommendationError:
                tags = ()
            candidates.append(
                CandidateSignals(
                    title=record["title"],
                    artist=record["artist"],
                    url=record["url"],
                    matches_by_seed=record["matches"],
                    tags=tags,
                )
            )

        return rank_playlist_candidates(
            candidates,
            playlist_name=playlist_name,
            playlist_tracks=playlist,
            library_tracks=library_tracks,
            seed_tags=seed_tags,
            limit=limit,
        )
