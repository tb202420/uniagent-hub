"""工具清单证明与审计校验工具（改进方案 §5 配套 CLI）。

子命令：
    hashes        从运行中的 Hub 拉取全部工具的内容哈希（+ Ed25519 签名，若已配置）
    genkey        生成 Ed25519 签名密钥（PEM），配合 HUB_ATTESTATION_KEY 使用
    audit-verify  校验审计哈希链（HUB_AUDIT_CHAIN=1 时写入的 pre_hash/rec_hash）

用法：
    python -m scripts.attestation hashes --url http://127.0.0.1:8020
    python -m scripts.attestation genkey --key data/attestation_key.pem
    python -m scripts.attestation audit-verify --file data/audit.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent.demo_agent import MCPClient
from core.guard.attestation import ManifestSigner
from core.guard.audit import read_jsonl, verify_chain


def cmd_hashes(args: argparse.Namespace) -> int:
    client = MCPClient(args.url.rstrip("/"), timeout=30.0)
    report = client.rpc("server/attestation", {})
    signed = report.get("signed")
    state = (f"是（key_id={report.get('key_id')}）" if signed
             else "否（未配置 HUB_ATTESTATION_KEY）")
    print(f"[attestation] 算法: {report.get('algorithm')}  签名: {state}")
    hashes = report.get("hashes") or {}
    signatures = report.get("signatures") or {}
    for name, h in sorted(hashes.items()):
        sig = signatures.get(name, "")
        suffix = f"  sig:{sig[:12]}…" if sig else ""
        print(f"  {name:<24} {h[:16]}…{suffix}")
    print(f"[attestation] 共 {len(hashes)} 个工具")
    return 0


def cmd_genkey(args: argparse.Namespace) -> int:
    signer = ManifestSigner.generate(args.key)
    print(f"[attestation] 密钥就绪: {args.key}（key_id={signer.key_id}）")
    print(f'使用：$env:HUB_ATTESTATION_KEY = "{args.key}" 后重启 Hub')
    return 0


def cmd_audit_verify(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"[attestation] 审计文件不存在: {path}")
        return 1
    records = read_jsonl(path)
    if not any(r.get("rec_hash") for r in records):
        print("[attestation] 该审计文件未启用哈希链"
              "（设置 HUB_AUDIT_CHAIN=1 后新写入的记录才含 rec_hash）")
        return 2
    ok, idx, msg = verify_chain(records)
    if ok:
        print(f"[attestation] ✓ 哈希链校验通过（{len(records)} 条记录）")
        return 0
    print(f"[attestation] ✗ 哈希链异常: {msg}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="工具清单证明与审计校验")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_hashes = sub.add_parser("hashes", help="拉取工具内容哈希（+签名）")
    p_hashes.add_argument("--url", default="http://127.0.0.1:8020")
    p_hashes.set_defaults(func=cmd_hashes)

    p_key = sub.add_parser("genkey", help="生成 Ed25519 签名密钥")
    p_key.add_argument("--key", default="data/attestation_key.pem")
    p_key.set_defaults(func=cmd_genkey)

    p_verify = sub.add_parser("audit-verify", help="校验审计哈希链")
    p_verify.add_argument("--file", default="data/audit.jsonl")
    p_verify.set_defaults(func=cmd_audit_verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())