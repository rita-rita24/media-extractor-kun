import requests

import pytest

import main
from tests.test_process_job_ytdlp import FakePopen, add_job


@pytest.fixture(autouse=True)
def reset_fake_popen_for_tiktok(monkeypatch):
    FakePopen.instances = []
    FakePopen.returncode_to_use = 0
    FakePopen.lines_to_use = []
    FakePopen.output_extension = "mp3"
    FakePopen.create_output = True
    FakePopen.timeout = False
    FakePopen.raise_on_init = None
    monkeypatch.setattr(main.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(main, "generate_random_filename", lambda: "generated")


class FakeContentResponse:
    def __init__(self, status_code=200, content=b"media", chunks=None):
        self.status_code = status_code
        self.content = content
        self._chunks = chunks or [content]
        self.headers = {"content-length": str(sum(len(chunk) for chunk in self._chunks))}

    def iter_content(self, chunk_size=8192):
        yield from self._chunks


def test_process_job_tiktok_audio_direct_success(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_tiktok_video_info",
        lambda url: {"success": True, "music_url": "https://music.example/audio.mp3", "title": ""},
    )
    monkeypatch.setattr(requests, "get", lambda url, timeout, stream=False: FakeContentResponse(content=b"mp3"))
    job = add_job("tiktok-audio", url="https://www.tiktok.com/@u/video/1")

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert job.filename == "generated.mp3"
    assert (main.TEMP_DIR / job.id / "generated.mp3").read_bytes() == b"mp3"
    assert FakePopen.instances == []


def test_process_job_tiktok_audio_does_not_complete_with_video_tiksave_when_music_download_fails(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_tiktok_video_info",
        lambda url: {
            "success": True,
            "music_url": "https://music.example/audio.mp3",
            "video_url": "https://video.example/video.mp4",
            "title": "normal",
        },
    )
    monkeypatch.setattr(requests, "get", lambda url, timeout, stream=False: FakeContentResponse(status_code=503))

    def unexpected_tiksave(*args, **kwargs):
        raise AssertionError("audio jobs must not complete through TikSave MP4 fallback")

    monkeypatch.setattr(main, "download_tiktok_via_tiksave", unexpected_tiksave)
    job = add_job("tiktok-audio-fallback", url="https://www.tiktok.com/@u/video/1")

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert job.filename == "generated.mp3"
    assert FakePopen.instances[0].cmd[-1] == "https://video.example/video.mp4"
    assert "-x" in FakePopen.instances[0].cmd


def test_process_job_tiktok_video_direct_success(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_tiktok_video_info",
        lambda url: {"success": True, "video_url": "https://video.example/video.mp4", "title": ""},
    )
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout, stream: FakeContentResponse(content=b"mp4", chunks=[b"m", b"p4"]),
    )
    job = add_job("tiktok-video", url="https://www.tiktok.com/@u/video/1", download_type=main.DownloadType.VIDEO)

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert job.filename == "generated.mp4"
    assert (main.TEMP_DIR / job.id / "generated.mp4").read_bytes() == b"mp4"


def test_process_job_tiktok_video_direct_skips_empty_chunks(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_tiktok_video_info",
        lambda url: {"success": True, "video_url": "https://video.example/video.mp4", "title": ""},
    )
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout, stream: FakeContentResponse(content=b"mp4", chunks=[b"", b"mp4"]),
    )
    job = add_job("tiktok-video-empty-chunk", url="https://www.tiktok.com/@u/video/1", download_type=main.DownloadType.VIDEO)

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert (main.TEMP_DIR / job.id / "generated.mp4").read_bytes() == b"mp4"


def test_process_job_tiktok_video_direct_exception_falls_back_to_tiksave(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_tiktok_video_info",
        lambda url: {"success": True, "video_url": "https://video.example/video.mp4", "title": "normal"},
    )

    def raising_get(*args, **kwargs):
        raise requests.Timeout("video timed out")

    def fake_tiksave(url, output_path):
        with open(output_path, "wb") as file:
            file.write(b"mp4")
        return True

    monkeypatch.setattr(requests, "get", raising_get)
    monkeypatch.setattr(main, "download_tiktok_via_tiksave", fake_tiksave)
    job = add_job("tiktok-video-exception", url="https://www.tiktok.com/@u/video/1", download_type=main.DownloadType.VIDEO)

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert job.filename == "generated.mp4"
    assert job.message == "完了！（予備サーバー経由）"


