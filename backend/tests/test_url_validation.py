import string
import ipaddress

import pytest
from hypothesis import given, strategies as st

import main


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc_123-XYZ",
        "https://music.youtube.com/watch?v=abc123",
        "https://www.youtube.com/shorts/short_123",
        "https://youtu.be/abc_123",
        "https://www.tiktok.com/@user/video/1234567890",
        "https://vm.tiktok.com/ZSaPaWdvS/",
        "https://www.instagram.com/reel/abc123/",
        "https://x.com/user/status/123456789",
        "https://cdn.example.com/media/audio.m4a?download=1",
        "https://media.example.org/videos/clip.mp4",
    ],
)
def test_validate_video_url_accepts_supported_public_urls(url):
    assert main.validate_video_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url.mp3",
        "file:///tmp/audio.mp3",
        "ftp://example.com/audio.mp3",
        "https://youtube.com/watch",
        "https://youtube.com/watch?v=",
        "https://evil.example/watch?v=abc",
        "http://localhost/audio.mp3",
        "http://127.0.0.1/audio.mp3",
        "http://[::1]/audio.mp3",
        "http://0.0.0.0/audio.mp3",
        "http://10.0.0.4/audio.mp3",
        "http://172.16.0.4/audio.mp3",
        "http://192.168.1.10/audio.mp3",
        "http://169.254.169.254/latest/meta-data/audio.mp3",
        "http://media.local/audio.mp3",
        "http://printer/audio.mp3",
    ],
)
def test_validate_video_url_rejects_unsupported_or_private_direct_media_urls(url):
    assert main.validate_video_url(url) is False


def test_public_direct_media_host_rejects_missing_hostname():
    assert main.is_public_direct_media_host(None) is False


def test_public_direct_media_host_rejects_domain_that_resolves_to_private_ip(monkeypatch):
    monkeypatch.setattr(
        main,
        "resolve_direct_media_host_ips",
        lambda hostname: [ipaddress.ip_address("10.0.0.10")],
    )

    assert main.is_public_direct_media_host("media.example.com") is False


def test_public_direct_media_host_rejects_mixed_public_and_private_dns_answers(monkeypatch):
    monkeypatch.setattr(
        main,
        "resolve_direct_media_host_ips",
        lambda hostname: [ipaddress.ip_address("93.184.216.34"), ipaddress.ip_address("10.0.0.10")],
    )

    assert main.is_public_direct_media_host("media.example.com") is False


def test_public_direct_media_host_rejects_unresolvable_domain(monkeypatch):
    monkeypatch.setattr(main, "resolve_direct_media_host_ips", lambda hostname: [])

    assert main.is_public_direct_media_host("media.example.com") is False


def test_resolve_direct_media_host_ips_ignores_unparseable_socket_addresses(monkeypatch):
    monkeypatch.setattr(
        main.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("not-an-ip-address", 0))],
    )

    assert main.resolve_direct_media_host_ips("media.example.com") == []


@given(st.text(alphabet=string.ascii_letters + string.digits + "_-", min_size=1, max_size=32))
def test_supported_youtube_watch_url_accepts_safe_video_ids(video_id):
    assert main.is_supported_youtube_url(f"https://www.youtube.com/watch?v={video_id}") is True
    assert main.is_supported_youtube_url(f"https://youtu.be/{video_id}") is True


@given(st.integers(min_value=0, max_value=32))
def test_generate_random_filename_returns_requested_lowercase_token(length):
    filename = main.generate_random_filename(length)

    assert len(filename) == length
    assert set(filename) <= set(string.ascii_lowercase + string.digits)
