import json
from pathlib import Path

from src.archive import ArchiveRepository
from src.song_context import build_song_context


ROOT = Path(__file__).resolve().parents[1]


def _fixtures():
    repository = ArchiveRepository.from_json(ROOT / "data" / "archive.json")
    context_index = json.loads(
        (ROOT / "data" / "song_contexts.json").read_text(encoding="utf-8")
    )
    return repository, context_index


def _song(universe, album, track):
    return {
        **track,
        "artist": universe["name"],
        "album": album["title"],
        "album_year": album["year"],
    }


def test_every_odd_future_group_song_has_reviewed_context():
    repository, context_index = _fixtures()
    universe = repository.get_universe("odd-future")
    songs = [
        _song(universe, album, track)
        for album in universe["albums"]
        for track in album["tracks"]
    ]

    assert len(songs) == 67
    for song in songs:
        context = build_song_context(repository.data, context_index, song)
        assert context["status"] == "ok"
        assert context["primary"]["title"]
        assert context["primary"]["summary"]
        assert context["primary"]["boundary"]
        assert context["source_ids"]


def test_context_builder_scales_to_member_and_subgroup_catalogs():
    repository, context_index = _fixtures()
    checked = 0
    for universe in repository.data["universes"]:
        if universe.get("id") != "odd-future" and not universe.get("odd_future_role"):
            continue
        for album in universe.get("albums", []):
            for track in album.get("tracks", []):
                context = build_song_context(
                    repository.data,
                    context_index,
                    _song(universe, album, track),
                )
                assert context["status"] == "ok"
                assert context["scope"] in {
                    "track-specific",
                    "release-era",
                    "artist-era",
                    "catalog-only",
                }
                checked += 1

    assert checked >= 1400


def test_oldie_uses_track_specific_context_and_separates_performers():
    repository, context_index = _fixtures()
    universe = repository.get_universe("odd-future")
    album = next(item for item in universe["albums"] if item["id"] == "of-tape-vol-2")
    track = next(item for item in album["tracks"] if item["title"] == "Oldie")

    context = build_song_context(
        repository.data, context_index, _song(universe, album, track)
    )

    assert context["scope"] == "track-specific"
    assert len(context["performer_threads"]) >= 7
    assert all(thread["summary"] for thread in context["performer_threads"])


def test_release_proximity_never_becomes_an_influence_claim():
    repository, context_index = _fixtures()
    universe = repository.get_universe("odd-future")
    album = next(item for item in universe["albums"] if item["id"] == "of-tape-vol-2")
    track = next(item for item in album["tracks"] if item["title"] == "Analog 2")

    context = build_song_context(
        repository.data, context_index, _song(universe, album, track)
    )

    assert context["nearby_releases"]
    assert "does not prove" in context["nearby_release_note"]
    assert context["scope"] == "release-era"


def test_album_background_is_shared_until_a_song_specific_source_exists():
    repository, context_index = _fixtures()
    universe = repository.get_universe("odd-future")
    album = next(item for item in universe["albums"] if item["id"] == "of-tape-vol-2")

    contexts = {}
    for title in ("Analog 2", "Rella", "Oldie"):
        track = next(item for item in album["tracks"] if item["title"] == title)
        contexts[title] = build_song_context(
            repository.data, context_index, _song(universe, album, track)
        )

    assert contexts["Analog 2"]["album_background"] == contexts["Rella"]["album_background"]
    assert contexts["Analog 2"]["song_background"]["status"] == "not-reviewed"
    assert contexts["Rella"]["song_background"]["status"] == "not-reviewed"
    assert contexts["Oldie"]["album_background"] == contexts["Analog 2"]["album_background"]
    assert contexts["Oldie"]["song_background"]["status"] == "reviewed"
    assert contexts["Oldie"]["scope"] == "track-specific"
