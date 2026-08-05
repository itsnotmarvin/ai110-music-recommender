from pathlib import Path

import pytest

from src.archive import ArchiveRepository, ArchiveValidationError


ARCHIVE_PATH = Path(__file__).resolve().parents[1] / "data" / "archive.json"


def test_reviewed_archive_loads_and_connections_resolve():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)

    assert repository.get_universe("tyler-the-creator")["name"] == "Tyler, the Creator"
    for universe in repository.list_universes():
        for relation in universe.get("related", []):
            assert repository.get_universe(relation["universe_id"]) is not None


def test_search_finds_relevant_reviewed_passage():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)

    results = repository.search(
        "How did Odd Future use Tumblr and YouTube?",
        universe_id="odd-future",
    )

    assert results
    assert results[0].document["id"] == "doc-of-internet-world"
    assert results[0].confidence >= 0.7


def test_critical_interpretation_is_opt_in():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)

    default_results = repository.search(
        "How did Flower Boy show creative growth?",
        universe_id="tyler-the-creator",
    )
    expanded_results = repository.search(
        "How did Flower Boy show creative growth?",
        universe_id="tyler-the-creator",
        include_interpretations=True,
    )

    assert all(
        result.document["claim_type"] != "critical-interpretation"
        for result in default_results
    )
    assert any(
        result.document["claim_type"] == "critical-interpretation"
        for result in expanded_results
    )


def test_archive_rejects_unknown_claim_type():
    data = {
        "archive_version": "test",
        "reviewed_at": "2026-08-04",
        "sources": [
            {"id": "s1", "url": "https://example.com", "title": "Test"}
        ],
        "universes": [
            {"id": "u1", "name": "Test", "related": []}
        ],
        "documents": [
            {
                "id": "d1",
                "universe_id": "u1",
                "claim_type": "rumor-presented-as-fact",
                "source_ids": ["s1"],
            }
        ],
    }

    with pytest.raises(ArchiveValidationError):
        ArchiveRepository(data)


def test_tyler_discography_draft_shows_every_release_chapter():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    albums = repository.get_universe("tyler-the-creator")["albums"]

    assert [album["id"] for album in albums] == [
        "bastard",
        "goblin",
        "wolf",
        "cherry-bomb",
        "flower-boy",
        "igor",
        "call-me-if-you-get-lost",
        "chromakopia",
        "dont-tap-the-glass",
    ]
    assert all(album["summary"] and album["before"] for album in albums)


def test_tyler_track_catalog_is_complete_through_current_deluxe_editions():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    albums = repository.get_universe("tyler-the-creator")["albums"]

    assert {album["id"]: len(album["tracks"]) for album in albums} == {
        "bastard": 15,
        "goblin": 18,
        "wolf": 18,
        "cherry-bomb": 13,
        "flower-boy": 14,
        "igor": 12,
        "call-me-if-you-get-lost": 24,
        "chromakopia": 15,
        "dont-tap-the-glass": 10,
    }
    assert all(album["catalog_complete"] for album in albums)


def test_odd_future_core_collective_catalog_is_present():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    albums = repository.get_universe("odd-future")["albums"]

    assert [album["id"] for album in albums] == [
        "odd-future-tape",
        "radical",
        "12-odd-future-songs",
        "of-tape-vol-2",
    ]
    assert [len(album["tracks"]) for album in albums] == [19, 17, 13, 18]


def test_every_catalog_track_has_safe_external_music_and_lyrics_destinations():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    tracks = [
        track
        for universe_id in ("tyler-the-creator", "odd-future")
        for album in repository.get_universe(universe_id)["albums"]
        for track in album["tracks"]
    ]

    assert len(tracks) == 206
    assert sum(track.get("youtube_status") == "official-artist-channel" for track in tracks) == 169
    for track in tracks:
        assert track["performers"]
        assert track["youtube_url"].startswith("https://www.youtube.com/")
        assert track["genius_url"].startswith("https://genius.com/")
        assert track["lyrics_status"] == "external-licensed-reference"
        assert "lyrics" not in track
        assert "full_lyrics" not in track
        if track["youtube_status"] == "official-artist-channel":
            assert track["youtube_id"] in track["youtube_url"]
        else:
            assert track["youtube_status"] == "search-only"
            assert "youtube_id" not in track


def test_album_connections_resolve_reviewed_targets():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    albums = repository.get_universe("tyler-the-creator")["albums"]

    for album in albums:
        for connection in album.get("connections", []):
            if connection.get("universe_id"):
                assert repository.get_universe(connection["universe_id"]) is not None


