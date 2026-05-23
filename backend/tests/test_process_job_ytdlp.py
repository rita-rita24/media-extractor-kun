import subprocess
import time
from pathlib import Path

import pytest

import main


class FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return ""


class FakePopen:
    instances = []
    returncode_to_use = 0
    lines_to_use = []
    output_extension = "mp3"
    create_output = True
    timeout = False
    raise_on_init = None

    def __init__(self, cmd, stdout, stderr, text, bufsize):
        if self.raise_on_init:
            raise self.raise_on_init
        self.cmd = cmd
        self.stdout = FakeStdout(self.lines_to_use)
        self.returncode = self.returncode_to_use
        self.killed = False
        self.instances.append(self)

    def wait(self, timeout):
        if self.timeout:
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        if self.create_output:
            template = self.cmd[self.cmd.index("-o") + 1]
            output_path = Path(template.replace("%(ext)s", self.output_extension))
            output_path.write_bytes(b"generated")
        return self.returncode

    def kill(self):
        self.killed = True


@pytest.fixture(autouse=True)
def reset_fake_popen(monkeypatch):
    FakePopen.instances = []
    FakePopen.returncode_to_use = 0
    FakePopen.lines_to_use = []
    FakePopen.output_extension = "mp3"
    FakePopen.create_output = True
    FakePopen.timeout = False
    FakePopen.raise_on_init = None
    monkeypatch.setattr(main.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(main, "generate_random_filename", lambda: "generated")


def add_job(job_id="job-1", **kwargs):
    job = main.Job(id=job_id, url=kwargs.pop("url", "https://www.youtube.com/watch?v=abc_123"), **kwargs)
    with main.jobs_lock:
        main.jobs[job_id] = job
    return job


def test_process_job_returns_without_creating_directory_for_missing_job(isolated_job_store):
    main.process_job("missing")

    assert not (isolated_job_store / "missing").exists()


def test_process_job_audio_ytdlp_success_updates_progress_and_completed_state():
    FakePopen.lines_to_use = [
        "\n",
        "[download] 50.0% of 10.00MiB at 1.00MiB/s ETA 00:05\n",
        "[ExtractAudio] Destination: generated.mp3\n",
        "noise line\n",
    ]
    job = add_job()

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert job.progress == 100.0
    assert job.message == "完了！"
    assert job.filename == "generated.mp3"
    assert (main.TEMP_DIR / job.id / "generated.mp3").read_bytes() == b"generated"
    assert "-x" in FakePopen.instances[0].cmd
    assert FakePopen.instances[0].cmd[-1] == "https://www.youtube.com/watch?v=abc_123"


@pytest.mark.parametrize(
    ("quality", "expected_format"),
    [
        ("best", "bestvideo+bestaudio/best"),
        ("1080p", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"),
        ("720p", "bestvideo[height<=720]+bestaudio/best[height<=720]"),
    ],
)
def test_process_job_video_ytdlp_uses_requested_quality_format(quality, expected_format):
    FakePopen.output_extension = "mp4"
    FakePopen.lines_to_use = ['[Merger] Merging formats into "generated.mp4"\n']
    job = add_job(download_type=main.DownloadType.VIDEO, video_quality=quality)

    main.process_job(job.id)

    assert job.status == main.JobStatus.COMPLETED
    assert job.filename == "generated.mp4"
    cmd = FakePopen.instances[0].cmd
    assert cmd[cmd.index("-f") + 1] == expected_format
    assert "--merge-output-format" in cmd


def test_process_job_ytdlp_nonzero_exit_marks_failed_and_removes_output_dir():
    FakePopen.returncode_to_use = 1
    job = add_job()

    main.process_job(job.id)

    assert job.status == main.JobStatus.FAILED
    assert job.error == "yt-dlpの実行に失敗しました"
    assert not (main.TEMP_DIR / job.id).exists()


def test_process_job_ytdlp_success_without_output_file_marks_failed():
    FakePopen.create_output = False
    job = add_job(download_type=main.DownloadType.VIDEO)

    main.process_job(job.id)

    assert job.status == main.JobStatus.FAILED
    assert job.error == "MP4ファイルが生成されませんでした"
    assert not (main.TEMP_DIR / job.id).exists()


def test_process_job_timeout_kills_process_and_cleans_output_dir():
    FakePopen.timeout = True
    job = add_job()

    main.process_job(job.id)

    assert FakePopen.instances[0].killed is True
    assert job.status == main.JobStatus.FAILED
    assert job.error == "処理がタイムアウトしました（最大12時間）"
    assert not (main.TEMP_DIR / job.id).exists()


def test_process_job_timeout_kills_process_even_when_stdout_readline_blocks(monkeypatch):
    class BlockingStdout:
        def readline(self):
            time.sleep(1)
            return "still running\n"

    class BlockingPopen:
        instances = []

        def __init__(self, cmd, stdout, stderr, text, bufsize):
            self.cmd = cmd
            self.stdout = BlockingStdout()
            self.returncode = None
            self.killed = False
            self.instances.append(self)

        def wait(self, timeout):
            return None

        def kill(self):
            self.killed = True
            self.returncode = -9

    monkeypatch.setattr(main.subprocess, "Popen", BlockingPopen)
    monkeypatch.setattr(main, "MAX_DURATION_SECONDS", 0.01)
    job = add_job("blocking-job")

    main.process_job(job.id)

    assert BlockingPopen.instances[0].killed is True
    assert job.status == main.JobStatus.FAILED
    assert job.error == "処理がタイムアウトしました（最大12時間）"
    assert not (main.TEMP_DIR / job.id).exists()


def test_read_process_output_raises_timeout_when_stdout_closes_after_deadline(monkeypatch):
    class EmptyStdout:
        def readline(self):
            return ""

    class Process:
        stdout = EmptyStdout()
        args = ["yt-dlp"]

        def wait(self, timeout):
            raise AssertionError("wait must not run after the deadline")

    times = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(main.time, "monotonic", lambda: next(times))

    with pytest.raises(subprocess.TimeoutExpired):
        list(main.read_process_output_with_timeout(Process(), 1))


@pytest.mark.parametrize(
    ("raw_error", "expected_error"),
    [
        ("Video unavailable", "動画が利用できません"),
        ("Private video", "非公開動画です"),
        ("Sign in to confirm", "ログインが必要な動画です"),
        ("TikTok API 203005", "TikTok動画の取得に失敗しました（詳細：Bot検知によりブロックされました）"),
    ],
)
def test_process_job_maps_known_ytdlp_errors(raw_error, expected_error):
    FakePopen.raise_on_init = RuntimeError(raw_error)
    job = add_job()

    main.process_job(job.id)

    assert job.status == main.JobStatus.FAILED
    assert job.error == expected_error
    assert not (main.TEMP_DIR / job.id).exists()
