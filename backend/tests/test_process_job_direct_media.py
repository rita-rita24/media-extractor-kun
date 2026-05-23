import requests

import main


class FakeStreamResponse:
    def __init__(self, status_code=200, chunks=None, include_content_length=True, headers=None):
        self.status_code = status_code
        self._chunks = chunks or [b"abc", b"def"]
        self.headers = headers or {}
        if include_content_length:
            self.headers["content-length"] = str(sum(len(chunk) for chunk in self._chunks))

    def iter_content(self, chunk_size=8192):
        yield from self._chunks


def test_process_job_downloads_direct_media_with_sanitized_custom_filename(monkeypatch):
    def fake_get(url, timeout, stream, allow_redirects=False):
        assert url == "https://cdn.example.com/path/source.mp3?token=redacted"
        assert timeout == 300
        assert stream is True
        assert allow_redirects is False
        return FakeStreamResponse(chunks=[b"audio", b"-bytes"])

    monkeypatch.setattr(requests, "get", fake_get)

    job_id = "11111111-1111-1111-1111-111111111111"
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(
            id=job_id,
            url="https://cdn.example.com/path/source.mp3?token=redacted",
            custom_filename="../meeting:notes",
        )

    main.process_job(job_id)

    with main.jobs_lock:
        job = main.jobs[job_id]
    assert job.status == main.JobStatus.COMPLETED
    assert job.progress == 100.0
    assert job.filename == ".._meeting_notes.mp3"
    assert (main.TEMP_DIR / job_id / job.filename).read_bytes() == b"audio-bytes"


def test_process_job_marks_direct_media_http_failure_without_leaving_partial_dir(monkeypatch):
    def fake_get(url, timeout, stream, allow_redirects=False):
        return FakeStreamResponse(status_code=503)

    monkeypatch.setattr(requests, "get", fake_get)

    job_id = "22222222-2222-2222-2222-222222222222"
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://cdn.example.com/source.mp3")

    main.process_job(job_id)

    with main.jobs_lock:
        job = main.jobs[job_id]
    assert job.status == main.JobStatus.FAILED
    assert "HTTP 503" in job.error
    assert not (main.TEMP_DIR / job_id).exists()


def test_process_job_direct_media_without_content_length_still_completes(monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout, stream, allow_redirects=False: FakeStreamResponse(chunks=[b"audio"], include_content_length=False),
    )

    job_id = "44444444-4444-4444-4444-444444444444"
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://cdn.example.com/source.mp3")

    main.process_job(job_id)

    with main.jobs_lock:
        job = main.jobs[job_id]
    assert job.status == main.JobStatus.COMPLETED
    assert job.progress == 100.0
    assert (main.TEMP_DIR / job_id / job.filename).read_bytes() == b"audio"


def test_process_job_direct_media_follows_public_redirect_once(monkeypatch):
    calls = []

    def fake_get(url, timeout, stream, allow_redirects=False):
        calls.append(url)
        if len(calls) == 1:
            return FakeStreamResponse(
                status_code=302,
                headers={"location": "https://download.example/source.mp3"},
                include_content_length=False,
            )
        return FakeStreamResponse(chunks=[b"redirected"])

    monkeypatch.setattr(requests, "get", fake_get)

    job_id = "88888888-8888-8888-8888-888888888888"
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://cdn.example.com/source.mp3")

    main.process_job(job_id)

    with main.jobs_lock:
        job = main.jobs[job_id]
    assert job.status == main.JobStatus.COMPLETED
    assert calls == ["https://cdn.example.com/source.mp3", "https://download.example/source.mp3"]
    assert (main.TEMP_DIR / job_id / job.filename).read_bytes() == b"redirected"


def test_process_job_direct_media_skips_empty_chunks(monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout, stream, allow_redirects=False: FakeStreamResponse(
            chunks=[b"", b"audio"],
            include_content_length=False,
        ),
    )

    job_id = "99999999-9999-9999-9999-999999999999"
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://cdn.example.com/source.mp3")

    main.process_job(job_id)

    with main.jobs_lock:
        job = main.jobs[job_id]
    assert job.status == main.JobStatus.COMPLETED
    assert (main.TEMP_DIR / job_id / job.filename).read_bytes() == b"audio"


def test_process_job_direct_media_rejects_private_redirect_without_following(monkeypatch):
    calls = []

    def fake_get(url, timeout, stream, allow_redirects=False):
        calls.append(url)
        return FakeStreamResponse(
            status_code=302,
            headers={"location": "http://127.0.0.1/private.mp3"},
            include_content_length=False,
        )

    monkeypatch.setattr(requests, "get", fake_get)

    job_id = "55555555-5555-5555-5555-555555555555"
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://cdn.example.com/source.mp3")

    main.process_job(job_id)

    with main.jobs_lock:
        job = main.jobs[job_id]
    assert job.status == main.JobStatus.FAILED
    assert "リダイレクト先" in job.error
    assert calls == ["https://cdn.example.com/source.mp3"]


def test_process_job_direct_media_rejects_content_length_over_limit(monkeypatch):
    monkeypatch.setattr(main, "MAX_DIRECT_MEDIA_BYTES", 5)
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout, stream, allow_redirects=False: FakeStreamResponse(chunks=[b"too-large"]),
    )

    job_id = "66666666-6666-6666-6666-666666666666"
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://cdn.example.com/source.mp3")

    main.process_job(job_id)

    with main.jobs_lock:
        job = main.jobs[job_id]
    assert job.status == main.JobStatus.FAILED
    assert "ファイルサイズが上限" in job.error


def test_process_job_direct_media_rejects_stream_that_exceeds_limit_without_content_length(monkeypatch):
    monkeypatch.setattr(main, "MAX_DIRECT_MEDIA_BYTES", 5)
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout, stream, allow_redirects=False: FakeStreamResponse(
            chunks=[b"123", b"456"],
            include_content_length=False,
        ),
    )

    job_id = "77777777-7777-7777-7777-777777777777"
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://cdn.example.com/source.mp3")

    main.process_job(job_id)

    with main.jobs_lock:
        job = main.jobs[job_id]
    assert job.status == main.JobStatus.FAILED
    assert "ファイルサイズが上限" in job.error
