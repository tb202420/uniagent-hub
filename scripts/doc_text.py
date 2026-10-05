"""提取 Word 97-2003（.doc）正文文本。

python-docx 只能读 .docx，而比赛模板是二进制 .doc（OLE2 复合文档）。
本模块实现最小可用的 Word 97 文本提取：读 WordDocument 流的 FIB →
定位 Table 流中的 Clx 分片表（piece table）→ 逐片按编码解码。

用法：
    python -m scripts.doc_text "路径.doc"            # 打印到 stdout
    python -m scripts.doc_text "路径.doc" -o out.txt  # 写入文件
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import olefile

# FIB 中的关键偏移（Word 97 及以后）
OFF_FLAGS = 0x000A          # bit 0x0200 = fWhichTblStm
OFF_FC_CLX = 0x01A2         # fibRgFcLcb97 第 33 项
OFF_LCB_CLX = 0x01A6

# 控制字符替换（\r 段末、\x07 单元格/行末、\x0C 分页等）
CTRL_MAP = {
    0x0D: "\n", 0x07: "\t", 0x0B: "\n", 0x0C: "\n",
    0x01: "", 0x02: "", 0x05: "", 0x08: "",
    0x13: "", 0x14: "", 0x15: "",
}


def _clean(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if o in CTRL_MAP:
            out.append(CTRL_MAP[o])
        elif o < 0x20 and o not in (0x09, 0x0A):
            continue
        else:
            out.append(ch)
    return "".join(out)


def extract(path: Path) -> str:
    ole = olefile.OleFileIO(str(path))
    try:
        wd = ole.openstream("WordDocument").read()
        if len(wd) < OFF_LCB_CLX + 4:
            raise ValueError("WordDocument 流过短，可能不是 Word 97 格式")
        ident = struct.unpack_from("<H", wd, 0)[0]
        if ident != 0xA5EC:
            raise ValueError(f"wIdent=0x{ident:04X}，非 Word 文档")

        flags = struct.unpack_from("<H", wd, OFF_FLAGS)[0]
        table_name = "1Table" if (flags & 0x0200) else "0Table"
        if not ole.exists(table_name):
            table_name = "0Table" if table_name == "1Table" else "1Table"
        tbl = ole.openstream(table_name).read()

        fc_clx = struct.unpack_from("<I", wd, OFF_FC_CLX)[0]
        lcb_clx = struct.unpack_from("<I", wd, OFF_LCB_CLX)[0]
        clx = tbl[fc_clx:fc_clx + lcb_clx]

        # 解析 Clx：跳过 Prc 数组，定位 Pcdt（分片表）
        pos = 0
        plc = None
        while pos < len(clx):
            kind = clx[pos]
            pos += 1
            if kind == 0x01:                      # Prc
                cb = struct.unpack_from("<h", clx, pos)[0]
                pos += 2 + cb
            elif kind == 0x02:                    # Pcdt
                lcb = struct.unpack_from("<I", clx, pos)[0]
                pos += 4
                plc = clx[pos:pos + lcb]
                break
            else:
                raise ValueError(f"Clx 结构异常（clxt=0x{kind:02X}）")
        if plc is None:
            raise ValueError("未找到分片表（Pcdt）")

        n = (len(plc) - 4) // 12                  # 片数
        cps = struct.unpack_from(f"<{n + 1}I", plc, 0)

        parts: list[str] = []
        for i in range(n):
            off = 4 * (n + 1) + i * 8
            fc = struct.unpack_from("<I", plc, off + 2)[0]
            chars = cps[i + 1] - cps[i]
            if fc & 0x40000000:                   # 压缩片：单字节（cp1252）
                start = (fc & 0x3FFFFFFF) // 2
                raw = wd[start:start + chars]
                parts.append(raw.decode("cp1252", errors="replace"))
            else:                                 # 未压缩片：UTF-16LE
                start = fc & 0x3FFFFFFF
                raw = wd[start:start + chars * 2]
                parts.append(raw.decode("utf-16-le", errors="replace"))
        return _clean("".join(parts))
    finally:
        ole.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="提取 .doc 文本")
    ap.add_argument("path")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    text = extract(Path(args.path))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"已写入 {args.out}（{len(text)} 字符）")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())