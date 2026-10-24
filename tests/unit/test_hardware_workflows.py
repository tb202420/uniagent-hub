"""硬件档工作流蓝图加载测试（smart_irrigation + 2 个灌溉策略变体）。"""

from pathlib import Path

import yaml

from core.gateway.server import MCPGateway
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry
from core.workflow.engine import WorkflowEngine

HERE = Path(__file__).resolve().parents[2]


def _engine_with(files: list[str]) -> WorkflowEngine:
    workflows: dict = {}
    for f in files:
        data = yaml.safe_load((HERE / f).read_text(encoding="utf-8")) or {}
        workflows.update(data.get("workflows") or {})
    gw = MCPGateway(ToolRegistry(), AuditLogger(AuditStore(max_memory=10)))
    engine = WorkflowEngine(gw)
    engine.register_workflows(workflows)
    gw.workflow = engine
    return engine


def test_hardware_blueprints_load_and_cover_three_strategies():
    engine = _engine_with([
        "core/workflow/workflows.yaml",
        "core/workflow/workflows_hardware.yaml",
    ])
    names = set(engine.workflows)
    # 三个灌溉策略：基础阈值 / 光照感知 / 三连干旱告警
    assert {"smart_irrigation", "light_aware_irrigation",
            "dry_soil_alert_irrigation"} <= names
    # 硬件档其余蓝图不受影响
    assert {"security_monitor", "office_auto_light", "phone_battery_snapshot",
            "dev_machine_health"} <= names


def test_irrigation_conditions_present():
    engine = _engine_with(["core/workflow/workflows_hardware.yaml"])
    light = engine.workflows["light_aware_irrigation"]["steps"]
    cond = [s["condition"] for s in light if "condition" in s][0]
    assert "{{s2.output}} > 500" in cond            # 白天判定（lux 阈值）
    dry = engine.workflows["dry_soil_alert_irrigation"]["steps"]
    cond = [s["condition"] for s in dry if "condition" in s][0]
    assert cond.count("< 20") == 3                  # 三连采样均低于 20%
