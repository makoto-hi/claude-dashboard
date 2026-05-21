"""board API クライアント（読み取り専用）。

注意：boardのAPIレスポンス構造はAPIドキュメントで最終確認すること。
このコードは典型的なboardの仕様を想定しているが、実際のフィールド名は
APIキー発行画面とドキュメントで照らし合わせて調整する。
"""
from __future__ import annotations
import os
import time
from typing import Iterator
import requests

BOARD_BASE = "https://api.the-board.jp/v1"


class BoardClient:
    def __init__(self, api_key: str | None = None, api_token: str | None = None) -> None:
        self.api_key = api_key or os.environ["BOARD_API_KEY"]
        self.api_token = api_token or os.environ["BOARD_API_TOKEN"]
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_token}",
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        })

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        url = f"{BOARD_BASE}{path}"
        for attempt in range(3):
            r = self.session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"board API failed after retries: {url}")

    def iter_projects(self, per_page: int = 100) -> Iterator[dict]:
        """全案件をページングで取得。

        board API はフラットなリストを返す（{"projects":[...]} 形式ではない）。
        per_page / page パラメータでページング。
        """
        page = 1
        while True:
            data = self._get("/projects", {"per_page": per_page, "page": page})
            items = data if isinstance(data, list) else (data.get("projects") or [])
            if not items:
                break
            for it in items:
                yield it
            if len(items) < per_page:
                break
            page += 1
