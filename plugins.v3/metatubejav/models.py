from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JavSearchItem:
    id: str
    title: str
    code: str | None = None
    year: int | None = None
    release_date: str | None = None
    poster: str | None = None
    provider: str | None = None
    homepage: str | None = None


@dataclass(frozen=True)
class JavTitle:
    id: str
    code: str | None
    title: str
    original_title: str | None = None
    release_date: str | None = None
    year: int | None = None
    runtime: int | None = None
    overview: str | None = None
    actors: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    studio: str | None = None
    rating: float | None = None
    poster: str | None = None
    backdrop: str | None = None
    external_ids: dict[str, str] = field(default_factory=dict)
    provider: str | None = None
    homepage: str | None = None


def as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def first(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if value.get(key) not in (None, ""):
            return value[key]
    return None


def string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, dict):
            name = first(item, "name", "title", "label")
            if name:
                result.append(str(name).strip())
    return tuple(dict.fromkeys(result))
