"""脚本适配器单元测试：注册 / 执行 / 路径逃逸拦截 / JSON 输出解析。"""

import tempfile
from pathlib import Path

import pytest

from adapters.script_adapter.adapter import ScriptAdapter
from core.contracts import CallContext
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore

HERE = Path(__file__).resolve().parents[2]
CFG = HERE / "adapters/script_adapter/configs/scripts.yaml"
SCRIPTS_ROOT = HERE / "adapters/script_adapter/scripts"


def _adapter(tmp_store: Path | None = None):
    reg = ToolRegistry(SQLiteStore(tmp_store or Path(tempfile.mkdtemp()) / "t.db"))
    adapter = ScriptAdapter(reg, config_path=CFG, scripts_root=SCRIPTS_ROOT)
    adapter.discover()
    return reg, adapter


def test_discover_registers_file_summary():
    reg, _ = _adapter()
    names = {t["name"] for t in reg.list_tools()}
    assert "file_summary" in names


def test_call_returns_json():
    reg, adapter = _adapter()
    tmp = tempfile.mkdtemp()
    Path(tmp, "a.py").write_text("x", encoding="utf-8")
    Path(tmp, "b.txt").write_text("y", encoding="utf-8")
    res = adapter.call_tool("file_summary", {"directory": tmp, "ext": "py"},
                            CallContext(trace_id="t1", caller="test"))
    assert res.ok is True
    assert res.data["count"] == 1
    assert "a.py" in res.data["files"]


def test_path_traversal_rejected_at_discover():
    reg = ToolRegistry(SQLiteStore(Path(tempfile.mkdtemp()) / "t.db"))
    adapter = ScriptAdapter(reg, config_path=CFG, scripts_root=SCRIPTS_ROOT)
    # 构造一个 entry 为 ../ 的配置
    from pathlib import Path as P
    cfg = P(tempfile.mkdtemp()) / "evil.yaml"
    cfg.write_text("scripts:\n  - id: script.evil\n    runtime: python\n"
                   "    entry: ../../core/gateway/server.py\n    args_template: ''\n",
                   encoding="utf-8")
    specs = adapter._entry_to_unispec({"id": "script.evil", "runtime": "python",
                                       "entry": "../../core/gateway/server.py",
                                       "args_template": ""})
    assert specs is None


def test_missing_script_rejected():
    reg = ToolRegistry(SQLiteStore(Path(tempfile.mkdtemp()) / "t.db"))
    adapter = ScriptAdapter(reg, config_path=CFG, scripts_root=SCRIPTS_ROOT)
    spec = adapter._entry_to_unispec({"id": "script.nope", "runtime": "python",
                                      "entry": "does_not_exist.py", "args_template": ""})
    assert spec is None


def test_call_script_not_found():
    reg, adapter = _adapter()
    res = adapter.call_tool("nope", {}, CallContext(trace_id="t1", caller="test"))
    assert res.ok is False
    assert res.error_code == 1001
