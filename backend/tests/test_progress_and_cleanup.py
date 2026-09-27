from datetime import datetime, timedelta

import pytest
from hypothesis import given, strategies as st

import main


@pytest.mark.parametrize(
    ("line", "expected_percent"),
    [
        ("[download]   0.0% of 10.00MiB", 0.0),
        ("[download]  45.2% of 10.00MiB", 45.2),
        ("[download] 100.0% of 10.00MiB", 100.0),
        ("plain log line", None),
        ("[download] percent% of file", None),
        ("[download] Destination: generated.mp4", None),
    ],
)
def test_parse_download_percent_accepts_only_numeric_download_updates(line, expected_percent):
    assert main.parse_download_percent(line) == expected_percent


def test_get_content_length_returns_zero_for_invalid_header_value():
    assert main.get_content_length({"content-length": "not-a-number"}) == 0


def test_write_streaming_response_to_file_skips_empty_chunks(tmp_path):
    class Response:
        headers = {"content-length": "4"}

        def iter_content(self, chunk_size=8192):
            yield b""
            yield b"data"

    output_path = tmp_path / "media.bin"
    main.write_streaming_response_to_file(Response(), output_path)

    assert output_path.read_bytes() == b"data"


def test_write_streaming_response_to_file_reports_integer_progress_steps(tmp_path, monkeypatch):
    class Response:
        headers = {"content-length": "100"}

        def iter_content(self, chunk_size=8192):
            for _ in range(10):
                yield b"x" * 10

    updates = []
    original_update = main.update_job_progress

    def tracking_update(job, progress, message=None, status=None):
        updates.append(int(progress))
        original_update(job, progress, message, status)

    monkeypatch.setattr(main, "update_job_progress", tracking_update)

    job = main.Job(id="progress-job", url="https://cdn.example.com/source.mp4")
    output_path = tmp_path / "media.bin"

    main.write_streaming_response_to_file(
        Response(),
        output_path,
        job=job,
        progress_start=20.0,
        progress_end=30.0,
        message="動画をダウンロード中...",
        status=main.JobStatus.DOWNLOADING,
    )

    assert output_path.read_bytes() == b"x" * 100
    assert updates == list(range(20, 31))
    assert job.progress == 30.0
    assert job.status == main.JobStatus.DOWNLOADING
    assert job.message == "動画をダウンロード中... 100B / 100B"


@given(st.decimals(min_value=0, max_value=100, places=1))
def test_download_progress_scales_percent_to_seventy_percent(percent):
    parsed = main.parse_download_percent(f"[download] {percent}% of 10.00MiB")

    assert parsed == float(percent)
    assert main.map_download_progress(parsed) == pytest.approx(float(percent) * 0.7)


def test_cleanup_old_jobs_removes_only_old_terminal_jobs(isolated_job_store):
    now = datetime.now()
    old_completed = main.Job(
        id="old-completed",
        url="https://youtu.be/old",
        status=main.JobStatus.COMPLETED,
        created_at=now - timedelta(hours=6, seconds=1),
        filename="old.mp3",
    )
    old_failed = main.Job(
        id="old-failed",
        url="https://youtu.be/failed",
        status=main.JobStatus.FAILED,
        created_at=now - timedelta(hours=7),
    )
    old_running = main.Job(
        id="old-running",
        url="https://youtu.be/running",
        status=main.JobStatus.DOWNLOADING,
        created_at=now - timedelta(hours=7),
    )
    recent_completed = main.Job(
        id="recent-completed",
        url="https://youtu.be/recent",
        status=main.JobStatus.COMPLETED,
        created_at=now - timedelta(hours=1),
    )

    with main.jobs_lock:
        main.jobs.update(
            {
                old_completed.id: old_completed,
                old_failed.id: old_failed,
                old_running.id: old_running,
                recent_completed.id: recent_completed,
            }
        )

    for job in (old_completed, old_failed, old_running, recent_completed):
        job_dir = isolated_job_store / job.id
        job_dir.mkdir()
        (job_dir / "artifact.mp3").write_bytes(b"data")

    main.cleanup_old_jobs()

    with main.jobs_lock:
        assert set(main.jobs) == {old_running.id, recent_completed.id}
    assert not (isolated_job_store / old_completed.id).exists()
    assert not (isolated_job_store / old_failed.id).exists()
    assert (isolated_job_store / old_running.id).exists()
    assert (isolated_job_store / recent_completed.id).exists()


def test_cleanup_old_jobs_removes_expired_terminal_job_even_when_directory_is_missing():
    old_failed = main.Job(
        id="old-failed-no-dir",
        url="https://youtu.be/failed",
        status=main.JobStatus.FAILED,
        created_at=datetime.now() - timedelta(hours=7),
    )
    with main.jobs_lock:
        main.jobs[old_failed.id] = old_failed

    main.cleanup_old_jobs()

    with main.jobs_lock:
        assert old_failed.id not in main.jobs
