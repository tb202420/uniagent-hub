"""REST 适配器：OpenAPI Spec 导入 → MCP Tool（阶段 2 核心亮点）。

安全设计（答辩重点）：
- SSRF 防护：只允许 Spec 声明的 servers 域名，拒绝私有/保留网段，不跟随重定向
  （断网降级例外：仅 `HUB_REST_ALLOWED_PRIVATE_HOSTS` 显式列出的精确主机名放行，
  用于指向本地 mock 服务，默认空表示维持全拦）
- 认证脱敏：API Key 从环境变量读取注入 Header，绝不写入审计
- 超时 + 响应上限：httpx timeout=10s，响应 >1MB 截断
- 参数校验：复用 Gateway Guard 横切管道（inputSchema）
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from adapters.rest_adapter.openapi import load_spec, resolve_refs, simplify_schema
from core.contracts import (
    CallContext, ToolResult,
    E_TOOL_NOT_FOUND, E_RESOURCE_UNAVAILABLE, E_INTERNAL,
)
from core.registry.registry import ToolRegistry

_TIMEOUT = 10.0
_MAX_RESPONSE_BYTES = 1_000_000
_READONLY_METHODS = {"get", "head", "options"}
# BE-4：域名 SSRF 校验开关（离线环境无 DNS 时可置 0，等价于禁止所有裸域名）
_CHECK_DNS = os.environ.get("HUB_REST_CHECK_DNS", "1") == "1"
_PRIVATE_IPV4 = ("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                 "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                 "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                 "172.30.", "172.31.", "192.168.", "169.254.", "127.", "0.")


class RESTAdapter:
    """实现 BaseAdapter 协议（discover / list_tools / call_tool）。"""

    def __init__(self, registry: ToolRegistry, spec_source: str | Path,
                 api_key_env: str | None = None, auth_header: str = "X-API-Key",
                 resource_id: str | None = None, base_url_override: str | None = None,
                 allowed_private_hosts: list[str] | None = None) -> None:
        self.registry = registry
        self.spec_source = spec_source
        self.api_key_env = api_key_env
        self.auth_header = auth_header
        self.resource_id = resource_id
        self.base_url_override = base_url_override
        if allowed_private_hosts is None:
            # 断网降级逃生舱（默认空 = 维持全拦）：仅放行显式列出的精确主机名，
            # 不做网段放行，SSRF 防护对未声明主机依旧生效。
            allowed_private_hosts = [
                h.strip() for h in
                os.environ.get("HUB_REST_ALLOWED_PRIVATE_HOSTS", "").split(",")
                if h.strip()]
        self.allowed_private_hosts = tuple(allowed_private_hosts)
        self._servers: list[str] = []      # SSRF 白名单（Spec 声明）
        self._cache: dict[tuple[str, str], tuple[float, str]] = {}  # (tool,args) -> (ts,text)
        self._cache_ttl = 300.0            # 只读响应缓存 5 分钟（演示稳定兜底）
        # 缓存仅对"整份 Spec 全只读"（如天气 API）启用；含写操作的设备类 Spec
        # （如智能插座）必须实时读取，否则 set 后 get 会命中旧值的缓存
        self._cache_reads = True
        # BE-7：复用连接池的 httpx.Client（此前每次 httpx.request 新建连接，
        # HTTPS 握手开销显著；Client 线程安全，timeout/follow_redirects 配置一致）
        self._client = httpx.Client(timeout=_TIMEOUT, follow_redirects=False)

    # ---- 生命周期回调（改进方案 §4，可选实现）----

    def on_health_check(self) -> dict:
        return {"ok": bool(self._servers), "servers": list(self._servers),
                "cached_reads": len(self._cache)}

    def on_shutdown(self) -> None:
        """优雅关闭：释放 HTTP 连接池。"""
        self._client.close()

    # ---- 注册（discover）----

    def discover(self) -> list[dict]:
        raw = load_spec(self.spec_source)
        spec = resolve_refs(raw, raw)
        servers = spec.get("servers") or []
        self._servers = [s.get("url", "").rstrip("/") for s in servers if isinstance(s, dict)]
        if self.base_url_override:
            self._servers = [self.base_url_override.rstrip("/")]

        info = spec.get("info", {})
        rid = self.resource_id or f"rest.{info.get('title', 'api')}".lower()
        # 仅保留 ASCII 字母/数字/._-（UniSpec id 约束 ^[a-z][a-z0-9_.-]*$）
        rid = "".join(c if (c.isascii() and c.isalnum()) or c in "._-" else "_" for c in rid)
        rid = rid.strip("._-").lower()

        caps: list[dict[str, Any]] = []
        for path, path_item in (spec.get("paths") or {}).items():
            for method, op in (path_item or {}).items():
                if method not in ("get", "post", "put", "patch", "delete", "head", "options"):
                    continue
                cap = self._operation_to_capability(rid, path, method, op)
                if cap:
                    caps.append(cap)
        if not caps:
            return []
        self._cache_reads = all(c.get("readOnly") for c in caps)

        unispec = {
            "id": rid,
            "type": "rest_api",
            "name": info.get("title", "REST API"),
            "description": info.get("description", f"OpenAPI 导入: {self.spec_source}"),
            "protocol": "http",
            "endpoint": {"base_url": self._servers[0] if self._servers else "",
                         "auth": self.auth_header if self.api_key_env else "none"},
            "capabilities": caps,
            "constraints": {
                "readOnly": all(c.get("readOnly") for c in caps),
                "permissionLevel": "read" if all(c.get("readOnly") for c in caps) else "write",
                "timeout": "10s",
                "rateLimit": "10/m",
            },
        }
        self.registry.register(unispec, adapter=self)
        return [unispec]

    def _operation_to_capability(self, rid: str, path: str, method: str,
                                 op: dict[str, Any]) -> dict[str, Any] | None:
        name = op.get("operationId") or f"{method}_{path.strip('/').replace('/', '_')}"
        name = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
        name = re.sub(r"^[^a-zA-Z_]", "_", name)

        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in op.get("parameters", []):
            pname = p.get("name")
            if not pname:
                continue
            schema = simplify_schema(p.get("schema", {"type": "string"}))
            props_key = pname
            if p.get("in") in ("header", "cookie"):
                props_key = f"{p.get('in')}_{pname}"
            properties[props_key] = schema
            if p.get("required"):
                required.append(props_key)

        request_body = op.get("requestBody")
        if isinstance(request_body, dict):
            content = (request_body.get("content") or {})
            js = next((c["schema"] for c in content.values()
                       if isinstance(c, dict) and "schema" in c), None)
            if js:
                # 直接展开 requestBody 的 properties（此前经 simplify_schema 丢失嵌套
                # properties，导致 body_* 参数从未注册——智能插座等 POST 类接口不可用）
                for k, v in (js.get("properties") or {}).items():
                    properties[f"body_{k}"] = simplify_schema(v)
                for k in (js.get("required") or []):
                    required.append(f"body_{k}")

        description = op.get("summary") or op.get("description") or f"{method.upper()} {path}"
        read_only = method in _READONLY_METHODS

        return {
            "name": name,
            "title": name,
            "description": description,
            "http": {"method": method.upper(), "path": path},
            "inputSchema": {"type": "object", "properties": properties, "required": required},
            "outputSchema": {"type": "object"},
            "readOnly": read_only,
        }

    # ---- 查询 ----

    def list_tools(self) -> list[dict]:
        return [t for t in self.registry.list_tools()]

    # ---- 执行 ----

    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult:
        resolved = self.registry.resolve(name)
        if resolved is None:
            return ToolResult(ok=False, error_code=E_TOOL_NOT_FOUND,
                              error_msg=f"工具不存在: {name}")
        _, cap = resolved
        http = cap.http or {}
        method = (http.get("method") or "GET").lower()
        path = http.get("path") or ""
        start = time.perf_counter()

        # 只读工具响应缓存（演示稳定：公共 API 慢/抖动时直接命中缓存；
        # 设备类 Spec（含写能力）禁用缓存，保证"写后读"一致）
        cache_key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
        if cap.readOnly and self._cache_reads and cache_key in self._cache:
            ts, text = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return ToolResult(ok=True, data=text, latency_ms=0,
                                  error_msg="(cache)")

        # SSRF 防护：只允许 Spec 声明（或覆写）的服务器
        base_url = self._servers[0] if self._servers else ""
        if not base_url:
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg="未配置服务器地址（SSRF 白名单为空）")
        host_check = self._check_host(base_url)
        if host_check is not None:
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg=f"SSRF 防护拦截: {host_check}")

        # 参数拆解：path 替换 / query / header / JSON body
        url = base_url + path
        query: dict[str, Any] = {}
        headers: dict[str, str] = {}
        body: dict[str, Any] = {}
        input_schema = cap.inputSchema
        for pname, pschema in (input_schema.get("properties") or {}).items():
            if pname not in args:
                continue
            value = args[pname]
            if pname.startswith("header_") or pname.startswith("cookie_"):
                headers[pname[len("header_"):] if pname.startswith("header_") else pname[len("cookie_"):]] = str(value)
            elif pname.startswith("body_"):
                # requestBody 参数（OpenAPI → body_<字段>）：以 JSON body 发送
                body[pname[len("body_"):]] = value
            elif "{" + pname + "}" in path:
                url = url.replace("{" + pname + "}", str(value))
            else:
                query[pname] = value

        # 认证脱敏：API Key 从环境变量注入，不进参数、不进审计
        if self.api_key_env and os.environ.get(self.api_key_env):
            headers[self.auth_header] = os.environ[self.api_key_env]

        try:
            resp = self._client.request(
                method, url, params=query, headers=headers, json=body or None,
            )
        except httpx.HTTPError as e:
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg=f"HTTP 请求失败: {type(e).__name__}")
        except Exception as e:
            return ToolResult(ok=False, error_code=E_INTERNAL, error_msg=f"请求异常: {e}")

        latency = int((time.perf_counter() - start) * 1000)
        if resp.status_code >= 400:
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg=f"HTTP {resp.status_code}: {resp.text[:300]}",
                              latency_ms=latency)
        text = resp.text
        truncated = len(text.encode("utf-8", errors="ignore")) > _MAX_RESPONSE_BYTES
        if truncated:
            text = text[:_MAX_RESPONSE_BYTES] + "\n[响应已截断: 超过 1MB 限制]"
        if cap.readOnly and self._cache_reads:
            self._cache[cache_key] = (time.time(), text)
        return ToolResult(ok=True, data=text, latency_ms=latency)

    def _check_host(self, base_url: str) -> str | None:
        """SSRF：拒绝私有/保留 IP、解析到内网的域名与非常用端口。

        返回 None=通过，否则返回拒绝原因。
        """
        parsed = urlparse(base_url)
        host = parsed.hostname
        if not host:
            return "无法解析主机名"
        if host in self.allowed_private_hosts:
            # 显式白名单（断网降级：本地 mock 服务）；仅精确主机名匹配
            return None
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local:
                return f"拒绝访问私有/保留地址: {host}"
        except ValueError:
            # BE-4 修复：域名先 DNS 解析再校验归属，防止解析到内网的域名绕过
            if not _CHECK_DNS:
                return f"拒绝未解析域名（DNS 校验关闭）: {host}"
            try:
                infos = socket.getaddrinfo(host, None)
            except OSError:
                return f"主机名解析失败: {host}"
            for info in infos:
                addr = info[4][0]
                try:
                    ip = ipaddress.ip_address(addr)
                except ValueError:
                    continue
                if (ip.is_private or ip.is_reserved
                        or ip.is_loopback or ip.is_link_local):
                    return f"拒绝访问解析到私有/保留地址的主机: {host} -> {addr}"
        if any(host.startswith(p) for p in _PRIVATE_IPV4):
            return f"拒绝访问私有网段: {host}"
        # BE-4 修复：公网主机仅允许常用端口，收紧 SSRF 面
        port = parsed.port
        if port is not None and port not in (80, 443):
            return f"拒绝非常用端口: {port}"
        return None
