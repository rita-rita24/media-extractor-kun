import os
import re
import uuid
import asyncio
import shutil
import time
import string
import random
import ipaddress
import queue
import socket
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess
import threading

app = FastAPI(title="Video Audio Extractor API")

# CORS設定
DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 一時ディレクトリ
TEMP_DIR = Path("/tmp/youtube-audio")
TEMP_DIR.mkdir(exist_ok=True)

# 最大処理時間（10時間 + バッファ）
MAX_DURATION_SECONDS = 12 * 60 * 60  # 12時間
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "3"))
JOB_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("JOB_RATE_LIMIT_WINDOW_SECONDS", "60"))
JOB_RATE_LIMIT_MAX_REQUESTS = int(os.getenv("JOB_RATE_LIMIT_MAX_REQUESTS", "5"))
MAX_DIRECT_MEDIA_BYTES = int(os.getenv("MAX_DIRECT_MEDIA_BYTES", str(512 * 1024 * 1024)))


class JobStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    COMPLETED = "completed"
    FAILED = "failed"


class DownloadType(str, Enum):
    AUDIO = "audio"
    VIDEO = "video"


@dataclass
class Job:
    id: str
    url: str
    custom_filename: Optional[str] = None
    download_type: DownloadType = DownloadType.AUDIO
    video_quality: str = "720p"
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    message: str = "待機中..."
    filename: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


# インメモリジョブストア
jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()
job_start_history: dict[str, list[float]] = {}
rate_limit_lock = threading.Lock()


TERMINAL_JOB_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED}


def count_active_jobs_locked() -> int:
    return sum(1 for job in jobs.values() if job.status not in TERMINAL_JOB_STATUSES)


def is_job_start_rate_limited(client_id: str, now: Optional[float] = None) -> bool:
    now = time.monotonic() if now is None else now
    window_start = now - JOB_RATE_LIMIT_WINDOW_SECONDS

    with rate_limit_lock:
        recent_starts = [
            timestamp
            for timestamp in job_start_history.get(client_id, [])
            if timestamp >= window_start
        ]
        if len(recent_starts) >= JOB_RATE_LIMIT_MAX_REQUESTS:
            job_start_history[client_id] = recent_starts
            return True

        recent_starts.append(now)
        job_start_history[client_id] = recent_starts
        return False


