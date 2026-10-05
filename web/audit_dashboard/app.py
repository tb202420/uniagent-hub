"""审计 Dashboard（阶段 3 展示层，FastAPI + 纯 HTML，无前端构建）。

页面：
  GET /          概览：工具列表 + 调用统计（总数/成功率/平均延迟）
  GET /audit     审计日志：分页表格 + 按工具/caller 筛选（数据源 SQLite）
  GET /workflows 最近工作流执行链路

安全：可选 Basic Auth（HUB_DASH_USER / HUB_DASH_PASS 环境变量，未设置则开放）。
"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from html import escape as _e
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse

from core.registry.store import SQLiteStore

_CSS = """
body{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f5f7fa;color:#1f2933}
header{background:#0f3d5c;color:#fff;padding:14px 24px}
header h1{margin:0;font-size:20px}
main{padding:20px 24px;max-width:1100px;margin:0 auto}
.card{background:#fff;border-radius:8px;padding:16px 20px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.1)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid #e4e7eb}
th{background:#f0f4f8}
.ok{color:#137c4f;font-weight:600}
.blocked{color:#c0392b;font-weight:600}
.skip{color:#8a6d3b}
.tag{display:inline-block;background:#e3f2fd;border-radius:4px;padding:1px 8px;margin:2px;font-size:12px}
.stat{display:inline-block;margin-right:28px}
.stat b{font-size:26px;display:block}
a{color:#0f3d5c}
"""


def _local_ts(ts: str) -> str:
    """UI-4：审计 ts 统一为 UTC（ISO + Z），展示时转本地时区；异常原样截断。"""
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return (ts or "")[:19]


def _html(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>{title} - UniAgent Hub</title><style>{_CSS}</style></head>
<body><header><h1>UniAgent Hub · 审计中心</h1>
<nav><a href="/" style="color:#fff;margin-right:12px">概览</a>
<a href="/audit" style="color:#fff;margin-right:12px">审计日志</a>
<a href="/workflows" style="color:#fff">工作流</a></nav></header>
<main>{body}</main></body></html>"""


def create_dashboard(hub_url: str = "http://127.0.0.1:8000",
                     db_path: str | Path = "data/uniagent.db") -> FastAPI:
    store = SQLiteStore(db_path)
    hub = hub_url.rstrip("/")
    app = FastAPI(title="UniAgent Hub Dashboard", version="0.3.0")

    auth_user = os.environ.get("HUB_DASH_USER")
    auth_pass = os.environ.get("HUB_DASH_PASS")

    @app.middleware("http")
    async def basic_auth(request: Request, call_next):
        if not auth_user:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        if not header.startswith("Basic "):
            return Response("401 Unauthorized", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="uniagent"'})
        decoded = base64.b64decode(header[6:]).decode("utf-8", errors="ignore")
        user, _, pwd = decoded.partition(":")
        if user != auth_user or pwd != auth_pass:
            return Response("401 Unauthorized", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="uniagent"'})
        return await call_next(request)

    def _hub_tools() -> list[dict]:
        try:
            headers = _hub_headers()
            resp = httpx.post(f"{hub}/mcp", json={"jsonrpc": "2.0", "id": 1,
                                                  "method": "tools/list", "params": {}},
                              timeout=5, headers=headers)
            return resp.json().get("result", {}).get("tools", [])
        except Exception:
            return []

    def _hub_workflows() -> list[dict]:
        try:
            resp = httpx.get(f"{hub}/workflows/recent", timeout=5,
                             headers=_hub_headers())
            return resp.json().get("items", [])
        except Exception:
            return []

    def _hub_headers() -> dict:
        # 网关启用 Bearer Token（HUB_API_TOKEN）时，面板调用需携带同一凭据
        token = os.environ.get("HUB_API_TOKEN", "")
        return {"Authorization": f"Bearer {token}"} if token else {}

    @app.get("/", response_class=HTMLResponse)
    def overview() -> str:
        tools = _hub_tools()
        # UI-3：统计在 SQL 层聚合（COUNT/SUM/AVG），不再拉 1000 条记录到 Python
        stats = store.audit_stats()
        total = stats["total"]
        ok = stats["ok"]
        avg = stats["avg_latency"]
        stat = f"""
        <div class="card">
          <span class="stat">调用次数<b>{total}</b></span>
          <span class="stat">成功率<b>{ok / total * 100 if total else 0:.1f}%</b></span>
          <span class="stat">平均延迟<b>{avg:.0f}ms</b></span>
        </div>"""
        tools_html = "".join(
            f'<span class="tag">{_e(t["name"])}</span>' for t in tools)
        return _html("概览", f"""
        <div class="card"><h2>已注册工具（{len(tools)}）</h2>{tools_html}</div>
        {stat}
        <div class="card"><p>演示提示：用 Agent 调用工具后刷新本页查看统计与审计。</p></div>""")

    @app.get("/audit", response_class=HTMLResponse)
    def audit(tool: str = "", caller: str = "", error_code: int = 0,
              limit: int = 50) -> str:
        # UI-2 修复：caller 改为 SQL 层过滤（store.query_audit），
        # 不再先 LIMIT 后 Python 过滤导致漏检
        rows = store.query_audit(tool=tool or None, caller=caller or None,
                                 error_code=error_code or None, limit=limit)
        # UI-1：所有动态值经 _e() HTML 转义，杜绝反射型/存储型 XSS
        trs = "".join(
            f"<tr><td>{_e(str(r['trace_id']))}</td><td>{_e(str(r['tool_name']))}</td>"
            f"<td>{_e(str(r.get('caller','')))}</td>"
            f"<td class='{'ok' if r.get('is_error')==0 else 'blocked'}'>"
            f"{'passed' if r.get('is_error')==0 else _e(str(r.get('guard_result','blocked')))}</td>"
            # A2 修复：错误码列（1007/1003/1004 可直接检索与核对）
            f"<td>{_e(str(r.get('error_code') or '-'))}</td>"
            f"<td>{_e(str(r.get('latency_ms') or ''))}ms</td>"
            # UI-5：schema_hash 前缀列（title 属性带全量哈希，同样经 HTML 转义）
            f"<td title='{_e(str(r.get('schema_hash') or ''))}'>"
            f"{_e(str(r.get('schema_hash') or '')[:12]) or '-'}</td>"
            # UI-4：UTC → 本地时区展示
            f"<td>{_e(_local_ts(str(r.get('ts',''))))}</td></tr>"
            for r in rows)
        filter_html = f"""
        <form method="get" style="margin-bottom:10px">
          工具: <input name="tool" value="{_e(tool)}">
          caller: <input name="caller" value="{_e(caller)}">
          错误码: <input name="error_code" value="{_e(str(error_code or ''))}" size="6">
          条数: <input name="limit" value="{_e(str(limit))}" size="5">
          <button>筛选</button></form>"""
        return _html("审计日志", f"""
        <div class="card"><h2>审计日志（SQLite）</h2>{filter_html}
        <table><tr><th>trace_id</th><th>工具</th><th>caller</th>
        <th>Guard 结果</th><th>错误码</th><th>延迟</th><th>schema_hash</th>
        <th>时间（本地）</th></tr>{trs}</table></div>""")

    @app.get("/workflows", response_class=HTMLResponse)
    def workflows() -> str:
        items = _hub_workflows()
        cards = ""
        for wf in items:
            steps_html = "".join(
                f"<tr><td>{_e(str(s['id']))}</td><td>{_e(str(s['tool']))}</td>"
                f"<td class='{'ok' if s['status']=='ok' else ('skip' if s['status']=='skipped' else 'blocked')}'>"
                f"{_e(str(s['status']))}</td><td>{_e(str(s.get('output',''))[:120])}</td>"
                f"<td>{_e(str(s.get('latency_ms','')))}ms</td></tr>"
                for s in wf.get("steps", []))
            cards += f"""
            <div class="card"><h3>{_e(str(wf['workflow']))} · ok={wf['ok']}
            <span style="font-weight:normal;font-size:12px;margin-left:12px">
            trace={_e(str(wf['trace_id']))}</span></h3>
            <table><tr><th>步骤</th><th>工具</th><th>状态</th><th>输出</th><th>延迟</th></tr>
            {steps_html}</table></div>"""
        return _html("工作流", f"<h2>最近工作流执行</h2>{cards}")

    return app
