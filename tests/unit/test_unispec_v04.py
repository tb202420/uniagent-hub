"""UniSpec v0.4.0 协议绑定字段测试（v3.0 批次）。"""

import pytest
from pydantic import ValidationError

from core.unispec.models import UniSpec

BASE = {
    "id": "iot.greenhouse",
    "type": "iot_device",
    "name": "温室节点",
    "protocol": "mqtt",
    "capabilities": [{
        "name": "control_pump",
        "description": "控制水泵",
        "inputSchema": {"type": "object", "properties": {}},
        "readOnly": False,
    }],
    "constraints": {"readOnly": False, "permissionLevel": "write"},
}


def test_default_version_is_v04():
    spec = UniSpec.model_validate(BASE)
    assert spec.version == "0.4.0"


def test_iot_device_derives_mhs_binding():
    spec = UniSpec.model_validate(BASE)
    assert spec.protocol_bindings.hardware_side == "MHS-compatible"
    assert spec.protocol_bindings.agent_access == ["mcp"]
    assert spec.control_mechanisms == ["mcp_tool"]


def test_cli_tool_derives_cli_control_mechanism():
    spec = UniSpec.model_validate({
        "id": "cli.git.status", "type": "cli_tool", "name": "git",
        "protocol": "subprocess",
        "capabilities": [{"name": "git_status", "description": "x",
                          "command": "git status", "readOnly": True}],
    })
    assert spec.protocol_bindings.hardware_side == "none"
    assert spec.control_mechanisms == ["mcp_tool", "cli"]


def test_local_script_derives_code_file_control_mechanism():
    spec = UniSpec.model_validate({
        "id": "script.summary", "type": "local_script", "name": "summary",
        "protocol": "script",
        "capabilities": [{"name": "file_summary", "description": "x",
                          "command": "python x.py", "readOnly": True}],
    })
    assert spec.control_mechanisms == ["mcp_tool", "code_file"]


def test_explicit_bindings_are_kept():
    spec = UniSpec.model_validate({
        **BASE,
        "version": "0.4.1",
        "protocol_bindings": {"hardware_side": "MHS-compatible",
                              "agent_access": ["mcp"],
                              "inter_agent": ["a2a"]},
        "control_mechanisms": ["mcp_tool", "cli"],
        "self_description": {"vendor": "demo", "model": "esp32-s3"},
    })
    assert spec.version == "0.4.1"
    assert spec.protocol_bindings.inter_agent == ["a2a"]
    assert spec.control_mechanisms == ["mcp_tool", "cli"]
    assert spec.self_description["model"] == "esp32-s3"


@pytest.mark.parametrize("bad", [
    {"hardware_side": "MHS"},                 # 枚举外
    {"agent_access": ["a2a"]},                # agent_access 仅 mcp
    {"inter_agent": ["mcp"]},                 # inter_agent 仅 a2a
])
def test_invalid_bindings_rejected(bad):
    with pytest.raises(ValidationError):
        UniSpec.model_validate({**BASE, "protocol_bindings": bad})


def test_invalid_control_mechanism_rejected():
    with pytest.raises(ValidationError):
        UniSpec.model_validate({**BASE, "control_mechanisms": ["pty"]})


@pytest.mark.parametrize("bad", ["0.4", "v0.4.0", "0.4.0.1", ""])
def test_invalid_version_rejected(bad):
    with pytest.raises(ValidationError):
        UniSpec.model_validate({**BASE, "version": bad})


def test_mcp_tools_carry_unispec_meta():
    spec = UniSpec.model_validate(BASE)
    tool = spec.mcp_tools()[0]
    meta = tool["_meta"]["unispec"]
    assert meta["version"] == "0.4.0"
    assert meta["protocol_bindings"]["hardware_side"] == "MHS-compatible"
    assert meta["control_mechanisms"] == ["mcp_tool"]
