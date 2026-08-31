from __future__ import annotations

import re
from typing import Any

from .models import JavSearchItem, JavTitle, as_mapping, first, string_list

NUMBER_RE = re.compile(r"(?i)([a-z\d]+(?:[-_][a-z\d]{2,})+)")
ALNUM_RE = re.compile(r"(?i)((?:[a-z]+\d|\d+[a-z])[a-z\d]+)")
DOMAIN_RE = re.compile(r"(?i)[a-z\d]+\.(?:com|net|top|xyz|tv|me)(?:[^a-z\d]|$)")
TAG_RE = re.compile(
    r"(?i)[-_.](dvd|iso|mkv|mp4|c?avi|\d*fps|whole|(f|hhb)?hd\d*|sd\d*|"
    r"(?:360|480|720|1080|2160)[pi]|x1080x|uncensored|leak|[2468]ks?|[xh]26[45])+"
)
MAKER_RE = re.compile(
    r"(?i)(^|[-_\s]+)(carib(b?ean)?(com)?(pr)?|1?pond?o?|10mu(sume)?|"
    r"paco(paco)?(mama)?|mura(mura)?|tokyo[-_\s]?hot)"
    r"([-_\s]+(?P<pattern>\d{4,}[-_]\d{2,}|[a-z]{1,4}\d{2,4})|$)"
)
SUFFIX_RE = re.compile(r"(?i)([-_](c|uc|ch|cd\d{1,2})|hhb\d*|ch|[a-d])\s*$")


def normalize_code(value: Any) -> str | None:
    """按 MetaTube SDK 规则从文件名或标题提取并规范化 JAV 番号。"""
    if not value:
        return None
    text = str(value).strip()
    # Mirror metatube-sdk-go/common/number.Trim before extracting the token.
    if "." in text:
        stem, extension = text.rsplit(".", 1)
        if 0 < len(extension) < 6:
            text = stem
    text = DOMAIN_RE.sub("", text)
    text = re.sub(r"(?i)^(?:f?hd|sd)[-_](.*$)", r"\1", text)
    match = NUMBER_RE.search(text) or ALNUM_RE.search(text)
    if not match:
        return None
    code = match.group(1)
    code = TAG_RE.sub("", code)
    code = MAKER_RE.sub(r"\g<pattern>", code)
    code = re.sub(r"(?i)^fc2[-_]?ppv[-_]", "FC2-", code)
    code = re.sub(r"(?i)^fc2[_-]?ppv[-_]?(\d+)$", r"FC2-\1", code)
    while SUFFIX_RE.search(code):
        code = SUFFIX_RE.sub("", code)
    code = re.sub(r"\s+", "-", code).strip("-_. ")
    return code.upper() if code else None


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
