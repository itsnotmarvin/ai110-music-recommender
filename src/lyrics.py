"""Timestamped lyric parsing and on-demand LRCLIB lookup utilities."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(value: str) -> List[Dict]:
    """Parse standard LRC timestamps into karaoke cue dictionaries.

    Metadata tags such as ``[ar:Artist]`` are ignored. Multiple timestamps on
    one line create multiple cues with the same text.
    """
    cues: List[Dict] = []
    for raw_line in value.splitlines():
        matches = list(_TIMESTAMP.finditer(raw_line))
        if not matches:
            continue
        text = _TIMESTAMP.sub("", raw_line).strip()
        if not text:
            continue
        for match in matches:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            fraction_text = match.group(3) or "0"
            fraction = int(fraction_text) / (10 ** len(fraction_text))
            cues.append(
                {
                    "time": round((minutes * 60) + seconds + fraction, 3),
                    "section": "Timed lyric",
                    "text": text,
                }
            )
    cues.sort(key=lambda cue: cue["time"])
    return cues


def _normalized(value: str) -> str:
    value = re.sub(r"\s*\[version\s+\d+\]\s*$", "", value, flags=re.IGNORECASE)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


@dataclass(frozen=True)
class LyricsLookupResult:
    """One normalized LRCLIB result safe for the song-page boundary."""

    status: str
    cues: List[Dict]
    plain_lyrics: str
    record_id: Optional[int]
    provider_url: str
    message: str

    def to_dict(self) -> Dict:
        return asdict(self)


class LrcLibClient:
    """Fetch synchronized lyrics without persisting them in the archive."""

    endpoint = "https://lrclib.net/api/search"

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout
        self.user_agent = "Threadline/0.3 (https://github.com/)"

    def _request_json(self, url: str) -> List[Dict]:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
                "X-User-Agent": self.user_agent,
                "Lrclib-Client": self.user_agent,
            },
        )
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310 - fixed HTTPS host
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("LRCLIB search returned an unexpected payload")
        return payload

    @staticmethod
    def _artist_score(expected: str, candidate: str) -> int:
        wanted = _normalized(expected)
        found = _normalized(candidate)
        if not wanted or not found:
            return 0
        if wanted == found:
            return 4
        if wanted in found or found in wanted:
            return 2
        wanted_terms = set(wanted.split())
        found_terms = set(found.split())
        overlap = len(wanted_terms & found_terms) / max(1, len(wanted_terms))
        return 1 if overlap >= 0.75 else 0

    def search(self, track: str, artist: str, album: str = "") -> LyricsLookupResult:
        clean_track = " ".join(track.split())
        search_track = re.sub(
            r"\s*\[version\s+\d+\]\s*$", "", clean_track, flags=re.IGNORECASE
        )
        clean_artist = " ".join(artist.split())
        clean_album = " ".join(album.split())
        if not clean_track or not clean_artist:
            return LyricsLookupResult(
                "invalid-input", [], "", None, "https://lrclib.net/", "Track and artist are required.",
            )

        params = {"track_name": search_track, "artist_name": clean_artist}
        if clean_album:
            params["album_name"] = clean_album
        try:
            records = self._request_json(f"{self.endpoint}?{urlencode(params)}")
            if not records and clean_album:
                records = self._request_json(
                    f"{self.endpoint}?{urlencode({'track_name': search_track, 'artist_name': clean_artist})}"
                )
        except Exception as exc:
            return LyricsLookupResult(
                "provider-error",
                [],
                "",
                None,
                "https://lrclib.net/",
                f"LRCLIB is temporarily unavailable: {type(exc).__name__}.",
            )

        wanted_title = _normalized(clean_track)
        wanted_album = _normalized(clean_album)
        ranked = []
        for record in records:
            if _normalized(str(record.get("trackName", ""))) != wanted_title:
                continue
            artist_score = self._artist_score(
                clean_artist, str(record.get("artistName", ""))
            )
            if not artist_score:
                continue
            candidate_album = _normalized(str(record.get("albumName", "")))
            album_score = 0
            if wanted_album and candidate_album:
                if wanted_album == candidate_album:
                    album_score = 3
                elif wanted_album in candidate_album or candidate_album in wanted_album:
                    album_score = 1
            synced = bool(str(record.get("syncedLyrics") or "").strip())
            plain = bool(str(record.get("plainLyrics") or "").strip())
            ranked.append(
                (
                    artist_score + album_score + (5 if synced else 0) + (1 if plain else 0),
                    record,
                )
            )

        if not ranked:
            return LyricsLookupResult(
                "not-found",
                [],
                "",
                None,
                "https://lrclib.net/",
                "No confident LRCLIB match was found for this recording.",
            )

        record = max(ranked, key=lambda item: item[0])[1]
        record_id = record.get("id")
        provider_url = (
            f"https://lrclib.net/tracks/{record_id}"
            if isinstance(record_id, int)
            else "https://lrclib.net/"
        )
        if record.get("instrumental"):
            return LyricsLookupResult(
                "instrumental",
                [],
                "",
                record_id if isinstance(record_id, int) else None,
                provider_url,
                "LRCLIB marks this recording as instrumental.",
            )

        synced_lyrics = str(record.get("syncedLyrics") or "")
        plain_lyrics = str(record.get("plainLyrics") or "").strip()
        cues = parse_lrc(synced_lyrics)
        if not cues and not plain_lyrics:
            return LyricsLookupResult(
                "not-found",
                [],
                "",
                record_id if isinstance(record_id, int) else None,
                provider_url,
                "The matching LRCLIB record does not contain displayable lyrics.",
            )
        return LyricsLookupResult(
            "matched",
            cues,
            plain_lyrics,
            record_id if isinstance(record_id, int) else None,
            provider_url,
            (
                "Synchronized lyrics loaded from LRCLIB."
                if cues
                else "Plain lyrics loaded from LRCLIB; synchronized timing is unavailable."
            ),
        )
