"""UniSpec 模型校验单元测试。"""

import pytest
from pydantic import ValidationError

from core.unispec.models import UniSpec

VALID_SPEC = {
    "id": "cli.git.status",
    "type": "cli_tool",
    "name": "Git 状态查询",
    "protocol": "subprocess",
    "capabilities": [{
        "name": "git_status",
        "description": "查看 Git 状态",
        "command": "git -C {repo_path} status --short",
        "inputSchema": {"type": "object",
                        "properties": {"repo_path": {"type": "string"}},
                        "required": ["repo_path"]},
        "readOnly": True,
    }],
    "constraints": {"readOnly": True, "timeout": "10s"},
}


def test_valid_spec():
    spec = UniSpec.model_validate(VALID_SPEC)
    assert spec.id == "cli.git.status"
    assert spec.capabilities[0].name == "git_status"


@pytest.mark.parametrize("bad_id", ["Git.xx", "cli git", "1abc", "cli.git.status/xx"])
def test_invalid_id(bad_id):
    with pytest.raises(ValidationError):
        UniSpec.model_validate({**VALID_SPEC, "id": bad_id})


@pytest.mark.parametrize("bad_name", ["GetTemp", "get-temp", "1temp"])
def test_invalid_capability_name(bad_name):
    spec = {**VALID_SPEC, "capabilities": [{**VALID_SPEC["capabilities"][0], "name": bad_name}]}
    with pytest.raises(ValidationError):
        UniSpec.model_validate(spec)


def test_duplicate_capability_names_rejected():
    caps = VALID_SPEC["capabilities"] * 2
    with pytest.raises(ValidationError, match="唯一"):
        UniSpec.model_validate({**VALID_SPEC, "capabilities": caps})


def test_type_protocol_pairing():
    # cli_tool 必须 protocol=subprocess
    with pytest.raises(ValidationError, match="protocol"):
        UniSpec.model_validate({**VALID_SPEC, "protocol": "http"})


def test_cli_tool_requires_command():
    spec = {**VALID_SPEC, "capabilities": [{**VALID_SPEC["capabilities"][0], "command": None}]}
    with pytest.raises(ValidationError, match="command"):
        UniSpec.model_validate(spec)


def test_timeout_format():
    with pytest.raises(ValidationError):
        UniSpec.model_validate({**VALID_SPEC, "constraints": {"timeout": "10x"}})


def test_mcp_tools_output():
    spec = UniSpec.model_validate(VALID_SPEC)
    tools = spec.mcp_tools()
    assert tools[0]["name"] == "git_status"
    assert tools[0]["annotations"]["readOnlyHint"] is True
