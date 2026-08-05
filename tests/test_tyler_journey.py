import json
from pathlib import Path

from src.archive import ArchiveRepository


ROOT = Path(__file__).resolve().parents[1]


def load_journey() -> dict:
    return json.loads((ROOT / "data" / "tyler_journey.json").read_text(encoding="utf-8"))


def test_tyler_journey_covers_every_release_in_chronological_order():
    repository = ArchiveRepository.from_json(ROOT / "data" / "archive.json")
    universe = repository.get_universe("tyler-the-creator")
    journey = load_journey()

    assert journey["artist_id"] == universe["id"]
    assert [release["album_id"] for release in journey["releases"]] == [
        album["id"] for album in universe["albums"]
    ]
    assert len(journey["releases"]) == 9


def test_every_journey_chapter_has_three_real_essential_tracks_and_a_transition():
    repository = ArchiveRepository.from_json(ROOT / "data" / "archive.json")
    universe = repository.get_universe("tyler-the-creator")
    journey = load_journey()
    albums = {album["id"]: album for album in universe["albums"]}

    for release in journey["releases"]:
        album = albums[release["album_id"]]
        catalog_titles = {track["title"] for track in album["tracks"]}
        essential_tracks = release["essential_tracks"]

        assert release["chapter_title"]
        assert release["transition"]
        assert len(essential_tracks) == 3
        assert len({track["title"] for track in essential_tracks}) == 3
        assert {track["title"] for track in essential_tracks} <= catalog_titles
        assert all(track["focus"] for track in essential_tracks)


def test_journey_uses_reviewed_album_context_for_every_chapter():
    repository = ArchiveRepository.from_json(ROOT / "data" / "archive.json")
    universe = repository.get_universe("tyler-the-creator")
    journey = load_journey()
    albums = {album["id"]: album for album in universe["albums"]}

    for release in journey["releases"]:
        album = albums[release["album_id"]]
        assert album["before"]
        assert album["summary"]
        assert album["source_ids"]
