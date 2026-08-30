from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .errors import MetatubeNotFoundError, MetatubeProtocolError, MetatubeTransportError, MetatubeValidationError
from .models import JavSearchItem, JavTitle
from .normalizer import search_item, title

LOGGER = logging.getLogger(__name__)


class MetatubeClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 10.0, opener: Any = urllib.request.urlopen, search_path: str = "v1/movies/search", detail_path: str = "v1/movies/{provider}/{id}"):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.opener = opener
        self.search_path = search_path
        self.detail_path = detail_path

    def _request(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with self.opener(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                body = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise MetatubeNotFoundError(f"Metatube resource not found: {path}") from exc
            if exc.code == 422:
                raise MetatubeValidationError(f"Metatube rejected request: {path}") from exc
            raise MetatubeTransportError(f"Metatube HTTP {exc.code} for {path}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MetatubeTransportError(f"Metatube request failed: {path}") from exc
        if status == 404:
            raise MetatubeNotFoundError(f"Metatube resource not found: {path}")
        if status == 422:
            raise MetatubeValidationError(f"Metatube rejected request: {path}")
        if status < 200 or status >= 300:
            raise MetatubeTransportError(f"Metatube HTTP {status} for {path}")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MetatubeProtocolError(f"Metatube returned invalid JSON for {path}") from exc

    @staticmethod
    def _items(payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "results", "items", "titles"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        raise MetatubeProtocolError("Metatube search response has no result list")

    def search(self, query: str) -> list[JavSearchItem]:
        return [search_item(item) for item in self._items(self._request(self.search_path, {"q": query}))]

    def detail(self, ident: str, provider: str | None = None) -> JavTitle:
        if provider is None and ":" in ident:
            provider, ident = ident.split(":", 1)
        provider = provider or "JavBus"
        path = self.detail_path.replace("{provider}", urllib.parse.quote(provider, safe="")).replace("{id}", urllib.parse.quote(ident, safe=""))
        payload = self._request(path)
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        if not isinstance(payload, dict):
            raise MetatubeProtocolError("Metatube detail response is not an object")
        return title(payload)
