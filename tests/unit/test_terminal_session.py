"""交互终端会话与输入 Guard 单元测试（v3.0 批次）。

用当前解释器起一个"回显 stdin"的持久子进程，避免依赖平台 shell 提示符；
Windows 走管道模式、POSIX 走 pty 模式，两条路径都覆盖到字节流与 Guard。
"""

import sys
import time

from core.gateway.event_bus import EventBus
from core.terminal.guard import check_input
from core.terminal.session import TerminalSession

_ECHO_CODE = (
    "import sys\n"
    "for line in iter(sys.stdin.readline, ''):\n"
    "    print('ECHO:' + line.strip(), flush=True)\n"
)


def _make_session(bus: EventBus) -> TerminalSession:
    return TerminalSession(bus, None, shell=[sys.executable, "-c", _ECHO_CODE],
                           max_runtime=20)


def _outputs(bus: EventBus, session_id: str) -> str:
    return "".join(e.get("data", "") for e in bus.since(0)
                   if e.get("kind") == "terminal.output"
                   and e.get("session_id") == session_id)


def test_guard_blocks_privilege_and_network():
    blocked, reason = check_input("sudo rm -rf /tmp/x")
    assert blocked is False and "sudo" in reason
    blocked, reason = check_input("curl https://example.com")
    assert blocked is False and "网络" in reason
    blocked, reason = check_input("dir")
    assert blocked is True


def test_guard_blocks_powershell_download():
    ok, reason = check_input("Invoke-WebRequest http://x")
    assert ok is False
    assert "网络" in reason


def test_session_echo_roundtrip():
    bus = EventBus()
    session = _make_session(bus)
    try:
        assert session.mode in ("pty", "pipe")
        result = session.write("hello\n")
        assert result["ok"] is True
        deadline = time.time() + 3
        while time.time() < deadline:
            if "ECHO:hello" in _outputs(bus, session.id):
                break
            time.sleep(0.05)
        assert "ECHO:hello" in _outputs(bus, session.id)
    finally:
        session.close()


def test_session_blocks_dangerous_input():
    bus = EventBus()
    session = _make_session(bus)
    try:
        result = session.write("curl https://example.com\n")
        assert result["ok"] is False
        assert "网络" in result["reason"]
        states = [e for e in bus.since(0)
                  if e.get("kind") == "terminal.state"
                  and e.get("state") == "blocked"]
        assert states
        assert session.write("echo ok\n")["ok"] is True
    finally:
        session.close()


def test_session_info_and_transcript():
    bus = EventBus()
    session = _make_session(bus)
    try:
        info = session.info()
        assert info["session_id"] == session.id
        assert info["mode"] in ("pty", "pipe")
        session.write("one\n")
        deadline = time.time() + 3
        while time.time() < deadline:
            if any("ECHO:one" in chunk for chunk in session.transcript()):
                break
            time.sleep(0.05)
        assert any("ECHO:one" in chunk for chunk in session.transcript())
    finally:
        session.close()
