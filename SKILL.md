---
name: pdg-zip-to-pdf
description: 把内含 PDG 格式书页（超星/读秀电子书）的 ZIP、RAR、CBZ、UVZ 压缩包，或已解压的 PDG 目录，批量合并成一个正常 PDF。自动处理：1) 加密压缩包用密码表逐个尝试（支持 ZipCrypto 与 AES-128/256）；2) RAR 调用 7-Zip/UnRAR 解压并尝试密码；3) 自动识别 PDG 内部封装的 JPG/PNG/BMP/GIF/TIFF/WEBP 真实图片格式；4) 中文文件名乱码修复；5) 按封面/前言/目录/正文/附录/封底自然排序；6) 多文件批量转换。当用户说"PDG 转 PDF""把这个读秀/超星的 zip 合并成 PDF""pdg2pdf""解压带密码的电子书压缩包转 pdf""cbz/uvz/rar 转 pdf"，或拖来一个内含 .pdg 文件的压缩包/目录时，必须使用本技能。纯 Python 实现，不依赖 Pdg2Pic、不抢占鼠标键盘，可无人值守批量运行。
---

# PDG ZIP → PDF

把读秀/超星等平台下载的、内部是一堆 `.pdg` 文件的压缩包，合并成可以正常阅读的 PDF。

## 核心原理（必须理解，遇到边缘情况靠它判断）

PDG 并不是一种图片格式，它的常见封装是：

```
[4 字节小端无符号整数 = 数据长度][1 字节类型码][真实图片数据 ...]
```

真实图片数据绝大多数就是标准 JPEG / PNG / BMP / GIF / TIFF / WEBP。脚本用三级策略识别：

1. 整个文件直接就是标准图片魔数 → 直接用；
2. 去掉前 5 字节头后是标准图片 → 剥头；
3. 在文件内暴力扫描常见图片魔数（应对多字节奇怪头部）。

类型码 `0x1B/0x1C/0x1D/0x28/0x29/0x2A` 是文本/目录型 PDG，不是位图，会被跳过并在报告中列出。常见整本书全是同一种类型，所以如果全部跳过，往往说明这是老式纯文本 PDG，需要 Pdg2Pic 专门处理——告知用户这一情况即可。

## 何时使用

- 用户发来/指向一个 `.zip/.rar/.cbz/.uvz`，描述为"电子书/书页/扫描书/读秀/超星/PDG"
- 用户要求把解压出来的一堆 `.pdg` 合并成 PDF
- 用户提到压缩包有密码、需要试密码表
- 用户要批量转换一批这类压缩包

不要用于：普通图片文件夹合并成 PDF（虽然也能跑，但用别的更轻量的工具即可）；真正的 PDF 重新排版；DRM 加密的在线电子书。

## 依赖

Python 3.8+。脚本依赖：

```
pyzipper   # AES 加密 ZIP
img2pdf    # JPEG 无损嵌入 PDF
Pillow     # 其他格式转码 / 回退方案
rarfile    # 可选；RAR 主要靠命令行 7z/UnRAR
```

RAR 解压还需要外部命令行工具（任选其一，脚本会自动找）：
- 脚本同级 `7-Zip/UnRAR.exe` 或 `7-Zip/7z.exe`（Windows）
- PATH 中的 `unrar` / `7z`

## 资源文件

技能脚本目录结构：

```
scripts/
├── zip2pdf_pure.py     # 主程序
├── requirements.txt
├── 7-Zip/              # Windows 下自带的 UnRAR.exe + 7z.exe（处理 RAR 用）
└── passwords/
    └── passwords.txt   # 密码表，每行一个；UTF-8/GB18030 自动识别
```

`zip2pdf_pure.py` 会在以下位置自动查找 `7-Zip/` 和 `passwords/passwords.txt`：
脚本所在目录 → 脚本上级目录 → 当前工作目录。用户也可以用 `-p path/to/passwords.txt` 指定。

## 标准工作流程

### 第 1 步：确认 Python 环境和依赖

```powershell
python --version
python -c "import pyzipper, img2pdf, PIL; print('deps ok')"
```

如果缺依赖，在脚本目录执行：

```powershell
python -m pip install -r scripts/requirements.txt
```

如果系统 Python 被 PEP 668 保护（uv 管理的 Python 会报 "externally managed"），用一个临时 venv：

