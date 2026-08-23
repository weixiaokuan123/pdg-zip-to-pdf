#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zip2pdf_pure.py
把内含 PDG 书页（或直接就是 JPG/PNG/TIFF 等图片）的 ZIP / RAR / CBZ / UVZ
压缩包，或已解压的目录，合并成一个正常的 PDF。

与原版 zip2pdf.py 的区别：
- 不再通过 pywinauto 模拟键鼠操作 Pdg2Pic.exe，全程纯 Python，可无人值守、可批量
- 自动识别 PDG 内部封装的真实图片格式（JPG / PNG / BMP / GIF / TIFF / WEBP）
- 加密包自动用密码表尝试（密码表用 UTF-8 与 GB18030 双编码读取，兼容中文密码）
- 支持 ZipCrypto、AES-128/256（pyzipper），RAR 交给 UnRAR.exe / 7z.exe
- 支持批量：可以一次拖入多个压缩包 / 目录

依赖：
    pip install pyzipper img2pdf Pillow rarfile

RAR 解压还需要一个外部命令行工具（任选其一），脚本会按顺序查找：
    1) 脚本目录下 7-Zip\\UnRAR.exe
    2) 脚本目录下 7-Zip\\7z.exe
    3) PATH 中的 UnRAR.exe / 7z.exe / unrar
RAR5 格式需要较新的 UnRAR.exe（随附的 6.x 版本即可）。

用法：
    python zip2pdf_pure.py <文件或目录> [文件或目录 ...]
    python zip2pdf_pure.py                # 不带参数则进入交互模式
也可以直接把文件 / 文件夹拖到配套的 .bat 启动器上。
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

try:
    import pyzipper  # type: ignore
except ImportError:  # pragma: no cover
    sys.stderr.write("[错误] 缺少 pyzipper，请先运行:  pip install pyzipper\n")
    raise

try:
    import img2pdf  # type: ignore
except ImportError:  # pragma: no cover
    img2pdf = None  # type: ignore

try:
    from PIL import Image, ImageFile  # type: ignore
    ImageFile.LOAD_TRUNCATED_IMAGES = True
except ImportError:  # pragma: no cover
    sys.stderr.write("[错误] 缺少 Pillow，请先运行:  pip install Pillow\n")
    raise

try:
    import rarfile  # type: ignore
except ImportError:  # pragma: no cover
    rarfile = None  # type: ignore


# ---------- 颜色输出 ----------
def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return bool(sys.stdout.isatty())


_COLOR = _supports_color()


