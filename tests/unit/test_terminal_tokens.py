"""终端 token 安全单元测试（v3.0 批次）。"""

import time

from core.terminal.tokens import TerminalTokenRegistry, parse_subprotocols, pick_token


def test_issue_and_single_use():
    reg = TerminalTokenRegistry(ttl=60)
    item = reg.issue(purpose="terminal")
    token = item["token"]
    assert len(token) > 20
    assert reg.consume(token, "terminal") is True
    assert reg.consume(token, "terminal") is False   # 单次有效


def test_purpose_isolation():
    reg = TerminalTokenRegistry(ttl=60)
    token = reg.issue(purpose="events")["token"]
    assert reg.consume(token, "terminal") is False
    assert reg.consume(token, "events") is True


def test_ttl_expiry():
    reg = TerminalTokenRegistry(ttl=0.02)
    token = reg.issue()["token"]
    time.sleep(0.05)
    assert reg.consume(token) is False


def test_subprotocol_parsing():
    header = "ua.events.abc123, ua.terminal.def456"
    assert parse_subprotocols(header) == ["ua.events.abc123", "ua.terminal.def456"]
    assert pick_token(header, "ua.events") == "abc123"
    assert pick_token(header, "ua.terminal") == "def456"
    assert pick_token(None, "ua.events") == ""
    assert pick_token("ua.events", "ua.events") == ""


def test_registry_prunes_expired():
    reg = TerminalTokenRegistry(ttl=0.01)
    reg.issue()
    time.sleep(0.03)
    reg.issue()
    assert len(reg) == 1
