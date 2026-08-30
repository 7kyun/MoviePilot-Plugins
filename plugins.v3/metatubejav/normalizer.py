from __future__ import annotations

import re
from typing import Any

from .models import JavSearchItem, JavTitle, as_mapping, first, string_list

CODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2,8}[-_ ]?\d{1,6})(?!\d)", re.IGNORECASE)


def normalize_code(value: Any) -> str | None:
    if not value:
        return None
    match = CODE_RE.search(str(value).upper())
    if not match:
        return None
    return re.sub(r"[ _]+", "-", match.group(1))


def normalize_title(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _year(date: Any) -> int | None:
    match = re.match(r"(\d{4})", str(date or ""))
    return int(match.group(1)) if match else None


def search_item(raw: Any) -> JavSearchItem:
    item = as_mapping(raw)
    code = normalize_code(first(item, "code", "number", "番号", "id", "title"))
    ident = str(first(item, "id", "uuid", "key", "code", "number") or code or "")
    release = first(item, "release_date", "releaseDate", "date", "premiered")
    provider = first(item, "provider", "source")
    return JavSearchItem(ident, normalize_title(first(item, "title", "name", "originalTitle") or code), code, _year(release), str(release) if release else None, first(item, "poster", "poster_url", "thumb_url", "image", "cover"), provider, first(item, "homepage", "url"))


def title(raw: Any) -> JavTitle:
    item = as_mapping(raw)
    release = first(item, "release_date", "releaseDate", "date", "premiered")
    code = normalize_code(first(item, "code", "number", "番号", "title", "id"))
    ident = str(first(item, "id", "uuid", "key", "code", "number") or code or "")
    rating_raw = first(item, "rating", "score", "vote_average")
    try:
        rating = float(rating_raw) if rating_raw is not None else None
    except (TypeError, ValueError):
        rating = None
    return JavTitle(
        id=ident,
        code=code,
        title=normalize_title(first(item, "title", "name", "originalTitle") or code),
        original_title=first(item, "original_title", "originalTitle"),
        release_date=str(release) if release else None,
        year=_year(release),
        runtime=first(item, "runtime", "duration", "length"),
        overview=first(item, "overview", "plot", "description", "summary"),
        actors=string_list(first(item, "actors", "cast", "performers")),
        tags=string_list(first(item, "tags", "genres", "genre")),
        studio=first(item, "studio", "maker", "company", "manufacturer"),
        rating=rating,
        poster=first(item, "poster", "poster_url", "cover_url", "big_cover_url", "thumb_url", "image", "cover"),
        backdrop=first(item, "backdrop", "backdrop_url", "fanart", "big_thumb_url"),
        external_ids={str(k): str(v) for k, v in as_mapping(first(item, "external_ids", "externalIds", "ids")).items() if v not in (None, "")},
        provider=first(item, "provider", "source"),
        homepage=first(item, "homepage", "url"),
    )