def generate_random_filename(length: int = 8) -> str:
    """ランダムな英数字のファイル名を生成"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


class ExtractRequest(BaseModel):
    url: str
    filename: Optional[str] = None
    download_type: str = "audio"  # "audio" or "video"
    video_quality: str = "720p"  # "720p", "1080p", or "best"


class JobResponse(BaseModel):
    job_id: str
    status: str
    progress: float
    message: str
    filename: Optional[str] = None
    error: Optional[str] = None


# 対応するメディア拡張子
MEDIA_EXTENSIONS = ('.mp3', '.mp4', '.wav', '.m4a', '.webm', '.ogg', '.aac', '.flac')
BLOCKED_DIRECT_MEDIA_HOSTS = {"localhost", "localhost.localdomain"}


def is_public_ip_address(ip: ipaddress._BaseAddress) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_direct_media_host_ips(hostname: str) -> list[ipaddress._BaseAddress]:
    try:
        ip = ipaddress.ip_address(hostname)
        return [ip]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError:
        return []

    addresses = []
    for info in infos:
        address = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(address))
        except ValueError:
            continue
    return addresses


def is_public_direct_media_host(hostname: Optional[str]) -> bool:
    """直接メディアURLとしてサーバー側取得してよいホストかを判定"""
    if not hostname:
        return False

    host = hostname.rstrip(".").lower()
    if host in BLOCKED_DIRECT_MEDIA_HOSTS or host.endswith(".localhost") or host.endswith(".local"):
        return False

    if "." not in host:
        return False

    resolved_ips = resolve_direct_media_host_ips(host)
    return bool(resolved_ips) and all(is_public_ip_address(ip) for ip in resolved_ips)


def is_direct_media_url(url: str) -> bool:
    """直接メディアファイルへのURLかどうかを判定"""
    # クエリパラメータを除いたパスで判定
    from urllib.parse import urlparse
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False
    if not is_public_direct_media_host(parsed.hostname):
        return False
    path = parsed.path.lower()
    return path.endswith(MEDIA_EXTENSIONS)


def validate_direct_media_response_url(url: str) -> None:
    if not is_direct_media_url(url):
        raise Exception("リダイレクト先が許可されていないURLです")


def get_content_length(headers: dict) -> int:
    try:
        return int(headers.get("content-length", 0) or 0)
    except (TypeError, ValueError):
        return 0


def ensure_download_size_within_limit(size: int) -> None:
    if size > MAX_DIRECT_MEDIA_BYTES:
        max_mb = MAX_DIRECT_MEDIA_BYTES // 1024 // 1024
        raise Exception(f"ファイルサイズが上限を超えています（最大{max_mb}MB）")


def clamp_progress(progress: float) -> float:
    return max(0.0, min(100.0, progress))


def format_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size}B"


def update_job_progress(
    job: Job,
    progress: float,
    message: Optional[str] = None,
    status: Optional[JobStatus] = None,
) -> None:
    progress = clamp_progress(progress)
    with jobs_lock:
        if status is not None:
            job.status = status
        if progress >= job.progress:
            job.progress = progress
        if message is not None:
            job.message = message


def write_streaming_response_to_file(
    response,
    output_path: Path,
    job: Optional[Job] = None,
    progress_start: float = 0.0,
    progress_end: float = 100.0,
    message: str = "ダウンロード中...",
    status: Optional[JobStatus] = None,
) -> None:
    total_size = get_content_length(response.headers)
    ensure_download_size_within_limit(total_size)

    downloaded = 0
    last_reported_progress = int(progress_start) - 1
    last_reported_bytes = 0
    if job:
        update_job_progress(job, progress_start, message, status)

    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            downloaded += len(chunk)
            ensure_download_size_within_limit(downloaded)
            f.write(chunk)

            if not job:
                continue

            if total_size > 0:
                progress = progress_start + (downloaded / total_size) * (progress_end - progress_start)
                progress = min(progress, progress_end)
                progress_bucket = int(progress)
                if progress_bucket > last_reported_progress or downloaded >= total_size:
                    last_reported_progress = progress_bucket
                    update_job_progress(
                        job,
                        progress,
                        f"{message} {format_bytes(downloaded)} / {format_bytes(total_size)}",
                        status,
                    )
            else:
                if last_reported_bytes == 0 or downloaded - last_reported_bytes >= 1024 * 1024:
                    last_reported_bytes = downloaded
                    update_job_progress(job, progress_start, f"{message} {format_bytes(downloaded)}", status)


def read_process_output_with_timeout(process, timeout_seconds: int):
    output_queue: queue.Queue = queue.Queue()
    sentinel = object()
    deadline = time.monotonic() + timeout_seconds

    def reader():
        try:
            for line in iter(process.stdout.readline, ""):
                output_queue.put(line)
        finally:
            output_queue.put(sentinel)

    threading.Thread(target=reader, daemon=True).start()

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(getattr(process, "args", None), timeout_seconds)

        try:
            item = output_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue

        if item is sentinel:
            break
        yield item

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(getattr(process, "args", None), timeout_seconds)
    process.wait(timeout=remaining)


def is_supported_youtube_url(url: str) -> bool:
    """YouTubeの動画URLかどうかを判定"""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")

    if parsed.scheme not in ("http", "https"):
        return False

    if hostname in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        if path == "/watch":
            video_ids = parse_qs(parsed.query).get("v", [])
            return any(re.fullmatch(r"[\w-]+", video_id) for video_id in video_ids)
        return re.fullmatch(r"/shorts/[\w-]+", path) is not None

    if hostname in ("youtu.be", "www.youtu.be"):
        return re.fullmatch(r"/[\w-]+", path) is not None

    return False


def validate_video_url(url: str) -> bool:
    """対応サイト（YouTube, TikTok, Instagram, X、直接メディアURL）のURL検証"""
    # 直接メディアファイルへのURLは許可
    if is_direct_media_url(url):
        return True

    if is_supported_youtube_url(url):
        return True

    patterns = [
        # TikTok
        r"^https?://(www\.|vm\.|vt\.)?tiktok\.com/.+",
        # Instagram
        r"^https?://(www\.)?instagram\.com/(p|reel|reels|tv)/.+",
        # X (Twitter)
        r"^https?://(www\.)?(twitter|x)\.com/.+/status/.+",
    ]
    return any(re.match(pattern, url.strip()) for pattern in patterns)


def cleanup_old_jobs():
    """古いジョブと一時ファイルを削除（6時間以上前）"""
    now = datetime.now()
    with jobs_lock:
        expired_jobs = [
            job_id for job_id, job in jobs.items()
            if (
                job.status in (JobStatus.COMPLETED, JobStatus.FAILED)
                and (now - job.created_at).total_seconds() > 6 * 60 * 60
            )
        ]
        for job_id in expired_jobs:
            # ファイル削除
            job_dir = TEMP_DIR / job_id
            if job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)
            del jobs[job_id]


def parse_download_percent(line: str) -> Optional[float]:
    if "[download]" not in line or "%" not in line:
        return None
    try:
        match = re.search(r"(\d+\.?\d*)%", line)
        if match:
            return float(match.group(1))
    except:
        pass
    return None


def map_download_progress(percent: float, progress_start: float = 0.0, progress_end: float = 70.0) -> float:
    return progress_start + (percent / 100.0) * (progress_end - progress_start)


def parse_progress(line: str) -> tuple[float, str]:
    """yt-dlpの出力から進捗をパース"""
    # ダウンロード進捗: [download]  45.2% of 150.00MiB at 5.00MiB/s ETA 00:20
    percent = parse_download_percent(line)
    if percent is not None:
        # ダウンロードは全体の70%とみなす
        return map_download_progress(percent), f"ダウンロード中... {percent:.1f}%"

    # 変換中
    if "[ExtractAudio]" in line:
        return 75.0, "音声を変換中..."

    # Post-processing
    if "[Merger]" in line or "Merging" in line:
        return 85.0, "ファイルを処理中..."

    return -1, ""


def resolve_tiktok_redirect(url: str) -> str:
    """curl_cffiを使用してTikTokの短縮URLを展開"""
    print(f"Resolving TikTok URL: {url}")
    try:
        from curl_cffi import requests
        # リダイレクト解決（impersonateを使用してBot検知を回避しつつ）
        r = requests.get(
            url,
            allow_redirects=True,
            impersonate="chrome",
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        print(f"Resolved URL: {url} -> {r.url}")
        return r.url
    except Exception as e:
        print(f"Redirect resolution failed: {e}")
        return url


def get_tiktok_video_info(url: str) -> dict:
    """tikwm.com APIを使用してTikTok動画情報を取得"""
    import requests
    import json

    print(f"Getting TikTok video info via tikwm.com API: {url}")

    try:
        api_url = f"https://tikwm.com/api/?url={url}"
        response = requests.get(api_url, timeout=30)
        data = response.json()

        if data.get("code") == 0 and data.get("data"):
            video_data = data["data"]
            video_id = video_data.get("id")

            # tikwm.comのメディアURL形式を使用（より安定したダウンロード）
            video_url = f"https://www.tikwm.com/video/media/hdplay/{video_id}.mp4" if video_id else video_data.get("play")
            music_url = f"https://www.tikwm.com/video/music/{video_id}.mp3" if video_id else video_data.get("music")

            result = {
                "success": True,
                "video_id": video_id,
                "video_url": video_url,  # メディアURL形式
                "video_url_fallback": video_data.get("play"),  # フォールバック用
                "music_url": music_url,  # 音声URL (MP3)
                "music_url_fallback": video_data.get("music"),  # フォールバック用
                "title": video_data.get("title", ""),
                "duration": video_data.get("duration", 0),
                "cover": video_data.get("cover", ""),
            }
            print(f"TikTok video info retrieved: id={video_id}, title={result['title']}, duration={result['duration']}s")
            return result
        else:
            print(f"tikwm.com API error: {data.get('msg', 'Unknown error')}")
            return {"success": False, "error": data.get("msg", "Unknown error")}

    except Exception as e:
        print(f"tikwm.com API request failed: {e}")
        return {"success": False, "error": str(e)}


def download_tiktok_via_tiksave(
    url: str,
    output_path: str,
    job: Optional[Job] = None,
    progress_start: float = 25.0,
    progress_end: float = 95.0,
    message: str = "予備サーバーでダウンロード中...",
) -> bool:
    """tiksave.ioを使用してTikTok動画をダウンロード（サブスク限定動画対応）"""
    import cloudscraper
    from bs4 import BeautifulSoup
    import os

    print(f"Attempting download via tiksave.io (fallback): {url}")

    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'darwin', 'desktop': True}
        )

        if job:
            update_job_progress(job, 15.0, "予備サーバーを確認中...", JobStatus.DOWNLOADING)

        # 1. メインページアクセス
        scraper.get("https://tiksave.io/ja")

        # 2. APIリクエスト
        if job:
            update_job_progress(job, 20.0, "ダウンロードリンクを取得中...", JobStatus.DOWNLOADING)

        api_url = "https://tiksave.io/api/ajaxSearch"
        data = {"q": url, "lang": "ja"}

        r = scraper.post(api_url, data=data)
        if r.status_code != 200:
            print(f"tiksave.io API failed: {r.status_code}")
            return False

        resp_json = r.json()
        html_content = resp_json.get("data", "")
        soup = BeautifulSoup(html_content, 'html.parser')

        download_link = None
        # クラス名で検索
        buttons = soup.find_all('a', class_='tik-button-dl')

        # HDを優先的に探す
        for btn in buttons:
            text = btn.get_text()
            if "HD" in text:
                download_link = btn.get('href')
                print("Selected HD link from tiksave.io")
                break

        # HDがなければ最初のMP4リンク
        if not download_link and buttons:
            download_link = buttons[0].get('href')
            print("Selected Standard MP4 link from tiksave.io")

        if not download_link:
            print("No download link found in tiksave.io response")
            return False

        # ダウンロード実行
        print(f"Downloading from tiksave.io: {download_link}")
        headers = {
            "Referer": "https://tiksave.io/",
            "User-Agent": scraper.headers["User-Agent"]
        }

        validate_direct_media_response_url(download_link)
        r_down = scraper.get(download_link, headers=headers, stream=True)
        if r_down.status_code == 200:
            write_streaming_response_to_file(
                r_down,
                Path(output_path),
                job=job,
                progress_start=progress_start,
                progress_end=progress_end,
                message=message,
                status=JobStatus.DOWNLOADING,
            )

            # ファイルサイズチェック
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                print(f"Download complete via tiksave.io: {output_path}")
                return True
            else:
                print("Downloaded file is too small")
                return False
        else:
            print(f"tiksave.io download failed: {r_down.status_code}")
            return False

    except Exception as e:
        print(f"Error downloading via tiksave.io: {e}")
        return False


def process_job(job_id: str):
    """バックグラウンドでyt-dlpを実行"""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return

    output_dir = TEMP_DIR / job_id
    output_dir.mkdir(exist_ok=True)

    # ファイル名を決定（ユーザー指定 > ランダム生成）
    if job.custom_filename:
        # ユーザー指定のファイル名（拡張子なし）
        base_filename = re.sub(r'[<>:"/\\|?*]', '_', job.custom_filename)
    else:
        # ランダム生成
        base_filename = generate_random_filename()

    output_template = str(output_dir / f"{base_filename}.%(ext)s")

    try:
        # 直接メディアファイルの場合はシンプルにHTTPダウンロード
        if is_direct_media_url(job.url):
            with jobs_lock:
                job.status = JobStatus.DOWNLOADING
                job.progress = 10.0
                job.message = "ファイルをダウンロード中..."

            import requests as req
            from urllib.parse import urlparse, unquote

            # 元のファイル名から拡張子を取得
            parsed_url = urlparse(job.url)
            original_filename = unquote(os.path.basename(parsed_url.path))
            _, ext = os.path.splitext(original_filename)
            ext = ext.lower() if ext else '.mp3'

            # 音声ファイルでaudio指定、または動画ファイルでvideo指定をチェック
            is_audio_ext = ext in ('.mp3', '.wav', '.m4a', '.ogg', '.aac', '.flac')
            is_video_ext = ext in ('.mp4', '.webm')

            print(f"Direct media download: {job.url} (ext: {ext})")

            response = req.get(job.url, timeout=300, stream=True, allow_redirects=False)
            if 300 <= response.status_code < 400:
                redirect_url = response.headers.get("location", "")
                validate_direct_media_response_url(redirect_url)
                response = req.get(redirect_url, timeout=300, stream=True, allow_redirects=False)

            if response.status_code == 200:
                output_path = output_dir / f"{base_filename}{ext}"
                write_streaming_response_to_file(
                    response,
                    output_path,
                    job=job,
                    progress_start=10.0,
                    progress_end=95.0,
                    message="ダウンロード中...",
                    status=JobStatus.DOWNLOADING,
                )

                # 完了
                with jobs_lock:
                    job.status = JobStatus.COMPLETED
                    job.progress = 100.0
                    job.message = "完了！"
                    job.filename = output_path.name
                    job.completed_at = datetime.now()
                print(f"Direct download complete: {output_path}")
                return
            else:
                raise Exception(f"ダウンロードに失敗しました (HTTP {response.status_code})")

        # ステータス更新: ダウンロード開始
        with jobs_lock:
            job.status = JobStatus.DOWNLOADING
            job.progress = 5.0
            job.message = "動画情報を取得中..."

        target_url = job.url
        extra_opts = []
        tiktok_info = None

        # TikTok特有の処理: tikwm.com APIを使用
        if "tiktok.com" in job.url or "vt.tiktok.com" in job.url:
            with jobs_lock:
                job.message = "TikTok URLを解析中..."

            # tikwm.com API で動画情報を取得
            tiktok_info = get_tiktok_video_info(job.url)

            if tiktok_info.get("success"):
                # 音声抽出でmusic_urlがある場合は直接ダウンロード
                if job.download_type == DownloadType.AUDIO and tiktok_info.get("music_url"):
                    update_job_progress(job, 20.0, "音声をダウンロード中...", JobStatus.DOWNLOADING)

                    # 直接ダウンロード
                    import requests as req
                    music_url = tiktok_info.get("music_url")
                    print(f"Downloading TikTok audio directly: {music_url}")

                    audio_response = req.get(music_url, timeout=120, stream=True)
                    if audio_response.status_code == 200:
                        output_path = output_dir / f"{base_filename}.mp3"
                        write_streaming_response_to_file(
                            audio_response,
                            output_path,
                            job=job,
                            progress_start=20.0,
                            progress_end=95.0,
                            message="音声をダウンロード中...",
                            status=JobStatus.DOWNLOADING,
                        )

                        # 完了
                        with jobs_lock:
                            job.status = JobStatus.COMPLETED
                            job.progress = 100.0
                            job.message = "完了！"
                            job.filename = output_path.name
                            job.completed_at = datetime.now()
                        return  # 処理終了
                    else:
                        print(f"Direct audio download failed: {audio_response.status_code}")
                        # フォールバックしてyt-dlpを使用

                # WebM/WebPなどの一時ファイルを無視する設定（既存）

                # 動画ダウンロード
                # サブスク限定動画かどうかを判定
                title = tiktok_info.get("title", "")
                is_subscriber_only = "サブスク" in title or "subscriber" in title.lower() or "限定" in title

                download_success = False

                # 1. サブスク限定動画ならTikSaveを優先
                if job.download_type == DownloadType.VIDEO and is_subscriber_only:
                    print(f"Subscriber-only video detected: {title}. Trying tiksave.io first.")
                    output_path = output_dir / f"{base_filename}.mp4"
                    if download_tiktok_via_tiksave(
                        job.url,
                        str(output_path),
                        job=job,
                        progress_start=25.0,
                        progress_end=95.0,
                        message="予備サーバーでダウンロード中...",
                    ):
                        download_success = True
                        with jobs_lock:
                            job.status = JobStatus.COMPLETED
                            job.progress = 100.0
                            job.message = "完了！（TikSave経由）"
                            job.filename = output_path.name
                            job.completed_at = datetime.now()
                        return

                # 2. 通常のtikwm.com直接ダウンロード
                if not download_success and job.download_type == DownloadType.VIDEO and tiktok_info.get("video_url"):
                    update_job_progress(job, 20.0, "動画をダウンロード中...", JobStatus.DOWNLOADING)

                    try:
                        # tikwm.comからダウンロード
                        import requests as req
                        # video_urlはget_tiktok_video_infoでtikwm.comのメディアURLになっている
                        video_url = tiktok_info.get("video_url")
                        print(f"Downloading TikTok video directly from tikwm: {video_url}")

                        video_response = req.get(video_url, timeout=300, stream=True)

                        if video_response.status_code == 200:
                            output_path = output_dir / f"{base_filename}.mp4"
                            write_streaming_response_to_file(
                                video_response,
                                output_path,
                                job=job,
                                progress_start=20.0,
                                progress_end=95.0,
                                message="動画をダウンロード中...",
                                status=JobStatus.DOWNLOADING,
                            )

                            print(f"Direct download successful. Size: {os.path.getsize(output_path)} bytes")
                            download_success = True

                            with jobs_lock:
                                job.status = JobStatus.COMPLETED
                                job.progress = 100.0
                                job.message = "完了！"
                                job.filename = output_path.name
                                job.completed_at = datetime.now()
                            return
                        else:
                            print(f"Direct video download failed: {video_response.status_code}")
                    except Exception as e:
                        print(f"Direct video download error: {e}")

                # 3. TikSaveへのフォールバック（tikwmが失敗した場合）
                if not download_success and job.download_type == DownloadType.VIDEO:
                    print("Falling back to tiksave.io...")
                    update_job_progress(job, 20.0, "予備サーバーでダウンロード中...", JobStatus.DOWNLOADING)

                    output_path = output_dir / f"{base_filename}.mp4"
                    if download_tiktok_via_tiksave(
                        job.url,
                        str(output_path),
                        job=job,
                        progress_start=25.0,
                        progress_end=95.0,
                        message="予備サーバーでダウンロード中...",
                    ):
                        download_success = True
                        with jobs_lock:
                            job.status = JobStatus.COMPLETED
                            job.progress = 100.0
                            job.message = "完了！（予備サーバー経由）"
                            job.filename = output_path.name
                            job.completed_at = datetime.now()
                        return

                # 4. 最終手段: yt-dlpへのフォールバック
                print("All direct methods failed. Falling back to yt-dlp...")
                target_url = tiktok_info.get("video_url") or job.url  # urlフォールバック

                with jobs_lock:
                    job.message = "ダウンロード中（標準モード）..."
            else:
                # APIが失敗した場合はフォールバック（従来の方法）
                print(f"tikwm.com API failed, falling back to yt-dlp direct")
                if "vt.tiktok.com" in job.url or "/t/" in job.url:
                    target_url = resolve_tiktok_redirect(job.url)

                extra_opts.extend([
                    "--impersonate", "chrome",
                ])

        # 共通のyt-dlpオプション
        common_opts = [
            "--no-playlist",
            "--restrict-filenames",
            "--newline",
            "--progress",
            *extra_opts,
        ]

        # ダウンロードタイプに応じてコマンドを構築
        if job.download_type == DownloadType.AUDIO:
            # 音声のみ抽出
            cmd = [
                "yt-dlp",
                "-x",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "-o", output_template,
                *common_opts,
                target_url,
            ]
            file_extension = "mp3"
            convert_message = "MP3に変換中..."
        else:
            # 動画ダウンロード
            if job.video_quality == "best":
                format_spec = "bestvideo+bestaudio/best"
            elif job.video_quality == "1080p":
                format_spec = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
            else:  # 720p
                format_spec = "bestvideo[height<=720]+bestaudio/best[height<=720]"

            # 直リンクの場合はフォーマット指定を緩める
            if target_url != job.url:
                format_spec = "best"

            cmd = [
                "yt-dlp",
                "-f", format_spec,
                "--merge-output-format", "mp4",
                "-o", output_template,
                *common_opts,
                target_url,
            ]
            file_extension = "mp4"
            convert_message = "MP4に変換中..."

        # yt-dlpプロセス開始
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # リアルタイム進捗更新
        last_download_percent = None
        download_progress_start = 5.0
        download_progress_end = 70.0
        for line in read_process_output_with_timeout(process, MAX_DURATION_SECONDS):
            line = line.strip()
            if not line:
                continue

            # 変換フェーズ検出
            if "[ExtractAudio]" in line:
                update_job_progress(job, 75.0, convert_message, JobStatus.CONVERTING)
                continue
            if "[Merger]" in line or "Merging" in line:
                update_job_progress(job, 85.0, "ファイルを処理中...", JobStatus.CONVERTING)
                continue

            download_percent = parse_download_percent(line)
            if download_percent is not None:
                if last_download_percent is not None and download_percent + 1.0 < last_download_percent:
                    download_progress_start = max(job.progress, download_progress_start)
                    download_progress_end = 75.0
                progress = map_download_progress(download_percent, download_progress_start, download_progress_end)
                update_job_progress(
                    job,
                    progress,
                    f"ダウンロード中... {download_percent:.1f}%",
                    JobStatus.DOWNLOADING,
                )
                last_download_percent = download_percent

        if process.returncode != 0:
            raise Exception("yt-dlpの実行に失敗しました")

        # 生成されたファイルを探す
        output_files = list(output_dir.glob(f"*.{file_extension}"))
        if not output_files:
            raise Exception(f"{file_extension.upper()}ファイルが生成されませんでした")

        output_file = output_files[0]

        # 完了
        with jobs_lock:
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
            job.message = "完了！"
            job.filename = output_file.name
            job.completed_at = datetime.now()

    except subprocess.TimeoutExpired:
        process.kill()
        with jobs_lock:
            job.status = JobStatus.FAILED
            job.error = "処理がタイムアウトしました（最大12時間）"
            job.message = "エラー"
        shutil.rmtree(output_dir, ignore_errors=True)

    except Exception as e:
        error_msg = str(e)
        if "Video unavailable" in error_msg:
            error_msg = "動画が利用できません"
        elif "Private video" in error_msg:
            error_msg = "非公開動画です"
        elif "Sign in" in error_msg:
            error_msg = "ログインが必要な動画です"
        # TikTokエラーメッセージの整形
        elif "TikTok" in error_msg and "203005" in error_msg:
            error_msg = "TikTok動画の取得に失敗しました（詳細：Bot検知によりブロックされました）"

        with jobs_lock:
            job.status = JobStatus.FAILED
            job.error = error_msg
            job.message = "エラー"
        shutil.rmtree(output_dir, ignore_errors=True)


def decode_safe_job_id(job_id: str) -> str:
    """APIパスから受け取ったjob_idを一時ディレクトリ配下の1要素として検証"""
    from urllib.parse import unquote

    decoded_job_id = unquote(job_id)
    if (
        not decoded_job_id
        or "/" in decoded_job_id
        or "\\" in decoded_job_id
        or decoded_job_id != Path(decoded_job_id).name
    ):
        raise HTTPException(status_code=400, detail="不正なリクエスト")

    try:
        uuid.UUID(decoded_job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="不正なリクエスト")

    return decoded_job_id


def decode_safe_filename(filename: str) -> str:
    """APIパスから受け取ったfilenameをジョブディレクトリ直下の1ファイルとして検証"""
    from urllib.parse import unquote

    decoded_filename = unquote(filename)
    if (
        not decoded_filename
        or "/" in decoded_filename
        or "\\" in decoded_filename
        or "\r" in decoded_filename
        or "\n" in decoded_filename
        or decoded_filename != Path(decoded_filename).name
    ):
        raise HTTPException(status_code=400, detail="不正なリクエスト")

    return decoded_filename


def resolve_download_path(job_id: str, filename: str) -> tuple[str, str, Path]:
    """ジョブの成果物だけをTEMP_DIR配下から安全に解決する"""
    decoded_job_id = decode_safe_job_id(job_id)
    decoded_filename = decode_safe_filename(filename)

    with jobs_lock:
        job = jobs.get(decoded_job_id)

    if not job or job.filename != decoded_filename:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    temp_root = TEMP_DIR.resolve()
    job_dir = (TEMP_DIR / decoded_job_id).resolve()
    file_path = (job_dir / decoded_filename).resolve()

    if temp_root != job_dir and temp_root not in job_dir.parents:
        raise HTTPException(status_code=400, detail="不正なリクエスト")
    if job_dir != file_path.parent:
        raise HTTPException(status_code=400, detail="不正なリクエスト")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    return decoded_job_id, decoded_filename, file_path


@app.post("/api/extract", response_model=JobResponse)
async def start_extraction(request: ExtractRequest, background_tasks: BackgroundTasks, http_request: Request):
    """音声抽出ジョブを開始"""

    # URL検証
    if not validate_video_url(request.url):
        raise HTTPException(status_code=400, detail="対応していないURLです。YouTube, TikTok, Instagram, X のURLを入力してください")

    # 古いジョブをクリーンアップ
    cleanup_old_jobs()

    client_host = http_request.client.host if http_request.client else "unknown"
    if is_job_start_rate_limited(client_host):
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください")

    # 新しいジョブを作成
    job_id = str(uuid.uuid4())
    custom_filename = request.filename.strip() if request.filename else None
    download_type = DownloadType.VIDEO if request.download_type == "video" else DownloadType.AUDIO
    video_quality = request.video_quality if request.video_quality in ["720p", "1080p", "best"] else "720p"
    job = Job(
        id=job_id,
        url=request.url,
        custom_filename=custom_filename,
        download_type=download_type,
        video_quality=video_quality,
    )

    with jobs_lock:
        if count_active_jobs_locked() >= MAX_CONCURRENT_JOBS:
            raise HTTPException(status_code=429, detail="同時処理数の上限に達しています。完了後に再試行してください")
        jobs[job_id] = job

    # バックグラウンドで処理開始
    thread = threading.Thread(target=process_job, args=(job_id,))
    thread.start()

    return JobResponse(
        job_id=job_id,
        status=job.status.value,
        progress=job.progress,
        message=job.message,
    )


@app.get("/api/job/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str):
    """ジョブのステータスを取得"""

    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    return JobResponse(
        job_id=job.id,
        status=job.status.value,
        progress=job.progress,
        message=job.message,
        filename=job.filename,
        error=job.error,
    )


@app.get("/api/download/{job_id}/{filename}")
async def download_audio(job_id: str, filename: str):
    """抽出した音声ファイルをダウンロード"""
    from urllib.parse import quote

    _, decoded_filename, file_path = resolve_download_path(job_id, filename)

    # 拡張子に応じてmedia_typeを決定
    if decoded_filename.lower().endswith(".mp4"):
        media_type = "video/mp4"
    else:
        media_type = "audio/mpeg"

    # RFC 5987準拠のContent-Dispositionヘッダーを生成
    encoded_filename = quote(decoded_filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
    }

    return FileResponse(
        path=str(file_path),
        filename=decoded_filename,
        media_type=media_type,
        headers=headers,
    )


@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str):
    """ジョブと関連ファイルを削除"""
    decoded_job_id = decode_safe_job_id(job_id)

    with jobs_lock:
        if decoded_job_id in jobs:
            del jobs[decoded_job_id]

    job_dir = TEMP_DIR / decoded_job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)

    return {"success": True}


@app.get("/api/health")
async def health_check():
    """ヘルスチェック"""
    return {"status": "ok", "active_jobs": len(jobs)}
