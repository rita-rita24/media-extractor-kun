from pathlib import Path

import pytest

import main


SOCIAL_PLATFORM_URLS = [
    ("youtube", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    ("tiktok", "https://www.tiktok.com/@patroxofficial/video/6742501081818877190?langCountry=en"),
    ("instagram", "https://www.instagram.com/reel/CDUMkliABpa/"),
    ("x", "https://x.com/historyinmemes/status/1790637656616943991"),
    ("twitter", "https://twitter.com/historyinmemes/status/1790637656616943991"),
]


class MatrixStdout:
    def __init__(self, lines=None):
        self._lines = list(lines or [])

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return ""


class MatrixPopen:
    instances = []
    output_extension = "mp3"

    def __init__(self, cmd, stdout, stderr, text, bufsize):
        self.cmd = cmd
        self.stdout = MatrixStdout(["[download] 100.0% of 1.00MiB\n"])
        self.returncode = 0
        self.killed = False
        self.instances.append(self)

    def wait(self, timeout):
        template = self.cmd[self.cmd.index("-o") + 1]
        output_path = Path(template.replace("%(ext)s", self.output_extension))
        output_path.write_bytes(b"generated")
        return self.returncode

    def kill(self):
        self.killed = True


@pytest.fixture(autouse=True)
def fake_ytdlp_process(monkeypatch):
    MatrixPopen.instances = []
    MatrixPopen.output_extension = "mp3"
    monkeypatch.setattr(main.subprocess, "Popen", MatrixPopen)
    monkeypatch.setattr(main, "generate_random_filename", lambda: "social")
    monkeypatch.setattr(main, "get_tiktok_video_info", lambda url: {"success": False, "error": "smoke fallback"})


@pytest.mark.parametrize("platform,url", SOCIAL_PLATFORM_URLS)
def test_validate_video_url_accepts_supported_social_platform_urls(platform, url):
    assert main.validate_video_url(url) is True, platform


@pytest.mark.parametrize("platform,url", SOCIAL_PLATFORM_URLS)
@pytest.mark.parametrize("download_type,expected_extension", [(main.DownloadType.AUDIO, "mp3"), (main.DownloadType.VIDEO, "mp4")])
def test_supported_social_platforms_can_enter_audio_and_video_extraction_paths(
    platform,
    url,
    download_type,
    expected_extension,
):
    MatrixPopen.output_extension = expected_extension
    job = main.Job(
        id=f"{platform}-{download_type.value}",
        url=url,
        download_type=download_type,
        video_quality="1080p",
    )
    with main.jobs_lock:
        main.jobs[job.id] = job

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert job.filename == f"social.{expected_extension}"
    assert MatrixPopen.instances, "yt-dlp path must be reached"

    cmd = MatrixPopen.instances[0].cmd
    assert cmd[0] == "yt-dlp"
    assert cmd[-1] == url

    if download_type == main.DownloadType.AUDIO:
        assert "-x" in cmd
        assert cmd[cmd.index("--audio-format") + 1] == "mp3"
    else:
        assert cmd[cmd.index("--merge-output-format") + 1] == "mp4"
        assert cmd[cmd.index("-f") + 1] == "bestvideo[height<=1080]+bestaudio/best[height<=1080]"

    if platform == "tiktok":
        assert "--impersonate" in cmd
