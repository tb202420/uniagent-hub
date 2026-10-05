"""ToolRegistry 单元测试。"""

from core.registry.registry import ToolRegistry
from core.unispec.models import UniSpec


def _spec(**kw):
    base = {
        "id": "cli.git.status", "type": "cli_tool", "name": "Git",
        "protocol": "subprocess",
        "capabilities": [{"name": "git_status", "description": "d",
                          "command": "git status --short"}],
    }
    base.update(kw)
    return base


def test_register_and_resolve():
    reg = ToolRegistry()
    spec = reg.register(_spec())
    assert reg.get("cli.git.status") is spec
    resolved = reg.resolve("git_status")
    assert resolved[0].id == "cli.git.status"


def test_owner_tracking():
    reg = ToolRegistry()
    reg.register(_spec(), adapter="CLI-ADAPTER")
    assert reg.owner_of("cli.git.status") == "CLI-ADAPTER"


def test_unregister_removes_tool():
    reg = ToolRegistry()
    reg.register(_spec())
    reg.unregister("cli.git.status")
    assert reg.resolve("git_status") is None
    assert reg.list_tools() == []


def test_invalid_dict_rejected_on_register():
    reg = ToolRegistry()
    try:
        reg.register({"id": "Bad", "type": "cli_tool", "name": "x", "protocol": "subprocess",
                      "capabilities": []})
        raised = False
    except Exception:
        raised = True
    assert raised
    assert len(reg) == 0
