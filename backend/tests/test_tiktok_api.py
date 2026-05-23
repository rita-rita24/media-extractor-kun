import requests

import main


class FakeJsonResponse:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def json(self):
        if self.error:
            raise self.error
        return self.payload


def test_get_tiktok_video_info_maps_successful_api_response(monkeypatch):
    def fake_get(url, timeout):
        assert url.startswith("https://tikwm.com/api/?url=")
        assert timeout == 30
        return FakeJsonResponse(
            {
                "code": 0,
                "data": {
                    "id": "7357",
                    "play": "https://fallback.example/video.mp4",
                    "music": "https://fallback.example/audio.mp3",
                    "title": "sample",
                    "duration": 12,
                    "cover": "https://cdn.example/cover.jpg",
                },
            }
        )

    monkeypatch.setattr(requests, "get", fake_get)

    result = main.get_tiktok_video_info("https://www.tiktok.com/@u/video/7357")

    assert result == {
        "success": True,
        "video_id": "7357",
        "video_url": "https://www.tikwm.com/video/media/hdplay/7357.mp4",
        "video_url_fallback": "https://fallback.example/video.mp4",
        "music_url": "https://www.tikwm.com/video/music/7357.mp3",
        "music_url_fallback": "https://fallback.example/audio.mp3",
        "title": "sample",
        "duration": 12,
        "cover": "https://cdn.example/cover.jpg",
    }


def test_get_tiktok_video_info_returns_failure_for_api_error(monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout: FakeJsonResponse({"code": -1, "msg": "blocked", "data": None}),
    )

    result = main.get_tiktok_video_info("https://www.tiktok.com/@u/video/7357")

    assert result == {"success": False, "error": "blocked"}


def test_get_tiktok_video_info_returns_failure_for_invalid_json(monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout: FakeJsonResponse(error=ValueError("not json")),
    )

    result = main.get_tiktok_video_info("https://www.tiktok.com/@u/video/7357")

    assert result == {"success": False, "error": "not json"}
