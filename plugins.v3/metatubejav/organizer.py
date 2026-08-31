from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import JavTitle

try:
    from app.sdk.logging import logger
except Exception:
    import logging
    logger = logging.getLogger("metatubejav")

try:
    from app.sdk.utilities import SystemUtils
except Exception:
    SystemUtils = None

INVALID_CHARS = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")
MAX_COMPONENT_BYTES = 220


def _limit_component(value: str, max_bytes: int = MAX_COMPONENT_BYTES) -> str:
    """限制单个文件系统名称的 UTF-8 字节长度，避免日文标题超过 255 字节。"""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip(" .")


def safe_name(value: str, fallback: str = "JAV") -> str:
    value = INVALID_CHARS.sub(" ", value or "")
    value = re.sub(r"\s+", " ", value).strip(" .")
    return _limit_component(value or fallback)


def folder_name(meta: JavTitle) -> str:
    label = meta.code or meta.id or "JAV"
    year = f" ({meta.year})" if meta.year else ""
    return safe_name(f"{label} - {meta.title}{year}", label)


def file_stem(meta: JavTitle) -> str:
    return safe_name(f"{meta.code or meta.id or 'JAV'} - {meta.title}")


@dataclass(frozen=True)
class OrganizeResult:
    source: Path
    destination: Path
    moved: bool


def organize_file(source: str | Path, library_root: str | Path, meta: JavTitle, *, dry_run: bool = False, transfer_type: str = "move", rename: bool = True, overwrite: str = "never") -> OrganizeResult:
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(src)
    root = Path(library_root)
    destination_dir = root / folder_name(meta)
    destination = destination_dir / (f"{file_stem(meta)}{src.suffix.lower()}" if rename else src.name)
    if destination.exists() and destination.resolve() != src.resolve():
        should_replace = overwrite == "always"
        if overwrite == "by_size":
            should_replace = src.stat().st_size > destination.stat().st_size
        elif overwrite == "latest":
            should_replace = src.stat().st_mtime > destination.stat().st_mtime
        if not should_replace:
            logger.info("Metatube JAV 整理跳过覆盖：目标已存在 %s", destination)
            return OrganizeResult(src, destination, False)
        if not dry_run:
            logger.info("Metatube JAV 整理删除旧目标：%s", destination)
            destination.unlink()
    if destination.exists() and destination.resolve() != src.resolve():
        index = 2
        while True:
            candidate = destination_dir / f"{file_stem(meta)}-{index}{src.suffix.lower()}"
            if not candidate.exists():
                destination = candidate
                break
            index += 1
    if not dry_run:
        destination_dir.mkdir(parents=True, exist_ok=True)
        if SystemUtils is None:
            raise RuntimeError("MoviePilot SystemUtils 不可用，无法执行文件整理")
        if transfer_type == "link":
            retcode, retmsg = SystemUtils.link(src, destination)
        elif transfer_type == "softlink":
            retcode, retmsg = SystemUtils.softlink(src, destination)
        elif transfer_type == "move":
            retcode, retmsg = SystemUtils.move(src, destination)
        else:
            retcode, retmsg = SystemUtils.copy(src, destination)
        if retcode != 0:
            raise OSError(f"MoviePilot 文件转移失败（{transfer_type}）：{retmsg or retcode}")
    return OrganizeResult(src, destination, not dry_run)
