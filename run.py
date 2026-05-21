"""定期実行用のエントリポイント。

  python run.py            # 本番実行
  python run.py --dry-run  # 通知を実送信せず標準出力に出す
"""
from __future__ import annotations
import argparse
import logging
from dotenv import load_dotenv

load_dotenv()

from sync import sync_all
from detect import find_newly_won, mark_notified
from notify import notify_order_won
from match import rebuild_auto_mappings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="通知を実送信しない")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("run")

    log.info("sync start (dry_run=%s)", args.dry_run)
    b, r = sync_all()
    log.info("sync done: board=%d repsona=%d", b, r)

    stats = rebuild_auto_mappings()
    log.info("mapping rebuilt: %s", stats)

    won = find_newly_won()
    log.info("newly won: %d", len(won))
    for p in won:
        notify_order_won(p, dry_run=args.dry_run)
        if not args.dry_run:
            mark_notified(p["id"])

    log.info("done")


if __name__ == "__main__":
    main()
