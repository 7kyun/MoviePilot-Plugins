import importlib
import threading
from types import SimpleNamespace

import pytest

from app.plugins.metatubejav import MetatubeJav
from app.plugins.metatubejav.client import MetatubeClient
from app.plugins.metatubejav.normalizer import normalize_code


@pytest.mark.parametrize(
    ("filename", "expected"),
    (
        ("@Milan@ty999.me_SONE-509_6K-C.mp4", "SONE-509"),
        ("SONE-112_CH-nyap2p.com", "SONE-112"),
        ("SONE-112_CH-nyap2p.com.mp4", "SONE-112"),
        ("SONE-509_6K-C", "SONE-509"),
        ("[98t.tv]vema-181-4k-C.mp4", "VEMA-181"),
        ("ABP-030-C-c_c-C-Cd1-cd4.mp4", "ABP-030"),
        ("caribbean-020317_001.mp4", "020317_001"),
        ("FC2-PPV-123456-C.mp4", "FC2-123456"),
        ("Tokyo Hot n9001 FHD.mp4", "N9001"),
    ),
)
def test_normalize_code_matches_metatube_number_trim(filename: str, expected: str) -> None:
    """验证插件番号清理与 MetaTube SDK 规则一致。"""
    assert normalize_code(filename) == expected


def test_stalled_detail_request_does_not_block_next_file() -> None:
    """验证详情请求超时后，后续文件可以立即跳过而不是继续等待。"""
    started = threading.Event()
    release = threading.Event()

    class BlockingClient:
        def detail(self, _code: str):
            """模拟不会及时返回的详情请求。"""
            started.set()
            release.wait(timeout=1)
            return None

    plugin = object.__new__(MetatubeJav)
    plugin._api_lock = threading.Semaphore(1)
    plugin._request_timeout = 0.01
    plugin._client = BlockingClient()

    with pytest.raises(TimeoutError, match="超过"):
        plugin._request_detail("SONE-112")
    assert started.wait(timeout=0.1)
    with pytest.raises(TimeoutError, match="仍在执行"):
        plugin._request_detail("SONE-113")
    release.set()


def test_image_api_url_uses_metatube_proxy_and_escapes_identity() -> None:
    """图片地址应指向 MetaTube 代理，并正确编码 provider 与番号。"""
    client = MetatubeClient("http://metatube:8080/")

    assert client.image_api_url("primary", "ABC/123", "Jav Bus") == (
        "http://metatube:8080/v1/images/primary/Jav%20Bus/ABC%2F123"
    )


def test_scrape_metadata_uses_metatube_image_proxy(monkeypatch) -> None:
    """刮削链的图片字段应使用 MetaTube 代理而不是来源站直链。"""
    module = importlib.import_module("app.plugins.metatubejav")

    class FakeDomainMediaInfo:
        def from_dict(self, fields):
            self.fields = fields

    monkeypatch.setattr(module, "DomainMediaInfo", FakeDomainMediaInfo)
    monkeypatch.setattr(module, "MediaSource", lambda value: value)
    monkeypatch.setattr(module, "MediaType", SimpleNamespace(MOVIE=SimpleNamespace(value="movie")))

    plugin = object.__new__(MetatubeJav)
    plugin._client = MetatubeClient("http://metatube:8080")
    item = SimpleNamespace(
        id="SSNI-999",
        provider="JavBus",
        title="Example",
        year=2024,
        original_title=None,
        poster="https://www.javbus.com/pics/cover/ssni-999_b.jpg",
        backdrop="https://www.javbus.com/pics/cover/ssni-999_t.jpg",
        overview=None,
        runtime=None,
        rating=None,
        release_date=None,
        actors=(),
        tags=(),
        studio=None,
        homepage=None,
    )

    result = plugin._scrape_metadata_info(item)

    assert result.fields["poster_path"] == "http://metatube:8080/v1/images/primary/JavBus/SSNI-999"
    assert result.fields["backdrop_path"] == "http://metatube:8080/v1/images/backdrop/JavBus/SSNI-999"