@pytest.mark.parametrize(
    ("title", "expected_message"),
    [
        ("subscriber only", "完了！（TikSave経由）"),
        ("normal video", "完了！（予備サーバー経由）"),
    ],
)
def test_process_job_tiktok_video_tiksave_fallback_success(monkeypatch, title, expected_message):
    monkeypatch.setattr(
        main,
        "get_tiktok_video_info",
        lambda url: {"success": True, "video_url": None, "title": title},
    )

    def fake_tiksave(url, output_path):
        with open(output_path, "wb") as file:
            file.write(b"mp4")
        return True

    monkeypatch.setattr(main, "download_tiktok_via_tiksave", fake_tiksave)
    job = add_job(f"tiktok-tiksave-{title}", url="https://www.tiktok.com/@u/video/1", download_type=main.DownloadType.VIDEO)

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert job.filename == "generated.mp4"
    assert job.message == expected_message


def test_process_job_tiktok_all_direct_video_methods_fall_back_to_ytdlp_with_direct_target(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_tiktok_video_info",
        lambda url: {"success": True, "video_url": "https://video.example/video.mp4", "title": "normal"},
    )
    monkeypatch.setattr(requests, "get", lambda url, timeout, stream: FakeContentResponse(status_code=503))
    monkeypatch.setattr(main, "download_tiktok_via_tiksave", lambda url, output_path: False)
    FakePopen.output_extension = "mp4"
    job = add_job("tiktok-video-ytdlp", url="https://www.tiktok.com/@u/video/1", download_type=main.DownloadType.VIDEO)

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert job.filename == "generated.mp4"
    cmd = FakePopen.instances[0].cmd
    assert cmd[-1] == "https://video.example/video.mp4"
    assert cmd[cmd.index("-f") + 1] == "best"


def test_process_job_tiktok_subscriber_tiksave_failure_continues_to_direct_video(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_tiktok_video_info",
        lambda url: {"success": True, "video_url": "https://video.example/video.mp4", "title": "subscriber only"},
    )
    monkeypatch.setattr(main, "download_tiktok_via_tiksave", lambda url, output_path: False)
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout, stream: FakeContentResponse(content=b"mp4", chunks=[b"mp4"]),
    )
    job = add_job("tiktok-subscriber-direct", url="https://www.tiktok.com/@u/video/1", download_type=main.DownloadType.VIDEO)

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert job.message == "完了！"
    assert job.filename == "generated.mp4"


def test_process_job_tiktok_api_failure_resolves_short_url_and_adds_impersonation(monkeypatch):
    monkeypatch.setattr(main, "get_tiktok_video_info", lambda url: {"success": False, "error": "blocked"})
    monkeypatch.setattr(main, "resolve_tiktok_redirect", lambda url: "https://www.tiktok.com/@u/video/1")
    job = add_job("tiktok-api-fallback", url="https://vt.tiktok.com/short/")

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    cmd = FakePopen.instances[0].cmd
    assert cmd[-1] == "https://www.tiktok.com/@u/video/1"
    assert "--impersonate" in cmd
    assert "chrome" in cmd


def test_process_job_tiktok_api_failure_without_short_url_uses_original_url_with_impersonation(monkeypatch):
    monkeypatch.setattr(main, "get_tiktok_video_info", lambda url: {"success": False, "error": "blocked"})
    job = add_job("tiktok-api-fallback-original", url="https://www.tiktok.com/@u/video/1")

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    cmd = FakePopen.instances[0].cmd
    assert cmd[-1] == "https://www.tiktok.com/@u/video/1"
    assert "--impersonate" in cmd
    assert "chrome" in cmd
