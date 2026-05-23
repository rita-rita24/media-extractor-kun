from pathlib import Path
import ipaddress

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(autouse=True)
def isolated_job_store(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "TEMP_DIR", tmp_path)
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main, "MAX_CONCURRENT_JOBS", 3)
    monkeypatch.setattr(main, "JOB_RATE_LIMIT_WINDOW_SECONDS", 60)
    monkeypatch.setattr(main, "JOB_RATE_LIMIT_MAX_REQUESTS", 5)
    monkeypatch.setattr(main, "MAX_DIRECT_MEDIA_BYTES", 512 * 1024 * 1024)

    original_resolver = main.resolve_direct_media_host_ips

    def stable_test_resolver(hostname):
        public_test_hosts = {
            "cdn.example.com",
            "media.example.org",
            "download.example",
            "video.example",
            "music.example",
        }
        if hostname in public_test_hosts:
            return [ipaddress.ip_address("93.184.216.34")]
        return original_resolver(hostname)

    monkeypatch.setattr(main, "resolve_direct_media_host_ips", stable_test_resolver)
    with main.jobs_lock:
        main.jobs.clear()
    with main.rate_limit_lock:
        main.job_start_history.clear()
    yield tmp_path
    with main.jobs_lock:
        main.jobs.clear()
    with main.rate_limit_lock:
        main.job_start_history.clear()


@pytest.fixture
def client():
    with TestClient(main.app) as test_client:
        yield test_client
