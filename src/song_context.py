"""Build source-backed listening context for every Odd Future network song.

The builder deliberately separates artist statements, reported era context, and
release proximity. It never converts two nearby releases into a claim of
influence and never invents a private mental state for an artist.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, Optional


IDENTITY_ALIASES = {
    "hodgy beats": "hodgy",
    "taco": "taco-bennett",
    "wolf haley": "tyler-the-creator",
}


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode().casefold()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _year(value: object) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 1900 <= parsed <= 2100 else None


def _era_distance(era: object, release_year: int) -> int:
    years = [int(value) for value in re.findall(r"(?:19|20)\d{2}", str(era))]
    if not years:
        return 100
    start, end = min(years), max(years)
    if len(years) == 1 and "present" in str(era).casefold():
        end = 2100
    if start <= release_year <= end:
        return 0
    return min(abs(release_year - start), abs(release_year - end))


def _find_universe(data: Dict, artist_name: object) -> Optional[Dict]:
    wanted = _normalized(artist_name)
    alias_id = IDENTITY_ALIASES.get(wanted)
    for universe in data.get("universes", []):
        if alias_id and universe.get("id") == alias_id:
            return universe
        if _normalized(universe.get("name")) == wanted:
            return universe
    return None


def _is_odd_future_network(universe: Dict) -> bool:
    return bool(
        universe.get("id") == "odd-future"
        or universe.get("odd_future_role")
        or "Odd Future" in universe.get("collectives", [])
    )


def _matching_song_chapter(
    universe: Optional[Dict],
    track_title: object,
    track_universe_id: str,
) -> Optional[Dict]:
    if not universe:
        return None
    wanted_title = _normalized(track_title)
    for chapter in universe.get("chapters", []):
        for link in chapter.get("song_links", []):
            target_id = link.get("universe_id", universe.get("id"))
            if target_id != track_universe_id:
                continue
            if _normalized(link.get("track_title")) == wanted_title:
                return chapter
    return None


def _nearest_chapter(universe: Optional[Dict], release_year: int) -> Optional[Dict]:
    if not universe or not universe.get("chapters"):
        return None
    return min(
        universe["chapters"],
        key=lambda chapter: (
            _era_distance(chapter.get("era"), release_year),
            0 if chapter.get("claim_type") == "artist-stated" else 1,
        ),
    )


def _release_context(context_index: Dict, track: Dict) -> Optional[Dict]:
    wanted_artist = _normalized(track.get("artist"))
    wanted_album = _normalized(track.get("album"))
    return next(
        (
            item
            for item in context_index.get("release_contexts", [])
            if _normalized(item.get("artist")) == wanted_artist
            and _normalized(item.get("album")) == wanted_album
        ),
        None,
    )


def _performer_threads(
    data: Dict,
    track: Dict,
    track_universe: Dict,
    release_year: int,
) -> list[Dict]:
    threads = []
    seen = set()
    for performer in track.get("performers") or [track.get("artist")]:
        identity = _normalized(performer)
        if not identity or identity in seen or identity == _normalized(track_universe["name"]):
            continue
        seen.add(identity)
        universe = _find_universe(data, performer)
        if universe is None:
            threads.append(
                {
                    "artist": performer,
                    "status": "not-reviewed",
                    "claim_type": "evidence-boundary",
                    "title": "No reviewed interview context indexed",
                    "summary": "Threadline has this performance credit, but not enough sourced material to describe what this artist was thinking during the release period.",
                    "source_ids": [],
                    "universe_id": None,
                }
            )
            continue

        chapter = _matching_song_chapter(
            universe, track.get("title"), track_universe["id"]
        ) or _nearest_chapter(universe, release_year)
        if chapter is None:
            threads.append(
                {
                    "artist": performer,
                    "status": "not-reviewed",
                    "claim_type": "evidence-boundary",
                    "title": "Cataloged, but not interpreted",
                    "summary": "A local catalog exists for this artist, but no reviewed statement or era chapter supports a headspace claim here.",
                    "source_ids": [],
                    "universe_id": universe["id"],
                }
            )
            continue

        threads.append(
            {
                "artist": universe["name"],
                "status": "reviewed",
                "claim_type": chapter["claim_type"],
                "title": chapter["title"],
                "summary": chapter["dek"],
                "era": chapter.get("era", ""),
                "source_ids": chapter.get("source_ids", []),
                "universe_id": universe["id"],
            }
        )
    return threads


def _nearby_releases(
    data: Dict,
    track: Dict,
    release_year: int,
    performer_universe_ids: Iterable[str],
    *,
    limit: int = 6,
) -> list[Dict]:
    performer_ids = set(performer_universe_ids)
    candidates = []
    for universe in data.get("universes", []):
        if not _is_odd_future_network(universe):
            continue
        for album in universe.get("albums", []):
            album_year = _year(album.get("year"))
            if album_year is None or abs(album_year - release_year) > 1:
                continue
            if (
                _normalized(universe.get("name")) == _normalized(track.get("artist"))
                and _normalized(album.get("title")) == _normalized(track.get("album"))
            ):
                continue
            candidates.append(
                {
                    "artist": universe["name"],
                    "title": album["title"],
                    "year": album_year,
                    "type": album.get("type", "Release"),
                    "universe_id": universe["id"],
                    "source_ids": [f"musicbrainz-catalog-{universe['id']}"],
                    "_rank": (
                        0 if universe["id"] in performer_ids else 1,
                        abs(album_year - release_year),
                        universe["name"].casefold(),
                        album["title"].casefold(),
                    ),
                }
            )
    candidates.sort(key=lambda item: item["_rank"])
    for item in candidates:
        item.pop("_rank", None)
    return candidates[:limit]


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def build_song_context(data: Dict, context_index: Dict, track: Dict) -> Dict:
    """Return an evidence-labeled context package for one local song."""
    release_year = _year(track.get("album_year"))
    track_universe = _find_universe(data, track.get("artist"))
    if release_year is None or track_universe is None:
        return {
            "status": "unavailable",
            "message": "A reviewed artist identity and release year are required.",
        }

    release_context = _release_context(context_index, track)
    direct_chapter = _matching_song_chapter(
        track_universe, track.get("title"), track_universe["id"]
    )
    era_chapter = _nearest_chapter(track_universe, release_year)

    if release_context is not None:
        album_background = dict(release_context)
        album_scope = "release-era"
    elif era_chapter is not None:
        album_background = {
            "title": era_chapter["title"],
            "summary": era_chapter["dek"],
            "claim_type": era_chapter["claim_type"],
            "source_ids": era_chapter.get("source_ids", []),
            "statement_timing": f"Nearest reviewed artist chapter · {era_chapter.get('era', '')}",
            "boundary": "No reviewed album-level interview is indexed. This is the closest sourced artist-era context, not a private-state inference.",
        }
        album_scope = "artist-era"
    else:
        album_background = {
            "title": "Cataloged without an album-era headspace claim",
            "summary": "The release is present in the verified catalog, but Threadline does not yet have a reviewed interview or era chapter that explains the artist's working context before release.",
            "claim_type": "evidence-boundary",
            "source_ids": [],
            "statement_timing": "No reviewed album statement indexed",
            "boundary": "Threadline leaves this unknown rather than generating a psychological explanation.",
        }
        album_scope = "catalog-only"

    if direct_chapter is not None:
        song_background = {
            "status": "reviewed",
            "title": direct_chapter["title"],
            "summary": direct_chapter["dek"],
            "claim_type": direct_chapter["claim_type"],
            "source_ids": direct_chapter.get("source_ids", []),
            "statement_timing": f"Track-linked reviewed chapter · {direct_chapter.get('era', '')}",
            "boundary": "This archive chapter names the song directly. Its claim label still controls how strongly the context should be read.",
        }
        scope = "track-specific"
    else:
        song_background = {
            "status": "not-reviewed",
            "title": "No separate reviewed song background yet",
            "summary": "No indexed public statement discusses this exact song. Until one is reviewed, Threadline uses the album background above and does not invent a song-specific motive or mental state.",
            "claim_type": "evidence-boundary",
            "source_ids": [],
            "statement_timing": "Album-level fallback is active",
            "boundary": "This absence is meaningful: the shared album context is supported, but a unique explanation for this song is not.",
        }
        scope = album_scope

    # ``primary`` remains as a compatibility view for callers that want the most
    # specific supported context. The UI presents both layers explicitly.
    primary = song_background if direct_chapter is not None else album_background

    performer_threads = _performer_threads(
        data, track, track_universe, release_year
    )
    performer_ids = [
        thread["universe_id"]
        for thread in performer_threads
        if thread.get("universe_id")
    ]
    nearby_releases = _nearby_releases(
        data, track, release_year, performer_ids
    )
    source_ids = _unique(
        [
            *album_background.get("source_ids", []),
            *song_background.get("source_ids", []),
            *(
                source_id
                for thread in performer_threads
                for source_id in thread.get("source_ids", [])
            ),
            *(
                source_id
                for release in nearby_releases
                for source_id in release.get("source_ids", [])
            ),
        ]
    )
    available_source_ids = {
        source.get("id") for source in data.get("sources", [])
    }

    return {
        "status": "ok",
        "scope": scope,
        "release_year": release_year,
        "primary": primary,
        "album_background": album_background,
        "song_background": song_background,
        "performer_threads": performer_threads,
        "nearby_releases": nearby_releases,
        "nearby_release_note": "These releases were nearby in the Odd Future network. Chronology can suggest context, but it does not prove that one artist or record influenced another.",
        "source_ids": [
            source_id for source_id in source_ids if source_id in available_source_ids
        ],
        "reviewed_at": context_index.get("reviewed_at", ""),
    }
