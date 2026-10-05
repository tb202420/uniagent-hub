#!/usr/bin/env python3
"""硬件测试 1：USB 摄像头抓拍 / 运动检测（Script 适配器，改进方案 §7 配套）。

零嵌入式开发：USB 摄像头是标准 UVC 设备，PC 直接识别；
依赖 opencv-python（pip install opencv-python）。未安装依赖或未接摄像头时
返回**结构化 JSON 错误**（ok=false），便于在无硬件环境先跑通链路、后接硬件。

用法：
    python camera_capture.py capture --out alert.jpg
    python camera_capture.py detect_motion [--threshold 5000]
输出：单行 JSON（stdout）。安全：输出路径强制限定在 HUB_CAPTURE_DIR
（默认 <仓库>/data/captures）之下，拒绝 ../ 逃逸。
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]   # adapters/script_adapter/scripts → 仓库根
_DEFAULT_DIR = _REPO / "data" / "captures"


def _capture_dir() -> Path:
    root = Path(os.environ.get("HUB_CAPTURE_DIR", str(_DEFAULT_DIR)))
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _resolve_out(output_path: str) -> Path:
    """输出路径白名单：必须位于 HUB_CAPTURE_DIR 之下（拒绝越界写入）。"""
    root = _capture_dir()
    p = Path(output_path)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if not p.is_relative_to(root):
        raise ValueError(f"输出路径超出白名单: {p}（允许目录 {root}）")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_cv2():
    try:
        import cv2  # noqa: PLC0415 - 硬件依赖惰性导入（未装时结构化降级）
        return cv2
    except ImportError:
        return None


def capture(output_path: str) -> dict:
    cv2 = _load_cv2()
    if cv2 is None:
        return {"ok": False, "error": "未安装 opencv-python",
                "hint": "pip install opencv-python"}
    out = _resolve_out(output_path)
    cap = cv2.VideoCapture(0)
    try:
        ret, frame = cap.read()
    finally:
        cap.release()
    if not ret:
        return {"ok": False, "error": "摄像头未就绪（未连接或被其他程序占用）"}
    cv2.imwrite(str(out), frame)
    return {"ok": True, "path": str(out), "timestamp": time.time()}


def detect_motion(threshold: int = 5000) -> dict:
    # 失败时也附带数值字段（motion_detected/pixel_count）：未采集到画面
    # 即视为 0 像素差（无运动）—— 保证工作流条件 {{s1.output.pixel_count}} 可解析，
    # 真实原因在 error/hint 字段中如实给出，不被数值字段掩盖。
    cv2 = _load_cv2()
    if cv2 is None:
        return {"ok": False, "error": "未安装 opencv-python",
                "hint": "pip install opencv-python",
                "motion_detected": False, "pixel_count": 0}
    cap = cv2.VideoCapture(0)
    try:
        ret1, frame1 = cap.read()
        time.sleep(0.5)
        ret2, frame2 = cap.read()
    finally:
        cap.release()
    if not (ret1 and ret2):
        return {"ok": False, "error": "摄像头未就绪（未连接或被其他程序占用）",
                "motion_detected": False, "pixel_count": 0}
    diff = cv2.absdiff(frame1, frame2)
    pixels = int((cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY) > 25).sum())
    return {"ok": True, "motion_detected": pixels > threshold,
            "pixel_count": pixels, "threshold": threshold}


def main() -> None:
    parser = argparse.ArgumentParser(description="USB 摄像头抓拍 / 运动检测")
    sub = parser.add_subparsers(dest="action", required=True)
    p_cap = sub.add_parser("capture")
    p_cap.add_argument("--out", required=True,
                       help="输出文件（相对路径以 data/captures 为根）")
    p_mo = sub.add_parser("detect_motion")
    p_mo.add_argument("--threshold", type=int, default=5000)
    args = parser.parse_args()

    try:
        result = (capture(args.out) if args.action == "capture"
                  else detect_motion(args.threshold))
    except Exception as e:  # noqa: BLE001 - 路径越界等也结构化输出
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    # 统一 exit 0：由 JSON 的 ok 字段表达结果（平台侧拿到结构化原因，而非 1999）
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()