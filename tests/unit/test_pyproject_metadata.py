"""打包元数据测试（v3.0 差距 #9：pyproject.toml 落地）。"""

import tomllib
from pathlib import Path

from core.unispec.models import UniSpec

ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_exists_and_parses():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "uniagent-hub"
    assert data["project"]["version"] == "0.4.0"
    assert data["build-system"]["build-backend"] == "setuptools.build_meta"


def test_entry_point_groups_declared():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    groups = data["project"]["entry-points"]
    assert "uniagent_hub.adapters" in groups
    assert "uniagent_hub.agent_adapters" in groups


def test_console_script_and_py_modules():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["uniagent-hub"] == "main:main"
    assert data["tool"]["setuptools"]["py-modules"] == ["main"]


def test_unispec_version_matches_project():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    spec = UniSpec.model_validate({
        "id": "cli.x", "type": "cli_tool", "name": "x",
        "protocol": "subprocess",
        "capabilities": [{"name": "x", "description": "x", "command": "x"}],
    })
    assert spec.version == data["project"]["version"]
