"""FastAPI ダッシュボード。

- Basic認証（1〜2名想定）
- /          : ダッシュボードHTML
- /api/metrics : KPIサマリJSON（?fiscal_year=2026 で期フィルター）
- /api/mapping : 手動マッピング登録（POST）
"""
from __future__ import annotations
import os
import secrets
from fastapi import FastAPI, Depends, HTTPException, status, Body, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv

from metrics import get_kpis, get_won_progress, get_invoice_breakdown
from match import add_manual_mapping
from db import get_conn

load_dotenv()
app = FastAPI()
security = HTTPBasic()


def auth(creds: HTTPBasicCredentials = Depends(security)) -> str:
    expected_user = os.environ.get("DASHBOARD_USER", "admin")
    expected_pass = os.environ.get("DASHBOARD_PASS", "changeme")
    ok_user = secrets.compare_digest(creds.username, expected_user)
    ok_pass = secrets.compare_digest(creds.password, expected_pass)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return creds.username


HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>事業進捗ダッシュボード</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Hiragino Sans", sans-serif; background: #f7f7f8; color: #222; margin: 0; padding: 32px; }
  .header { display: flex; align-items: center; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
  h1 { font-size: 20px; margin: 0; flex: 1; }
  .period-selector { display: flex; align-items: center; gap: 8px; }
  .period-selector label { font-size: 13px; color: #6b6b70; }
  .period-selector select {
    font-size: 14px; padding: 6px 12px; border: 1px solid #d1d1d6;
    border-radius: 8px; background: #fff; cursor: pointer; appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%236b6b70' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 10px center; padding-right: 28px;
  }
  .period-selector select:focus { outline: none; border-color: #0071e3; }
  .period-badge { font-size: 12px; color: #6b6b70; background: #e5e5ea; padding: 3px 8px; border-radius: 10px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }
  .card { background: #fff; border: 1px solid #e5e5e7; border-radius: 12px; padding: 20px; }
  .card .label { color: #6b6b70; font-size: 12px; margin-bottom: 8px; }
  .card .value { font-size: 28px; font-weight: 600; }
  .card .sub { color: #6b6b70; font-size: 12px; margin-top: 4px; }
  section { background: #fff; border: 1px solid #e5e5e7; border-radius: 12px; padding: 20px; margin-bottom: 24px; }
  section h2 { font-size: 15px; margin: 0 0 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid #eee; }
  th { color: #6b6b70; font-weight: 500; }
  td.amount { text-align: right; font-variant-numeric: tabular-nums; }
  td.pct { text-align: right; font-variant-numeric: tabular-nums; width: 48px; }
  .empty { color: #999; font-size: 13px; }
  .loading { color: #999; font-size: 13px; }
  /* 進捗バー */
  .bar-wrap { display: flex; align-items: center; gap: 8px; min-width: 160px; }
  .bar-bg { flex: 1; background: #f0f0f0; border-radius: 4px; height: 10px; position: relative; overflow: hidden; }
  .bar-done  { position: absolute; left: 0; top: 0; height: 10px; background: #34c759; border-radius: 4px; transition: width .3s; }
  .bar-ideal { position: absolute; top: 0; height: 10px; background: #ff9500; opacity: .6; }
  .badge-ok   { color: #34c759; font-weight: 600; font-size: 12px; }
  .badge-warn { color: #ff9500; font-weight: 600; font-size: 12px; }
  .badge-ng   { color: #ff3b30; font-weight: 600; font-size: 12px; }
  .btn-del { background: none; border: 1px solid #d1d1d6; border-radius: 6px; color: #999; cursor: pointer; font-size: 12px; padding: 2px 7px; }
  .btn-del:hover { background: #ff3b30; border-color: #ff3b30; color: #fff; }
  .btn-link { background: none; border: 1px solid #d1d1d6; border-radius: 6px; color: #0071e3; cursor: pointer; font-size: 12px; padding: 2px 7px; margin-right: 4px; }
  .btn-link:hover { background: #0071e3; border-color: #0071e3; color: #fff; }
  .map-select { font-size: 12px; padding: 3px 6px; border: 1px solid #0071e3; border-radius: 6px; background: #fff; }
  .card.clickable { cursor: pointer; transition: transform .1s, box-shadow .1s; }
  .card.clickable:hover { transform: translateY(-1px); box-shadow: 0 2px 8px rgba(0,0,0,.06); border-color: #0071e3; }
  dialog#detail-modal { border: none; border-radius: 12px; padding: 0; max-width: 880px; width: 90vw; max-height: 80vh; box-shadow: 0 10px 40px rgba(0,0,0,.2); }
  dialog#detail-modal::backdrop { background: rgba(0,0,0,.4); }
  .modal-head { display: flex; align-items: center; gap: 12px; padding: 18px 20px; border-bottom: 1px solid #eee; }
  .modal-head h3 { font-size: 16px; margin: 0; flex: 1; }
  .modal-head .total { color: #6b6b70; font-size: 13px; font-variant-numeric: tabular-nums; }
  .modal-close { background: none; border: none; cursor: pointer; font-size: 18px; color: #6b6b70; padding: 4px 8px; }
  .modal-body { padding: 12px 20px 20px; overflow: auto; max-height: calc(80vh - 60px); }
  .modal-body small { color: #999; }
</style>
</head>
<body>
<div class="header">
  <h1>事業進捗ダッシュボード</h1>
  <div class="period-selector">
    <label for="fy-select">表示期間</label>
    <select id="fy-select" onchange="load()">
      <option value="">全期間</option>
    </select>
  </div>
  <span class="period-badge" id="period-label"></span>
</div>
<div class="grid" id="kpis"><div class="loading">読み込み中...</div></div>
<section><h2>受注案件の進捗（Repsona）</h2><div id="won-progress"></div></section>
<section><h2>未マッチ受注案件（Repsonaに紐付いていない）</h2><div id="unmatched"></div></section>
<dialog id="detail-modal">
  <div class="modal-head">
    <h3 id="modal-title"></h3>
    <span class="total" id="modal-total"></span>
    <button class="modal-close" onclick="closeDetail()">✕</button>
  </div>
  <div class="modal-body" id="modal-body"></div>
</dialog>
<script>
const FY_LABELS = {};

const fmt = n => n != null ? '¥' + Number(n).toLocaleString('ja-JP') : '';

async function load() {
  const fy = document.getElementById('fy-select').value;
  const mUrl = fy ? `/api/metrics?fiscal_year=${fy}` : '/api/metrics';
  const pUrl = fy ? `/api/progress?fiscal_year=${fy}` : '/api/progress';
  // metrics / progress を並列取得
  const [mRes, pRes] = await Promise.all([fetch(mUrl), fetch(pUrl)]);
  const d = await mRes.json();

  // 年度セレクターを初期化（初回のみ）
  const sel = document.getElementById('fy-select');
  if (sel.options.length === 1 && d.available_fiscal_years?.length) {
    d.available_fiscal_years.slice().reverse().forEach(y => {
      const opt = document.createElement('option');
      opt.value = y;
      const label = `${y}年度（${y}/03〜${y+1}/02）`;
      opt.textContent = label;
      FY_LABELS[y] = label;
      sel.appendChild(opt);
    });
    // デフォルト: 2026年度（現在の期）
    const defaultFY = '2026';
    if ([...sel.options].some(o => o.value === defaultFY)) {
      sel.value = defaultFY;
      load();
      return;
    }
  }

  // 期ラベル更新
  const badge = document.getElementById('period-label');
  badge.textContent = fy ? `${fy}年度 ${fy}/03/01〜${parseInt(fy)+1}/02/28` : '全期間';

  document.getElementById('kpis').innerHTML = `
    <div class="card"><div class="label">受注率</div><div class="value">${d.win_rate != null ? d.win_rate + '%' : '—'}</div><div class="sub">${d.won} 受注 / ${d.lost} 失注</div></div>
    <div class="card"><div class="label">見積中の案件</div><div class="value">${d.active}</div><div class="sub">パイプライン</div></div>
    <div class="card clickable" onclick="openDetail('invoiced')"><div class="label">請求済み（受注案件）</div><div class="value" style="font-size:20px">${fmt(d.invoiced_amount)}</div><div class="sub">請求日が過去の案件 →</div></div>
    <div class="card clickable" onclick="openDetail('un_invoiced')"><div class="label">未請求（受注案件）</div><div class="value" style="font-size:20px;color:#ff9500">${fmt(d.un_invoiced_amount)}</div><div class="sub">これから請求する金額 →</div></div>
    <div class="card"><div class="label">遅延タスク（Repsona）</div><div class="value">${d.overdue_tasks_total}</div><div class="sub">全プロジェクト合計</div></div>
  `;

  const renderTable = (id, rows, cols) => {
    const el = document.getElementById(id);
    if (!rows.length) { el.innerHTML = '<div class="empty">該当なし</div>'; return; }
    const head = cols.map(c => `<th>${c.label}</th>`).join('');
    const body = rows.map(row => '<tr>' + cols.map(c => {
      const v = row[c.key] ?? '';
      const val = c.fmt ? c.fmt(v) : v;
      return `<td${c.cls ? ' class="'+c.cls+'"' : ''}>${val}</td>`;
    }).join('') + '</tr>').join('');
    el.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  };

  // 受注案件の進捗（並列で取得済み）
  const progress = await pRes.json();
  const wpEl = document.getElementById('won-progress');
  if (!progress.length) {
    wpEl.innerHTML = '<div class="empty">Repsona にデータがありません</div>';
  } else {
    const head = '<tr><th>案件（Repsona）</th><th>金額</th><th>予算工数</th><th>進捗</th><th>実績</th><th>理想</th><th>状態</th></tr>';
    const rows = progress.map(p => {
      const actual = p.actual_pct, ideal = p.ideal_pct, over = p.task_overdue;
      const badge = over === 0
        ? '<span class="badge-ok">✓ オンスケ</span>'
        : over <= 1
          ? `<span class="badge-warn">⚠ ${over}件遅延</span>`
          : `<span class="badge-ng">✗ ${over}件遅延</span>`;
      const bar = `<div class="bar-wrap">
        <div class="bar-bg">
          <div class="bar-ideal" style="left:${actual}%;width:${Math.max(0,ideal-actual)}%"></div>
          <div class="bar-done"  style="width:${actual}%"></div>
        </div>
      </div>`;
      const boardNames = p.board_projects.map(b => b.name).join('、') || '—';
      const budgetLabel = p.budget_days != null
        ? `${p.budget_days}人日<br><small style="color:#999">@¥68,000/日</small>`
        : '—';
      return `<tr>
        <td><strong>${p.group_name}</strong><br><small style="color:#999">${boardNames}</small></td>
        <td class="amount">${p.total_amount ? '¥' + p.total_amount.toLocaleString('ja-JP') : '—'}</td>
        <td class="amount">${budgetLabel}</td>
        <td>${bar}</td>
        <td class="pct">${actual}%</td>
        <td class="pct">${ideal}%</td>
        <td>${badge}</td>
      </tr>`;
    }).join('');
    wpEl.innerHTML = `<table><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  }

  const unmatchedEl = document.getElementById('unmatched');
  if (!d.unmatched_won.length) {
    unmatchedEl.innerHTML = '<div class="empty">該当なし</div>';
  } else {
    const head = '<tr><th>見積日</th><th>案件名</th><th>クライアント</th><th style="width:170px"></th></tr>';
    const body = d.unmatched_won.map(row => `<tr>
      <td>${row.estimate_date || ''}</td>
      <td>${row.name}</td>
      <td>${row.client_name || ''}</td>
      <td>
        <button class="btn-link" onclick="linkUnmatched(${row.id}, this)" title="Repsonaグループに紐付ける">🔗 紐付け</button>
        <button class="btn-del" onclick="excludeUnmatched(${row.id}, this)" title="リストから除外">✕</button>
      </td>
    </tr>`).join('');
    unmatchedEl.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }
}
async function openDetail(kind) {
  const fy = document.getElementById('fy-select').value;
  const url = fy
    ? `/api/invoice-breakdown?kind=${kind}&fiscal_year=${fy}`
    : `/api/invoice-breakdown?kind=${kind}`;
  const r = await fetch(url);
  const items = await r.json();
  const title = kind === 'invoiced' ? '請求済み 受注案件' : '未請求 受注案件';
  document.getElementById('modal-title').textContent = title + (fy ? `（${fy}年度）` : '');
  const total = items.reduce((s, i) => s + (i.total_amount || 0), 0);
  document.getElementById('modal-total').textContent = `${items.length}件 / 計 ${fmt(total)}`;

  const body = document.getElementById('modal-body');
  if (!items.length) {
    body.innerHTML = '<div class="empty">該当なし</div>';
  } else {
    const head = '<tr><th>見積日</th><th>案件名</th><th>クライアント</th><th>金額</th><th>請求日</th></tr>';
    const rows = items.map(i => `<tr>
      <td>${i.estimate_date || ''}</td>
      <td>${i.name}</td>
      <td>${i.client_name || ''}</td>
      <td class="amount">${fmt(i.total_amount)}</td>
      <td><small>${(i.invoice_dates || []).join(', ') || '—'}</small></td>
    </tr>`).join('');
    body.innerHTML = `<table><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  }
  document.getElementById('detail-modal').showModal();
}

function closeDetail() {
  document.getElementById('detail-modal').close();
}

async function excludeUnmatched(id, btn) {
  btn.disabled = true;
  await fetch(`/api/unmatched/${id}/exclude`, {method: 'POST'});
  btn.closest('tr').remove();
}

let _groupsCache = null;
async function linkUnmatched(id, btn) {
  if (!_groupsCache) {
    const r = await fetch('/api/repsona-groups');
    _groupsCache = await r.json();
  }
  if (!_groupsCache.length) {
    alert('Repsona グループがまだありません。先に sync を実行してください。');
    return;
  }
  const cell = btn.closest('td');
  const options = _groupsCache.map(g => `<option value="${g}">${g}</option>`).join('');
  cell.innerHTML = `
    <select class="map-select" onchange="submitMapping(${id}, this.value, this)">
      <option value="">グループを選択...</option>
      ${options}
    </select>
    <button class="btn-del" onclick="load()" title="キャンセル">×</button>
  `;
}

async function submitMapping(id, groupName, select) {
  if (!groupName) return;
  select.disabled = true;
  await fetch('/api/mapping', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({board_id: id, repsona_id: groupName}),
  });
  // 紐付け後、ダッシュボード全体をリロードして進捗にも反映
  load();
}
load();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index(user: str = Depends(auth)) -> str:
    return HTML


@app.get("/api/metrics")
def api_metrics(
    fiscal_year: int | None = Query(default=None, description="年度（例: 2026 → 2026/03〜2027/02）"),
    user: str = Depends(auth),
) -> dict:
    return get_kpis(fiscal_year=fiscal_year)


@app.get("/api/progress")
def api_progress(
    fiscal_year: int | None = Query(default=None),
    user: str = Depends(auth),
) -> list:
    return get_won_progress()


@app.get("/api/invoice-breakdown")
def api_invoice_breakdown(
    kind: str = Query(default="invoiced", pattern="^(invoiced|un_invoiced)$"),
    fiscal_year: int | None = Query(default=None),
    user: str = Depends(auth),
) -> list:
    return get_invoice_breakdown(fiscal_year=fiscal_year, kind=kind)


@app.get("/api/repsona-groups")
def api_repsona_groups(user: str = Depends(auth)) -> list[str]:
    """Repsona の親タスク名（= グループ）一覧。手動マッピング用。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT group_name FROM repsona_task_groups ORDER BY group_name"
        ).fetchall()
        return [r["group_name"] for r in rows]
    finally:
        conn.close()


@app.post("/api/unmatched/{board_id}/exclude")
def api_exclude_unmatched(board_id: int, user: str = Depends(auth)) -> dict:
    conn = get_conn()
    try:
        conn.execute("UPDATE board_projects SET is_excluded = 1 WHERE id = ?", (board_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.post("/api/mapping")
def api_mapping(payload: dict = Body(...), user: str = Depends(auth)) -> dict:
    board_id = int(payload["board_id"])
    repsona_id = str(payload["repsona_id"])
    add_manual_mapping(board_id, repsona_id)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
