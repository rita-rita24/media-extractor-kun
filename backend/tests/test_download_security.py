from datetime import datetime
from urllib.parse import quote
import uuid

import main


def create_completed_job(filename: str, payload: bytes = b"artifact") -> str:
    job_id = str(uuid.uuid4())
    job_dir = main.TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / filename).write_bytes(payload)
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(
            id=job_id,
            url="https://youtu.be/abc_123",
            status=main.JobStatus.COMPLETED,
            progress=100.0,
            message="完了！",
            filename=filename,
            completed_at=datetime.now(),
        )
    return job_id


def test_download_completed_audio_file_uses_safe_content_disposition(client):
    filename = "会議 録音.mp3"
    job_id = create_completed_job(filename, b"mp3-bytes")

    response = client.get(f"/api/download/{job_id}/{quote(filename)}")

    assert response.status_code == 200
    assert response.content == b"mp3-bytes"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert "filename*=UTF-8''%E4%BC%9A%E8%AD%B0%20%E9%8C%B2%E9%9F%B3.mp3" in response.headers[
        "content-disposition"
    ]


def test_download_completed_video_file_uses_video_media_type(client):
    job_id = create_completed_job("clip.mp4", b"mp4-bytes")

    response = client.get(f"/api/download/{job_id}/clip.mp4")

    assert response.status_code == 200
    assert response.content == b"mp4-bytes"
    assert response.headers["content-type"].startswith("video/mp4")


def test_download_rejects_files_not_registered_on_the_job(client):
    job_id = create_completed_job("expected.mp3", b"expected")
    (main.TEMP_DIR / job_id / "sibling.mp3").write_bytes(b"secret")

    response = client.get(f"/api/download/{job_id}/sibling.mp3")

    assert response.status_code == 404
    assert response.json()["detail"] == "ファイルが見つかりません"
