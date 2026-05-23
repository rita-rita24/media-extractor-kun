from datetime import datetime
import uuid

import main


class NoopThread:
    def __init__(self, target, args):
        self.target = target
        self.args = args

    def start(self):
        return None


def test_start_extraction_creates_video_job_without_running_external_process(client, monkeypatch):
    monkeypatch.setattr(main.threading, "Thread", NoopThread)

    response = client.post(
        "/api/extract",
        json={
            "url": "https://www.youtube.com/watch?v=abc_123-XYZ",
            "filename": "  lecture:name  ",
            "download_type": "video",
            "video_quality": "1080p",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["progress"] == 0.0
    assert data["message"] == "待機中..."

    with main.jobs_lock:
        job = main.jobs[data["job_id"]]
    assert job.custom_filename == "lecture:name"
    assert job.download_type == main.DownloadType.VIDEO
    assert job.video_quality == "1080p"


def test_start_extraction_rejects_invalid_url_before_starting_thread(client, monkeypatch):
    started = False

    class UnexpectedThread(NoopThread):
        def start(self):
            nonlocal started
            started = True

    monkeypatch.setattr(main.threading, "Thread", UnexpectedThread)

    response = client.post("/api/extract", json={"url": "file:///tmp/private.mp3"})

    assert response.status_code == 400
    assert started is False
    with main.jobs_lock:
        assert main.jobs == {}


def test_start_extraction_defaults_unknown_type_and_quality(client, monkeypatch):
    monkeypatch.setattr(main.threading, "Thread", NoopThread)

    response = client.post(
        "/api/extract",
        json={
            "url": "https://youtu.be/abc_123",
            "download_type": "archive",
            "video_quality": "4k",
        },
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    with main.jobs_lock:
        job = main.jobs[job_id]
    assert job.download_type == main.DownloadType.AUDIO
    assert job.video_quality == "720p"


def test_start_extraction_rejects_when_active_job_limit_is_reached(client, monkeypatch):
    monkeypatch.setattr(main.threading, "Thread", NoopThread)
    monkeypatch.setattr(main, "MAX_CONCURRENT_JOBS", 1)
    with main.jobs_lock:
        main.jobs[str(uuid.uuid4())] = main.Job(id=str(uuid.uuid4()), url="https://youtu.be/running")

    response = client.post("/api/extract", json={"url": "https://youtu.be/abc_123"})

    assert response.status_code == 429
    assert response.json()["detail"] == "同時処理数の上限に達しています。完了後に再試行してください"


def test_start_extraction_does_not_count_terminal_jobs_toward_active_limit(client, monkeypatch):
    monkeypatch.setattr(main.threading, "Thread", NoopThread)
    monkeypatch.setattr(main, "MAX_CONCURRENT_JOBS", 1)
    with main.jobs_lock:
        main.jobs[str(uuid.uuid4())] = main.Job(
            id=str(uuid.uuid4()),
            url="https://youtu.be/done",
            status=main.JobStatus.COMPLETED,
        )

    response = client.post("/api/extract", json={"url": "https://youtu.be/abc_123"})

    assert response.status_code == 200


def test_start_extraction_rate_limits_repeated_job_starts(client, monkeypatch):
    monkeypatch.setattr(main.threading, "Thread", NoopThread)
    monkeypatch.setattr(main, "JOB_RATE_LIMIT_MAX_REQUESTS", 1)
    first_response = client.post("/api/extract", json={"url": "https://youtu.be/abc_123"})

    second_response = client.post("/api/extract", json={"url": "https://youtu.be/abc_123"})

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["detail"] == "リクエストが多すぎます。しばらく待ってから再試行してください"


def test_get_job_status_and_delete_job_remove_state_and_temp_dir(client, isolated_job_store):
    job_id = str(uuid.uuid4())
    job_dir = isolated_job_store / job_id
    job_dir.mkdir()
    (job_dir / "clip.mp3").write_bytes(b"audio")
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(
            id=job_id,
            url="https://youtu.be/abc_123",
            status=main.JobStatus.COMPLETED,
            progress=100.0,
            message="完了！",
            filename="clip.mp3",
            completed_at=datetime.now(),
        )

    status_response = client.get(f"/api/job/{job_id}")
    delete_response = client.delete(f"/api/job/{job_id}")
    missing_response = client.get(f"/api/job/{job_id}")

    assert status_response.status_code == 200
    assert status_response.json()["filename"] == "clip.mp3"
    assert delete_response.status_code == 200
    assert delete_response.json() == {"success": True}
    assert missing_response.status_code == 404
    assert not job_dir.exists()


def test_delete_job_accepts_missing_safe_job_and_missing_directory(client):
    missing_job_id = "33333333-3333-3333-3333-333333333333"

    response = client.delete(f"/api/job/{missing_job_id}")

    assert response.status_code == 200
    assert response.json() == {"success": True}


def test_health_reports_active_job_count(client):
    with main.jobs_lock:
        main.jobs[str(uuid.uuid4())] = main.Job(id=str(uuid.uuid4()), url="https://youtu.be/a")
        main.jobs[str(uuid.uuid4())] = main.Job(id=str(uuid.uuid4()), url="https://youtu.be/b")

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "active_jobs": 2}


def test_cors_allows_local_frontend_origin_but_not_untrusted_origin(client):
    local_response = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    evil_response = client.get("/api/health", headers={"Origin": "https://evil.example"})

    assert local_response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in evil_response.headers
