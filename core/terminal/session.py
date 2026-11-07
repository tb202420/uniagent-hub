"""交互式终端会话（v3.0 终端控制层后端）。

平台差异（如实标注）：
- POSIX：stdlib `pty` 伪终端（真实 PTY 语义，支持行编辑 / ANSI）
- Windows：`subprocess` 持久 stdin/stdout 管道会话（交互可用，但**不是 PTY**；
  Windows 无 stdlib pty，ConPTY 需 pywinpty 额外依赖，本项目不引入）

两种模式共享同一字节流 / 接管 / Guard 语义，前端 xterm.js 无感知。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
import uuid
from collections import deque
from typing import Any

from core.terminal.guard import check_input

_MAX_RUNTIME_S = 600          # 单会话最长 10 分钟（防僵尸会话）
_MAX_TRANSCRIPT = 400         # 回放转录上限（块）


def shell_command() -> list[str]:
    configured = os.environ.get("HUB_TERMINAL_SHELL", "").strip()
    if configured:
        return shlex.split(configured)
    if os.name == "nt":
        return ["powershell.exe", "-NoLogo", "-NoProfile"]
    return [os.environ.get("SHELL", "/bin/sh")]


class TerminalSession:
    def __init__(self, bus: Any, audit: Any, *, shell: list[str] | None = None,
                 max_runtime: float = _MAX_RUNTIME_S) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.trace_id = uuid.uuid4().hex[:8]
        self.bus = bus
        self.audit = audit
        self.shell = shell or shell_command()
        self.max_runtime = max_runtime
        self.created_ts = time.time()
        self.closed = False
        self._lock = threading.Lock()
        self._transcript: deque[str] = deque(maxlen=_MAX_TRANSCRIPT)
        self._proc: subprocess.Popen | None = None
        self._master: int | None = None
        self.mode = "pipe"
        self._reader: threading.Thread | None = None
        self._timer: threading.Thread | None = None
        self._start()

    # ---- 启动 ----

    def _start(self) -> None:
        env = {**os.environ, "TERM": "xterm-256color", "PYTHONUTF8": "1"}
        if os.name != "nt":
            try:
                import pty
                master, slave = pty.openpty()
                self._proc = subprocess.Popen(
                    self.shell, stdin=slave, stdout=slave, stderr=slave,
                    close_fds=True, preexec_fn=os.setsid, env=env)
                os.close(slave)
                self._master = master
                self.mode = "pty"
            except Exception:  # noqa: BLE001 - pty 不可用时回落管道
                self._proc = None
                self.mode = "pipe"
        if self._proc is None:
            flags = (subprocess.CREATE_NEW_PROCESS_GROUP
                     if os.name == "nt" else 0)
            self._proc = subprocess.Popen(
                self.shell, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, bufsize=0, env=env,
                creationflags=flags)
            self.mode = "pipe"
        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name=f"term-reader-{self.id}")
        self._reader.start()
        self._timer = threading.Thread(target=self._watchdog, daemon=True,
                                       name=f"term-timer-{self.id}")
        self._timer.start()
        self.bus.publish("terminal.state", session_id=self.id, state="running",
                         mode=self.mode, shell=self.shell[0])
        self._emit_meta()

    def _emit_meta(self) -> None:
        self.bus.publish(
            "terminal.output", session_id=self.id,
            data=(f"\r\n[UniAgent Hub] 会话 {self.id} · 模式 {self.mode}"
                  f" · shell {self.shell[0]}\r\n"))

    # ---- 读线程 ----

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None
        while not self.closed:
            try:
                if self._master is not None:
                    import select
                    ready, _, _ = select.select([self._master], [], [], 0.2)
                    if not ready:
                        continue
                    raw = os.read(self._master, 4096)
                else:
                    raw = proc.stdout.read(4096)
            except (OSError, ValueError):
                break
            if not raw:
                break
            text = raw.decode("utf-8", errors="replace")
            with self._lock:
                self._transcript.append(text)
            self.bus.publish("terminal.output", session_id=self.id, data=text)
        self._emit_exit()

    def _emit_exit(self) -> None:
        if self.closed:
            return
        code = self._proc.poll() if self._proc else None
        self.closed = True
        self.bus.publish("terminal.state", session_id=self.id, state="closed",
                         code=code)

    def _watchdog(self) -> None:
        while not self.closed:
            if time.time() - self.created_ts > self.max_runtime:
                self.close(reason="会话超过最长运行时间")
                return
            time.sleep(1.0)

    # ---- 输入 ----

    def write(self, data: str) -> dict[str, Any]:
        """写入一行/一段输入；先过 Guard，再进子进程。"""
        if self.closed or self._proc is None or self._proc.poll() is not None:
            return {"ok": False, "reason": "会话已关闭"}
        line = (data or "").replace("\r", "\n").strip("\n")
        allowed, reason = check_input(line)
        self._audit_input(line, allowed, reason)
        if not allowed:
            self.bus.publish("terminal.state", session_id=self.id,
                             state="blocked", reason=reason)
            return {"ok": False, "reason": reason}
        payload = data
        if self.mode == "pipe":
            payload = data.replace("\r\n", "\n").replace("\r", "\n")
        try:
            if self._master is not None:
                os.write(self._master, payload.encode("utf-8"))
            else:
                self._proc.stdin.write(payload.encode("utf-8"))
                self._proc.stdin.flush()
        except (OSError, ValueError, AttributeError) as e:
            return {"ok": False, "reason": f"写入失败: {e}"}
        return {"ok": True}

    def _audit_input(self, line: str, allowed: bool, reason: str) -> None:
        if self.audit is None:
            return
        try:
            self.audit.record(
                trace_id=self.trace_id, caller=f"terminal:{self.id}",
                tool="terminal.input", args={"line": line[:200]},
                guard_result="passed" if allowed else "blocked",
                block_reason="" if allowed else reason,
                result={"ok": allowed}, latency_ms=0,
                error_code=0 if allowed else 1007)
        except Exception:  # noqa: BLE001 - 审计失败不阻断终端
            pass

    # ---- 尺寸 / 关闭 / 回放 ----

    def resize(self, rows: int, cols: int) -> None:
        if self._master is None:
            return
        try:
            import fcntl
            import struct
            import termios
            fcntl.ioctl(self._master, termios.TIOCSWINSZ,
                        struct.pack("HHHH", max(2, rows), max(2, cols), 0, 0))
        except Exception:  # noqa: BLE001 - 非 POSIX/终端不支持时忽略
            pass

    def transcript(self, limit: int = 200) -> list[str]:
        with self._lock:
            return list(self._transcript)[-limit:]

    def info(self) -> dict[str, Any]:
        return {"session_id": self.id, "mode": self.mode, "shell": self.shell[0],
                "closed": self.closed, "created_ts": round(self.created_ts, 3)}

    def close(self, reason: str = "用户关闭") -> None:
        if self.closed:
            return
        self.closed = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception:  # noqa: BLE001
                pass
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None
        self.bus.publish("terminal.state", session_id=self.id, state="closed",
                         reason=reason)


class TerminalManager:
    """会话注册表：限制并发数（低配演示友好），进程退出时统一回收。"""

    def __init__(self, bus: Any, audit: Any, max_sessions: int = 2) -> None:
        self.bus = bus
        self.audit = audit
        self.max_sessions = max_sessions
        self._lock = threading.Lock()
        self._sessions: dict[str, TerminalSession] = {}

    def create(self) -> TerminalSession:
        with self._lock:
            alive = {k: s for k, s in self._sessions.items() if not s.closed}
            self._sessions = alive
            if len(alive) >= self.max_sessions:
                raise RuntimeError(f"终端会话数已达上限 {self.max_sessions}")
            session = TerminalSession(self.bus, self.audit)
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> TerminalSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def close(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close(reason="Hub 关闭")

    def info(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.info() for s in self._sessions.values()]
