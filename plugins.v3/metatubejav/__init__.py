from __future__ import annotations

import os
from typing import Any

try:
    from app import schemas
    from app.plugins import _PluginBase
except Exception:
    schemas = None
    class _PluginBase:
        def __init__(self, *args, **kwargs): pass

from .client import MetatubeClient
from .normalizer import title as parse_title
from .organizer import organize_file

PLUGIN_MEDIA_SOURCE = "metatube-jav"


class MetatubeJav(_PluginBase):
    plugin_name = "Metatube JAV"
    plugin_desc = "使用局域网 Metatube 服务刮削 JAV 元数据并参与文件整理。"
    plugin_version = "1.0.0"
    plugin_author = "7kyun"
    plugin_config_prefix = "metatubejav_"
    auth_level = 1

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._client = None

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled", True))
        self._client = MetatubeClient(
            config.get("url") or os.getenv("METATUBE_URL", "http://metatube:8080"),
            config.get("token") or os.getenv("METATUBE_TOKEN") or None,
            float(config.get("timeout", 10)),
        )

    def stop_service(self) -> None:
        """释放插件资源；可被 MoviePilot 重复调用。"""
        client = self._client
        self._enabled = False
        self._client = None
        close = getattr(client, "close", None)
        if callable(close):
            close()

    def get_state(self):
        return self._enabled and self._client is not None

    def get_api(self): return []
    def get_page(self): return None

    def get_form(self):
        return ([
            {"component": "VSwitch", "props": {"model": "enabled", "label": "启用 Metatube JAV"}},
            {"component": "VTextField", "props": {"model": "url", "label": "Metatube URL"}},
            {"component": "VTextField", "props": {"model": "token", "label": "API Token", "type": "password"}},
        ], {"enabled": False, "url": "", "token": "", "timeout": 10})

    def get_media_source(self):
        return [{"name": self.plugin_name, "media_source": PLUGIN_MEDIA_SOURCE, "media_types": ["电影"]}]

    def get_module(self):
        return {"search_medias": self.search_medias, "recognize_media": self.recognize_media} if self.get_state() else {}

    def _media_info(self, item):
        fields = {"type": "电影", "title": item.title, "year": item.year, "title_year": f"{item.title} ({item.year})" if item.year else item.title, "media_source": PLUGIN_MEDIA_SOURCE, "media_id": f"{item.provider}:{item.id}" if item.provider else item.id, "poster_path": item.poster, "overview": item.overview, "runtime": item.runtime, "vote_average": item.rating, "release_date": item.release_date}
        return schemas.MediaInfo(**fields) if schemas is not None and hasattr(schemas, "MediaInfo") else fields

    def search_medias(self, meta: Any, media_source: Any = None, **_: Any):
        if not self.get_state() or (media_source and str(getattr(media_source, "value", media_source)) != PLUGIN_MEDIA_SOURCE):
            return []
        query = str(getattr(meta, "name", "") or getattr(meta, "title", "") or "").strip()
        if not query: return []
        return [self._media_info(parse_title({"id": r.id, "number": r.code, "title": r.title, "provider": r.provider, "homepage": r.homepage, "thumb_url": r.poster, "release_date": r.release_date})) for r in self._client.search(query)]

    def recognize_media(self, meta: Any, mtype: Any = None, **kwargs: Any):
        results = self.search_medias(meta, PLUGIN_MEDIA_SOURCE)
        return results[0] if results else None

    def organize(self, source: str, library_root: str, media_id: str, provider: str | None = None, *, dry_run: bool = False):
        if not self.get_state(): raise RuntimeError("Metatube JAV plugin is disabled")
        result = organize_file(source, library_root, self._client.detail(media_id, provider), dry_run=dry_run)
        return {"source": str(result.source), "destination": str(result.destination), "moved": result.moved}