def test_synchronized_demo_has_official_external_destinations():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    flower_boy = next(
        album
        for album in repository.get_universe("tyler-the-creator")["albums"]
        if album["id"] == "flower-boy"
    )
    see_you_again = next(
        track for track in flower_boy["tracks"] if track["title"] == "See You Again"
    )

    assert see_you_again["youtube_url"].startswith("https://www.youtube.com/")
    assert see_you_again["genius_url"].startswith("https://genius.com/")
    assert len(see_you_again["sync_cues"]) == 4


def test_full_odd_future_roster_and_subgroup_catalogs_are_local():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    member_catalogs = [
        universe
        for universe in repository.list_universes()
        if universe.get("catalog_generated")
    ]

    assert len(repository.list_universes()) == 22
    assert {universe["id"] for universe in member_catalogs} == {
        "brandun-deshay",
        "casey-veggies",
        "domo-genesis",
        "earl-sweatshirt",
        "frank-ocean",
        "hodgy",
        "i-smell-panties",
        "jasper-dolphin",
        "left-brain",
        "l-boy",
        "matt-martians",
        "mellowhigh",
        "mellowhype",
        "mike-g",
        "na-kel-smith",
        "pyramid-vritra",
        "syd",
        "taco-bennett",
        "the-internet",
        "the-jet-age-of-tomorrow",
    }
    assert len(repository.get_universe("odd-future")["related"]) == 21
    assert repository.get_universe("jasper-dolphin")["albums"] == []
    assert repository.get_universe("l-boy")["albums"] == []
    assert repository.get_universe("taco-bennett")["albums"] == []


def test_member_catalog_tracks_have_safe_destinations_without_copied_lyrics():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    tracks = [
        track
        for universe in repository.list_universes()
        if universe.get("catalog_generated")
        for album in universe.get("albums", [])
        for track in album.get("tracks", [])
    ]

    assert len(tracks) == 1431
    assert sum(
        track["youtube_status"] == "official-artist-channel" for track in tracks
    ) == 780
    for track in tracks:
        assert track["performers"]
        assert track["youtube_url"].startswith("https://www.youtube.com/")
        assert track["genius_url"].startswith("https://genius.com/")
        assert track["lyrics_status"] == "external-licensed-reference"
        assert "lyrics" not in track
        assert "full_lyrics" not in track


def test_catalog_quality_rules_keep_public_releases_and_reviewed_context():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    frank = repository.get_universe("frank-ocean")
    earl = repository.get_universe("earl-sweatshirt")
    internet = repository.get_universe("the-internet")

    assert [album["title"] for album in frank["albums"]] == [
        "nostalgia,ULTRA.",
        "channel ORANGE",
        "Endless",
        "Blonde",
    ]
    assert [len(album["tracks"]) for album in frank["albums"]] == [14, 17, 19, 17]
    assert len(earl["albums"][0]["tracks"]) == 10

    ego_death = next(
        album for album in internet["albums"] if album["title"] == "Ego Death"
    )
    assert ego_death["id"] == "ego-death"
    assert len(ego_death["tracks"]) == 12
    assert ego_death["source_ids"] == ["time-internet-interview-2015"]


def test_every_odd_future_universe_has_a_finished_reviewed_story():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    universes = repository.list_universes()

    assert len(universes) == 22
    assert sum(len(universe.get("chapters", [])) for universe in universes) == 91
    for universe in universes:
        assert universe["reviewed"] is True
        assert len(universe["chapters"]) >= 3
        assert universe["coverage"].startswith("Reviewed")
        assert all(chapter.get("song_links") for chapter in universe["chapters"])


def test_tyler_and_the_internet_stories_reach_the_current_reviewed_endpoint():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    tyler = repository.get_universe("tyler-the-creator")
    internet = repository.get_universe("the-internet")

    assert tyler["chapters"][0]["era"] == "2007–2010"
    assert tyler["chapters"][-1]["era"] == "2025–present"
    assert tyler["chapters"][-1]["song_links"][0]["track_title"] == (
        "Sugar on My Tongue"
    )
    assert internet["chapters"][0]["era"] == "2011"
    assert internet["chapters"][-1]["era"] == "2019–2027 announced"
    assert "fader-internet-return-2026" in internet["chapters"][-1]["source_ids"]


def test_story_chapters_are_searchable_archive_evidence_for_every_profile():
    repository = ArchiveRepository.from_json(ARCHIVE_PATH)
    document_ids = {document["id"] for document in repository.documents}

    for universe in repository.list_universes():
        for chapter in universe["chapters"]:
            assert f"story-{universe['id']}-{chapter['id']}" in document_ids

    results = repository.search(
        "Beard Internet reconvenes",
        universe_id="syd",
    )
    assert results
    assert results[0].document["id"] == "story-syd-beard-and-return"
