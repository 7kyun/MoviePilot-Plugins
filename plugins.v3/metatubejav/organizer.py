from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .models import JavTitle

INVALID_CHARS = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")


def safe_name(value: str, fallback: str = "JAV") -> str:
    value = INVALID_CHARS.sub(" ", value or "")
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or fallback


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


def organize_file(source: str | Path, library_root: str | Path, meta: JavTitle, *, dry_run: bool = False, transfer_type: str = "move", rename: bool = True) -> OrganizeResult:
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(src)
    root = Path(library_root)
    destination_dir = root / folder_name(meta)
    destination = destination_dir / (f"{file_stem(meta)}{src.suffix.lower()}" if rename else src.name)
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
        if transfer_type == "copy":
            shutil.copy2(str(src), str(destination))
        elif transfer_type == "link":
            destination.hardlink_to(src)
        elif transfer_type == "softlink":
            destination.symlink_to(src)
        else:
            shutil.move(str(src), str(destination))
    return OrganizeResult(src, destination, not dry_run)
