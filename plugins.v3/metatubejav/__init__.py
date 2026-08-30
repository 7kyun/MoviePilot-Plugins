from __future__ import annotations

import os
import logging
from typing import Any

try:
    from app import schemas
    from app.plugins import _PluginBase
    from app.sdk.logging import logger
except Exception:
    schemas = None
    logger = logging.getLogger(__name__)
    class _PluginBase:
        def __init__(self, *args, **kwargs): pass

from .client import MetatubeClient
from .normalizer import normalize_code, title as parse_title
from .organizer import organize_file

PLUGIN_MEDIA_SOURCE = "metatube-jav"


class MetatubeJav(_PluginBase):
    plugin_name = "Metatube JAV"
    plugin_desc = "使用局域网 Metatube 服务刮削 JAV 元数据并参与文件整理。"
    plugin_version = "1.0.6"
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
        url = config.get("url") or os.getenv("METATUBE_URL", "http://metatube:8080")
        token = config.get("token") or os.getenv("METATUBE_TOKEN") or None
        self._client = MetatubeClient(
            url,
            token,
            float(config.get("timeout", 10)),
        )
        logger.info("Metatube JAV 插件已%s，服务地址：%s", "启用" if self._enabled else "禁用", url)

    def stop_service(self) -> None:
        """释放插件资源；可被 MoviePilot 重复调用。"""
        client = self._client
        self._enabled = False
        self._client = None
        close = getattr(client, "close", None)
        if callable(close):
            close()
        logger.info("Metatube JAV 插件服务已停止")

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
        try:
            from app.schemas.types import MediaSource, MediaType
            source = schemas.MediaSourceInfo(
                name=self.plugin_name,
                media_source=MediaSource(PLUGIN_MEDIA_SOURCE),
                media_types=[MediaType.MOVIE],
            )
            return [source.model_dump()]
        except (AttributeError, ImportError, TypeError, ValueError):
            return [{"name": self.plugin_name, "media_source": PLUGIN_MEDIA_SOURCE, "media_types": ["电影"]}]

    def get_module(self):
        logger.debug("Metatube JAV 注册媒体模块，当前状态：%s", "启用" if self.get_state() else "禁用")
        return {"search_medias": self.search_medias, "recognize_media": self.recognize_media}

    @staticmethod
    def _source_matches(media_source: Any) -> bool:
        if media_source in (None, "", (), [], set()):
            return True
        values = media_source if isinstance(media_source, (list, tuple, set)) else (media_source,)
        return any(str(getattr(value, "value", value)) == PLUGIN_MEDIA_SOURCE for value in values)

    def _media_info(self, item):
        year = str(item.year) if item.year is not None else None
        fields = {"type": "电影", "title": item.title, "year": year, "title_year": f"{item.title} ({year})" if year else item.title, "media_source": PLUGIN_MEDIA_SOURCE, "media_id": f"{item.provider}:{item.id}" if item.provider else item.id, "poster_path": item.poster, "overview": item.overview, "runtime": item.runtime, "vote_average": item.rating, "release_date": item.release_date}
        return schemas.MediaInfo(**fields) if schemas is not None and hasattr(schemas, "MediaInfo") else fields

    def search_medias(self, meta: Any, media_source: Any = None, **_: Any):
        if not self.get_state() or not self._source_matches(media_source):
            logger.debug("Metatube JAV 搜索跳过：插件未启用或媒体源不匹配")
            return []
        query = str(getattr(meta, "name", "") or getattr(meta, "title", "") or "").strip()
        if not query:
            logger.debug("Metatube JAV 搜索跳过：查询标题为空")
            return []
        code = normalize_code(query)
        if not code:
            logger.debug("Metatube JAV 搜索跳过：未识别到 JAV 番号，标题=%s", query)
            return []
        logger.info("Metatube JAV 开始搜索：%s", code)
        try:
            results = self._client.search(code)
            logger.info("Metatube JAV 搜索完成：%s，结果数：%d", code, len(results))
            return [self._media_info(parse_title({"id": r.id, "number": r.code, "title": r.title, "provider": r.provider, "homepage": r.homepage, "thumb_url": r.poster, "release_date": r.release_date})) for r in results]
        except Exception:
            logger.exception("Metatube JAV 搜索失败：%s", code)
            return []

    def recognize_media(self, meta: Any, mtype: Any = None, media_source: Any = None, **kwargs: Any):
        logger.info("Metatube JAV 收到识别请求：标题=%s，媒体源=%s", getattr(meta, "name", None) or getattr(meta, "title", ""), media_source)
        if not self._source_matches(media_source):
            logger.debug("Metatube JAV 识别跳过：媒体源不匹配")
            return None
        results = self.search_medias(meta, PLUGIN_MEDIA_SOURCE)
        logger.info("Metatube JAV 识别%s：%s", "成功" if results else "失败", getattr(meta, "name", None) or getattr(meta, "title", ""))
        return results[0] if results else None

    def organize(self, source: str, library_root: str, media_id: str, provider: str | None = None, *, dry_run: bool = False):
        if not self.get_state(): raise RuntimeError("Metatube JAV plugin is disabled")
        logger.info("Metatube JAV 开始整理：%s", source)
        result = organize_file(source, library_root, self._client.detail(media_id, provider), dry_run=dry_run)
        logger.info("Metatube JAV 整理%s：%s -> %s", "预览" if dry_run else "完成", result.source, result.destination)
        return {"source": str(result.source), "destination": str(result.destination), "moved": result.moved}
