"""生成研究报告的 6 张正式图件（替代原 Markdown 中的 ASCII 示意图）。

输出：docs/figures/图1..图6.png（200 dpi，白底，适合置入 Word）
用法：python -m scripts.make_report_figures
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

OUT = Path(__file__).resolve().parent.parent / "docs" / "figures"

# 配色（柔和、印刷友好）
C_AGENT = "#DCE9F7"
C_HUB = "#EAE4F5"
C_ADAPTER = "#DFF0E3"
C_RES = "#FBEEDC"
C_GUARD = "#FADCD9"
C_TOOL = "#E8F3FA"
C_EDGE = "#7A8699"
C_TEXT = "#1F2937"

BOX_KW = dict(boxstyle="round,pad=0.02,rounding_size=0.02",
              linewidth=1.1, edgecolor=C_EDGE)


def setup_font() -> str:
    from matplotlib import font_manager as fm
    names = {f.name for f in fm.fontManager.ttflist}
    for cand in ("Microsoft YaHei", "SimHei", "SimSun", "DengXian"):
        if cand in names:
            plt.rcParams["font.sans-serif"] = [cand, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return cand
    return "DejaVu Sans"


def box(ax, x, y, w, h, text, fc, fontsize=10, bold=False, align="center"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, facecolor=fc, **BOX_KW))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, color=C_TEXT,
            fontweight="bold" if bold else "normal", linespacing=1.5,
            wrap=True)


def arrow(ax, x1, y1, x2, y2, style="-|>", color="#5A6472", lw=1.4,
          rad=0.0, ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                                 mutation_scale=13, linewidth=lw,
                                 color=color, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}"))


def new_ax(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    return fig, ax


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    fig.savefig(p, dpi=200, facecolor="white", bbox_inches="tight",
                pad_inches=0.12)
    plt.close(fig)
    print(f"  已生成 {p.name}")


# ---------------- 图 1 三层总体架构 ----------------
def fig1():
    fig, ax = new_ax(7.6, 6.2)
    ax.text(0.5, 0.975, "UniAgent Hub 三层总体架构", ha="center", va="center",
            fontsize=12.5, fontweight="bold", color=C_TEXT)

    box(ax, 0.10, 0.855, 0.80, 0.085,
        "Agent 层　Claude / DeepSeek / 本地 Ollama 模型（MCP Client）",
        C_AGENT, 10.5)
    arrow(ax, 0.5, 0.853, 0.5, 0.792)
    ax.text(0.525, 0.822,
            "JSON-RPC 2.0　·　tools/list · tools/call · server/discover",
            ha="left", va="center", fontsize=8.6, color="#556070")

    ax.add_patch(Rectangle((0.04, 0.395), 0.92, 0.39, facecolor=C_HUB,
                           edgecolor=C_EDGE, linewidth=1.2))
    ax.text(0.5, 0.755, "UniAgent Hub 核心层", ha="center", va="center",
            fontsize=11, fontweight="bold", color=C_TEXT)
    hub = [("工具注册中心\nToolRegistry", "#FFFFFF"),
           ("MCP 路由网关\nMCP Gateway", "#FFFFFF"),
           ("工作流引擎\nWorkflowEngine", "#FFFFFF"),
           ("规范适配层\nSpecAdapter", "#FFFFFF"),
           ("安全与权限\nGuard", "#FFFFFF"),
           ("CLI 生成器\nCLIGenerator", "#FFFFFF")]
    for i, (txt, fc) in enumerate(hub):
        r, c = divmod(i, 3)
        box(ax, 0.075 + c * 0.297, 0.635 - r * 0.118, 0.26, 0.095,
            txt, fc, 9)

    arrow(ax, 0.5, 0.393, 0.5, 0.338)
    ax.text(0.525, 0.366,
            "统一适配器协议　discover / list_tools / call_tool",
            ha="left", va="center", fontsize=8.6, color="#556070")

    labels = ["MQTT 适配器\n（物联网设备）", "CLI 适配器\n（subprocess 沙箱）",
              "REST 适配器\n（OpenAPI 导入）", "脚本适配器\n（路径沙箱）"]
    for c, t in enumerate(labels):
        box(ax, 0.045 + c * 0.237, 0.195, 0.21, 0.135, t, C_ADAPTER, 8.8)

    arrow(ax, 0.5, 0.193, 0.5, 0.172)
    res = ["ESP32 温室节点\n（模拟器）/ 空调", "git / find\n等命令行",
           "open-meteo\n等 REST API", "本地 Python\n/ Shell 脚本"]
    for c, t in enumerate(res):
        box(ax, 0.045 + c * 0.237, 0.03, 0.21, 0.135, t, C_RES, 8.8)

    save(fig, "图1-三层总体架构.png")


# ---------------- 图 2 端到端主链路与 Guard 管道 ----------------
def fig2():
    fig, ax = new_ax(8.2, 4.6)
    ax.text(0.5, 0.965, "端到端主链路与 Guard 管道", ha="center", va="center",
            fontsize=12.5, fontweight="bold", color=C_TEXT)

    box(ax, 0.015, 0.60, 0.115, 0.20, "Agent", C_AGENT, 10, bold=True)
    box(ax, 0.155, 0.60, 0.135, 0.20, "MCP 路由网关\nGateway", C_HUB, 9.5)
    arrow(ax, 0.132, 0.70, 0.153, 0.70)
    ax.text(0.142, 0.755, "tools/\ncall", ha="center", va="center",
            fontsize=7.5, color="#556070")

    ax.add_patch(Rectangle((0.315, 0.49), 0.275, 0.42, facecolor="#FDF1EF",
                           edgecolor=C_EDGE, linewidth=1.2))
    ax.text(0.4525, 0.878, "Guard 管道（所有调用必经）", ha="center",
            va="center", fontsize=9.5, fontweight="bold", color="#9B3B33")
    steps = ["① 存在性检查　1001", "② 权限校验　1003",
             "③ 限流　1004", "④ 参数校验 + 注入拦截　1002 / 1007",
             "⑤ 审计落盘（SQLite + JSONL）"]
    for i, s in enumerate(steps):
        box(ax, 0.328, 0.785 - i * 0.070, 0.249, 0.060, s, C_GUARD, 8.2)

    arrow(ax, 0.292, 0.70, 0.313, 0.70)
    box(ax, 0.615, 0.60, 0.135, 0.20, "适配器层\n（4 类）", C_ADAPTER, 9.5)
    arrow(ax, 0.592, 0.70, 0.613, 0.70)
    box(ax, 0.775, 0.60, 0.21, 0.20, "资源层\n设备 / CLI / API / 脚本", C_RES, 9.5)
    arrow(ax, 0.752, 0.70, 0.773, 0.70)

    box(ax, 0.31, 0.09, 0.60, 0.115,
        "返回结果 + trace_id　—　每一步均留痕，可按 caller / 工具 / 拦截结果查询",
        "#F4F6F8", 9)
    arrow(ax, 0.4525, 0.395, 0.61, 0.208, rad=-0.25, ls="--", lw=1.1)
    arrow(ax, 0.88, 0.598, 0.83, 0.208, rad=0.3, ls="--", lw=1.1)

    save(fig, "图2-主链路与Guard管道.png")


# ---------------- 图 3 UniSpec → MCP 工具转换 ----------------
def fig3():
    fig, ax = new_ax(8.0, 3.9)
    ax.text(0.5, 0.955, "UniSpec 一份描述，两个消费方", ha="center",
            va="center", fontsize=12.5, fontweight="bold", color=C_TEXT)

    ax.add_patch(Rectangle((0.02, 0.20), 0.34, 0.66, facecolor="#F7F4FC",
                           edgecolor=C_EDGE, linewidth=1.2))
    ax.text(0.19, 0.80, "UniSpec（资源能力描述）", ha="center", va="center",
            fontsize=10, fontweight="bold", color=C_TEXT)
    ax.text(0.045, 0.63,
            "id: iot.ac_01\n"
            "type: iot_device\n"
            "capabilities:\n"
            "  · get_ac_state  (readOnly: true)\n"
            "  · ac_control    (readOnly: false)\n"
            "constraints:\n"
            "  rateLimit: \"5/m\"\n"
            "  permissionLevel: write",
            ha="left", va="top", fontsize=8.6, color=C_TEXT, linespacing=1.7,
            family="monospace")

    arrow(ax, 0.365, 0.62, 0.435, 0.62)
    ax.text(0.40, 0.685, "正向生成", ha="center", va="center", fontsize=8.5,
            color="#556070")

    box(ax, 0.44, 0.575, 0.33, 0.235,
        "MCP 工具 get_ac_state\ninputSchema: {}　（只读）", C_TOOL, 9)
    box(ax, 0.44, 0.285, 0.33, 0.235,
        "MCP 工具 ac_control\ninputSchema: { action, temperature }", C_TOOL, 9)

    arrow(ax, 0.365, 0.33, 0.435, 0.33)
    ax.text(0.40, 0.245, "同时生成", ha="center", va="center", fontsize=8.5,
            color="#556070")
    box(ax, 0.44, 0.055, 0.33, 0.175,
        "Guard 校验规则\n限流 5/m　权限 write　只读降级", "#FDF1EF", 9)
    arrow(ax, 0.365, 0.145, 0.435, 0.145)

    box(ax, 0.79, 0.285, 0.175, 0.525,
        "Agent 看到的内容\n\n同一份 tools/list\n\n无法区分资源类型\n\n新增资源\n不改 Agent 代码",
        "#EFF6EE", 8.8)
    arrow(ax, 0.775, 0.55, 0.787, 0.55)

    save(fig, "图3-UniSpec转换.png")


# ---------------- 图 4 CLI 三层防护 ----------------
def fig4():
    fig, ax = new_ax(8.2, 3.2)
    ax.text(0.5, 0.94, "CLI 调用的三层防护（参数在到达 shell 之前被拦下）",
            ha="center", va="center", fontsize=12, fontweight="bold",
            color=C_TEXT)

    steps = [("LLM 参数\n\"x; rm -rf /\"", C_RES),
             ("① 参数白名单正则\n命中元字符 → 拒绝", C_GUARD),
             ("② argv 数组\n不经过 shell", C_GUARD),
             ("③ 命令白名单\n仅允许 git / find", C_GUARD),
             ("执行\n（资源层）", C_ADAPTER)]
    w, gap = 0.165, 0.0425
    for i, (t, fc) in enumerate(steps):
        x = 0.02 + i * (w + gap)
        box(ax, x, 0.48, w, 0.235, t, fc, 8.5)
        if i:
            arrow(ax, x - gap + 0.004, 0.5975, x - 0.004, 0.5975)

    box(ax, 0.02, 0.12, 0.42, 0.20,
        "× 返回错误码 1007（注入拦截）\n命令从未执行", "#F6D9D3", 9)
    arrow(ax, 0.28, 0.475, 0.24, 0.325, rad=0.2, color="#B03A2E")

    box(ax, 0.47, 0.12, 0.51, 0.20,
        "拦截率 100%（四类工具一致）\n参数校验位于网关 Guard 管道，横切所有适配器",
        "#EEF4FA", 8.8)

    save(fig, "图4-CLI三层防护.png")


# ---------------- 图 5 延迟对比 ----------------
def fig5():
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.8),
                             gridspec_kw={"width_ratios": [1.35, 1]})
    fig.suptitle("各类型工具调用延迟对比", fontsize=12.5, fontweight="bold",
                 color=C_TEXT, y=0.975)

    ax1 = axes[0]
    items = [("IoT 读取（缓存）", 0.0), ("ESP32 模拟器读取（缓存）", 0.0),
             ("SQLite 查询", 5.4), ("CLI git_status", 68),
             ("脚本 file_summary", 115), ("ESP32 模拟器开泵回执", 100),
             ("REST 缓存命中", 10)]
    names = [i[0] for i in items]
    vals = [i[1] for i in items]
    colors = ["#9CC3A6", "#9CC3A6", "#9CC3A6", "#7FA8D4", "#C9A96A",
              "#D9A6C0", "#9CC3A6"]
    bars = ax1.barh(names, vals, color=colors, edgecolor=C_EDGE, height=0.58)
    for b, v in zip(bars, vals):
        ax1.text(v + 3, b.get_y() + b.get_height() / 2,
                 f"{v:g} ms" if v else "0 ms（缓存读取）",
                 va="center", fontsize=8.4, color=C_TEXT)
    ax1.set_xlim(0, 290)
    ax1.set_xlabel("延迟（毫秒）", fontsize=9)
    ax1.tick_params(labelsize=8.6)
    ax1.set_title("本地与硬件资源：全部远低于 500ms 设计指标",
                  fontsize=9.5, color="#44506B", pad=8)
    for s in ("top", "right"):
        ax1.spines[s].set_visible(False)

    ax2 = axes[1]
    names2 = ["REST 冷调用\n（公网首字节）", "REST 缓存命中\n（300s 只读缓存）"]
    vals2 = [2400, 10]
    bars2 = ax2.barh(names2, vals2, color=["#D98A7F", "#9CC3A6"],
                     edgecolor=C_EDGE, height=0.5)
    for b, v in zip(bars2, vals2):
        ax2.text(v + 70, b.get_y() + b.get_height() / 2, f"{v} ms",
                 va="center", fontsize=8.6, color=C_TEXT)
    ax2.set_xlim(0, 3100)
    ax2.set_xlabel("延迟（毫秒）", fontsize=9)
    ax2.tick_params(labelsize=8.6)
    ax2.set_title("外部 API：缓存把冷调用 2.4s 降到 <10ms",
                  fontsize=9.5, color="#44506B", pad=8)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)

    fig.subplots_adjust(left=0.16, right=0.97, top=0.80, bottom=0.16, wspace=0.42)
    save(fig, "图5-延迟对比.png")


# ---------------- 图 6 Guard 拦截分布 ----------------
def fig6():
    fig, ax = new_ax(8.2, 3.4)
    ax.text(0.5, 0.945, "Guard 管道拦截分布（注入 / 越权 / 限流 / 描述篡改，全部拦在资源层之前）",
            ha="center", va="center", fontsize=12, fontweight="bold",
            color=C_TEXT)

    steps = [("请求进入", C_AGENT), ("1001\n存在性", C_GUARD),
             ("1003\n权限", C_GUARD), ("1004\n限流", C_GUARD),
             ("1002 / 1007\n校验拦截", C_GUARD), ("资源层", C_ADAPTER)]
    w, gap = 0.138, 0.032
    xs = []
    for i, (t, fc) in enumerate(steps):
        x = 0.02 + i * (w + gap)
        xs.append(x)
        box(ax, x, 0.56, w, 0.22, t, fc, 8.5)
        if i:
            arrow(ax, x - gap + 0.004, 0.67, x - 0.004, 0.67)

    notes = [(1, "越权调用\n100% 拦截"), (3, "第 6 次\n触发限流"),
             (4, "注入参数\n100% 拦截")]
    for idx, note in notes:
        cx = xs[idx] + w / 2
        box(ax, cx - 0.078, 0.245, 0.156, 0.155, note, "#F6D9D3", 8.2)
        arrow(ax, cx, 0.555, cx, 0.405, color="#B03A2E", lw=1.1)

    box(ax, 0.02, 0.055, 0.96, 0.135,
        "被拦截请求的完整参数全部写入审计（SQLite + JSONL 双写）"
        "　—　拦截率与调用方是否为 AI 无关", "#EEF4FA", 9)

    save(fig, "图6-Guard拦截分布.png")


def main() -> int:
    font = setup_font()
    print(f"中文字体：{font}")
    print(f"输出目录：{OUT}")
    for fn in (fig1, fig2, fig3, fig4, fig5, fig6):
        fn()
    print("完成：6 张图件")
    return 0


if __name__ == "__main__":
    sys.exit(main())