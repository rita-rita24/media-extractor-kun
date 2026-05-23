import uuid

import pytest
from fastapi import HTTPException

import main


def register_job_file(filename: str) -> str:
    job_id = str(uuid.uuid4())
    job_dir = main.TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / filename).write_bytes(b"safe")
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://youtu.be/abc_123", filename=filename)
    return job_id


@pytest.mark.parametrize(
    "bad_filename",
    [
        "../secret.mp3",
        "%2e%2e%2fsecret.mp3",
        "/tmp/secret.mp3",
        "nested/file.mp3",
        "nested\\file.mp3",
        "clip.mp3\r\nx-malicious: 1",
    ],
)
def test_resolve_download_path_rejects_traversal_and_header_injection_filenames(bad_filename):
    job_id = register_job_file("clip.mp3")

    with pytest.raises(HTTPException) as exc_info:
        main.resolve_download_path(job_id, bad_filename)

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize("bad_job_id", ["../job", "%2e%2e", "not-a-uuid", "nested/job"])
def test_decode_safe_job_id_rejects_unsafe_job_ids(bad_job_id):
    with pytest.raises(HTTPException) as exc_info:
        main.decode_safe_job_id(bad_job_id)

    assert exc_info.value.status_code == 400


def test_resolve_download_path_requires_registered_job_filename():
    job_id = register_job_file("expected.mp3")
    (main.TEMP_DIR / job_id / "sibling.mp3").write_bytes(b"secret")

    with pytest.raises(HTTPException) as exc_info:
        main.resolve_download_path(job_id, "sibling.mp3")

    assert exc_info.value.status_code == 404


def test_resolve_download_path_rejects_symlinked_job_directory_escape(tmp_path):
    job_id = str(uuid.uuid4())
    outside_dir = tmp_path.parent / f"outside-{job_id}"
    outside_dir.mkdir()
    (outside_dir / "clip.mp3").write_bytes(b"secret")
    (main.TEMP_DIR / job_id).symlink_to(outside_dir, target_is_directory=True)
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://youtu.be/abc_123", filename="clip.mp3")

    with pytest.raises(HTTPException) as exc_info:
        main.resolve_download_path(job_id, "clip.mp3")

    assert exc_info.value.status_code == 400


def test_resolve_download_path_rejects_symlinked_file_escape(tmp_path):
    job_id = str(uuid.uuid4())
    job_dir = main.TEMP_DIR / job_id
    job_dir.mkdir()
    outside_file = tmp_path / "secret.mp3"
    outside_file.write_bytes(b"secret")
    (job_dir / "clip.mp3").symlink_to(outside_file)
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://youtu.be/abc_123", filename="clip.mp3")

    with pytest.raises(HTTPException) as exc_info:
        main.resolve_download_path(job_id, "clip.mp3")

    assert exc_info.value.status_code == 400


def test_resolve_download_path_returns_404_when_registered_file_is_missing():
    job_id = str(uuid.uuid4())
    (main.TEMP_DIR / job_id).mkdir()
    with main.jobs_lock:
        main.jobs[job_id] = main.Job(id=job_id, url="https://youtu.be/abc_123", filename="missing.mp3")

    with pytest.raises(HTTPException) as exc_info:
        main.resolve_download_path(job_id, "missing.mp3")

    assert exc_info.value.status_code == 404
