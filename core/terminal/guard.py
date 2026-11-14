"""终端输入 Guard（v3.0 安全增量）。

目标不是"可以随便敲 shell"，而是把 PTY 输入纳入与工具调用同一条安全语义：
- 禁止提权（sudo / runas）
- 禁止网络外联（curl/wget/ssh/scp/nc/Invoke-WebRequest 等）
- 禁止明显破坏性命令（rm -rf /、format、diskpart、shutdown 等）

命中即拒绝写入子进程，并写入审计（tool="terminal.input"）。
"""

from __future__ import annotations

import re

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsudo\b", re.I), "禁止提权命令 sudo"),
    (re.compile(r"\brunas\b", re.I), "禁止提权命令 runas"),
    (re.compile(r"\b(curl|wget|ssh|scp|sftp|ncat|telnet)\b", re.I),
     "禁止网络外联命令"),
    (re.compile(r"\b(nc)\s+-", re.I), "禁止网络外联命令 nc"),
    (re.compile(r"\b(invoke-webrequest|invoke-restmethod|iwr|irm|test-netconnection)\b",
                re.I), "禁止 PowerShell 网络外联命令"),
    (re.compile(r"https?://", re.I), "禁止在终端访问网络地址"),
    (re.compile(r"\brm\s+-[rf]{2}\s+/", re.I), "禁止破坏性删除"),
    (re.compile(r"\b(format|diskpart|shutdown|reboot)\b", re.I), "禁止系统级破坏命令"),
    (re.compile(r"\bmkfs\b", re.I), "禁止格式化文件系统"),
]


def check_input(line: str) -> tuple[bool, str]:
    """返回 (是否放行, 拒绝原因)。空行放行。"""
    text = (line or "").strip()
    if not text:
        return True, ""
    for pattern, reason in _RULES:
        if pattern.search(text):
            return False, f"终端 Guard 拦截：{reason}"
    return True, ""
