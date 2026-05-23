import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
REPORT_PATH = ROOT_DIR / "reports" / "social-platform-smoke.json"

sys.path.insert(0, str(BACKEND_DIR))

import main  # noqa: E402


SAMPLES = {
    "youtube": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "tiktok": "https://www.tiktok.com/@patroxofficial/video/6742501081818877190?langCountry=en",
    "instagram": "https://www.instagram.com/reel/CDUMkliABpa/",
    "x": "https://x.com/historyinmemes/status/1790637656616943991",
    "twitter": "https://twitter.com/historyinmemes/status/1790637656616943991",
}


def clean_tail(text: str, limit: int = 400) -> str:
    return " ".join((text or "").split())[-limit:]


def run_command(args: list[str], timeout: int = 60) -> dict:
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "error": f"timeout after {exc.timeout}s",
        }

    output = completed.stderr or completed.stdout
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "tail": clean_tail(output),
        "stdout": completed.stdout if completed.returncode == 0 else "",
    }


def yt_dlp_version() -> str | None:
    yt_dlp = shutil.which("yt-dlp")
    if not yt_dlp:
        return None
    result = run_command([yt_dlp, "--version"], timeout=10)
    if result["ok"]:
        return clean_tail(result["stdout"], limit=80)
    return None


def has_audio_format(info: dict) -> bool:
    formats = info.get("formats") or []
    return any(
        fmt.get("acodec") not in (None, "none")
        or fmt.get("audio_ext") not in (None, "none")
        for fmt in formats
    ) or info.get("acodec") not in (None, "none")


def has_video_format(info: dict) -> bool:
    formats = info.get("formats") or []
    return any(
        fmt.get("vcodec") not in (None, "none")
        or fmt.get("video_ext") not in (None, "none")
        for fmt in formats
    ) or info.get("vcodec") not in (None, "none")


def metadata_probe(url: str) -> dict:
    result = run_command([
        "yt-dlp",
        "--skip-download",
        "--no-playlist",
        "--dump-single-json",
        "--no-warnings",
        url,
    ])
    if not result["ok"]:
        return {"ok": False, "error": result.get("tail", "")}

    info = json.loads(result["stdout"])
    formats = info.get("formats") or []
    return {
        "ok": True,
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "format_count": len(formats),
        "has_audio_format": has_audio_format(info),
        "has_video_format": has_video_format(info),
    }


def simulate_app_mode(url: str, mode: str) -> dict:
    if mode == "audio":
        args = [
            "yt-dlp",
            "--simulate",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            url,
        ]
    else:
        args = [
            "yt-dlp",
            "--simulate",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
            "-f",
            "bestvideo+bestaudio/best",
            "--merge-output-format",
            "mp4",
            url,
        ]
    result = run_command(args)
    return {
        "ok": result["ok"],
        "returncode": result["returncode"],
        "tail": result.get("tail", ""),
    }


def tiktok_direct_api_probe(url: str) -> dict:
    info = main.get_tiktok_video_info(url)
    if not info.get("success"):
        return {"ok": False, "error": clean_tail(info.get("error", ""))}
    return {
        "ok": True,
        "video_id": info.get("video_id"),
        "duration": info.get("duration"),
        "music_url_present": bool(info.get("music_url")),
        "video_url_present": bool(info.get("video_url")),
        "title": info.get("title"),
    }


def main_cli() -> int:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "metadata and simulate only; no media files downloaded",
        "yt_dlp_version": yt_dlp_version(),
        "platforms": {},
    }

    exit_code = 0
    for platform, url in SAMPLES.items():
        platform_result = {
            "url": url,
            "backend_validation": main.validate_video_url(url),
            "metadata": metadata_probe(url),
            "audio_simulate": simulate_app_mode(url, "audio"),
            "video_simulate": simulate_app_mode(url, "video"),
        }
        if platform == "tiktok":
            platform_result["tiktok_direct_api"] = tiktok_direct_api_probe(url)

        platform_result["audio_extractable_without_download"] = bool(
            platform_result["audio_simulate"]["ok"]
            and (
                platform_result["metadata"].get("has_audio_format")
                or platform_result.get("tiktok_direct_api", {}).get("music_url_present")
            )
        )
        platform_result["video_extractable_without_download"] = bool(
            platform_result["video_simulate"]["ok"]
            and (
                platform_result["metadata"].get("has_video_format")
                or platform_result.get("tiktok_direct_api", {}).get("video_url_present")
            )
        )

        if not (
            platform_result["backend_validation"]
            and platform_result["audio_simulate"]["ok"]
            and platform_result["video_simulate"]["ok"]
            and platform_result["video_extractable_without_download"]
        ):
            exit_code = 1

        report["platforms"][platform] = platform_result

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main_cli())
