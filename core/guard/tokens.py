"""短期 JWT 令牌（v2.0 §3.6：令牌管理，MCP 规范强制"禁止会话认证"的对应实现）。

与静态 Bearer（HUB_API_TOKEN）并存的可选模式：
    HUB_AUTH_MODE=jwt + HUB_JWT_SECRET=<密钥>   → /mcp 需携带短期 JWT
    未设置 HUB_AUTH_MODE（默认）               → 维持静态 token / 本机回路兼容

令牌约束（对齐 v2.0 设计）：
- HS256 签名，默认 10 分钟过期（exp 强制校验）
- claims: caller（调用方标识）/ perm（read|write|admin）/ tools（允许的工具名列表，空=全部）
- 服务端按 claims 裁决权限与工具范围 —— 客户端不可自报（与静态模式的裁决原则一致）

签发：python -m scripts.issue_token --caller demo --perm write --ttl 600
"""

from __future__ import annotations

import os
import time
from typing import Any

import jwt

_DEFAULT_TTL = 600  # 10 分钟（v2.0 规格）


class TokenError(ValueError):
    """令牌签发/校验失败。"""


def _secret() -> str:
    secret = os.environ.get("HUB_JWT_SECRET", "").strip()
    if not secret:
        raise TokenError("HUB_JWT_SECRET 未设置（JWT 模式必需）")
    return secret


def issue_token(caller: str, perm: str = "read", ttl: int = _DEFAULT_TTL,
                tools: list[str] | None = None,
                secret: str | None = None) -> str:
    """签发短期令牌。perm ∈ read/write/admin；tools 为空表示不限制工具范围。"""
    if perm not in ("read", "write", "admin"):
        raise TokenError(f"非法权限级别: {perm}")
    now = int(time.time())
    payload: dict[str, Any] = {
        "caller": caller, "perm": perm, "tools": tools or [],
        "iat": now, "exp": now + int(ttl),
        # 会话标识明确置否 —— MCP 规范禁止以会话作为认证依据
        "session": False,
    }
    return jwt.encode(payload, secret or _secret(), algorithm="HS256")


def verify_token(token: str, secret: str | None = None) -> dict[str, Any]:
    """校验并返回 claims；过期/签名不符/格式错误均抛 TokenError。"""
    try:
        claims = jwt.decode(
            token or "", secret or _secret(), algorithms=["HS256"],
            options={"require": ["exp", "caller", "perm"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenError("令牌已过期") from e
    except jwt.InvalidTokenError as e:
        raise TokenError(f"令牌无效: {e}") from e
    if claims.get("perm") not in ("read", "write", "admin"):
        raise TokenError(f"令牌携带非法权限: {claims.get('perm')}")
    return {"caller": str(claims["caller"]), "perm": claims["perm"],
            "tools": list(claims.get("tools") or [])}


def from_bearer_header(header_value: str,
                       secret: str | None = None) -> dict[str, Any] | None:
    """从 Authorization 头解析并校验；非 Bearer/无效返回 None（由调用方决定 401）。"""
    if not header_value.startswith("Bearer "):
        return None
    try:
        return verify_token(header_value[7:], secret)
    except TokenError:
        return None
