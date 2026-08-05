"""Separate, freshness-aware access to upcoming concert information."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import urlopen


@dataclass(frozen=True)
class LiveEventsResult:
    status: str
    events: List[Dict]
    checked_at: str
    provider: str
    message: str


class TicketmasterEventsClient:
    """Small client for Ticketmaster Discovery API with a safe no-key state."""

    endpoint = "https://app.ticketmaster.com/discovery/v2/events.json"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 8.0):
        self.api_key = api_key if api_key is not None else os.getenv("TICKETMASTER_API_KEY")
        self.timeout = timeout

    def _request_json(self, url: str) -> Dict:
        with urlopen(url, timeout=self.timeout) as response:  # nosec B310 - fixed HTTPS host
            return json.loads(response.read().decode("utf-8"))

    def search(self, artist: str, city: str = "") -> LiveEventsResult:
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self.api_key:
            return LiveEventsResult(
                status="not-configured",
                events=[],
                checked_at=checked_at,
                provider="Ticketmaster Discovery API",
                message=(
                    "Live concerts are separate from the reviewed archive. Add a "
                    "TICKETMASTER_API_KEY to enable current results."
                ),
            )

        params = {
            "apikey": self.api_key,
            "keyword": artist,
            "classificationName": "music",
            "size": 8,
            "sort": "date,asc",
        }
        if city.strip():
            params["city"] = city.strip()

        try:
            payload = self._request_json(f"{self.endpoint}?{urlencode(params)}")
        except Exception as exc:  # network/provider failures must not crash the archive
            return LiveEventsResult(
                status="provider-error",
                events=[],
                checked_at=checked_at,
                provider="Ticketmaster Discovery API",
                message=f"The live provider could not be reached: {type(exc).__name__}.",
            )

        raw_events = payload.get("_embedded", {}).get("events", [])
        events: List[Dict] = []
        for event in raw_events:
            venue = (event.get("_embedded", {}).get("venues") or [{}])[0]
            events.append(
                {
                    "name": event.get("name", "Untitled event"),
                    "date": event.get("dates", {}).get("start", {}).get("localDate", "TBA"),
                    "time": event.get("dates", {}).get("start", {}).get("localTime", ""),
                    "venue": venue.get("name", "Venue TBA"),
                    "city": venue.get("city", {}).get("name", ""),
                    "region": venue.get("state", {}).get("stateCode", ""),
                    "url": event.get("url", ""),
                    "status": event.get("dates", {}).get("status", {}).get("code", "unknown"),
                }
            )

        return LiveEventsResult(
            status="ok",
            events=events,
            checked_at=checked_at,
            provider="Ticketmaster Discovery API",
            message=(
                f"Found {len(events)} current event result{'s' if len(events) != 1 else ''}. "
                "Verify details with the official ticket page before traveling or purchasing."
            ),
        )

