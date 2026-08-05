from src.live_events import TicketmasterEventsClient


def test_live_events_without_key_is_safe_and_explicit():
    result = TicketmasterEventsClient(api_key="").search("Test Artist")

    assert result.status == "not-configured"
    assert result.events == []
    assert "separate from the reviewed archive" in result.message


def test_live_event_response_is_normalized():
    class FakeClient(TicketmasterEventsClient):
        def _request_json(self, url):
            assert "keyword=Test+Artist" in url
            return {
                "_embedded": {
                    "events": [
                        {
                            "name": "Test Artist Live",
                            "url": "https://example.com/tickets",
                            "dates": {
                                "start": {"localDate": "2027-01-02", "localTime": "20:00:00"},
                                "status": {"code": "onsale"},
                            },
                            "_embedded": {
                                "venues": [
                                    {
                                        "name": "Test Hall",
                                        "city": {"name": "Boston"},
                                        "state": {"stateCode": "MA"},
                                    }
                                ]
                            },
                        }
                    ]
                }
            }

    result = FakeClient(api_key="test-key").search("Test Artist")

    assert result.status == "ok"
    assert result.events[0]["venue"] == "Test Hall"
    assert result.events[0]["status"] == "onsale"

