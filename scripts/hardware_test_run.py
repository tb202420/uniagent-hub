"""硬件测试用例执行器（无外部硬件用例，改进方案 §7 / docs/hardware/hardware_test_cases.md）。

一键执行**不需要外部硬件**的用例，输出与用例编号一一对应的 PASS/FAIL/SKIP，
便于填入测试记录与报告（可反复运行，也是后续接真硬件后的回归工具）。

覆盖：TC-15 / TC-21 / TC-22 / TC-23 / TC-24 / TC-31 / TC-32 / TC-33 /
      TC-41 / TC-42 / TC-43 / TC-44 / TG-2 / TG-3 / TG-4
未覆盖（运行结束打印复现指引）：TC-11/12/13（摄像头取景·人工）、TC-14（依赖缺失分支）、
      TC-25 / TC-34（需特定 Hub 配置或重启）、TC-35（需一台"只注册不上报"的设备）。

用法：
    python -m scripts.hardware_test_run --url http://127.0.0.1:8020
    python -m scripts.hardware_test_run --only TC-41,TC-42
    python -m scripts.hardware_test_run --perf 3      # 附性能采样（每工具 3 次）
退出码：0 = 无 FAIL；1 = 存在 FAIL。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from agent.demo_agent import MCPClient
from core.guard.audit import read_jsonl, verify_chain

HERE = Path(__file__).resolve().parents[1]
_META = {"discover_tools", "get_tool_schema", "execute_tool", "refresh_registry"}
# tg3 校验 schema_hash 时排除元工具名（其定义不在注册中心，A2 修复后
# 元层记录亦带自身定义哈希，但按工具名分组判据与执行顺序解耦更稳）
_META_TOOL_NAMES = ("discover_tools", "get_tool_schema",
                    "execute_tool", "refresh_registry")
EXPECTED_TOOLS = 19   # 硬件测试档：默认 11 + 硬件 8（含 3 台模拟设备）


def _text(res: dict) -> str:
    return (res.get("content") or [{}])[0].get("text", "")


def _code(res: dict) -> int:
    return (res.get("meta") or {}).get("error_code", 0)


class Runner:
    """用例实现（每个方法返回 (ok, detail)；ok 为 None 表示 SKIP）。"""

    def __init__(self, url: str) -> None:
        self.client = MCPClient(url.rstrip("/"), timeout=60.0)
        self.caller = "hardware_test_run"

    def call(self, name: str, args: dict | None = None, perm: str = "read") -> dict:
        return self.client.call_tool(name, args or {}, caller=self.caller,
                                     permission_level=perm)

    # ---- 测试 1：USB 摄像头（无硬件用例）----

    def tc15(self):
        """路径白名单：输出路径越界必须被拒，且白名单外无文件生成。"""
        r = self.call("capture_image", {"output_path": "../../escape_test.jpg"},
                      perm="write")
        text, code = _text(r), _code(r)
        blocked = ("超出白名单" in text) or code in (1007, 1999)
        leaked = (HERE / "escape_test.jpg").exists() or \
                 (HERE.parent / "escape_test.jpg").exists()
        return (blocked and not leaked), \
            f"blocked={blocked} leaked_file={leaked} | {text[:70]}"

    # ---- 测试 2：智能插座 ----

    def tc21(self):
        r = self.call("plug_get_state")
        ok = (not r.get("isError")) and '"online": true' in _text(r)
        return ok, _text(r)[:80]

    def tc22(self):
        r1 = self.call("plug_set_power", {"body_power": True}, perm="write")
        r2 = self.call("plug_get_state")
        r3 = self.call("plug_set_power", {"body_power": False}, perm="write")
        r4 = self.call("plug_get_state")
        ok = ('"power": true' in _text(r2)) and ('"power": false' in _text(r4)) \
            and not (r1.get("isError") or r3.get("isError"))
        return ok, f"set T→{_text(r2)[:44]} ; set F→{_text(r4)[:44]}"

    def tc23(self):
        temp = self.call("get_temperature")
        t = None if temp.get("isError") else float(_text(temp))
        wf = self.call("run_workflow", {"workflow": "office_auto_light"}, perm="write")
        data = json.loads(_text(wf)) if not wf.get("isError") else {}
        steps = {s["id"]: s["status"] for s in data.get("steps", [])}
        powered = '"power": true' in _text(self.call("plug_get_state"))
        if t is not None and t < 20:
            ok = steps.get("s2") == "ok" and powered
            branch = f"低温分支（{t}°C<20）→ s2={steps.get('s2')} plug_on={powered}"
        else:
            ok = steps.get("s2") == "skipped"
            branch = f"常温分支（{t}°C≥20）→ s2={steps.get('s2')}（跳过）"
        return ok, branch

    def tc24(self):
        forbid = self.call("plug_set_power", {"body_power": True}, perm="read")
        allow = self.call("plug_get_state", perm="read")
        ok = _code(forbid) == 1003 and not allow.get("isError")
        return ok, (f"写(read权限)={_code(forbid) or 'ok'} / "
                    f"读(read权限)={'ok' if not allow.get('isError') else _code(allow)}")

    # ---- 测试 3：手机传感器节点 ----

    def tc31(self):
        names = {t["name"] for t in self.client.list_tools()}
        ok = {"get_phone_battery", "get_phone_temperature"} <= names
        return ok, f"手机工具已注册={ok}（注册发现；probe watch 证据另行采集）"

    def tc32(self):
        b = self.call("get_phone_battery")
        t = self.call("get_phone_temperature")
        ok = (not b.get("isError")) and (not t.get("isError"))
        return ok, f"battery={_text(b)} temperature={_text(t)}"

    def tc33(self):
        r = self.call("run_workflow", {"workflow": "phone_battery_snapshot"},
                      perm="write")
        data = json.loads(_text(r)) if not r.get("isError") else {}
        ok = bool(data.get("ok")) and len(data.get("steps", [])) == 2
        return ok, f"steps={[s['status'] for s in data.get('steps', [])]}"

    # ---- 测试 4：PC 系统监控 ----

    def tc41(self):
        r = self.call("get_system_cpu")
        try:
            v = float(_text(r))
            ok = (not r.get("isError")) and 0 <= v <= 100
        except ValueError:
            ok = False
        return ok, f"CPU={_text(r)}%"

    def tc42(self):
        r = self.call("get_system_memory")
        try:
            v = float(_text(r))
            ok = (not r.get("isError")) and 0 < v < 1024
        except ValueError:
            ok = False
        return ok, f"可用内存={_text(r)}GB"

    def tc43(self):
        r = self.call("run_workflow",
                      {"workflow": "dev_machine_health",
                       "params": {"repo": str(HERE)}}, perm="write")
        data = json.loads(_text(r)) if not r.get("isError") else {}
        steps = data.get("steps", [])
        ok = bool(data.get("ok")) and len(steps) == 3
        return ok, f"steps={[(s['id'], s['status']) for s in steps]}"

    def tc44(self):
        r = self.call("get_system_cpu", {"evil": "x"})
        ok = _code(r) == 1002
        return ok, f"未知参数→{_code(r)}"

    # ---- 通用性（横切）----

    def tg2(self):
        names = [t["name"] for t in self.client.list_tools()]
        if set(names) == _META:
            return True, "元工具模式（4 个）——全量面见非 meta 模式"
        ok = len(names) == EXPECTED_TOOLS
        return ok, f"tools={len(names)}（期望 {EXPECTED_TOOLS}）"

    def tg3(self, audit_file: str):
        path = Path(audit_file)
        if not path.exists():
            return False, f"审计文件不存在: {path}"
        records = read_jsonl(path)
        chained = [r for r in records if r.get("rec_hash")]
        ok, idx, msg = verify_chain(records)
        # 按工具名分组校验 schema_hash（A2 修复）：排除元工具名，
        # 不再依赖 records[-10:] —— TG-3 / TG-4 任意先后执行，结果一致
        missing = sorted({r.get("tool") for r in records
                          if r.get("tool") not in _META_TOOL_NAMES
                          and not r.get("schema_hash")})
        has_hash = bool(chained) and not missing
        return (ok and len(chained) > 0 and has_hash), \
            (f"records={len(records)} chained={len(chained)} "
             f"chain_ok={ok} 非元工具缺schema_hash={missing or '无'} {msg}")

    def tg4(self):
        names = [t["name"] for t in self.client.list_tools()]
        if set(names) != _META:
            return None, "Hub 未以 --meta-tools 启动（复现：重启并加 --meta-tools）"
        r = self.client.call_tool(
            "execute_tool", {"tool": "get_system_cpu", "arguments": {}},
            caller=self.caller)
        ok = not r.get("isError")
        return ok, f"execute_tool(get_system_cpu)={'ok' if ok else _code(r)}"


def _perf(runner: Runner, n: int) -> None:
    """性能采样（每次用独立 caller，避免触发限流）。"""
    tools = ["get_system_cpu", "get_system_memory", "plug_get_state",
             "get_phone_battery", "get_temperature"]
    print("\n性能采样（中位 / 最大，单位 ms；每工具 %d 次，独立 caller）：" % n)
    for name in tools:
        lats = []
        for i in range(n):
            r = runner.client.call_tool(name, {}, caller=f"hardware_perf_{name}_{i}")
            lats.append((r.get("meta") or {}).get("latency_ms", -1))
        lats.sort()
        print(f"  {name:<22} 中位 {lats[len(lats) // 2]:>5}  最大 {lats[-1]:>5}")
    for wf in ["dev_machine_health", "phone_battery_snapshot"]:
        lats = []
        for i in range(n):
            t0 = time.perf_counter()
            runner.client.call_tool(
                "run_workflow",
                {"workflow": wf, "params": {"repo": str(HERE)}},
                caller=f"hardware_perf_wf_{i}", permission_level="write")
            lats.append(int((time.perf_counter() - t0) * 1000))
        lats.sort()
        print(f"  run_workflow({wf})".ljust(24)
              + f" 中位 {lats[len(lats) // 2]:>5}  最大 {lats[-1]:>5}")


def main() -> int:
    ap = argparse.ArgumentParser(description="UniAgent Hub 硬件测试用例执行器")
    ap.add_argument("--url", default="http://127.0.0.1:8020")
    ap.add_argument("--only", default="", help="逗号分隔用例编号（如 TC-41,TC-42）")
    ap.add_argument("--audit-file", default="data/audit_hardware.jsonl")
    ap.add_argument("--perf", type=int, default=0, help="性能采样次数（0=关闭）")
    args = ap.parse_args()

    runner = Runner(args.url)
    cases = [
        ("TC-15", runner.tc15),
        ("TC-21", runner.tc21),
        ("TC-22", runner.tc22),
        ("TC-23", runner.tc23),
        ("TC-24", runner.tc24),
        ("TC-31", runner.tc31),
        ("TC-32", runner.tc32),
        ("TC-33", runner.tc33),
        ("TC-41", runner.tc41),
        ("TC-42", runner.tc42),
        ("TC-43", runner.tc43),
        ("TC-44", runner.tc44),
        ("TG-2", runner.tg2),
        ("TG-3", lambda: runner.tg3(args.audit_file)),
        ("TG-4", runner.tg4),
    ]
    only = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print("=" * 72)
    print(f"UniAgent Hub 硬件测试用例执行器（无外部硬件用例） — {args.url}")
    print("=" * 72)
    passed = fails = skips = 0
    for cid, fn in cases:
        if only and cid not in only:
            continue
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001 - 单个用例异常不中断整批
            ok, detail = False, f"异常: {type(e).__name__}: {e}"
        if ok is None:
            skips += 1
            tag = "SKIP"
        elif ok:
            passed += 1
            tag = "PASS"
        else:
            fails += 1
            tag = "FAIL"
        print(f"[{tag}] {cid:<6} {detail}")
    print("-" * 72)
    print(f"PASS={passed}  FAIL={fails}  SKIP={skips}")

    if args.perf:
        _perf(runner, args.perf)

    print("\n未覆盖用例（需特定环境 / 人工执行，复现指引见 docs/hardware/hardware_test_cases.md）：")
    print("  TC-11/12/13  摄像头取景（人工执行，涉及取景与隐私）")
    print("  TC-14        依赖缺失 / 无摄像头降级分支（需卸载 opencv 或断开摄像头）")
    print("  TC-25        去掉 HUB_REST_ALLOWED_PRIVATE_HOSTS 重启 Hub 后复跑 plug_get_state（预期 1006）")
    print("  TC-34        重启 Hub 后复跑 TC-32（晚订阅 retain 恢复）")
    print("  TC-35        以 mock 注册一台“只注册不上报”的设备后调用其工具（预期 1006）")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())