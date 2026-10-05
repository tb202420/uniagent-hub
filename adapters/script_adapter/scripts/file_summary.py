#!/usr/bin/env python3
"""演示脚本：统计目录下文件，输出 JSON。

用法：python file_summary.py --dir <目录> [--ext <扩展名>]
输出：{"count": N, "files": ["..."], "dir": "..."}
"""

import argparse
import json
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="要统计的目录")
    parser.add_argument("--ext", default="", help="扩展名过滤，如 py")
    args = parser.parse_args()

    d = os.path.abspath(args.dir)
    if not os.path.isdir(d):
        print(json.dumps({"error": f"目录不存在: {d}"}, ensure_ascii=False))
        sys.exit(1)

    files = []
    for root, _dirs, names in os.walk(d):
        for n in names:
            if args.ext and not n.endswith("." + args.ext):
                continue
            files.append(os.path.relpath(os.path.join(root, n), d))
    print(json.dumps({"count": len(files), "files": files, "dir": d},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
