from __future__ import annotations

import os
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

try:
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    CronTrigger = None

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
    from app.chain.scraping import ScrapingChain
    from app.plugins import _PluginBase
    from app.sdk.logging import logger
except Exception:
    schemas = None
    ScrapingChain = None
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
    plugin_version = "1.9.0"
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
        self._task_lock = threading.Lock()
        self._exclude_keywords = ""
        self._transfer_type = "move"
        self._interval = 10
        self._request_interval = 2.0
        self._request_timeout = 10.0
        self._overwrite_mode = "never"
        self._notify = False
        self._scrape_enabled = False
        self._scrape_onlyonce = False
        self._scrape_cron = ""
        self._scrape_paths = ""
        self._scrape_overwrite = False
        self._scrape_exclude = ""
        self._scheduler = None
        self._scrape_event = threading.Event()

    def init_plugin(self, config: dict = None):
        """根据插件配置初始化整理监控和独立刮削服务。"""
        self.stop_service()
        self._api_lock = threading.Semaphore(1)
        self._scrape_event.clear()
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        onlyonce = bool(config.get("onlyonce", False))
        self._exclude_keywords = str(config.get("exclude_keywords") or "")
        self._notify = bool(config.get("notify", False))
        self._transfer_type = str(config.get("transfer_type") or "move")
        self._interval = max(1, int(config.get("interval") or 10))
        self._request_interval = max(0.0, float(config.get("request_interval") or 2))
        self._request_timeout = max(1.0, float(config.get("timeout") or 10))
        self._overwrite_mode = str(config.get("overwrite_mode") or "never")
        self._scrape_enabled = bool(config.get("scrape_enabled", False))
        self._scrape_onlyonce = bool(config.get("scrape_onlyonce", False))
        self._scrape_cron = str(config.get("scrape_cron") or "")
        self._scrape_paths = str(config.get("scrape_paths") or "")
        scrape_overwrite = config.get("scrape_overwrite", "")
        self._scrape_overwrite = scrape_overwrite in (True, "always", "force_all", "true", "1", 1)
        self._scrape_exclude = str(config.get("scrape_exclude") or "")
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
                threading.Thread(target=self._scan_all_monitors, daemon=True).start()
                self.update_config({**config, "onlyonce": False})
        if self._scrape_enabled or self._scrape_onlyonce:
            self._start_scraper_service()

    def _start_monitors(self, monitor_confs: str) -> None:
        if not monitor_confs:
            return
        if Observer is None:
            logger.error("Metatube JAV 无法启动目录监控：未安装 watchdog")
            return
        self._observers = []
        for line in monitor_confs.splitlines():
            parts = [item.strip() for item in line.split("#")]
            if len(parts) == 6 and parts[0] in ("fast", "compatibility"):
                mode, source, target, transfer_type, rename, overwrite = parts
            elif len(parts) == 4 and parts[0] in ("fast", "compatibility"):
                mode, source, target, rename = parts
                transfer_type, overwrite = self._transfer_type, self._overwrite_mode
            elif len(parts) == 4 and parts[2] in ("move", "copy", "link", "softlink"):
                mode, source, target, rename = "fast", parts[0], parts[1], parts[3]
                transfer_type, overwrite = self._transfer_type, self._overwrite_mode
            elif len(parts) == 4:
                mode, source, target, rename = "fast", *parts
                transfer_type, overwrite = self._transfer_type, self._overwrite_mode
            elif len(parts) == 5:
                mode, source, target, transfer_type, rename = parts
                overwrite = self._overwrite_mode
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
            logger.info(
                "Metatube JAV 目录监控已启动：%s -> %s（处理模式=%s，转移=%s，重命名=%s，覆盖=%s）",
                source,
                target,
                mode,
                transfer_type,
                rename,
                overwrite,
            )
            self._monitor_targets[source] = (target, transfer_type, rename, overwrite)

    def _scan_monitor(self, source_dir: str) -> None:
        logger.info("Metatube JAV 开始扫描监控目录：%s", source_dir)
        processed = 0
        try:
            files = sorted(
                (path for path in Path(source_dir).rglob("*")
                 if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS),
                key=lambda path: str(path).lower(),
            )
            logger.info("Metatube JAV 扫描完成，共发现 %d 个视频文件，开始逐项处理", len(files))
            for index, path in enumerate(files, 1):
                processed = index
                logger.info("Metatube JAV 全量处理第 %d/%d 个视频：%s", index, len(files), path)
                destination = self._handle_monitored_file(str(path), source_dir)
                if self._request_interval and index < len(files):
                    time.sleep(self._request_interval)
        except Exception:
            logger.exception("Metatube JAV 全量扫描异常中止：%s，已处理 %d 个视频", source_dir, processed)
        finally:
            logger.info("Metatube JAV 监控目录扫描完成：%s，共处理 %d 个视频", source_dir, processed)

    def _scan_all_monitors(self) -> None:
        """先递归收集全部监控目录的视频，再按顺序处理。"""
        files = []
        for source_dir in self._monitor_targets:
            files.extend(
                (path, source_dir)
                for path in Path(source_dir).rglob("*")
                if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
            )
        files.sort(key=lambda item: str(item[0]).lower())
        logger.info("Metatube JAV 全量递归扫描完成，共发现 %d 个视频文件", len(files))
        for index, (path, source_dir) in enumerate(files, 1):
            logger.info("Metatube JAV 全量处理第 %d/%d 个视频：%s", index, len(files), path)
            destination = None
            try:
                destination = self._handle_monitored_file(str(path), source_dir)
            except Exception:
                logger.exception("Metatube JAV 全量处理单个文件异常，继续下一个：%s", path)
            logger.info("Metatube JAV 全量处理完成第 %d/%d 个视频：%s -> %s", index, len(files), path, destination or "未整理")
            if self._request_interval and index < len(files):
                time.sleep(self._request_interval)

    def _start_scraper_service(self) -> None:
        """按配置启动独立刮削的一次性任务；周期任务由插件服务调度。"""
        if not self._scrape_paths:
            logger.warning("Metatube JAV 独立刮削未启动：未配置刮削监控目录")
            return
        if not self._scrape_onlyonce:
            return
        logger.info("Metatube JAV 刮削服务立即运行一次")
        self._scrape_onlyonce = False
        config = self.get_config() if hasattr(self, "get_config") else {}
        self.update_config({**(config or {}), "scrape_onlyonce": False})
        threading.Thread(target=self._scrape_library, name="metatubejav-scraper", daemon=True).start()

    def _scrape_library(self) -> None:
        """扫描独立刮削目录，并使用 Metatube 元数据写入 NFO 和图片。"""
        with self._task_lock:
            paths = [Path(value.strip()) for value in self._scrape_paths.splitlines() if value.strip()]
            excluded = [Path(value.strip()) for value in self._scrape_exclude.splitlines() if value.strip()]
            if not paths:
                return
            scanned = 0
            scraped = 0
            seen: set[tuple[Path, str]] = set()
            logger.info("Metatube JAV 开始扫描 %d 个刮削监控目录", len(paths))
            for root in paths:
                if self._scrape_event.is_set():
                    break
                if not root.is_dir():
                    logger.warning("Metatube JAV 刮削监控目录不存在：%s", root)
                    continue
                for file_path in sorted(root.rglob("*"), key=lambda value: str(value).lower()):
                    if self._scrape_event.is_set():
                        break
                    if not file_path.is_file() or file_path.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue
                    if any(exclude == file_path or exclude in file_path.parents for exclude in excluded):
                        continue
                    code = normalize_code(file_path.stem)
                    if not code:
                        continue
                    scanned += 1
                    target = file_path.parent if file_path.parent != root else file_path
                    key = (target, code)
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        meta = self._request_detail(code)
                        if self._scrape_path(target, meta):
                            scraped += 1
                    except MetatubeValidationError as exc:
                        logger.warning("Metatube JAV 刮削跳过 %s：%s", file_path, exc)
                    except TimeoutError as exc:
                        logger.warning("Metatube JAV 刮削请求超时，跳过 %s：%s", file_path, exc)
                    except Exception:
                        logger.exception("Metatube JAV 刮削失败：%s", file_path)
                    if self._request_interval:
                        time.sleep(self._request_interval)
            logger.info("Metatube JAV 刮削完成：扫描 %d 个 JAV 视频，完成 %d 项", scanned, scraped)

    def _scrape_path(self, path: Path, meta: Any) -> bool:
        """下载海报资源并将 Metatube 元数据刮削到视频或其媒体目录。"""
        if schemas is None or ScrapingChain is None:
            logger.error("Metatube JAV 无法刮削：MoviePilot 刮削组件不可用")
            return False
        try:
            target = Path(path)
            target_type = "dir" if target.is_dir() else "file"
            mediainfo = self._metadata_info(meta)
            obtain_images = getattr(self.chain, "obtain_images", None)
            if callable(obtain_images):
                obtain_images(mediainfo)
            item_path = str(target).replace("\\", "/")
            if target_type == "dir":
                item_path = f"{item_path}/"
            ScrapingChain().scrape_metadata(
                fileitem=schemas.FileItem(
                    storage="local",
                    type=target_type,
                    path=item_path,
                    name=target.name,
                    basename=target.stem,
                    extension=target.suffix[1:] if target_type == "file" else None,
                    modify_time=target.stat().st_mtime,
                ),
                mediainfo=mediainfo,
                overwrite=self._scrape_overwrite,
            )
            logger.info("Metatube JAV 刮削完成：%s", target)
            return True
        except Exception:
            logger.exception("Metatube JAV 写入刮削元数据失败：%s", path)
            return False

    def _handle_monitored_file(self, path: str, source_dir: str) -> str | None:
        with self._task_lock:
            return self._process_monitored_file(path, source_dir)

    def _process_monitored_file(self, path: str, source_dir: str) -> str | None:
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
        target, transfer_type, rename, overwrite = self._monitor_targets.get(source_dir, (None, None, None, "never"))
        if not target:
            return
        try:
            meta = self._request_detail(code)
            result = organize_file(file_path, target, meta, transfer_type=transfer_type, rename=str(rename).lower() != "false", overwrite=overwrite)
            if not result.moved:
                file_path.unlink(missing_ok=True)
                self._cleanup_empty_dirs(file_path.parent, source_dir)
                self._scrape_path(result.destination, meta)
                return str(result.destination)
            logger.info("Metatube JAV 整理完成：%s -> %s", path, result.destination)
            self._scrape_path(result.destination, meta)
            self._cleanup_empty_dirs(file_path.parent, source_dir)
            return str(result.destination)
        except MetatubeValidationError as exc:
            logger.warning("Metatube JAV 请求被拒绝（422），跳过文件：%s，原因：%s", path, exc)
        except TimeoutError as exc:
            logger.warning("Metatube JAV 详情请求超时或已有请求卡住，跳过文件：%s，原因：%s", path, exc)
        except Exception:
            logger.exception("Metatube JAV 自动整理失败：%s", path)

    def _request_detail(self, code: str, provider: str | None = None):
        """在截止时间内请求详情，避免单个卡死请求阻塞后续文件。"""
        api_lock = self._api_lock
        if not api_lock.acquire(blocking=False):
            raise TimeoutError("已有 Metatube 详情请求仍在执行")
        client = self._client
        result = queue.Queue(maxsize=1)

        def request() -> None:
            try:
                result.put((client.detail(code, provider), None))
            except Exception as exc:
                result.put((None, exc))
            finally:
                api_lock.release()

        # urllib 无法强制取消已进入 read() 的线程，守护线程配合锁占用让后续文件快速跳过。
        worker = threading.Thread(target=request, name="metatubejav-detail", daemon=True)
        worker.start()
        worker.join(timeout=self._request_timeout)
        if worker.is_alive():
            raise TimeoutError(f"详情请求超过 {self._request_timeout:g} 秒")
        meta, error = result.get_nowait()
        if error is not None:
            raise error
        return meta

    @staticmethod
    def _cleanup_empty_dirs(directory: Path, root: str) -> None:
        root_path = Path(root).resolve()
        current = directory.resolve()
        while current != root_path and root_path in current.parents:
            try:
                if any(current.iterdir()):
                    break
                current.rmdir()
                logger.info("Metatube JAV 已删除空目录：%s", current)
            except OSError:
                break
            current = current.parent

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
        self._scrape_event.set()
        scheduler = getattr(self, "_scheduler", None)
        if scheduler is not None:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                logger.exception("Metatube JAV 停止刮削服务失败")
        self._scheduler = None
        close = getattr(client, "close", None)
        if callable(close):
            close()
        logger.info("Metatube JAV 插件服务已停止")

    def get_state(self):
        """返回整理或独立刮削是否处于启用状态。"""
        return (self._enabled or self._scrape_enabled) and self._client is not None

    @staticmethod
    def get_command():
        """返回插件远程命令列表。"""
        return []

    def get_api(self):
        """返回插件 API 列表。"""
        return []

    def get_page(self):
        """不提供详情面板，让插件卡片点击直接打开配置页。"""
        return None

    def get_service(self):
        """注册独立刮削的周期服务。"""
        if not self._scrape_enabled or not self._scrape_paths or CronTrigger is None:
            return []
        return [{
            "id": "MetatubeJavScraper",
            "name": "Metatube JAV 刮削",
            "trigger": CronTrigger.from_crontab(self._scrape_cron or "0 0 */7 * *"),
            "func": self._scrape_library,
            "kwargs": {},
        }]

    def get_form(self):
        """返回整理和独立刮削两组 JSON 配置表单。"""
        return ([{"component": "VForm", "content": [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即运行一次"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "发送通知"}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "interval", "label": "兼容模式轮询间隔", "placeholder": "10", "hint": "处理模式为 compatibility 时生效"}}]},
            ]},
            {"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextarea", "props": {"model": "monitor_confs", "label": "监控目录（支持换行批量配置）", "rows": 5, "hint": "格式：处理模式#监控目录#目标目录#转移方式#是否重命名#覆盖模式；fast=性能模式，compatibility=兼容模式", "placeholder": "fast#/源目录#/目标目录#link#true#never\ncompatibility#/源目录2#/目标目录2#move#false#by_size"}}]}]},
            {"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextarea", "props": {"model": "exclude_keywords", "label": "排除关键词", "rows": 2, "placeholder": "每行一个关键词"}}]}]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [{"component": "VTextField", "props": {"model": "url", "label": "Metatube URL"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "timeout", "label": "请求超时（秒）", "placeholder": "10"}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "token", "label": "API Token", "type": "password"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "request_interval", "label": "请求间隔（秒）", "placeholder": "2"}}]},
            ]},
        ]}, {"component": "VForm", "content": [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "scrape_enabled", "label": "启用独立刮削"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "scrape_onlyonce", "label": "立即运行一次"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSelect", "props": {"model": "scrape_overwrite", "label": "覆盖方式", "items": [{"title": "不覆盖已有元数据", "value": ""}, {"title": "覆盖所有元数据和图片", "value": "force_all"}]}}]},
            ]},
            {"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VCronField", "props": {"model": "scrape_cron", "label": "刮削周期", "placeholder": "留空默认每 7 天"}}]}]},
            {"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextarea", "props": {"model": "scrape_paths", "label": "刮削监控目录", "rows": 5, "placeholder": "每行一个目录"}}]}]},
            {"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextarea", "props": {"model": "scrape_exclude", "label": "刮削排除目录", "rows": 2, "placeholder": "每行一个目录"}}]}]},
        ]}], {"enabled": False, "onlyonce": False, "notify": False, "url": "", "token": "", "timeout": 10, "transfer_type": "move", "interval": 10, "request_interval": 2, "overwrite_mode": "never", "monitor_confs": "", "exclude_keywords": "", "scrape_enabled": False, "scrape_onlyonce": False, "scrape_cron": "", "scrape_paths": "", "scrape_overwrite": "", "scrape_exclude": ""})

    def get_media_source(self):
        """返回全局媒体源列表；本插件仅响应自身目录和媒体身份。"""
        # Metatube JAV 仅通过插件自身目录监控工作，不注册全局媒体源。
        return []

    def get_module(self):
        """返回需要重载的宿主模块映射。"""
        return {}

    @staticmethod
    def _source_matches(media_source: Any) -> bool:
        if media_source in (None, "", (), [], set()):
            return True
        values = media_source if isinstance(media_source, (list, tuple, set)) else (media_source,)
        return any(str(getattr(value, "value", value)) == PLUGIN_MEDIA_SOURCE for value in values)

    def _media_info(self, item):
        return self._metadata_info(item)

    @staticmethod
    def _metadata_info(item):
        """将 Metatube 详情转换为 MoviePilot 可刮削的媒体信息。"""
        year = str(item.year) if item.year is not None else None
        fields = {"type": "电影", "title": item.title, "year": year, "title_year": f"{item.title} ({year})" if year else item.title, "media_source": PLUGIN_MEDIA_SOURCE, "media_id": f"{item.provider}:{item.id}" if item.provider else item.id, "poster_path": item.poster, "backdrop_path": item.backdrop, "overview": item.overview, "runtime": item.runtime, "vote_average": item.rating, "release_date": item.release_date}
        fields.update({"original_title": item.original_title, "actors": list(item.actors), "tags": list(item.tags), "studio": item.studio, "homepage": item.homepage})
        if schemas is None or not hasattr(schemas, "MediaInfo"):
            return fields
        model = schemas.MediaInfo
        model_fields = getattr(model, "model_fields", None) or getattr(model, "__fields__", None)
        if model_fields:
            fields = {key: value for key, value in fields.items() if key in model_fields}
        try:
            return model(**fields)
        except (TypeError, ValueError):
            # 不同宿主版本的演员/标签类型可能不同，基础字段仍可完成 NFO 与图片刮削。
            base_keys = {"type", "title", "year", "title_year", "media_source", "media_id", "poster_path", "backdrop_path", "overview", "runtime", "vote_average", "release_date"}
            return model(**{key: value for key, value in fields.items() if key in base_keys})

    def search_medias(self, meta: Any, media_source: Any = None, **_: Any):
        """按 JAV 番号搜索 Metatube 媒体。"""
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
            api_lock = self._api_lock
            if not api_lock.acquire(timeout=self._request_timeout):
                logger.warning("Metatube JAV 搜索请求锁超时，跳过：%s", code)
                return []
            try:
                results = self._client.search(code)
            finally:
                api_lock.release()
            logger.info("Metatube JAV 搜索完成：%s，结果数：%d", code, len(results))
            return [self._media_info(parse_title({"id": r.id, "number": r.code, "title": r.title, "provider": r.provider, "homepage": r.homepage, "thumb_url": r.poster, "release_date": r.release_date})) for r in results]
        except MetatubeValidationError as exc:
            logger.warning("Metatube JAV 搜索请求被拒绝（422）：%s", exc)
            return []
        except Exception:
            logger.exception("Metatube JAV 搜索失败：%s", code)
            return []

    def recognize_media(self, meta: Any, mtype: Any = None, media_source: Any = None, **kwargs: Any):
        """将文件名识别为第一个匹配的 JAV 媒体。"""
        if not self._source_matches(media_source):
            return None
        logger.info("Metatube JAV 收到识别请求：标题=%s，媒体源=%s", getattr(meta, "name", None) or getattr(meta, "title", ""), media_source)
        results = self.search_medias(meta, PLUGIN_MEDIA_SOURCE)
        logger.info("Metatube JAV 识别%s：%s", "成功" if results else "失败", getattr(meta, "name", None) or getattr(meta, "title", ""))
        return results[0] if results else None

    def organize(self, source: str, library_root: str, media_id: str, provider: str | None = None, *, dry_run: bool = False):
        """整理单个视频，并在成功后默认写入 NFO 和图片。"""
        if not self.get_state(): raise RuntimeError("Metatube JAV plugin is disabled")
        logger.info("Metatube JAV 开始整理：%s", source)
        meta = self._request_detail(media_id, provider)
        result = organize_file(source, library_root, meta, dry_run=dry_run)
        if not dry_run:
            self._scrape_path(result.destination, meta)
        logger.info("Metatube JAV 整理%s：%s -> %s", "预览" if dry_run else "完成", result.source, result.destination)
        return {"source": str(result.source), "destination": str(result.destination), "moved": result.moved}
