"""研究报告 docx 结构验证器（可复用）：任意一轮"排版审阅"先跑本脚本客观裁决。

用法：python tools/verify_report_docx.py [docx路径] [md路径]
校验项：
  1. 表格行数与 md 逐表一致（缺行/混排的客观判据）
  2. 表格行 cantSplit 全覆盖、表头行 tblHeader 全覆盖
  3. 表题 keep_with_next（题与表同页）
  4. 目录：Heading 1/2/3 样式段落计数、TOC 域指令（无 \\u）、updateFields
  5. 内容抽查：校验行/作品名称/关键工具名
退出码：0=全部通过，1=存在问题。
"""

import io
import re
import sys
import zipfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
docx_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/研究报告.docx"
md_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "docs/研究报告.md"

md = md_path.read_text(encoding="utf-8")
z = zipfile.ZipFile(docx_path)
xml = z.read("word/document.xml").decode("utf-8", errors="replace")
settings = z.read("word/settings.xml").decode("utf-8", errors="replace")

problems = []

# 1) 表格行数
tbls = re.findall(r"<w:tbl>.*?</w:tbl>", xml, re.S)
md_tbls = re.findall(r"((?:^\|.*\n)+)", md, re.M)
if len(tbls) != len(md_tbls):
    problems.append(f"表格数量不一致：docx {len(tbls)} / md {len(md_tbls)}")
for i, (t, m) in enumerate(zip(tbls, md_tbls), 1):
    d = len(re.findall(r"<w:tr[ >]", t))
    mm = len(m.strip().splitlines()) - 1
    if d != mm:
        problems.append(f"表{i} 行数：docx {d} / md {mm}")

# 2/3) 表格属性
rows = sum(len(re.findall(r"<w:tr[ >]", t)) for t in tbls)
cant = xml.count("<w:cantSplit/>")
hdr = xml.count("<w:tblHeader")
if cant < rows:
    problems.append(f"cantSplit 覆盖 {cant}/{rows}")
if hdr != len(tbls):
    problems.append(f"tblHeader {hdr}/{len(tbls)}")

# 4) 目录
h1 = xml.count('w:val="Heading1"')
h2 = xml.count('w:val="Heading2"')
h3 = xml.count('w:val="Heading3"')
md_h = (len(re.findall(r"^## ", md, re.M)), len(re.findall(r"^### ", md, re.M)),
        len(re.findall(r"^#### ", md, re.M)))
if (h1, h2, h3) != md_h:
    problems.append(f"Heading 样式段落 {(h1, h2, h3)} != md 标题 {md_h}")
toc = re.search(r"TOC[^<]*", xml)
if not toc or "\\u" in toc.group(0):
    problems.append(f"TOC 指令异常: {toc.group(0) if toc else '缺失'}")
if "w:updateFields" not in settings:
    problems.append("updateFields 缺失（打开不会自动生成目录）")

# 5) 内容抽查
for needle in ("139 + 77 + 20 + 25", "作品名称：UniAgent Hub", "control_pump",
               "desktop_build_20261024"):
    if needle not in xml:
        problems.append(f"内容缺失: {needle}")
for banned in ("~~", "§", "worksflows", "EC harts", "五个适配器", "七个模块",
               "八个创新点", "以下五点"):
    if banned in xml:
        problems.append(f"禁用残留: {banned}")

print(f"docx: {docx_path.name}")
print(f"表 {len(tbls)} 张 · 行 {rows} · cantSplit {cant} · tblHeader {hdr} · "
      f"Heading {h1}/{h2}/{h3} · TOC {(toc.group(0)[:24] + '…') if toc else '无'}")
if problems:
    print("\n问题清单：")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("ALL PASS（结构校验全部通过）")
