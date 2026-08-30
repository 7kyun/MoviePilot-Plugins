from __future__ import annotations

import os
import logging
import threading
from pathlib import Path
from typing import Any

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    from watchdog.observers.polling import PollingObserver
except ImportError:
    FileSystemEventHandler = None
    Observer = None
    PollingObserver = None

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
from .errors import MetatubeValidationError

PLUGIN_MEDIA_SOURCE = "metatube-jav"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".ts", ".m2ts", ".flv", ".webm"}


if FileSystemEventHandler is not None:
    class _MonitorHandler(FileSystemEventHandler):
        def __init__(self, plugin, source_dir):
            super().__init__()
            self.plugin = plugin
            self.source_dir = source_dir

        def on_created(self, event):
            if not event.is_directory:
                self.plugin._handle_monitored_file(event.src_path, self.source_dir)

        def on_moved(self, event):
            if not event.is_directory:
                self.plugin._handle_monitored_file(event.dest_path, self.source_dir)


class MetatubeJav(_PluginBase):
    plugin_name = "Metatube JAV"
    plugin_desc = "使用局域网 Metatube 服务刮削 JAV 元数据并参与文件整理。"
    plugin_version = "1.3.0"
    plugin_author = "7kyun"
    plugin_config_prefix = "metatubejav_"
    auth_level = 1

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._client = None
        self._observers = []
        self._monitor_targets = {}
        self._api_lock = threading.Semaphore(1)
        self._exclude_keywords = ""
        self._transfer_type = "move"
        self._interval = 10

    def init_plugin(self, config: dict = None):
        self.stop_service()
        config = config or {}
        self._enabled = bool(config.get("enabled", True))
        onlyonce = bool(config.get("onlyonce", False))
        self._exclude_keywords = str(config.get("exclude_keywords") or "")
        self._transfer_type = str(config.get("transfer_type") or "move")
        self._interval = max(1, int(config.get("interval") or 10))
        url = config.get("url") or os.getenv("METATUBE_URL", "http://metatube:8080")
        token = config.get("token") or os.getenv("METATUBE_TOKEN") or None
        self._client = MetatubeClient(
            url,
            token,
            float(config.get("timeout", 10)),
        )
        logger.info("Metatube JAV 插件已%s，服务地址：%s", "启用" if self._enabled else "禁用", url)
        if self._enabled:
            self._start_monitors(str(config.get("monitor_confs") or os.getenv("METATUBE_MONITOR_CONFS", "")))
            if onlyonce:
                logger.info("Metatube JAV 监控服务启动，立即执行一次全量扫描")
                for source in self._monitor_targets:
                    threading.Thread(target=self._scan_monitor, args=(source,), daemon=True).start()
                self.update_config({**config, "onlyonce": False})

    def _start_monitors(self, monitor_confs: str) -> None:
        if not monitor_confs:
            return
        if Observer is None:
            logger.error("Metatube JAV 无法启动目录监控：未安装 watchdog")
            return
        self._observers = []
        for line in monitor_confs.splitlines():
            parts = [item.strip() for item in line.split("#")]
            if len(parts) == 4:
                mode, source, target, rename = "fast", *parts
            elif len(parts) == 5:
                mode, source, target, rename = parts[0], parts[1], parts[2], parts[3]
            else:
                logger.error("Metatube JAV 监控配置格式错误：%s", line)
                continue
            if not Path(source).is_dir():
                logger.warning("Metatube JAV 监控目录不存在：%s", source)
                continue
            observer = PollingObserver(timeout=self._interval) if mode == "compatibility" and PollingObserver else Observer()
            observer.schedule(_MonitorHandler(self, source), source, recursive=True)
            observer.daemon = True
            observer.start()
            self._observers.append(observer)
            logger.info("Metatube JAV 目录监控已启动：%s -> %s（模式=%s，转移=%s，重命名=%s）", source, target, mode, self._transfer_type, rename)
            self._monitor_targets[source] = (target, self._transfer_type, rename)

    def _scan_monitor(self, source_dir: str) -> None:
        logger.info("Metatube JAV 开始扫描监控目录：%s", source_dir)
        count = 0
        for path in Path(source_dir).rglob("*"):
            if path.is_file():
                count += 1
                self._handle_monitored_file(str(path), source_dir)
        logger.info("Metatube JAV 监控目录扫描完成：%s，共检查 %d 个文件", source_dir, count)

    def _handle_monitored_file(self, path: str, source_dir: str) -> None:
        file_path = Path(path)
        if file_path.suffix.lower() not in VIDEO_EXTENSIONS:
            return
        keywords = [item.strip().lower() for item in self._exclude_keywords.splitlines() if item.strip()]
        if any(keyword in file_path.name.lower() for keyword in keywords):
            logger.info("Metatube JAV 监控命中过滤关键词，跳过：%s", path)
            return
        code = normalize_code(file_path.stem)
        if not code:
            logger.debug("Metatube JAV 监控跳过普通资源：%s", path)
            return
        target, transfer_type, rename = self._monitor_targets.get(source_dir, (None, None, None))
        if not target:
            return
        try:
            with self._api_lock:
                meta = self._client.detail(code)
            result = organize_file(file_path, target, meta, transfer_type=transfer_type, rename=str(rename).lower() != "false")
            logger.info("Metatube JAV 自动整理完成：%s -> %s（方式=%s，重命名=%s）", path, result.destination, transfer_type, rename)
        except MetatubeValidationError as exc:
            logger.warning("Metatube JAV 请求被拒绝（422），跳过文件：%s，原因：%s", path, exc)
        except Exception:
            logger.exception("Metatube JAV 自动整理失败：%s", path)

    def stop_service(self) -> None:
        """释放插件资源；可被 MoviePilot 重复调用。"""
        client = self._client
        self._enabled = False
        self._client = None
        for observer in getattr(self, "_observers", []):
            try:
                observer.stop()
                observer.join(timeout=5)
            except Exception:
                logger.exception("Metatube JAV 停止目录监控失败")
        self._observers = []
        self._monitor_targets = {}
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
            {"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即运行一次"}},
            {"component": "VTextField", "props": {"model": "url", "label": "Metatube URL"}},
            {"component": "VTextField", "props": {"model": "token", "label": "API Token", "type": "password"}},
            {"component": "VSelect", "props": {"model": "transfer_type", "label": "转移方式", "items": [{"title": "移动", "value": "move"}, {"title": "复制", "value": "copy"}, {"title": "硬链接", "value": "link"}, {"title": "软链接", "value": "softlink"}]}},
            {"component": "VTextField", "props": {"model": "interval", "label": "兼容模式轮询间隔（秒）", "placeholder": "10"}},
            {"component": "VTextarea", "props": {"model": "monitor_confs", "label": "监控目录", "rows": 5, "placeholder": "监控方式#监控目录#目标目录#是否重命名"}},
            {"component": "VTextarea", "props": {"model": "exclude_keywords", "label": "排除关键词", "rows": 2, "placeholder": "每行一个关键词"}},
        ], {"enabled": False, "onlyonce": False, "url": "", "token": "", "timeout": 10, "transfer_type": "move", "interval": 10, "monitor_confs": "", "exclude_keywords": ""})

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
            with self._api_lock:
                results = self._client.search(code)
            logger.info("Metatube JAV 搜索完成：%s，结果数：%d", code, len(results))
            return [self._media_info(parse_title({"id": r.id, "number": r.code, "title": r.title, "provider": r.provider, "homepage": r.homepage, "thumb_url": r.poster, "release_date": r.release_date})) for r in results]
        except MetatubeValidationError as exc:
            logger.warning("Metatube JAV 搜索请求被拒绝（422）：%s", exc)
            return []
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