```powershell
python -m venv "$env:TEMP\zip2pdf-venv"
& "$env:TEMP\zip2pdf-venv\Scripts\python.exe" -m pip install -r scripts/requirements.txt
```

之后所有调用都用这个 venv 的 python。

### 第 2 步：运行转换

**重要（Windows）**：不要把工作目录设在 `D:\Software\zip2pdf` 这类残留了 PyInstaller 打包文件（`python38.dll`、`_ctypes.pyd` 等）的目录，会导致现代 Python 报 `Module use of python38.dll conflicts`。脚本放在哪里都行，但**运行时的工作目录要设在别处**（比如压缩包所在目录或临时目录）。

单文件：

```powershell
python <skill>/scripts/zip2pdf_pure.py "C:\path\to\book.zip"
```

批量：

```powershell
python <skill>/scripts/zip2pdf_pure.py "book1.zip" "book2.rar" "book3.cbz" "D:\books\dir"
```

传入一个目录时，会自动收集该目录下所有 zip/rar/cbz/uvz 批量转换。

不带参数会进入交互模式，可粘贴路径。

### 第 3 步：解读输出

成功时输出类似：

```
[*] 已加载密码表 ...\passwords.txt（49614 条）
[*] 正在解压 book.zip ...
[*] 共找到 193 个页面，正在识别格式 ...
[OK] book.zip  ->  book.pdf
     页数: 193
     密码: 52gv          # 仅在加密包找到密码时显示
```

PDF 默认输出到**压缩包同目录、同名 .pdf**。如果已存在会自动加 `_1`、`_2` 后缀，绝不覆盖。

如果有页面被跳过，会列出前 10 条原因。常见原因：
- `文本/目录型 PDG (type=0x..)，非位图`：老式文本页，脚本无法渲染
- `未识别的 PDG 格式`：可能是加密或特殊老格式
- `文件过小` / `图片解码失败`：损坏页

### 第 4 步：报告给用户

简洁报告：输出 PDF 的绝对路径、页数、大小；如果有跳过页，列出来让用户决定是否需要用 Pdg2Pic 补救。不要假装全部成功。

## 命令行选项

| 选项 | 作用 |
|------|------|
| `inputs` | 一个或多个压缩包/目录路径 |
| `-p, --passwords FILE` | 指定密码表（默认自动查找） |
| `--keep` | 保留临时解压目录（调试用） |
| `--workdir DIR` | 指定临时解压目录（默认系统 temp） |

## 常见问题

**Q: 报 `Module use of python38.dll conflicts with this version of Python`**
A: 当前工作目录或 `PYTHONPATH` 里混入了 Python 3.8 的旧 DLL（典型场景：原版 zip2pdf 打包目录）。换一个干净的工作目录运行，或 `cd $env:TEMP` 后用绝对路径调用脚本。

**Q: RAR 报"未找到 UnRAR.exe 或 7z.exe"**
A: 安装 7-Zip 并把它加入 PATH，或把 `UnRAR.exe`/`7z.exe` 放到脚本同级的 `7-Zip/` 目录。

**Q: 所有页面都是"文本型 PDG"被跳过**
A: 这是老式纯文本 PDG（多见于 2000 年以前的书），需要 Pdg2Pic.exe 渲染。告知用户本脚本不支持该格式，建议用原作者的 GUI 版 zip2pdf。

**Q: 密码表不命中**
A: 用户可以编辑 `scripts/passwords/passwords.txt` 追加密码，或用 `-p` 指定自己的密码表。密码会依次以 UTF-8 和 GB18030 编码尝试。

**Q: 想让 PDF 页面顺序不同**
A: 脚本按 封面(fcov/cov) → 书脊(bok) → 勒口(leg) → 前言(pre/bok0) → 序(fow) → 目录(dir/toc) → 凡例(dat) → 正文(数字页) → 附录(att) → 封底(bak) 排序，同类内自然排序。如果源文件命名不符合这套规则，在反馈中说明具体文件名，可调整 `_CATEGORY_ORDER`。

## 不要做的事

- 不要用 pywinauto/Pdg2Pic 自动化 GUI——这正是本脚本要替代的脆弱方案
- 不要在转换完成前删除源压缩包（脚本本身不删源文件，保持安全默认）
- 不要覆盖已存在的 PDF（脚本自动加序号）
- 不要把整本纯文本 PDG 硬转成空白 PDF——明确告知用户格式不支持
