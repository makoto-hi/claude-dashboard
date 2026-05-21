"""Discord Incoming Webhook への通知。

dry_run=True ならstdoutに出すだけで実送信しない。
"""
from __future__ import annotations
import json
import os
import logging
import requests

log = logging.getLogger(__name__)


def notify_order_won(project: dict, dry_run: bool = False) -> None:
    name = project.get("name", "(no name)")
    client = project.get("client_name") or "(unknown client)"
    amount = project.get("total_amount") or 0
    pid = project.get("id")

    content = (
        f"🎉 **受注通知** `案件#{pid}`\n"
        f"• 案件: **{name}**\n"
        f"• クライアント: {client}\n"
        f"• 金額: ¥{int(amount):,}\n"
        f"\nRepsonaにプロジェクトを作成してください。"
    )
    payload = {"content": content}

    if dry_run:
        log.info("[dry-run] would send to Discord: %s", content)
        return

    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        log.warning("DISCORD_WEBHOOK_URL is not set; skipping notification")
        return

    r = requests.post(url, data=json.dumps(payload), headers={"Content-Type": "application/json"}, timeout=10)
    if r.status_code >= 300:
        log.error("Discord notify failed: %s %s", r.status_code, r.text)
    else:
        log.info("Discord notified: project %s", pid)
