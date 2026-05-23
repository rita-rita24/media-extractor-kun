import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
REPORT_PATH = REPO_DIR / "reports" / "mutation-smoke.json"

MUTANTS = [
    {
        "name": "direct_media_allows_non_http_scheme",
        "find": 'if parsed.scheme not in ("http", "https"):',
        "replace": 'if False and parsed.scheme not in ("http", "https"):',
    },
    {
        "name": "direct_media_skips_public_host_check",
        "find": "if not is_public_direct_media_host(parsed.hostname):",
        "replace": "if False and not is_public_direct_media_host(parsed.hostname):",
    },
    {
        "name": "direct_media_allows_private_ip",
        "find": "ip.is_private\n        or ip.is_loopback",
        "replace": "False\n        or ip.is_loopback",
    },
    {
        "name": "direct_media_allows_mixed_public_and_private_dns_answers",
        "find": "return bool(resolved_ips) and all(is_public_ip_address(ip) for ip in resolved_ips)",
        "replace": "return bool(resolved_ips) and any(is_public_ip_address(ip) for ip in resolved_ips)",
    },
    {
        "name": "job_start_rate_limit_disabled",
        "find": "if len(recent_starts) >= JOB_RATE_LIMIT_MAX_REQUESTS:",
        "replace": "if False and len(recent_starts) >= JOB_RATE_LIMIT_MAX_REQUESTS:",
    },
    {
        "name": "active_job_limit_disabled",
        "find": "if count_active_jobs_locked() >= MAX_CONCURRENT_JOBS:",
        "replace": "if False and count_active_jobs_locked() >= MAX_CONCURRENT_JOBS:",
    },
    {
        "name": "direct_media_size_limit_disabled",
        "find": "if size > MAX_DIRECT_MEDIA_BYTES:",
        "replace": "if False and size > MAX_DIRECT_MEDIA_BYTES:",
    },
    {
        "name": "stdout_timeout_disabled",
        "find": "if remaining <= 0:\n            raise subprocess.TimeoutExpired(getattr(process, \"args\", None), timeout_seconds)",
        "replace": "if False and remaining <= 0:\n            raise subprocess.TimeoutExpired(getattr(process, \"args\", None), timeout_seconds)",
    },
    {
        "name": "cleanup_removes_active_old_jobs",
        "find": "job.status in (JobStatus.COMPLETED, JobStatus.FAILED)\n                and",
        "replace": "True\n                and",
    },
    {
        "name": "download_allows_unregistered_filename",
        "find": "if not job or job.filename != decoded_filename:",
        "replace": "if not job and job.filename != decoded_filename:",
    },
    {
        "name": "extract_inverts_video_type_default",
        "find": 'download_type = DownloadType.VIDEO if request.download_type == "video" else DownloadType.AUDIO',
        "replace": 'download_type = DownloadType.VIDEO if request.download_type != "video" else DownloadType.AUDIO',
    },
    {
        "name": "extract_rejects_all_video_quality_values",
        "find": 'video_quality = request.video_quality if request.video_quality in ["720p", "1080p", "best"] else "720p"',
        "replace": 'video_quality = request.video_quality if False else "720p"',
    },
    {
        "name": "direct_media_success_treated_as_failure",
        "find": "if response.status_code == 200:",
        "replace": "if response.status_code != 200:",
    },
    {
        "name": "audio_jobs_can_complete_through_video_tiksave_fallback",
        "find": "if not download_success and job.download_type == DownloadType.VIDEO:",
        "replace": "if not download_success:",
    },
    {
        "name": "progress_noise_reports_zero",
        "find": 'return -1, ""',
        "replace": 'return 0, ""',
    },
]


def run_mutant(mutant):
    original = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")
    if mutant["find"] not in original:
        return {
            "name": mutant["name"],
            "status": "skipped",
            "reason": "mutation target text was not found",
        }

    with tempfile.TemporaryDirectory(prefix="qa-mutation-") as temp_name:
        temp_dir = Path(temp_name)
        (temp_dir / "main.py").write_text(
            original.replace(mutant["find"], mutant["replace"], 1),
            encoding="utf-8",
        )
        shutil.copytree(BACKEND_DIR / "tests", temp_dir / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(BACKEND_DIR / "pytest.ini", temp_dir / "pytest.ini")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(temp_dir)
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=temp_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    return {
        "name": mutant["name"],
        "status": "killed" if completed.returncode != 0 else "survived",
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
    }


def main():
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results = [run_mutant(mutant) for mutant in MUTANTS]
    checked = [result for result in results if result["status"] != "skipped"]
    killed = [result for result in checked if result["status"] == "killed"]
    survived = [result for result in checked if result["status"] == "survived"]
    report = {
        "tool": "custom mutation smoke",
        "checked": len(checked),
        "killed": len(killed),
        "survived": len(survived),
        "skipped": len(results) - len(checked),
        "mutation_score": round((len(killed) / len(checked)) * 100, 2) if checked else 0.0,
        "results": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
