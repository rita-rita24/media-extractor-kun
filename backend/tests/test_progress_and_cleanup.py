from datetime import datetime, timedelta

import pytest
from hypothesis import given, strategies as st

import main


@pytest.mark.parametrize(
    ("line", "expected_progress", "expected_message"),
    [
        ("[download]   0.0% of 10.00MiB at 1.00MiB/s ETA 00:10", 0.0, "ダウンロード中... 0.0%"),
        ("[download]  45.2% of 10.00MiB at 1.00MiB/s ETA 00:05", 31.64, "ダウンロード中... 45.2%"),
        ("[download] 100.0% of 10.00MiB at 1.00MiB/s ETA 00:00", 70.0, "ダウンロード中... 100.0%"),
        ("[ExtractAudio] Destination: file.mp3", 75.0, "音声を変換中..."),
        ('[Merger] Merging formats into "file.mp4"', 85.0, "ファイルを処理中..."),
    ],
)
def test_parse_progress_maps_known_yt_dlp_lines(line, expected_progress, expected_message):
    progress, message = main.parse_progress(line)

    assert progress == pytest.approx(expected_progress)
    assert message == expected_message


def test_parse_progress_ignores_noise_or_unparseable_percent_lines():
    assert main.parse_progress("plain log line") == (-1, "")
    assert main.parse_progress("[download] percent% of file") == (-1, "")


def test_parse_progress_returns_no_progress_when_regex_raises(monkeypatch):
    def raising_search(*args, **kwargs):
        raise RuntimeError("regex engine failed")

    monkeypatch.setattr(main.re, "search", raising_search)

    assert main.parse_progress("[download] 50.0% of file") == (-1, "")


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


@given(st.decimals(min_value=0, max_value=100, places=1))
def test_parse_progress_scales_download_percent_to_seventy_percent(percent):
    line = f"[download] {percent}% of 10.00MiB at 1.00MiB/s ETA 00:10"

    progress, message = main.parse_progress(line)

    assert progress == pytest.approx(float(percent) * 0.7)
    assert message == f"ダウンロード中... {float(percent):.1f}%"


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
