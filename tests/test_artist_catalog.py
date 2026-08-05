from src.artist_catalog import MusicBrainzCatalogClient


def test_empty_artist_search_is_rejected_without_network():
    response = MusicBrainzCatalogClient().search_artists("   ")

    assert response.status == "invalid-input"
    assert response.artists == []


def test_artist_search_normalizes_provider_response():
    class FakeClient(MusicBrainzCatalogClient):
        def _request_json(self, url):
            assert "artist" in url
            return {
                "artists": [
                    {
                        "id": "artist-id",
                        "name": "Test Artist",
                        "type": "Person",
                        "country": "US",
                        "area": {"name": "Atlanta"},
                        "score": 100,
                        "tags": [{"name": "hip hop", "count": 4}],
                    }
                ]
            }

    response = FakeClient().search_artists("Test Artist")

    assert response.status == "ok"
    assert response.artists[0].name == "Test Artist"
    assert response.artists[0].tags == ["hip hop"]


def test_catalog_profile_keeps_external_metadata_unreviewed():
    class FakeClient(MusicBrainzCatalogClient):
        def _request_json(self, url):
            return {
                "release-groups": [
                    {
                        "id": "release-id",
                        "title": "First Album",
                        "primary-type": "Album",
                        "secondary-types": [],
                        "first-release-date": "2020-06-01",
                    }
                ]
            }

    profile = FakeClient().load_profile(
        {
            "mbid": "artist-id",
            "name": "Test Artist",
            "artist_type": "Person",
            "country": "US",
            "area": "Atlanta",
            "disambiguation": "",
            "score": 100,
            "tags": ["hip hop"],
        }
    )

    assert profile["reviewed"] is False
    assert profile["albums"][0]["title"] == "First Album"
    assert "Live MusicBrainz" in profile["coverage"]
