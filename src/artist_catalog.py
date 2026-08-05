"""Universal artist lookup backed by the public MusicBrainz catalog.

Catalog metadata is not part of the reviewed story archive.  The UI labels it
as external and current so a search result cannot be mistaken for an approved
narrative chapter.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ArtistSearchResult:
    mbid: str
    name: str
    artist_type: str
    country: str
    area: str
    disambiguation: str
    score: int
    tags: List[str]

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass(frozen=True)
class CatalogSearchResponse:
    status: str
    artists: List[ArtistSearchResult]
    message: str


class MusicBrainzCatalogClient:
    """Search artist identities and release groups without an API key."""

    base_url = "https://musicbrainz.org/ws/2"

    def __init__(self, timeout: float = 8.0, contact_url: Optional[str] = None):
        self.timeout = timeout
        self.contact_url = contact_url or os.getenv(
            "THREADLINE_CONTACT_URL",
            "https://github.com/itsnotmarvin/ai110-module3show-musicrecommendersimulation-starter",
        )
        self.user_agent = f"Threadline/0.1 (classroom music archive; {self.contact_url})"

    def _request_json(self, url: str) -> Dict:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310 - fixed HTTPS host
            return json.loads(response.read().decode("utf-8"))

    def search_artists(self, query: str, limit: int = 8) -> CatalogSearchResponse:
        clean_query = " ".join(query.split())
        if not clean_query:
            return CatalogSearchResponse("invalid-input", [], "Enter an artist name.")

        params = urlencode(
            {
                "query": clean_query,
                "fmt": "json",
                "limit": max(1, min(limit, 12)),
                "dismax": "true",
            }
        )
        try:
            payload = self._request_json(f"{self.base_url}/artist/?{params}")
        except Exception as exc:
            return CatalogSearchResponse(
                "provider-error",
                [],
                f"Artist catalog search is temporarily unavailable: {type(exc).__name__}.",
            )

        artists = []
        for item in payload.get("artists", []):
            tags = sorted(
                item.get("tags", []),
                key=lambda tag: -int(tag.get("count", 0)),
            )
            artists.append(
                ArtistSearchResult(
                    mbid=item["id"],
                    name=item.get("name", "Unknown artist"),
                    artist_type=item.get("type", "Artist"),
                    country=item.get("country", ""),
                    area=item.get("area", {}).get("name", ""),
                    disambiguation=item.get("disambiguation", ""),
                    score=int(item.get("score", 0)),
                    tags=[tag["name"] for tag in tags[:4]],
                )
            )
        return CatalogSearchResponse(
            "ok",
            artists,
            f"Found {len(artists)} artist match{'es' if len(artists) != 1 else ''}.",
        )

    def load_profile(self, artist: Dict) -> Dict:
        """Build a browseable, explicitly unreviewed profile from release groups."""
        mbid = artist["mbid"]
        params = urlencode(
            {
                "artist": mbid,
                "fmt": "json",
                "limit": 100,
            }
        )
        releases: List[Dict] = []
        status = "ok"
        try:
            payload = self._request_json(f"{self.base_url}/release-group?{params}")
            seen = set()
            for item in payload.get("release-groups", []):
                title = item.get("title", "Untitled")
                primary_type = item.get("primary-type") or "Release"
                secondary_types = item.get("secondary-types", [])
                if primary_type not in {"Album", "EP"} and "Mixtape/Street" not in secondary_types:
                    continue
                key = (title.casefold(), item.get("first-release-date", "")[:4])
                if key in seen:
                    continue
                seen.add(key)
                releases.append(
                    {
                        "id": item["id"],
                        "title": title,
                        "year": item.get("first-release-date", "")[:4] or "Date unknown",
                        "type": ", ".join([primary_type] + secondary_types),
                        "musicbrainz_url": f"https://musicbrainz.org/release-group/{item['id']}",
                    }
                )
        except Exception:
            status = "partial"

        releases.sort(
            key=lambda release: (
                release["year"] == "Date unknown",
                release["year"],
                release["title"].casefold(),
            )
        )
        accent, secondary = self._colors_for(mbid)
        initials = "".join(part[0] for part in artist["name"].split()[:2]).upper() or "♪"
        location = artist.get("area") or artist.get("country") or "Location not listed"
        description = artist.get("disambiguation") or (
            "This catalog identity does not yet have a reviewed Threadline narrative."
        )
        return {
            "id": f"catalog:{mbid}",
            "mbid": mbid,
            "reviewed": False,
            "catalog_status": status,
            "name": artist["name"],
            "kind": f"{artist.get('artist_type') or 'Artist'} catalog profile",
            "initials": initials,
            "accent": accent,
            "accent_secondary": secondary,
            "tagline": "A universal catalog profile. A reviewed story can be added without changing this artist's identity.",
            "summary": description,
            "coverage": "Live MusicBrainz catalog lookup",
            "genres": artist.get("tags") or [artist.get("artist_type") or "Artist"],
            "collectives": [],
            "location": location,
            "catalog_score": artist.get("score", 0),
            "catalog_url": f"https://musicbrainz.org/artist/{mbid}",
            "popular_tracks": [],
            "albums": releases,
            "chapters": [],
            "related": [],
        }

    @staticmethod
    def _colors_for(value: str) -> tuple[str, str]:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        hue = int(digest[:4], 16) % 360
        second_hue = (hue + 52 + (int(digest[4:8], 16) % 80)) % 360
        return f"hsl({hue} 54% 48%)", f"hsl({second_hue} 45% 25%)"
