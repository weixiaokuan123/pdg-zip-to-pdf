# pdg-zip-to-pdf

把内含 PDG 格式书页（读秀 / 超星电子书）的 **ZIP / RAR / CBZ / UVZ** 压缩包，或已经解压的 PDG 目录，批量合并成一个正常 PDF。

- 加密压缩包自动用密码表逐个尝试（ZipCrypto + AES-128/256；RAR 调用 7z/UnRAR）
- 自动剥掉 PDG 封装头，识别内部的 JPG/PNG/BMP/GIF/TIFF/WEBP
- 自动修复 ZIP 中文文件名乱码（CP437 → GB18030）
- 按封面 → 前言 → 目录 → 正文 → 附录 → 封底的物理顺序自然排序
- JPEG 用 img2pdf 无损嵌入，其它格式 Pillow 回退
- 纯 Python，不调用 Pdg2Pic、不抢鼠标键盘，可无人值守批量跑

## 这是什么

读秀 / 超星等平台下载的电子书压缩包打开后通常是上百个名字像 `!00001.pdg`、`000002.pdg`、`bok001.pdg` 的文件。原版 [`Davy-Zhou/zip2pdf`](https://github.com/Davy-Zhou/zip2pdf) 通过 pywinauto 模拟键鼠驱动 Pdg2Pic.exe 来转换，使用时会霸占鼠标键盘、靠 `sleep` 猜转换时长、无法批量。

本工具改用纯 Python 直接解析 PDG 并合成 PDF，解决了上述问题。

## PDG 是什么

PDG 不是一种图片格式，它最常见的封装是：

```
[4 字节小端数据长度][1 字节类型码][真实图片数据 ...]
```

后面的真实图片数据绝大多数就是标准 JPEG / PNG / BMP / GIF / TIFF / WEBP。脚本用三级策略识别：直接看魔数 → 剥 5 字节头后看魔数 → 在文件内暴力扫描常见图片魔数。类型码 `0x1B/0x1C/0x1D/0x28/0x29/0x2A` 是文本 / 目录型 PDG，不是位图，会被跳过并在报告里列出。

## 安装

需要 Python 3.8+。

```bash
pip install -r scripts/requirements.txt
```

依赖：`pyzipper`（AES ZIP）、`img2pdf`（JPEG 无损嵌入）、`Pillow`（其它格式回退）、`rarfile`（可选）。

处理 RAR 还需要外部命令行工具（任选其一，脚本会自动找）：

- 把 `7z.exe` 或 `UnRAR.exe` 放到脚本同级的 `7-Zip/` 目录
- 或把 7-Zip / WinRAR 加入系统 PATH

## 用法

```bash
# 单个文件
python scripts/zip2pdf_pure.py "书.zip"

# 批量
python scripts/zip2pdf_pure.py book1.zip book2.rar book3.cbz "D:\books\dir"

# 自定义密码表
python scripts/zip2pdf_pure.py -p my_passwords.txt book.zip

# 不带参数进入交互模式（可粘贴路径，多个用空格分隔）
python scripts/zip2pdf_pure.py
```

Windows 用户可以直接把压缩包/文件夹拖到 `scripts/zip2pdf_pure.bat` 上；首次运行会自动安装依赖。

PDF 输出到**压缩包同目录、同名 .pdf**；若文件已存在会自动加 `_1`、`_2` 后缀，不覆盖。

### 作为 opencode skill 使用

整个仓库本身就是一个 opencode skill。把它 clone 或软链到 opencode 的 skills 目录即可：

```powershell
git clone https://github.com/<you>/pdg-zip-to-pdf.git "$env:USERPROFILE\.config\opencode\skills\pdg-zip-to-pdf"
```

之后说"把这个 PDG 压缩包转成 PDF"之类的话，opencode 会自动加载 `SKILL.md` 并调用脚本。

## 密码表

仓库自带了一份在中文电子书圈流传的常用密码表（约 4.9 万条，`scripts/passwords/passwords.txt`），用于尝试读秀 / 超星常见分享密码。想自己加密码直接追加即可，每行一个；脚本会依次用 UTF-8 和 GB18030 编码尝试，兼容中文密码。

如果你的压缩包密码不在表里，用 `-p your_passwords.txt` 指定自己的密码表。

## 常见问题

**`Module use of python38.dll conflicts with this version of Python`**

当前工作目录里混入了旧版 Python 的 DLL（典型场景：在原 PyInstaller 打包版 zip2pdf 目录里直接跑脚本）。`cd` 到别的干净目录，用绝对路径调用脚本即可。脚本目录本身放哪里都行。

**所有页面都是"文本型 PDG"被跳过**

这是老式纯文本 PDG（多见于 2000 年以前的书），里面是文字流而不是扫描图。本工具不支持渲染这种格式，请用原作者的 GUI 版 zip2pdf（Pdg2Pic.exe）处理。

**RAR 提示"未找到 UnRAR.exe 或 7z.exe"**

安装 7-Zip 并加入 PATH，或者把 `UnRAR.exe` / `7z.exe` 放到脚本同级的 `7-Zip/` 目录。

## 许可证

本仓库代码以 MIT 许可证发布。`scripts/passwords/passwords.txt` 来源于互联网公开收集的常用密码表，版权归原作者；`7-Zip/` 目录里的二进制不随仓库分发，请自行从 [7-zip.org](https://www.7-zip.org/) 或 [rarlab.com](https://www.rarlab.com/) 获取。

## 致谢

- 原工具作者 [@Davy-Zhou](https://github.com/Davy-Zhou/zip2pdf) 提供了最初的解压 + Pdg2Pic 自动化思路与密码表
- 读秀 / 超星 PDG 封装格式由社区前辈逆向整理
