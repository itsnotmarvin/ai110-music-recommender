"""Reviewed archive loading, validation, and retrieval utilities.

The archive is intentionally static.  Human-reviewed passages are the only
material that the question-answering layer is allowed to present as evidence.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


CLAIM_TYPES = {
    "documented-fact",
    "artist-stated",
    "reported",
    "critical-interpretation",
    "fan-theory",
}

DEFAULT_ALLOWED_CLAIMS = {
    "documented-fact",
    "artist-stated",
    "reported",
}

_STOP_WORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "because", "by",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "i",
    "in", "into", "is", "it", "of", "on", "or", "that", "the", "their",
    "then", "this", "to", "was", "were", "what", "when", "where", "who",
    "why", "with",
}


def _tokenize(value: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token not in _STOP_WORDS and len(token) > 1
    ]


@dataclass(frozen=True)
class SearchResult:
    """One reviewed passage returned by archive retrieval."""

    document: Dict
    score: float
    confidence: float
    matched_terms: Tuple[str, ...]


class ArchiveValidationError(ValueError):
    """Raised when reviewed archive data breaks the published schema."""


class ArchiveRepository:
    """Read-only access to artist universes and grounded evidence passages."""

    def __init__(self, data: Dict):
        self.data = data
        self._validate()
        self.sources = {source["id"]: source for source in data["sources"]}
        self.universes = {universe["id"]: universe for universe in data["universes"]}
        self.documents = list(data["documents"])
        self._document_frequencies = self._build_document_frequencies()

    @classmethod
    def from_json(cls, path: str | Path) -> "ArchiveRepository":
        archive_path = Path(path)
        with archive_path.open(encoding="utf-8") as archive_file:
            data = json.load(archive_file)

        member_catalog_path = archive_path.with_name("odd_future_members.json")
        if member_catalog_path.exists():
            with member_catalog_path.open(encoding="utf-8") as catalog_file:
                member_catalog = json.load(catalog_file)
            cls._hydrate_member_catalog(data, member_catalog)

        track_catalog_path = archive_path.with_name("track_catalog.json")
        if track_catalog_path.exists():
            with track_catalog_path.open(encoding="utf-8") as catalog_file:
                track_catalog = json.load(catalog_file)
            cls._hydrate_track_catalog(data, track_catalog)

        story_profiles_path = archive_path.with_name("story_profiles.json")
        if story_profiles_path.exists():
            with story_profiles_path.open(encoding="utf-8") as story_file:
                story_profiles = json.load(story_file)
            cls._hydrate_story_profiles(data, story_profiles)

        interview_videos_path = archive_path.with_name("interview_videos.json")
        if interview_videos_path.exists():
            with interview_videos_path.open(encoding="utf-8") as interview_file:
                interview_videos = json.load(interview_file)
            cls._hydrate_interview_videos(data, interview_videos)
        return cls(data)

    @staticmethod
    def _hydrate_member_catalog(data: Dict, member_catalog: Dict) -> None:
        """Merge synchronized Odd Future member catalogs into local universes.

        Existing editorial fields remain authoritative. Generated metadata fills
        discographies and track destinations, and creates clearly unreviewed local
        profiles for roster members/subgroups that do not yet have story chapters.
        """
        artists = member_catalog.get("artists")
        if not isinstance(artists, list):
            raise ArchiveValidationError("Member catalog needs an artists list")

        universes = data.get("universes", [])
        existing_by_id = {universe.get("id"): universe for universe in universes}

        for catalog_artist in artists:
            artist_id = catalog_artist.get("id")
            if not artist_id:
                raise ArchiveValidationError("Every member catalog artist needs an id")
            existing = existing_by_id.get(artist_id)
            if existing is None:
                universes.append(catalog_artist)
                existing_by_id[artist_id] = catalog_artist
                continue

            existing_albums = existing.get("albums", [])
            existing_by_title = {
                str(album.get("title", "")).casefold(): album
                for album in existing_albums
            }
            merged_albums = []
            matched_titles = set()
            for catalog_album in catalog_artist.get("albums", []):
                title_key = str(catalog_album.get("title", "")).casefold()
                reviewed_album = existing_by_title.get(title_key)
                if reviewed_album is None:
                    merged_albums.append(catalog_album)
                    continue

                reviewed_tracks = {
                    str(track.get("title", "")).casefold(): track
                    for track in reviewed_album.get("tracks", [])
                }
                merged_tracks = [
                    {
                        **track,
                        **reviewed_tracks.get(
                            str(track.get("title", "")).casefold(), {}
                        ),
                    }
                    for track in catalog_album.get("tracks", [])
                ]
                merged_album = {**catalog_album, **reviewed_album}
                merged_album["tracks"] = merged_tracks
                for field in (
                    "catalog_complete",
                    "catalog_generated",
                    "catalog_track_count",
                    "musicbrainz_url",
                    "tracklist_source_url",
                    "youtube_playlist_url",
                ):
                    if field in catalog_album:
                        merged_album[field] = catalog_album[field]
                merged_albums.append(merged_album)
                matched_titles.add(title_key)

            merged_albums.extend(
                album
                for album in existing_albums
                if str(album.get("title", "")).casefold() not in matched_titles
            )

            existing_related = {
                relation.get("universe_id"): relation
                for relation in existing.get("related", [])
            }
            merged_related = list(existing.get("related", []))
            for relation in catalog_artist.get("related", []):
                if relation.get("universe_id") not in existing_related:
                    merged_related.append(relation)

            existing.update(
                {
                    "mbid": catalog_artist.get("mbid"),
                    "catalog_generated": True,
                    "catalog_coverage": catalog_artist.get("catalog_coverage", {}),
                    "catalog_score": catalog_artist.get("catalog_score", 100),
                    "catalog_status": catalog_artist.get("catalog_status"),
                    "catalog_url": catalog_artist.get("catalog_url"),
                    "odd_future_role": catalog_artist.get("odd_future_role"),
                    "membership_begin": catalog_artist.get("membership_begin"),
                    "membership_end": catalog_artist.get("membership_end"),
                    "membership_ended": catalog_artist.get("membership_ended", False),
                    "albums": merged_albums,
                    "related": merged_related,
                }
            )

        odd_future = existing_by_id.get("odd-future")
        if odd_future is None:
            raise ArchiveValidationError("Member catalog needs an Odd Future universe")
        existing_relations = {
            relation.get("universe_id")
            for relation in odd_future.get("related", [])
        }
        for artist in artists:
            if artist["id"] in existing_relations:
                continue
            if artist.get("odd_future_role") == "subgroup":
                relationship = "Connected subgroup"
            elif artist.get("membership_ended"):
                relationship = "Former member"
            else:
                relationship = "Member"
            odd_future.setdefault("related", []).append(
                {"universe_id": artist["id"], "relationship": relationship}
            )

        data["member_catalog_version"] = member_catalog.get(
            "catalog_version", "unknown"
        )
        data["member_catalog_updated_at"] = member_catalog.get("generated_at", "")
        data["member_catalog_note"] = member_catalog.get("provider_note", "")

    @staticmethod
    def _hydrate_track_catalog(data: Dict, track_catalog: Dict) -> None:
        """Merge the separately maintained track catalog into album chapters.

        The narrative archive stays readable while the larger, factual song-link
        catalog can grow independently. Existing reviewed track fields (for
        example permissioned lyric cues) override catalog defaults.
        """
        catalog_albums = track_catalog.get("albums")
        if not isinstance(catalog_albums, dict):
            raise ArchiveValidationError("Track catalog needs an albums object")

        matched_keys = set()
        for universe in data.get("universes", []):
            for album in universe.get("albums", []):
                catalog_key = f"{universe['id']}:{album['id']}"
                catalog_album = catalog_albums.get(catalog_key)
                if not catalog_album:
                    continue

                existing_tracks = {
                    str(track.get("title", "")).casefold(): track
                    for track in album.get("tracks", [])
                }
                album["tracks"] = [
                    {
                        **catalog_track,
                        **existing_tracks.get(
                            str(catalog_track.get("title", "")).casefold(), {}
                        ),
                    }
                    for catalog_track in catalog_album.get("tracks", [])
                ]
                album["catalog_complete"] = True
                album["catalog_track_count"] = len(album["tracks"])
                for field in (
                    "tracklist_source_url",
                    "youtube_playlist_url",
                    "apple_music_url",
                ):
                    if catalog_album.get(field):
                        album[field] = catalog_album[field]
                matched_keys.add(catalog_key)

        unmatched = set(catalog_albums) - matched_keys
        if unmatched:
            raise ArchiveValidationError(
                "Track catalog links to missing albums: "
                + ", ".join(sorted(unmatched))
            )

        data["track_catalog_version"] = track_catalog.get("catalog_version", "unknown")
        data["track_catalog_updated_at"] = track_catalog.get("updated_at", "")
        data["lyrics_policy"] = track_catalog.get("lyrics_policy", "")

    @staticmethod
    def _hydrate_story_profiles(data: Dict, story_profiles: Dict) -> None:
        """Publish reviewed narratives without coupling them to catalog sync files."""
        sources = story_profiles.get("sources")
        profiles = story_profiles.get("profiles")
        if not isinstance(sources, list) or not isinstance(profiles, list):
            raise ArchiveValidationError(
                "Story profiles need sources and profiles lists"
            )

        existing_source_ids = {source.get("id") for source in data.get("sources", [])}
        for source in sources:
            if source.get("id") not in existing_source_ids:
                data.setdefault("sources", []).append(source)
                existing_source_ids.add(source.get("id"))

        universes = data.get("universes", [])
        universe_by_id = {universe.get("id"): universe for universe in universes}

        # Every synchronized artist receives an inspectable catalog source. The
        # narrative file may use that source only for release chronology—not for
        # biographical claims.
        for universe in universes:
            catalog_url = universe.get("catalog_url")
            if not catalog_url:
                continue
            source_id = f"musicbrainz-catalog-{universe['id']}"
            if source_id in existing_source_ids:
                continue
            data.setdefault("sources", []).append(
                {
                    "id": source_id,
                    "title": f"{universe['name']} — release-group catalog",
                    "publisher": "MusicBrainz",
                    "published_at": story_profiles.get("reviewed_at", "date unavailable"),
                    "source_type": "community-catalog-metadata",
                    "url": catalog_url,
                }
            )
            existing_source_ids.add(source_id)

        for profile in profiles:
            universe_id = profile.get("universe_id")
            universe = universe_by_id.get(universe_id)
            if universe is None:
                raise ArchiveValidationError(
                    f"Story profile links to missing universe {universe_id}"
                )

            for field in (
                "summary",
                "tagline",
                "coverage",
                "chapters",
                "popular_tracks",
            ):
                if field in profile:
                    universe[field] = profile[field]
            universe["reviewed"] = True
            universe["story_reviewed_at"] = story_profiles.get("reviewed_at", "")

            relations_by_id = {
                relation.get("universe_id"): relation
                for relation in universe.get("related", [])
            }
            for relation in profile.get("related", []):
                relations_by_id[relation.get("universe_id")] = relation
            universe["related"] = list(relations_by_id.values())

        existing_document_ids = {
            document.get("id") for document in data.get("documents", [])
        }
        for profile in profiles:
            universe_id = profile["universe_id"]
            universe = universe_by_id[universe_id]
            for chapter in universe.get("chapters", []):
                document_id = f"story-{universe_id}-{chapter['id']}"
                document = {
                    "id": document_id,
                    "universe_id": universe_id,
                    "title": chapter["title"],
                    "text": chapter["dek"],
                    "claim_type": chapter["claim_type"],
                    "source_ids": chapter["source_ids"],
                    "entities": [
                        universe["name"],
                        *[
                            link.get("track_title", "")
                            for link in chapter.get("song_links", [])
                            if link.get("track_title")
                        ],
                    ],
                    "tags": [chapter["era"], "artist story", "Odd Future"],
                }
                if document_id in existing_document_ids:
                    for index, existing in enumerate(data["documents"]):
                        if existing.get("id") == document_id:
                            data["documents"][index] = document
                            break
                else:
                    data.setdefault("documents", []).append(document)
                    existing_document_ids.add(document_id)

        data["story_profile_version"] = story_profiles.get(
            "story_version", "unknown"
        )
        data["reviewed_at"] = story_profiles.get(
            "reviewed_at", data.get("reviewed_at", "")
        )

    @staticmethod
    def _hydrate_interview_videos(data: Dict, interview_data: Dict) -> None:
        """Attach curated, watchable interviews without treating them as transcripts."""
        videos = interview_data.get("videos")
        if not isinstance(videos, list):
            raise ArchiveValidationError("Interview video data needs a videos list")

        universe_by_id = {
            universe.get("id"): universe for universe in data.get("universes", [])
        }
        source_ids = {source.get("id") for source in data.get("sources", [])}

        for video in videos:
            video_id = video.get("id")
            youtube_id = str(video.get("youtube_id", ""))
            if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", youtube_id):
                raise ArchiveValidationError(
                    f"Interview {video_id or 'without id'} needs a valid YouTube id"
                )
            if not video.get("profile_ids"):
                raise ArchiveValidationError(
                    f"Interview {video_id} needs at least one profile"
                )

            if video_id not in source_ids:
                data.setdefault("sources", []).append(
                    {
                        key: video[key]
                        for key in (
                            "id",
                            "title",
                            "publisher",
                            "published_at",
                            "source_type",
                            "url",
                        )
                    }
                )
                source_ids.add(video_id)

            attached_video = {
                key: video[key]
                for key in (
                    "id",
                    "title",
                    "publisher",
                    "published_at",
                    "url",
                    "youtube_id",
                    "description",
                )
            }
            for profile_id in video["profile_ids"]:
                universe = universe_by_id.get(profile_id)
                if universe is None:
                    raise ArchiveValidationError(
                        f"Interview {video_id} links to missing universe {profile_id}"
                    )
                existing_ids = {
                    item.get("id") for item in universe.get("interview_videos", [])
                }
                if video_id not in existing_ids:
                    universe.setdefault("interview_videos", []).append(attached_video)

        data["interview_video_version"] = interview_data.get(
            "interview_version", "unknown"
        )

    def _validate(self) -> None:
        required = {"archive_version", "reviewed_at", "sources", "universes", "documents"}
        missing = required - self.data.keys()
        if missing:
            raise ArchiveValidationError(
                f"Archive is missing fields: {', '.join(sorted(missing))}"
            )

        def ensure_unique(items: Sequence[Dict], label: str) -> set[str]:
            ids = [str(item.get("id", "")) for item in items]
            if "" in ids:
                raise ArchiveValidationError(f"Every {label} needs an id")
            if len(ids) != len(set(ids)):
                raise ArchiveValidationError(f"Duplicate {label} id found")
            return set(ids)

        source_ids = ensure_unique(self.data["sources"], "source")
        universe_ids = ensure_unique(self.data["universes"], "universe")
        ensure_unique(self.data["documents"], "document")

        for source in self.data["sources"]:
            if not str(source.get("url", "")).startswith(("https://", "http://")):
                raise ArchiveValidationError(f"Source {source['id']} needs a web URL")

        for universe in self.data["universes"]:
            for chapter in universe.get("chapters", []):
                if chapter.get("claim_type") not in CLAIM_TYPES:
                    raise ArchiveValidationError(
                        f"Chapter {chapter.get('id')} has an unsupported claim type"
                    )
                missing_sources = set(chapter.get("source_ids", [])) - source_ids
                if missing_sources:
                    raise ArchiveValidationError(
                        f"Chapter {chapter.get('id')} has missing sources: "
                        f"{', '.join(sorted(missing_sources))}"
                    )
                for song_link in chapter.get("song_links", []):
                    target_id = song_link.get("universe_id", universe["id"])
                    if target_id not in universe_ids:
                        raise ArchiveValidationError(
                            f"Chapter {chapter.get('id')} links to missing song universe "
                            f"{target_id}"
                        )
                    target = next(
                        item for item in self.data["universes"] if item["id"] == target_id
                    )
                    track_title = str(song_link.get("track_title", "")).casefold()
                    matching_tracks = [
                        track
                        for album in target.get("albums", [])
                        for track in album.get("tracks", [])
                        if str(track.get("title", "")).casefold() == track_title
                    ]
                    if not track_title or not matching_tracks:
                        raise ArchiveValidationError(
                            f"Chapter {chapter.get('id')} links to missing track "
                            f"{song_link.get('track_title')} in {target_id}"
                        )
            for related in universe.get("related", []):
                if related["universe_id"] not in universe_ids:
                    raise ArchiveValidationError(
                        f"Universe {universe['id']} links to missing universe "
                        f"{related['universe_id']}"
                    )

            for album in universe.get("albums", []):
                if not album.get("catalog_complete"):
                    continue
                tracks = album.get("tracks", [])
                expected_count = album.get("catalog_track_count")
                if not tracks or expected_count != len(tracks):
                    raise ArchiveValidationError(
                        f"Album {album['id']} has an incomplete track catalog"
                    )
                titles = [str(track.get("title", "")) for track in tracks]
                if "" in titles or len(titles) != len({title.casefold() for title in titles}):
                    raise ArchiveValidationError(
                        f"Album {album['id']} needs unique, non-empty track titles"
                    )
                positions = [track.get("position") for track in tracks]
                if positions != list(range(1, len(tracks) + 1)):
                    raise ArchiveValidationError(
                        f"Album {album['id']} needs consecutive track positions"
                    )
                for track in tracks:
                    for field in ("youtube_url", "genius_url"):
                        if not str(track.get(field, "")).startswith("https://"):
                            raise ArchiveValidationError(
                                f"Track {track['title']} needs a valid {field}"
                            )
                    if not track.get("performers"):
                        raise ArchiveValidationError(
                            f"Track {track['title']} needs at least one performer"
                        )
                    if track.get("youtube_status") not in {
                        "official-artist-channel",
                        "search-only",
                    }:
                        raise ArchiveValidationError(
                            f"Track {track['title']} has an invalid YouTube status"
                        )
                    youtube_id = track.get("youtube_id")
                    if youtube_id and not re.fullmatch(r"[A-Za-z0-9_-]{11}", youtube_id):
                        raise ArchiveValidationError(
                            f"Track {track['title']} has an invalid YouTube id"
                        )

        for document in self.data["documents"]:
            if document.get("universe_id") not in universe_ids:
                raise ArchiveValidationError(
                    f"Document {document['id']} links to a missing universe"
                )
            if document.get("claim_type") not in CLAIM_TYPES:
                raise ArchiveValidationError(
                    f"Document {document['id']} has an unsupported claim type"
                )
            missing_sources = set(document.get("source_ids", [])) - source_ids
            if missing_sources:
                raise ArchiveValidationError(
                    f"Document {document['id']} has missing sources: "
                    f"{', '.join(sorted(missing_sources))}"
                )

    def _build_document_frequencies(self) -> Dict[str, int]:
        frequencies: Dict[str, int] = {}
        for document in self.documents:
            terms = set(_tokenize(self._searchable_text(document)))
            for term in terms:
                frequencies[term] = frequencies.get(term, 0) + 1
        return frequencies

    @staticmethod
    def _searchable_text(document: Dict) -> str:
        return " ".join(
            [
                str(document.get("title", "")),
                str(document.get("text", "")),
                " ".join(document.get("entities", [])),
                " ".join(document.get("tags", [])),
            ]
        )

    def list_universes(self) -> List[Dict]:
        return sorted(self.universes.values(), key=lambda item: item["name"].casefold())

    def get_universe(self, universe_id: str) -> Optional[Dict]:
        return self.universes.get(universe_id)

    def find_universes(self, query: str, limit: int = 6) -> List[Dict]:
        """Find local universes by name, genre, or collective."""
        terms = _tokenize(query)
        if not terms:
            return []

        ranked = []
        for universe in self.universes.values():
            name = universe["name"].casefold()
            searchable = " ".join(
                [
                    universe["name"],
                    universe.get("kind", ""),
                    " ".join(universe.get("genres", [])),
                    " ".join(universe.get("collectives", [])),
                ]
            ).casefold()
            score = sum(1 for term in terms if term in searchable)
            if query.strip().casefold() == name:
                score += 10
            elif name.startswith(query.strip().casefold()):
                score += 5
            if score:
                ranked.append((score, universe))

        ranked.sort(key=lambda item: (-item[0], item[1]["name"].casefold()))
        return [universe for _, universe in ranked[:limit]]

    def get_source(self, source_id: str) -> Dict:
        return self.sources[source_id]

    def sources_for(self, source_ids: Iterable[str]) -> List[Dict]:
        return [self.sources[source_id] for source_id in source_ids if source_id in self.sources]

    def search(
        self,
        query: str,
        *,
        universe_id: Optional[str] = None,
        include_interpretations: bool = False,
        limit: int = 4,
    ) -> List[SearchResult]:
        """Rank reviewed passages with a transparent TF-IDF-style scorer."""
        query_terms = _tokenize(query)
        if not query_terms or limit <= 0:
            return []

        allowed_claims = set(DEFAULT_ALLOWED_CLAIMS)
        if include_interpretations:
            allowed_claims.update({"critical-interpretation", "fan-theory"})

        query_phrase = " ".join(query_terms)
        total_documents = max(1, len(self.documents))
        ranked: List[SearchResult] = []

        for document in self.documents:
            if universe_id and document["universe_id"] != universe_id:
                continue
            if document["claim_type"] not in allowed_claims:
                continue

            title_terms = _tokenize(document.get("title", ""))
            body_terms = _tokenize(document.get("text", ""))
            entity_terms = _tokenize(" ".join(document.get("entities", [])))
            tag_terms = _tokenize(" ".join(document.get("tags", [])))
            searchable = " ".join(title_terms + body_terms + entity_terms + tag_terms)

            score = 0.0
            matched: List[str] = []
            for term in query_terms:
                term_frequency = (
                    body_terms.count(term)
                    + (3 * title_terms.count(term))
                    + (2.5 * entity_terms.count(term))
                    + (2 * tag_terms.count(term))
                )
                if not term_frequency:
                    continue
                document_frequency = self._document_frequencies.get(term, 1)
                inverse_frequency = math.log((total_documents + 1) / document_frequency) + 1
                score += term_frequency * inverse_frequency
                matched.append(term)

            if query_phrase and query_phrase in searchable:
                score += 4.0
            if not score:
                continue

            coverage = len(set(matched)) / len(set(query_terms))
            score *= 0.65 + (0.7 * coverage)
            confidence = min(0.96, 0.30 + (0.5 * coverage) + (score / (score + 30)))
            ranked.append(
                SearchResult(
                    document=document,
                    score=round(score, 4),
                    confidence=round(confidence, 3),
                    matched_terms=tuple(sorted(set(matched))),
                )
            )

        ranked.sort(key=lambda item: (-item.score, item.document["title"].casefold()))
        return ranked[:limit]
