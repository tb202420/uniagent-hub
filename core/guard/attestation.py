"""Schema 签名与工具投毒防护（改进方案 §5.1）。

MCP 生态的"工具投毒"缺口：服务器工具描述可能在用户批准后被替换，
客户端缺少协议级手段检测变化。本模块提供内容寻址 + 签名基线：

1. 每个 MCP 工具定义（name/description/inputSchema）经规范化 JSON 计算
   **SHA-256**，作为其内容标识 —— Schema 一旦变化，哈希即变化（可检测篡改）；
2. **Ed25519** 对 `{tool, schema_hash, version}` 三元组签名（参考 MCP 社区
   signed tool manifests 提案）；Agent 调用前可用 `verify` 校验一致性；
3. 审计记录携带 schema_hash（见 core/guard/audit.py），事后可追溯。

依赖 cryptography（已在 requirements 的可选清单）；未安装时本模块可导入，
但签名/验签会给出明确错误（哈希功能不依赖它）。
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1


def canonical_json(obj: Any) -> str:
    """规范化 JSON（sorted keys、无多余空格）——哈希与签名的稳定性基础。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def tool_manifest(tool: dict) -> dict:
    """参与哈希的字段：名称 + 描述 + 参数 Schema（投毒攻击的关注面）。"""
    return {
        "name": tool.get("name"),
        "description": tool.get("description", ""),
        "inputSchema": tool.get("inputSchema", {}),
    }


def schema_hash(tool: dict) -> str:
    """工具定义的 SHA-256 内容哈希（hex）。"""
    payload = canonical_json(tool_manifest(tool)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def manifest_hashes(tools: list[dict]) -> dict[str, str]:
    """批量计算：工具名 -> 内容哈希。"""
    return {t["name"]: schema_hash(t) for t in tools if t.get("name")}


def _is_available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


class ManifestSigner:
    """Ed25519 清单签名器（密钥为 PEM 文件；不存在时可 generate 新建）。"""

    def __init__(self, key_path: str | Path) -> None:
        if not _is_available():
            raise RuntimeError(
                "需要 cryptography 库才能使用 Ed25519 签名："
                "pip install cryptography")
        from cryptography.hazmat.primitives import serialization
        self.key_path = Path(key_path)
        if not self.key_path.exists():
            raise FileNotFoundError(
                f"签名密钥不存在: {self.key_path}（先执行 genkey 或 generate()）")
        self._private = serialization.load_pem_private_key(
            self.key_path.read_bytes(), password=None)
        pub_raw = self._private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        self.key_id = hashlib.sha256(pub_raw).hexdigest()[:16]

    @classmethod
    def generate(cls, key_path: str | Path) -> "ManifestSigner":
        """生成新密钥并写入 PEM（PKCS#8，未加密）。已存在则直接加载。"""
        if not _is_available():
            raise RuntimeError(
                "需要 cryptography 库才能使用 Ed25519 签名："
                "pip install cryptography")
        path = Path(key_path)
        if path.exists():
            return cls(path)
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        key = Ed25519PrivateKey.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()))
        return cls(path)

    # ---- 签名 / 验签 ----

    @staticmethod
    def _payload(tool: str, schema_hash_hex: str, version: int = _SCHEMA_VERSION) -> bytes:
        return canonical_json({
            "tool": tool, "schema_hash": schema_hash_hex, "version": version,
        }).encode("utf-8")

    def sign(self, tool: str, schema_hash_hex: str,
             version: int = _SCHEMA_VERSION) -> str:
        """对三元组签名，返回 base64 字符串。"""
        sig = self._private.sign(self._payload(tool, schema_hash_hex, version))
        return base64.b64encode(sig).decode("ascii")

    def verify(self, tool: str, schema_hash_hex: str, signature_b64: str,
               version: int = _SCHEMA_VERSION) -> bool:
        """验签（True = 签名与该工具当前 Schema 哈希一致）。"""
        from cryptography.exceptions import InvalidSignature
        try:
            self._private.public_key().verify(
                base64.b64decode(signature_b64),
                self._payload(tool, schema_hash_hex, version))
            return True
        except (InvalidSignature, ValueError):
            return False


def attestation_report(tools: list[dict],
                       key_path: str | Path | None = None) -> dict:
    """生成证明报告（供 `server/attestation` RPC 与调试脚本复用）。

    key_path 为 None 或空时只返回哈希（unsigned）；提供时附带每工具签名。
    """
    hashes = manifest_hashes(tools)
    report: dict[str, Any] = {
        "algorithm": "sha256",
        "hash_version": _SCHEMA_VERSION,
        "signed": False,
        "hashes": hashes,
    }
    if key_path:
        signer = ManifestSigner(key_path)
        report["signed"] = True
        report["key_id"] = signer.key_id
        report["signatures"] = {n: signer.sign(n, h) for n, h in hashes.items()}
    return report