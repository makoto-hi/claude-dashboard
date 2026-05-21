"""Repsona API クライアント（読み取り専用）。

エンドポイント: https://<space_id>.repsona.com/api/...
  - プロジェクト一覧: GET /api/me/project
  - タスク一覧:       GET /api/project/{id}/task
  - ステータス一覧:   GET /api/project/{id}/status
認証: Authorization: Bearer {token}
updatedAt はミリ秒 Unix タイムスタンプ。
"""
from __future__ import annotations
import os
import time
from typing import Iterator
import requests


class RepsonaClient:
    def __init__(self, space_id: str | None = None, api_token: str | None = None) -> None:
        self.space_id = space_id or os.environ["REPSONA_SPACE_ID"]
        self.api_token = api_token or os.environ["REPSONA_API_TOKEN"]
        self.base = f"https://{self.space_id}.repsona.com/api"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        })

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        for attempt in range(3):
            r = self.session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Repsona API failed: {url}")

    def iter_projects(self) -> Iterator[dict]:
        data = self._get("/me/project")
        for it in data.get("projects", []):
            yield it

    def get_closed_status_ids(self, project_id: int) -> set[int]:
        """isClosed=True のステータス ID セットを返す（完了タスク判定用）。"""
        data = self._get(f"/project/{project_id}/status")
        return {s["id"] for s in data.get("statuses", []) if s.get("isClosed")}

    def iter_tasks(self, project_id: int) -> Iterator[dict]:
        """指定プロジェクトの全タスク。"""
        data = self._get(f"/project/{project_id}/task")
        for it in data.get("tasks", []):
            yield it
