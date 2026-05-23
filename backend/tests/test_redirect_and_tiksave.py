import sys
import types

import main


def test_resolve_tiktok_redirect_returns_final_url(monkeypatch):
    class FakeResponse:
        url = "https://www.tiktok.com/@user/video/123"

    def fake_get(url, allow_redirects, impersonate, timeout, headers):
        assert url == "https://vt.tiktok.com/short/"
        assert allow_redirects is True
        assert impersonate == "chrome"
        assert timeout == 10
        assert "User-Agent" in headers
        return FakeResponse()

    fake_requests = types.SimpleNamespace(get=fake_get)
    monkeypatch.setitem(sys.modules, "curl_cffi", types.SimpleNamespace(requests=fake_requests))

    assert main.resolve_tiktok_redirect("https://vt.tiktok.com/short/") == "https://www.tiktok.com/@user/video/123"


def test_resolve_tiktok_redirect_returns_original_url_on_failure(monkeypatch):
    def fake_get(*args, **kwargs):
        raise TimeoutError("network timeout")

    fake_requests = types.SimpleNamespace(get=fake_get)
    monkeypatch.setitem(sys.modules, "curl_cffi", types.SimpleNamespace(requests=fake_requests))

    original_url = "https://vt.tiktok.com/short/"
    assert main.resolve_tiktok_redirect(original_url) == original_url


class FakePostResponse:
    def __init__(self, status_code=200, html=""):
        self.status_code = status_code
        self._html = html

    def json(self):
        return {"data": self._html}


class FakeDownloadResponse:
    def __init__(self, status_code=200, chunks=None):
        self.status_code = status_code
        self._chunks = chunks or [b"x" * 2048]
        self.headers = {"content-length": str(sum(len(chunk) for chunk in self._chunks))}

    def iter_content(self, chunk_size=8192):
        yield from self._chunks


class FakeScraper:
    def __init__(self, post_response, download_response=None):
        self.headers = {"User-Agent": "fake-agent"}
        self.post_response = post_response
        self.download_response = download_response or FakeDownloadResponse()
        self.download_calls = []

    def get(self, url, **kwargs):
        if url == "https://tiksave.io/ja":
            return FakeDownloadResponse()
        self.download_calls.append((url, kwargs))
        return self.download_response

    def post(self, url, data):
        assert url == "https://tiksave.io/api/ajaxSearch"
        assert data["lang"] == "ja"
        return self.post_response


def install_fake_cloudscraper(monkeypatch, scraper):
    fake_cloudscraper = types.SimpleNamespace(create_scraper=lambda browser: scraper)
    monkeypatch.setitem(sys.modules, "cloudscraper", fake_cloudscraper)


def test_download_tiktok_via_tiksave_prefers_hd_link_and_writes_large_file(tmp_path, monkeypatch):
    html = """
    <a class="tik-button-dl" href="https://download.example/standard.mp4">Download</a>
    <a class="tik-button-dl" href="https://download.example/hd.mp4">Download HD</a>
    """
    scraper = FakeScraper(FakePostResponse(html=html))
    install_fake_cloudscraper(monkeypatch, scraper)
    output_path = tmp_path / "clip.mp4"

    assert main.download_tiktok_via_tiksave("https://www.tiktok.com/@u/video/1", str(output_path)) is True

    assert output_path.read_bytes() == b"x" * 2048
    assert scraper.download_calls[0][0] == "https://download.example/hd.mp4"
    assert scraper.download_calls[0][1]["headers"]["Referer"] == "https://tiksave.io/"


def test_download_tiktok_via_tiksave_returns_false_when_api_fails(monkeypatch, tmp_path):
    scraper = FakeScraper(FakePostResponse(status_code=503))
    install_fake_cloudscraper(monkeypatch, scraper)

    assert main.download_tiktok_via_tiksave("https://www.tiktok.com/@u/video/1", str(tmp_path / "clip.mp4")) is False


def test_download_tiktok_via_tiksave_returns_false_when_no_download_link(monkeypatch, tmp_path):
    scraper = FakeScraper(FakePostResponse(html="<p>no links</p>"))
    install_fake_cloudscraper(monkeypatch, scraper)

    assert main.download_tiktok_via_tiksave("https://www.tiktok.com/@u/video/1", str(tmp_path / "clip.mp4")) is False


def test_download_tiktok_via_tiksave_returns_false_for_small_file(monkeypatch, tmp_path):
    html = '<a class="tik-button-dl" href="https://download.example/clip.mp4">Download</a>'
    scraper = FakeScraper(FakePostResponse(html=html), FakeDownloadResponse(chunks=[b"tiny"]))
    install_fake_cloudscraper(monkeypatch, scraper)

    assert main.download_tiktok_via_tiksave("https://www.tiktok.com/@u/video/1", str(tmp_path / "clip.mp4")) is False


def test_download_tiktok_via_tiksave_returns_false_when_download_status_fails(monkeypatch, tmp_path):
    html = '<a class="tik-button-dl" href="https://download.example/clip.mp4">Download</a>'
    scraper = FakeScraper(FakePostResponse(html=html), FakeDownloadResponse(status_code=404))
    install_fake_cloudscraper(monkeypatch, scraper)

    assert main.download_tiktok_via_tiksave("https://www.tiktok.com/@u/video/1", str(tmp_path / "clip.mp4")) is False


def test_download_tiktok_via_tiksave_returns_false_on_unexpected_exception(monkeypatch, tmp_path):
    fake_cloudscraper = types.SimpleNamespace(create_scraper=lambda browser: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setitem(sys.modules, "cloudscraper", fake_cloudscraper)

    assert main.download_tiktok_via_tiksave("https://www.tiktok.com/@u/video/1", str(tmp_path / "clip.mp4")) is False
