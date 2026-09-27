# -*- coding: utf-8 -*-
"""zip2pdf_pure 回归测试：覆盖本次修复的全部缺陷。

运行: python test_regression.py
全部通过时退出码 0。
"""
import io
import os
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from zip2pdf_pure import (  # noqa: E402
    _category_key,
    _fix_zip_name,
    natural_sort_key,
    detect_image_format,
    extract_page_data,
)

FAILURES = []


def check(cond, label, detail=""):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        FAILURES.append(label)


# ---------------------------------------------------------------- 排序分类
print("== 分类归属 (_category_key) ==")
CASES = [
    ("fcov001", 0), ("cov001", 0), ("cov0", 9), ("bak001", 9),
    # 约定：bok0 开头一律算前言(3)，其余 bok 前缀算书脊(1)
    ("bok001", 3), ("bok010", 3), ("bok0", 3), ("bok1", 1),
    ("leg001", 2), ("pre001", 3), ("fow001", 4),
    ("dir001", 5), ("toc001", 5), ("dat001", 6),
    ("000001", 7), ("att001", 8), ("add001", 8),
    # "!" 开头的超星命名：!0000x 是目录，不能退化成正文
    ("!00001", 5), ("!00004", 5), ("!000", 5), ("!toc", 5),
]
for stem, expect in CASES:
    got = _category_key(stem)
    check(got == expect, f"{stem} -> {expect}", f"实际 {got}")


# ---------------------------------------------------------------- 整书排序
print("\n== 整书排序 ==")
book = ["cov001.pdg", "bok001.pdg", "pre001.pdg", "000001.pdg",
        "000002.pdg", "000010.pdg", "att001.pdg", "bak001.pdg"]
got = sorted(book, key=natural_sort_key)
# bok001 与 pre001 同属前言组(3)，组内按名字自然排序 -> bok001 在 pre001 前
expect = ["cov001.pdg", "bok001.pdg", "pre001.pdg", "000001.pdg",
          "000002.pdg", "000010.pdg", "att001.pdg", "bak001.pdg"]
check(got == expect, "封面在最前 / 自然排序正确", f"实际 {got}")

check(_category_key("cov001") == 0, "cov001 归类为封面(0)，不是封底(9)")
check(_category_key("bok001") == 3, "bok001 归类为前言(3)")
check(_category_key("bok1") == 1, "bok1 归类为书脊(1)")

# 真实读秀包（13059200_像工程师那样思考）暴露的问题：!0000x 是目录，不能排到最后
check(_category_key("!00001") == 5, "!00001 归类为目录(5)，不是正文(7)")
bang_book = ["cov001.pdg", "leg001.pdg", "bok001.pdg", "fow001.pdg",
             "!00001.pdg", "!00004.pdg", "000001.pdg", "000320.pdg"]
got_bang = sorted(bang_book, key=natural_sort_key)
expect_bang = ["cov001.pdg", "leg001.pdg", "bok001.pdg", "fow001.pdg",
               "!00001.pdg", "!00004.pdg", "000001.pdg", "000320.pdg"]
check(got_bang == expect_bang, "!0000x 目录排在序之后、正文之前", f"实际 {got_bang}")


# ---------------------------------------------------------------- 中文名修复
print("\n== ZIP 文件名修复 (_fix_zip_name) ==")
gbk_name = "封面.jpg".encode("gbk").decode("cp437")
check(_fix_zip_name(gbk_name) == "封面.jpg", "GBK 中文名修回 封面.jpg",
      f"实际 {_fix_zip_name(gbk_name)!r}")

nested = "正文/000001.pdg".encode("gbk").decode("cp437")
check(_fix_zip_name(nested) == "正文/000001.pdg", "含目录的中文名修复",
      f"实际 {_fix_zip_name(nested)!r}")

# 已声明 UTF-8 的名字必须原样保留
check(_fix_zip_name("封面.jpg", 0x800) == "封面.jpg",
      "flag_bits=UTF-8 的中文名原样保留")
check(_fix_zip_name("café.jpg", 0x800) == "café.jpg",
      "flag_bits=UTF-8 的西文名原样保留",
      f"实际 {_fix_zip_name('café.jpg', 0x800)!r}")
check(_fix_zip_name("Ω.jpg", 0x800) == "Ω.jpg",
      "flag_bits=UTF-8 的希腊字母名原样保留",
      f"实际 {_fix_zip_name('Ω.jpg', 0x800)!r}")
check(_fix_zip_name("readme.txt") == "readme.txt", "纯 ASCII 名不变")
check(_fix_zip_name("café.jpg") == "café.jpg",
      "未标 UTF-8 但本就合法的 Unicode 名不被破坏",
      f"实际 {_fix_zip_name('café.jpg')!r}")


# ---------------------------------------------------------------- PDG 解包
print("\n== PDG 解包 ==")
JPEG = (b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\x00" * 40)
check(detect_image_format(JPEG) == "jpg", "识别裸 JPEG")
wrapped = struct.pack("<I", len(JPEG)) + bytes([0x02]) + JPEG
data, fmt = extract_page_data(wrapped)
check(data == JPEG and fmt == "jpg", "剥离 5 字节 PDG 头")
check(detect_image_format(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20) == "png", "识别 PNG")

try:
    extract_page_data(struct.pack("<I", 10) + bytes([0x1B]) + b"text" * 5)
    check(False, "文本型 PDG 应抛错")
except ValueError as e:
    check("文本" in str(e), "文本型 PDG 抛 ValueError", str(e))


# ---------------------------------------------------------------- 端到端
print("\n== 端到端（真实压缩包） ==")
from PIL import Image  # noqa: E402

def jpg(color):
    im = Image.new("RGB", (40, 50), color)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


def pdg(b):
    return struct.pack("<I", len(b)) + bytes([0x02]) + b


tmp = Path(tempfile.mkdtemp(prefix="z2p_test_"))
zp = tmp / "book.zip"
files = ["cov001.pdg", "bok001.pdg", "pre001.pdg", "000001.pdg", "bak001.pdg"]
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
    for i, f in enumerate(files):
        z.writestr(f, pdg(jpg((i * 40, 90, 90))))

import subprocess  # noqa: E402
SCRIPT_PATH = SCRIPT_DIR / "zip2pdf_pure.py"
r = subprocess.run([sys.executable, str(SCRIPT_PATH),
                    "--workdir", str(tmp / "wd"), str(zp)],
                   capture_output=True, text=True, encoding="utf-8",
                   cwd=str(tmp))
out_pdf = zp.with_suffix(".pdf")
check(r.returncode == 0, "端到端转换退出码 0", r.stderr.strip()[:200])
check(out_pdf.exists(), "生成 PDF 文件")
if out_pdf.exists():
    try:
        from pypdf import PdfReader
        n = len(PdfReader(str(out_pdf)).pages)
        check(n == len(files), f"PDF 页数 = {len(files)}", f"实际 {n}")
    except ImportError:
        print("  SKIP  未装 pypdf，跳过页数校验")

print("\n" + "=" * 50)
if FAILURES:
    print(f"失败 {len(FAILURES)} 项:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("全部通过")
