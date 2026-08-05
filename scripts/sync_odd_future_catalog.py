"""Build Odd Future member/subgroup catalogs from public catalog providers.

MusicBrainz supplies the roster, release groups, fallback track lists, and source
URLs. YouTube Music supplies direct official album-track video IDs where a
confident artist/title match exists. The generated file contains metadata and
external destinations only; it never downloads audio or republishes lyrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from ytmusicapi import YTMusic


ODD_FUTURE_MBID = "519336c2-f5a3-4137-a88e-58fecc604575"
TYLER_MBID = "f6beac20-5dfe-4d1f-ae02-0b0a740aafd6"
NA_KEL_MBID = "c3a1bcae-525d-48b5-bfef-46d3d9901ebd"
I_SMELL_PANTIES_MBID = "72fb2204-47ad-4abd-b3f0-8be1cacef86f"

# MusicBrainz currently includes this misspelled, unsupported relationship on
# the collective record. It is not part of the documented Odd Future roster.
EXCLUDED_RELATION_MBIDS = {"0a4904df-1ba9-452a-8ecc-3c950b1bcbcd"}
EXCLUDED_SECONDARY_TYPES = {
    "Audiobook",
    "Compilation",
    "DJ-mix",
    "Interview",
    "Live",
    "Remix",
}
ALLOWED_PRIMARY_TYPES = {"Album", "EP"}

# These provider records package leaked reference recordings as unofficial
# Frank Ocean albums. They are intentionally outside Threadline's public-release
# catalog even though one record is incorrectly marked Official in MusicBrainz.
EXCLUDED_RELEASE_GROUP_IDS = {
    "24d3b8f9-a099-407d-8c7a-4841c32c7f40",  # Lonny Breaux, Pt. 2
    "59d84657-3381-4db8-a36c-a6cdf86d526c",  # Dream Killa
    # Duplicate Jasper attribution; the EP is indexed under its actual duo.
    "31f0e532-d799-4daa-91b1-3ef52dc3f5b3",
}


def normalized(value: str) -> str:
    value = value.replace("‐", "-").replace("–", "-").replace("—", "-")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def slug(value: str) -> str:
    return normalized(value).replace(" ", "-") or "artist"


def colors_for(value: str) -> tuple[str, str]:
    digest = hashlib.sha256(value.encode()).hexdigest()
    hue = int(digest[:4], 16) % 360
    second = (hue + 55 + int(digest[4:8], 16) % 75) % 360
    return f"hsl({hue} 54% 48%)", f"hsl({second} 45% 25%)"


def initials(name: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", name)
    return "".join(part[0] for part in parts[:2]).upper() or "OF"


def split_title_features(title: str) -> tuple[str, List[str]]:
    match = re.search(r"\s*[\[(]feat\.\s*(.*?)[\])]$", title, re.IGNORECASE)
    if not match:
        return title, []
    features = [
        item.strip()
        for item in re.split(r",|\s+&\s+|\s+and\s+", match.group(1))
        if item.strip()
    ]
    return title[: match.start()].strip(), features


class MusicBrainz:
    base_url = "https://musicbrainz.org/ws/2"

    def __init__(self, cache_dir: Path, refresh: bool = False):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.last_request_at = 0.0
        cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        query = urlencode({**(params or {}), "fmt": "json"})
        url = f"{self.base_url}/{endpoint}?{query}"
        cache_path = self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.json"
        if cache_path.exists() and not self.refresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))

        for attempt in range(6):
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < 1.05:
                time.sleep(1.05 - elapsed)
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Threadline/0.3 (catalog sync; https://github.com/itsnotmarvin/ai110-module3show-musicrecommendersimulation-starter)",
                },
            )
            try:
                with urlopen(request, timeout=35) as response:  # nosec B310 - fixed HTTPS host
                    payload = json.loads(response.read().decode("utf-8"))
                self.last_request_at = time.monotonic()
                cache_path.write_text(json.dumps(payload), encoding="utf-8")
                return payload
            except Exception:
                self.last_request_at = time.monotonic()
                if attempt == 5:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("MusicBrainz request failed")

    def artist(self, mbid: str, relationships: bool = False) -> Dict:
        inc = "artist-rels+tags" if relationships else "tags"
        return self.get(f"artist/{mbid}", {"inc": inc})

    def release_groups(self, mbid: str) -> List[Dict]:
        groups: List[Dict] = []
        offset = 0
        while True:
            payload = self.get(
                "release-group",
                {"artist": mbid, "limit": 100, "offset": offset},
            )
            groups.extend(payload.get("release-groups", []))
            if len(groups) >= int(payload.get("release-group-count", len(groups))):
                return groups
            offset += 100

    def releases(self, release_group_id: str) -> List[Dict]:
        return self.get(
            "release",
            {
                "release-group": release_group_id,
                "inc": "recordings+artist-credits",
                "limit": 100,
            },
        ).get("releases", [])


def discover_targets(musicbrainz: MusicBrainz) -> List[Dict]:
    collective = musicbrainz.artist(ODD_FUTURE_MBID, relationships=True)
    targets = []
    for relation in collective.get("relations", []):
        if relation.get("direction") != "backward":
            continue
        relation_type = relation.get("type")
        if relation_type not in {"member of band", "subgroup"}:
            continue
        artist = relation.get("artist", {})
        mbid = artist.get("id")
        if not mbid or mbid == TYLER_MBID or mbid in EXCLUDED_RELATION_MBIDS:
            continue
        role = "subgroup" if relation_type == "subgroup" else "member"
        targets.append(
            {
                "mbid": mbid,
                "name": artist.get("name", "Unknown artist"),
                "disambiguation": artist.get("disambiguation", ""),
                "role": role,
                "begin": relation.get("begin"),
                "end": relation.get("end"),
                "ended": bool(relation.get("ended")),
            }
        )

    # The documented later-member roster includes Na-Kel Smith, although the
    # current structured relationship list omits him.
    if all(target["mbid"] != NA_KEL_MBID for target in targets):
        targets.append(
            {
                "mbid": NA_KEL_MBID,
                "name": "Na-Kel Smith",
                "disambiguation": "",
                "role": "member",
                "begin": None,
                "end": None,
                "ended": False,
                "roster_override": True,
            }
        )
    # MusicBrainz links the duo to Tyler but currently omits it from Odd
    # Future's own subgroup relationship list. Include the documented spinoff
    # so the five core music subgroups are all represented.
    if all(target["mbid"] != I_SMELL_PANTIES_MBID for target in targets):
        targets.append(
            {
                "mbid": I_SMELL_PANTIES_MBID,
                "name": "I Smell Panties",
                "disambiguation": "",
                "role": "subgroup",
                "begin": "2007",
                "end": "2008",
                "ended": True,
                "roster_override": True,
            }
        )
    return sorted(targets, key=lambda item: item["name"].casefold())


def qualifying_release_group(group: Dict) -> bool:
    if group.get("id") in EXCLUDED_RELEASE_GROUP_IDS:
        return False
    primary = group.get("primary-type")
    secondary = set(group.get("secondary-types", []))
    if secondary & EXCLUDED_SECONDARY_TYPES:
        return False
    return primary in ALLOWED_PRIMARY_TYPES or "Mixtape/Street" in secondary


def release_type(group: Dict) -> str:
    values = [group.get("primary-type") or "Release", *group.get("secondary-types", [])]
    return ", ".join(dict.fromkeys(values))


def artist_credit_names(credits: Iterable[Dict]) -> List[str]:
    names = []
    for credit in credits or []:
        name = credit.get("name") or credit.get("artist", {}).get("name")
        if name and name not in names:
            names.append(name)
    return names


def best_release(
    releases: List[Dict], first_release_date: str = ""
) -> Optional[Dict]:
    candidates = [release for release in releases if release.get("status") != "Bootleg"]
    if not candidates:
        candidates = releases

    def score(release: Dict) -> tuple:
        media = release.get("media", [])
        track_count = sum(len(medium.get("tracks", [])) for medium in media)
        digital = any(medium.get("format") == "Digital Media" for medium in media)
        official = release.get("status") == "Official"
        worldwide = release.get("country") == "XW"
        release_date = release.get("date", "")
        canonical_date = bool(first_release_date) and release_date == first_release_date
        date_distance = 99999999
        if first_release_date and release_date:
            try:
                date_distance = abs(
                    int(re.sub(r"\D", "", release_date).ljust(8, "0")[:8])
                    - int(re.sub(r"\D", "", first_release_date).ljust(8, "0")[:8])
                )
            except ValueError:
                pass
        # Prefer the original official release. This avoids selecting later
        # expanded reissues containing instrumentals merely because they have
        # more tracks (for example Earl's 2015 expanded mixtape edition).
        return official, canonical_date, digital, -date_distance, worldwide, track_count

    return max(candidates, key=score) if candidates else None


def unique_track_titles(tracks: List[Dict]) -> None:
    counts: Dict[str, int] = {}
    totals: Dict[str, int] = {}
    for track in tracks:
        key = track["title"].casefold()
        totals[key] = totals.get(key, 0) + 1
    for track in tracks:
        key = track["title"].casefold()
        counts[key] = counts.get(key, 0) + 1
        if totals[key] > 1:
            track["title"] = f"{track['title']} [version {counts[key]}]"


def external_links(track: Dict, fallback_artist: str) -> Dict:
    query_artist = ", ".join(track.get("performers") or [fallback_artist])
    query = f"{query_artist} {track['title']}"
    track["genius_url"] = "https://genius.com/search?q=" + quote_plus(query)
    track["lyrics_status"] = "external-licensed-reference"
    if track.get("youtube_id"):
        track["youtube_url"] = f"https://www.youtube.com/watch?v={track['youtube_id']}"
        track["youtube_status"] = "official-artist-channel"
    else:
        track["youtube_url"] = (
            "https://www.youtube.com/results?search_query="
            + quote_plus(query + " official audio")
        )
        track["youtube_status"] = "search-only"
    return track


def youtube_album_match(ytmusic: YTMusic, artist: str, title: str) -> Optional[Dict]:
    try:
        results = ytmusic.search(f"{artist} {title}", filter="albums", limit=10)
    except Exception:
        return None
    wanted_artist = normalized(artist).removeprefix("the ")
    wanted_title = normalized(title)
    matches = []
    for result in results:
        result_title = normalized(result.get("title", ""))
        result_artists = [
            normalized(item.get("name", "")).removeprefix("the ")
            for item in result.get("artists", [])
        ]
        artist_match = any(
            candidate == wanted_artist
            or candidate in wanted_artist
            or wanted_artist in candidate
            for candidate in result_artists
        )
        if not artist_match:
            continue
        exact = result_title == wanted_title
        expanded = result_title.startswith(wanted_title + " deluxe")
        if exact or expanded:
            matches.append((2 if exact else 1, result))
    if not matches:
        return None
    result = max(matches, key=lambda item: item[0])[1]
    browse_id = result.get("browseId")
    if not browse_id:
        return None
    try:
        album = ytmusic.get_album(browse_id)
    except Exception:
        return None
    album["_search_result"] = result
    return album


def youtube_tracks(album: Dict, fallback_artist: str) -> List[Dict]:
    tracks = []
    for position, source in enumerate(album.get("tracks", []), start=1):
        title, features = split_title_features(source.get("title", "Untitled"))
        performers = artist_credit_names(source.get("artists", [])) or [fallback_artist]
        track = {
            "position": position,
            "title": title,
            "performers": performers,
            "featured_artists": features,
            "theme": (
                "Collaboration featuring " + ", ".join(features)
                if features
                else "Catalog track"
            ),
        }
        if source.get("videoId"):
            track["youtube_id"] = source["videoId"]
        tracks.append(external_links(track, fallback_artist))
    unique_track_titles(tracks)
    return tracks


def musicbrainz_tracks(release: Dict, fallback_artist: str) -> List[Dict]:
    tracks = []
    position = 0
    for disc, medium in enumerate(release.get("media", []), start=1):
        for disc_position, source in enumerate(medium.get("tracks", []), start=1):
            position += 1
            performers = artist_credit_names(source.get("artist-credit", []))
            if not performers:
                performers = artist_credit_names(
                    source.get("recording", {}).get("artist-credit", [])
                )
            track = {
                "position": position,
                "disc": disc,
                "disc_position": disc_position,
                "title": source.get("title", "Untitled"),
                "performers": performers or [fallback_artist],
                "featured_artists": [],
                "theme": "Catalog track",
            }
            tracks.append(external_links(track, fallback_artist))
    unique_track_titles(tracks)
    return tracks


def build_album(
    musicbrainz: MusicBrainz,
    ytmusic: YTMusic,
    artist: Dict,
    group: Dict,
) -> Dict:
    title = group.get("title", "Untitled")
    year_text = str(group.get("first-release-date", ""))[:4]
    year: int | str = int(year_text) if year_text.isdigit() else "Date unknown"
    album_type = release_type(group)
    youtube_album = youtube_album_match(ytmusic, artist["name"], title)
    youtube_playlist_url = None
    release_url = f"https://musicbrainz.org/release-group/{group['id']}"
    if youtube_album and youtube_album.get("tracks"):
        tracks = youtube_tracks(youtube_album, artist["name"])
        playlist_id = youtube_album.get("audioPlaylistId") or youtube_album.get(
            "_search_result", {}
        ).get("playlistId")
        if playlist_id:
            youtube_playlist_url = (
                "https://music.youtube.com/playlist?list=" + playlist_id
            )
    else:
        release = best_release(
            musicbrainz.releases(group["id"]),
            str(group.get("first-release-date", "")),
        )
        tracks = musicbrainz_tracks(release, artist["name"]) if release else []
        if release:
            release_url = f"https://musicbrainz.org/release/{release['id']}"

    accent, _ = colors_for(group["id"])
    album = {
        "id": f"rg-{group['id']}",
        "title": title,
        "year": year,
        "type": album_type,
        "accent": accent,
        "summary": (
            f"Generated catalog entry with {len(tracks)} indexed track"
            f"{'s' if len(tracks) != 1 else ''}."
        ),
        "before": (
            "Catalog metadata synchronized from MusicBrainz and, when an exact "
            "match was available, YouTube Music. No reviewed narrative has been "
            "written for this release yet."
        ),
        "tracks": tracks,
        "connections": [],
        "source_ids": [],
        "tracklist_source_url": release_url,
        "musicbrainz_url": f"https://musicbrainz.org/release-group/{group['id']}",
        "catalog_complete": bool(tracks),
        "catalog_track_count": len(tracks),
        "catalog_generated": True,
    }
    if youtube_playlist_url:
        album["youtube_playlist_url"] = youtube_playlist_url
    return album


def build_artist(
    musicbrainz: MusicBrainz,
    ytmusic: YTMusic,
    target: Dict,
) -> Dict:
    details = musicbrainz.artist(target["mbid"])
    target = {**target, **{key: details.get(key, target.get(key)) for key in ("name", "type", "country", "area", "disambiguation")}}
    groups = [
        group
        for group in musicbrainz.release_groups(target["mbid"])
        if qualifying_release_group(group)
    ]
    groups.sort(
        key=lambda group: (
            not bool(group.get("first-release-date")),
            group.get("first-release-date", ""),
            group.get("title", "").casefold(),
        )
    )
    albums = []
    for index, group in enumerate(groups, start=1):
        print(f"  [{index}/{len(groups)}] {group.get('title')}", flush=True)
        albums.append(build_album(musicbrainz, ytmusic, target, group))

    artist_id = slug(target["name"])
    accent, secondary = colors_for(target["mbid"])
    tags = sorted(
        details.get("tags", []),
        key=lambda tag: -int(tag.get("count", 0)),
    )
    role_label = "Odd Future subgroup" if target["role"] == "subgroup" else "Odd Future member"
    relationship = "Subgroup" if target["role"] == "subgroup" else (
        "Former member" if target.get("ended") else "Member"
    )
    location = (
        (details.get("area") or {}).get("name")
        or details.get("country")
        or "Location not listed"
    )
    total_tracks = sum(len(album["tracks"]) for album in albums)
    return {
        "id": artist_id,
        "mbid": target["mbid"],
        "reviewed": False,
        "catalog_generated": True,
        "name": target["name"],
        "kind": role_label + " catalog",
        "initials": initials(target["name"]),
        "accent": accent,
        "accent_secondary": secondary,
        "tagline": "A synchronized catalog connected to the Odd Future universe.",
        "summary": (
            f"Generated catalog coverage for {target['name']}: {len(albums)} album, "
            f"EP, or mixtape release{'s' if len(albums) != 1 else ''} and "
            f"{total_tracks} indexed track{'s' if total_tracks != 1 else ''}."
        ),
        "coverage": "Generated MusicBrainz + YouTube Music catalog metadata",
        "catalog_coverage": {
            "releases": len(albums),
            "tracks": total_tracks,
        },
        "genres": [tag["name"] for tag in tags[:5]] or ["Catalog metadata"],
        "collectives": ["Odd Future"],
        "location": location,
        "catalog_score": 100,
        "catalog_url": f"https://musicbrainz.org/artist/{target['mbid']}",
        "catalog_status": "static-synced",
        "odd_future_role": target["role"],
        "membership_begin": target.get("begin"),
        "membership_end": target.get("end"),
        "membership_ended": bool(target.get("ended")),
        "popular_tracks": [],
        "albums": albums,
        "chapters": [],
        "related": [
            {"universe_id": "odd-future", "relationship": relationship}
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/odd_future_members.json"),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".catalog-cache/musicbrainz"),
    )
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    musicbrainz = MusicBrainz(args.cache_dir, refresh=args.refresh)
    ytmusic = YTMusic()
    targets = discover_targets(musicbrainz)
    artists = []
    for index, target in enumerate(targets, start=1):
        print(f"[{index}/{len(targets)}] {target['name']}", flush=True)
        artists.append(build_artist(musicbrainz, ytmusic, target))

    payload = {
        "catalog_version": "1.0.0",
        "generated_at": time.strftime("%Y-%m-%d"),
        "collective_mbid": ODD_FUTURE_MBID,
        "provider_note": (
            "Roster and release metadata come from MusicBrainz. Exact album "
            "matches on YouTube Music supply official video IDs. LRCLIB lyrics are "
            "fetched only when a song page opens; Genius remains a fallback "
            "destination and lyric text is not stored."
        ),
        "artists": artists,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    release_count = sum(len(artist["albums"]) for artist in artists)
    track_count = sum(
        len(album["tracks"])
        for artist in artists
        for album in artist["albums"]
    )
    print(
        f"Wrote {args.output}: {len(artists)} artists/subgroups, "
        f"{release_count} releases, {track_count} tracks"
    )


if __name__ == "__main__":
    main()
