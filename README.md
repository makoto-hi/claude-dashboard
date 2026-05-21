# board × Repsona ダッシュボード

board と Repsona を読み取り、案件の進捗・受注率・請求状況を一画面で見るための社内ダッシュボード。

## 主な機能

- **受注率 KPI** — 受注 / (受注 + 失注) の率を年度フィルターで表示
- **請求済み・未請求 金額** — board の `invoice_dates` から自動集計
- **受注案件の進捗（Repsona）** — Repsonaの親タスク単位で進捗バー（実績 vs 理想）と予算工数（¥68,000/人日換算）を表示
- **未マッチ受注案件** — Repsonaに紐付いていない受注案件。✕ボタンで個別除外可
- **新規受注の検知 + Discord 通知**（run.py 実行時）

## 構成

```
[board]──┐
         ├─► sync.py ─► data.db (SQLite) ─► metrics.py ─► app.py (FastAPI)
[Repsona]┘                │                                 │
                          └─► notify.py ─► Discord          └─► /
```

- `sync.py` : board と Repsona の全件を取得して SQLite に upsert
- `detect.py` : 前回ステータスとの差分で「新規受注」を検出
- `notify.py` : Discord Webhook に投稿
- `match.py` : board 案件と Repsona プロジェクトを手動/自動で突合
- `metrics.py` : KPI を集計
- `app.py` : FastAPI ダッシュボード（Basic認証）
- `run.py` : sync → detect → notify を順番に実行（cron / GitHub Actions 用）

## セットアップ

```bash
git clone <このリポジトリのURL>
cd board-repsona-dashboard

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env に各種トークンを記入（下の表参照）

python -m uvicorn app:app --host 127.0.0.1 --port 8000
# → http://localhost:8000 でダッシュボードが開く
```

初回起動時に SQLite が自動で作られる。データを入れるには別ターミナルで:

```bash
source .venv/bin/activate
python sync.py        # board と Repsona の全件を取得
```

## 環境変数（.env）

| 変数名 | 説明 | 取得元 |
| ----- | ---- | ---- |
| `BOARD_API_KEY` | board のAPIキー | board 設定 → API設定 |
| `BOARD_API_TOKEN` | board のAPIトークン | 同上（**APIキーとは別の値**） |
| `REPSONA_SPACE_ID` | Repsona のスペースID | URL の `https://<ここ>.repsona.com` |
| `REPSONA_API_TOKEN` | Repsona のAPIトークン | Repsona 個人設定 → APIトークン |
| `DISCORD_WEBHOOK_URL` | Discord 受注通知の宛先 | Discordチャンネル設定 → 連携サービス → ウェブフック |
| `DASHBOARD_USER` | Basic認証ユーザー名 | 任意 |
| `DASHBOARD_PASS` | Basic認証パスワード | 任意 |

## 運用

GitHub Actions で15分毎に `python run.py` を実行する想定（`.github/workflows/sync.yml`）。

## API レート

- board: 1日3000リクエスト上限。15分毎なら1日96回で十分余裕。
- Repsona: 明示的な上限なし。

## データの永続化

- 各PCローカルの `data.db` (SQLite) に保存。
- 別のPCで使う場合は **そのPCで別途 sync が必要**（DBファイルはリポジトリに含まれない）。
- チーム全員で同じDBを共有したい場合は Fly.io 等にデプロイすること。
