from src.lyrics import LrcLibClient, parse_lrc


def test_lrc_parser_orders_timestamped_lines():
    cues = parse_lrc("[00:10.50]Second line\n[00:02.00]First line")

    assert [cue["text"] for cue in cues] == ["First line", "Second line"]
    assert cues[1]["time"] == 10.5


def test_lrc_parser_ignores_metadata_and_blank_cues():
    cues = parse_lrc("[ar:Example Artist]\n[00:01.00]\n[00:03.25]Allowed text")

    assert cues == [
        {"time": 3.25, "section": "Timed lyric", "text": "Allowed text"}
    ]


def test_lrc_parser_supports_multiple_timestamps():
    cues = parse_lrc("[00:01][00:05]Repeated line")

    assert [cue["time"] for cue in cues] == [1.0, 5.0]


def test_lrclib_lookup_selects_exact_artist_album_and_synced_record():
    class FakeClient(LrcLibClient):
        def _request_json(self, url):
            assert "track_name=Example+Song" in url
            assert "artist_name=Example+Artist" in url
            assert "album_name=Example+Album" in url
            return [
                {
                    "id": 1,
                    "trackName": "Example Song",
                    "artistName": "Different Artist",
                    "albumName": "Example Album",
                    "plainLyrics": "Wrong match",
                    "syncedLyrics": "[00:01.00]Wrong match",
                    "instrumental": False,
                },
                {
                    "id": 2,
                    "trackName": "Example Song",
                    "artistName": "Example Artist",
                    "albumName": "Example Album",
                    "plainLyrics": "First line\nSecond line",
                    "syncedLyrics": "[00:01.00]First line\n[00:03.50]Second line",
                    "instrumental": False,
                },
            ]

    result = FakeClient().search("Example Song", "Example Artist", "Example Album")

    assert result.status == "matched"
    assert result.record_id == 2
    assert [cue["time"] for cue in result.cues] == [1.0, 3.5]
    assert result.provider_url == "https://lrclib.net/tracks/2"


def test_lrclib_lookup_ignores_local_duplicate_version_suffix():
    class FakeClient(LrcLibClient):
        def _request_json(self, url):
            return [
                {
                    "id": 3,
                    "trackName": "Repeated Song",
                    "artistName": "Example Artist",
                    "albumName": "Example Album",
                    "plainLyrics": "Available text",
                    "syncedLyrics": None,
                    "instrumental": False,
                }
            ]

    result = FakeClient().search(
        "Repeated Song [version 2]", "Example Artist", "Example Album"
    )

    assert result.status == "matched"
    assert result.cues == []
    assert result.plain_lyrics == "Available text"


def test_lrclib_lookup_abstains_on_wrong_artist():
    class FakeClient(LrcLibClient):
        def _request_json(self, url):
            return [
                {
                    "id": 4,
                    "trackName": "Same Title",
                    "artistName": "Unrelated Performer",
                    "albumName": "Other Album",
                    "plainLyrics": "Do not display",
                    "syncedLyrics": None,
                    "instrumental": False,
                }
            ]

    result = FakeClient().search("Same Title", "Expected Artist", "Expected Album")

    assert result.status == "not-found"
    assert result.plain_lyrics == ""


def test_lrclib_lookup_reports_instrumental_record():
    class FakeClient(LrcLibClient):
        def _request_json(self, url):
            return [
                {
                    "id": 5,
                    "trackName": "Instrumental",
                    "artistName": "Example Artist",
                    "albumName": "Example Album",
                    "plainLyrics": None,
                    "syncedLyrics": None,
                    "instrumental": True,
                }
            ]

    result = FakeClient().search("Instrumental", "Example Artist", "Example Album")

    assert result.status == "instrumental"
    assert result.cues == []