def c(text: str, code: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def info(msg: str) -> None:
    print(c(msg, "0;32"))


def warn(msg: str) -> None:
    print(c(msg, "0;33"))


def err(msg: str) -> None:
    print(c(msg, "0;31"), file=sys.stderr)


# ---------- 配置 ----------
SCRIPT_DIR = Path(__file__).resolve().parent


def _candidate_dirs() -> List[Path]:
    """按优先级返回可能存放 7-Zip/ 和 passwords/ 的目录。"""
    dirs: List[Path] = [SCRIPT_DIR, SCRIPT_DIR.parent, Path.cwd()]
    result: List[Path] = []
    seen = set()
    for d in dirs:
        try:
            rp = d.resolve()
        except OSError:
            continue
        if rp not in seen:
            seen.add(rp)
            result.append(rp)
    return result


def find_password_file(explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    names = ("passwords.txt", "password.txt")
    for d in _candidate_dirs():
        for sub in (d / "passwords", d):
            for n in names:
                cand = sub / n
                if cand.is_file():
                    return cand
    return None


ARCHIVE_EXTS = (".zip", ".cbz", ".uvz", ".rar")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".jp2"}
IGNORE_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
PDG_TEXT_TYPES = {0x1B, 0x1C, 0x1D, 0x28, 0x29, 0x2A}


@dataclass
class ConvertResult:
    source: Path
    output: Optional[Path] = None
    pages_ok: int = 0
    pages_skipped: List[Tuple[str, str]] = field(default_factory=list)
    password: Optional[str] = None
    note: str = ""

    def summary(self) -> str:
        if self.output:
            lines = [f"[OK] {self.source}  ->  {self.output}",
                     f"     页数: {self.pages_ok}"]
            if self.pages_skipped:
                lines.append(f"     跳过 {len(self.pages_skipped)} 页:")
                for name, reason in self.pages_skipped[:10]:
                    lines.append(f"       - {name}: {reason}")
                if len(self.pages_skipped) > 10:
                    lines.append(f"       ... 其余 {len(self.pages_skipped)-10} 页略")
            if self.password and self.password != "-":
                lines.append(f"     密码: {self.password}")
            if self.note:
                lines.append(f"     备注: {self.note}")
            return "\n".join(lines)
        return f"[失败] {self.source}: {self.note}"


# ---------- 密码表 ----------
def load_passwords(pwd_file: Path) -> List[str]:
    """读取密码表，UTF-8 失败则 GB18030，自动去重保留顺序。"""
    if not pwd_file.exists():
        return []
    raw = pwd_file.read_bytes()
    text = None
    for enc in ("utf-8-sig", "gb18030", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("latin-1", errors="replace")
    seen = set()
    pwds: List[str] = []
    for line in text.splitlines():
        p = line.strip()
        if p and p not in seen:
            seen.add(p)
            pwds.append(p)
    return pwds

# ---------- PDG / 图片识别 ----------
def detect_image_format(data: bytes) -> Optional[str]:
    """根据文件头魔数判断图片格式，返回小写扩展名（不含点）或 None。"""
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:2] == b"BM":
        return "bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:12] == b"\x00\x00\x00\x0cjP  \r\n\x87\n":
        return "jp2"
    return None


def extract_page_data(raw: bytes) -> Tuple[bytes, str]:
    """
    解析一个 PDG 文件的内容，返回 (真实图片字节, 格式)。
    最常见的 PDG 封装：
        [4 字节小端数据长度][1 字节类型码][真实数据 ...]
    但也有大量 PDG 其实就是改了扩展名的普通图片。这里采用
    "直接认魔数 -> 5 字节头后认魔数 -> 暴力扫描" 的三级策略。
    """
    fmt = detect_image_format(raw)
    if fmt:
        return raw, fmt

    if len(raw) > 6:
        try:
            (declared_len,) = struct.unpack("<I", raw[:4])
        except struct.error:
            declared_len = 0
        ptype = raw[4]
        payload = raw[5:]
        fmt = detect_image_format(payload)
        if fmt:
            return payload, fmt
        if ptype in PDG_TEXT_TYPES:
            raise ValueError(f"文本/目录型 PDG (type=0x{ptype:02X})，非位图")
        if 0 < declared_len <= len(payload):
            inner = payload[:declared_len]
            fmt = detect_image_format(inner)
            if fmt:
                return inner, fmt

    for magic, ext in (
        (b"\xff\xd8\xff", "jpg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"BM", "bmp"),
        (b"GIF87a", "gif"),
        (b"GIF89a", "gif"),
        (b"RIFF", "webp"),
        (b"II*\x00", "tiff"),
        (b"MM\x00*", "tiff"),
    ):
        idx = raw.find(magic)
        if idx > 0:
            candidate = raw[idx:]
            if detect_image_format(candidate):
                return candidate, ext

    raise ValueError("未识别的 PDG 格式（可能是加密/旧版文本页）")


# ---------- 页面排序 ----------
_CATEGORY_ORDER = {
    "fcov": 0, "cov": 0,
    "bok": 1,
    "leg": 2, "!000": 2,
    "pre": 3, "bok0": 3,
    "fow": 4, "foreword": 4,
    "dir": 5, "toc": 5, "!toc": 5,
    "dat": 6,
    "000": 7,
    "att": 8, "add": 8,
    "bak": 9, "cov0": 9,
}
_NAT_RE = re.compile(r"(\d+)")


def _category_key(stem: str) -> int:
    candidate = stem.lower().lstrip("!")
    for prefix, order in sorted(_CATEGORY_ORDER.items(), key=lambda x: -len(x[0])):
        if candidate.startswith(prefix):
            return order
    if candidate[:1].isdigit():
        return 7
    return 7


def natural_sort_key(name: str) -> Tuple[int, List]:
    stem = Path(name).stem
    cat = _category_key(stem)
    parts = _NAT_RE.split(stem.lower())
    key: List = []
    for p in parts:
        if p.isdigit():
            key.append((1, int(p)))
        else:
            key.append((0, p))
    return (cat, key)


# ---------- 收集 / 规整页面 ----------
def gather_pages(root: Path) -> List[Path]:
    pages: List[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name.lower() in IGNORE_NAMES:
            continue
        ext = p.suffix.lower()
        if ext == ".pdg" or ext in IMAGE_EXTS:
            pages.append(p)
    pages.sort(key=lambda p: natural_sort_key(p.relative_to(root).as_posix()))
    return pages


def normalize_extracted_folder(root: Path) -> Path:
    """如果解压出来套了一层只有一个子目录的壳，剥掉它（最多剥 5 层）。"""
    for _ in range(5):
        entries = [e for e in root.iterdir() if e.name.lower() not in IGNORE_NAMES]
        if len(entries) == 1 and entries[0].is_dir():
            root = entries[0]
            continue
        break
    return root

# ---------- ZIP 解压（含密码尝试） ----------
def _fix_zip_name(name: str) -> str:
    """修复 ZIP 中文文件名乱码（CP437 -> GB18030）。"""
    try:
        if name and all(ord(ch) < 0x8000 for ch in name):
            raw = name.encode("cp437")
            try:
                return raw.decode("gb18030")
            except UnicodeDecodeError:
                return raw.decode("utf-8", errors="replace")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return name


def _zip_extract_all(zf: zipfile.ZipFile, dest: Path, pwd: Optional[bytes]) -> None:
    for member in zf.infolist():
        member.filename = _fix_zip_name(member.filename)
        zf.extract(member, dest, pwd=pwd)


def extract_zip(archive: Path, dest: Path, pwds: Sequence[str]) -> Optional[str]:
    """解压 ZIP / CBZ / UVZ，自动尝试密码。返回正确密码（无密码返回 '-'）。"""
    with pyzipper.AESZipFile(archive) as zf:
        infolist = zf.infolist()
        if not infolist:
            return "-"

        encrypted = any(info.flag_bits & 0x1 for info in infolist)
        if not encrypted:
            _zip_extract_all(zf, dest, None)
            return "-"

        test_members = [m for m in infolist if not m.is_dir() and m.file_size > 0]
        if not test_members:
            test_members = [m for m in infolist if not m.is_dir()]

        for pwd in pwds:
            for enc in ("utf-8", "gb18030"):
                try:
                    pwd_b = pwd.encode(enc)
                    for m in test_members[:3]:
                        zf.read(m, pwd=pwd_b)
                    _zip_extract_all(zf, dest, pwd_b)
                    return pwd
                except (RuntimeError, NotImplementedError, zipfile.BadZipFile,
                        UnicodeEncodeError, EOFError):
                    continue
                except Exception:  # noqa: BLE001
                    continue
        raise RuntimeError("ZIP 密码尝试全部失败，请补充密码表或手动解压")


# ---------- RAR 解压（含密码尝试） ----------
def _find_rar_tool() -> Tuple[str, bool]:
    """
    返回 (tool_path, is_unrar)。优先用 UnRAR.exe（可处理 RAR5），
    其次 7z.exe。两者都支持通过命令行传密码。
    """
    candidates: List[Path] = []
    for d in _candidate_dirs():
        candidates.append(d / "7-Zip" / "UnRAR.exe")
        candidates.append(d / "7-Zip" / "7z.exe")
        candidates.append(d / "UnRAR.exe")
        candidates.append(d / "7z.exe")
    for cand in candidates:
        if cand.exists():
            return str(cand), cand.name.lower() == "unrar.exe"
    from shutil import which
    for name in ("UnRAR.exe", "unrar", "7z.exe", "7z"):
        p = which(name)
        if p:
            return p, Path(p).name.lower().startswith("unrar")
    raise RuntimeError("未找到 UnRAR.exe 或 7z.exe，无法处理 RAR 压缩包")


def _run_extract(tool: str, is_unrar: bool, archive: Path, dest: Path,
                 pwd: Optional[str]) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    if is_unrar:
        cmd = [tool, "x", str(archive), f"-o{dest}\\", "-y", "-inul"]
        if pwd:
            cmd.append(f"-p{pwd}")
        else:
            cmd.append("-p-")
    else:
        cmd = [tool, "x", str(archive), f"-o{dest}", "-y"]
        if pwd:
            cmd.append(f"-p{pwd}")
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode


def extract_rar(archive: Path, dest: Path, pwds: Sequence[str]) -> Optional[str]:
    if rarfile is not None:
        try:
            with rarfile.RarFile(archive) as rf:
                if not rf.needs_password():
                    rf.extractall(dest)
                    return "-"
        except Exception:
            pass  # 回退到命令行工具

    tool, is_unrar = _find_rar_tool()

    # 先试空密码 / 无密码
    if _run_extract(tool, is_unrar, archive, dest, None) == 0:
        return "-"

    # 清空目标目录再开始试密码（避免残留）
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    for pwd in pwds:
        rc = _run_extract(tool, is_unrar, archive, dest, pwd)
        if rc == 0:
            return pwd
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
    raise RuntimeError("RAR 密码尝试全部失败，请补充密码表或手动解压")

# ---------- 组装 PDF ----------
def _normalise_for_pdf(raw: bytes, fmt: str) -> bytes:
    """把 img2pdf 处理不了的图片转成标准 RGB JPEG。"""
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=92)
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"图片解码失败: {e}") from e


def build_pdf(images: Sequence[Tuple[Path, bytes, str]], output_pdf: Path) -> int:
    """
    images: [(源路径, 图片字节, 扩展名)]
    返回成功写入的页数。
    """
    if not images:
        raise ValueError("没有可合并的页面")

    # 优先用 img2pdf（JPEG 直接无损嵌入）
    if img2pdf is not None:
        payloads: List[bytes] = []
        for _src, raw, fmt in images:
            try:
                if fmt.lower() in ("jpg", "jpeg"):
                    img2pdf.parse_jpeg(raw)  # 校验
                    payloads.append(raw)
                else:
                    payloads.append(_normalise_for_pdf(raw, fmt))
            except Exception:  # noqa: BLE001
                try:
                    payloads.append(_normalise_for_pdf(raw, fmt))
                except Exception:
                    continue
        if payloads:
            try:
                output_pdf.write_bytes(img2pdf.convert(*payloads))
                return len(payloads)
            except Exception as e:  # noqa: BLE001
                warn(f"img2pdf 直接转换失败，回退到 Pillow: {e}")

    # Pillow 回退
    pil_images: List[Image.Image] = []
    for _src, raw, fmt in images:
        try:
            im = Image.open(io.BytesIO(raw))
            im.load()
            if im.mode == "RGBA":
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            pil_images.append(im)
        except Exception:  # noqa: BLE001
            continue
    if not pil_images:
        raise ValueError("所有页面都无法被 Pillow 解码")
    first, rest = pil_images[0], pil_images[1:]
    first.save(output_pdf, "PDF", save_all=True, append_images=rest, resolution=150.0)
    return len(pil_images)


# ---------- 单个输入的完整转换 ----------
def convert_one(source: Path, work_root: Path, pwds: Sequence[str],
                keep_extracted: bool = False) -> ConvertResult:
    result = ConvertResult(source=source)
    extracted_dir: Optional[Path] = None
    created_temp = False
    try:
        if source.is_file() and source.suffix.lower() in ARCHIVE_EXTS:
            extracted_dir = work_root / source.stem
            if extracted_dir.exists():
                shutil.rmtree(extracted_dir, ignore_errors=True)
            extracted_dir.mkdir(parents=True, exist_ok=True)
            created_temp = True
            suffix = source.suffix.lower()
            info(f"[*] 正在解压 {source.name} ...")
            if suffix == ".rar":
                result.password = extract_rar(source, extracted_dir, pwds)
            else:
                result.password = extract_zip(source, extracted_dir, pwds)
            page_root = normalize_extracted_folder(extracted_dir)
        elif source.is_dir():
            page_root = Path(source)
        else:
            result.note = "不是支持的压缩包或目录"
            return result

        pages = gather_pages(page_root)
        if not pages:
            result.note = f"目录里没有找到 .pdg 或图片文件: {page_root}"
            return result
        info(f"[*] 共找到 {len(pages)} 个页面，正在识别格式 ...")

        prepared: List[Tuple[Path, bytes, str]] = []
        for p in pages:
            try:
                raw = p.read_bytes()
                if len(raw) < 8:
                    result.pages_skipped.append((p.name, "文件过小"))
                    continue
                if p.suffix.lower() in IMAGE_EXTS:
                    fmt = detect_image_format(raw) or p.suffix.lower().lstrip(".")
                    prepared.append((p, raw, fmt))
                else:
                    data, fmt = extract_page_data(raw)
                    prepared.append((p, data, fmt))
            except Exception as e:  # noqa: BLE001
                result.pages_skipped.append((p.name, str(e)))

        if not prepared:
            result.note = "没有任何页面能被识别为图片"
            return result

        output_pdf = source.with_suffix(".pdf") if source.is_file() \
            else source.with_name(source.rstrip("\\/").split("\\")[-1] + ".pdf")
        # 上面 source 是目录时更稳的写法：
        if source.is_dir():
            output_pdf = source.parent / (source.name + ".pdf")

        n = 0
        if output_pdf.exists():
            i = 1
            stem = output_pdf.stem
            while True:
                candidate = output_pdf.with_name(f"{stem}_{i}.pdf")
                if not candidate.exists():
                    output_pdf = candidate
                    break
                i += 1

        n = build_pdf(prepared, output_pdf)
        result.output = output_pdf
        result.pages_ok = n
        if result.pages_skipped:
            result.note = f"成功 {n} 页，跳过 {len(result.pages_skipped)} 页"
        return result
    finally:
        if created_temp and extracted_dir and extracted_dir.exists() and not keep_extracted:
            shutil.rmtree(extracted_dir, ignore_errors=True)


# ---------- 入口 ----------
def _collect_inputs(paths: Sequence[str]) -> List[Path]:
    items: List[Path] = []
    for raw in paths:
        p = Path(raw.strip().strip('"')).expanduser()
        if p.is_dir():
            for child in sorted(p.iterdir()):
                if child.suffix.lower() in ARCHIVE_EXTS:
                    items.append(child)
        elif p.exists():
            items.append(p)
        else:
            err(f"[!] 路径不存在: {p}")
    return items


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="把 PDG 书页压缩包（ZIP/RAR/CBZ/UVZ）或已解压目录合并为 PDF")
    parser.add_argument("inputs", nargs="*", help="压缩包或目录（可多个，可拖入）")
    parser.add_argument("-p", "--passwords", default=None,
                        help="密码表文件（默认自动在脚本同级及 passwords/ 下查找 passwords.txt）")
    parser.add_argument("--keep", action="store_true",
                        help="保留解压出来的临时目录（调试用）")
    parser.add_argument("--workdir", default=None,
                        help="临时解压目录（默认系统临时目录）")
    args = parser.parse_args(argv)

    if os.name == "nt":
        try:
            import colorama  # type: ignore
            colorama.just_fix_windows_console()
        except Exception:
            pass

    raw_inputs = list(args.inputs)
    if not raw_inputs:
        print(c("zip2pdf_pure - 把 PDG 书页压缩包合并成 PDF", "1;36"))
        print("直接把 ZIP/RAR/CBZ/UVZ 或目录拖进来，回车确认；多个路径用空格或回车分隔。")
        print("输入 q 退出。")
        while True:
            try:
                line = input(c("> ", "1;33")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            if line.lower() in ("q", "quit", "exit"):
                return 0
            raw_inputs.append(line)
            break

    items = _collect_inputs(raw_inputs)
    if not items:
        err("没有可用的输入文件。")
        return 2

    pwd_file = find_password_file(args.passwords)
    if pwd_file is not None:
        pwds = load_passwords(pwd_file)
        info(f"[*] 已加载密码表 {pwd_file}（{len(pwds)} 条）")
    else:
        if args.passwords:
            warn(f"[!] 指定的密码表不存在: {args.passwords}，加密包将只能尝试空密码")
        else:
            warn("[!] 未找到密码表 (passwords/passwords.txt)，加密包将只能尝试空密码")
        pwds = []

    import tempfile
    work_root = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="zip2pdf_"))
    work_root.mkdir(parents=True, exist_ok=True)

    rc = 0
    try:
        for src in items:
            try:
                r = convert_one(src, work_root, pwds, keep_extracted=args.keep)
                print(r.summary())
                if not r.output:
                    rc = 1
            except Exception as e:  # noqa: BLE001
                err(f"[失败] {src}: {e}")
                rc = 1
    finally:
        if not args.keep and not args.workdir:
            shutil.rmtree(work_root, ignore_errors=True)

    if not args.inputs and sys.stdout.isatty():
        try:
            input("按回车退出 ...")
        except EOFError:
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
