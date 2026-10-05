"""Schema 哈希与 Ed25519 清单签名测试（改进方案 §5.1）。"""

import pytest

from core.guard.attestation import (
    ManifestSigner, attestation_report, manifest_hashes, schema_hash,
)

TOOL = {
    "name": "get_temperature",
    "description": "测温",
    "inputSchema": {"type": "object", "properties": {}},
}


def test_schema_hash_deterministic_and_order_insensitive():
    t1 = dict(TOOL)
    t2 = {"inputSchema": {"properties": {}, "type": "object"},
          "description": "测温", "name": "get_temperature"}
    assert schema_hash(t1) == schema_hash(t2)          # 键序无关
    assert len(schema_hash(t1)) == 64                  # sha256 hex
    t3 = {**TOOL, "description": "测温 v2"}
    assert schema_hash(t3) != schema_hash(t1)          # 描述变化 → 哈希变化（投毒可检测）
    t4 = {**TOOL, "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}}}
    assert schema_hash(t4) != schema_hash(t1)


def test_manifest_hashes_batch():
    hashes = manifest_hashes([TOOL, {"name": "x", "description": "", "inputSchema": {}}])
    assert set(hashes) == {"get_temperature", "x"}


def test_signer_sign_verify(tmp_path):
    pytest.importorskip("cryptography")
    signer = ManifestSigner.generate(tmp_path / "k.pem")
    h = schema_hash(TOOL)
    sig = signer.sign("get_temperature", h)
    assert signer.verify("get_temperature", h, sig) is True
    assert signer.verify("get_temperature", h + "0", sig) is False   # 哈希被改 → 验签失败
    assert signer.verify("other_tool", h, sig) is False              # 换工具名 → 失败
    assert signer.verify("get_temperature", h, "!!!not-base64!!!") is False


def test_signer_key_reload_stable(tmp_path):
    pytest.importorskip("cryptography")
    path = tmp_path / "k.pem"
    s1 = ManifestSigner.generate(path)
    s2 = ManifestSigner(path)                # 重新加载同一密钥
    assert s1.key_id == s2.key_id
    assert s2.verify("t", "abc", s1.sign("t", "abc")) is True


def test_signer_missing_key(tmp_path):
    pytest.importorskip("cryptography")
    with pytest.raises(FileNotFoundError):
        ManifestSigner(tmp_path / "nope.pem")


def test_attestation_report_unsigned_and_signed(tmp_path):
    pytest.importorskip("cryptography")
    rep = attestation_report([TOOL])
    assert rep["signed"] is False
    assert rep["algorithm"] == "sha256"
    assert rep["hashes"]["get_temperature"] == schema_hash(TOOL)

    key = tmp_path / "k.pem"
    ManifestSigner.generate(key)
    rep2 = attestation_report([TOOL], key_path=key)
    assert rep2["signed"] is True
    assert rep2["key_id"] == ManifestSigner(key).key_id
    sig = rep2["signatures"]["get_temperature"]
    assert ManifestSigner(key).verify("get_temperature",
                                      rep2["hashes"]["get_temperature"], sig)