# pdg-zip-to-pdf

把读秀、超星下回来的 PDG 书页压缩包（ZIP / RAR / CBZ / UVZ）或已经解压的目录，合并成一个能正常看的 PDF。

- 压缩包带密码就用密码表挨个试，ZipCrypto 和 AES-128/256 都吃，RAR 走 7z/UnRAR
- 自动剥 PDG 封装头，识别里面藏着的 JPG、PNG、BMP、GIF、TIFF、WEBP
- ZIP 中文文件名乱码会自动修（CP437 → GB18030）
- 按封面、前言、目录、正文、附录、封底的顺序排
- JPEG 用 img2pdf 直接塞进 PDF，不二次压缩；其他格式 Pillow 兜底
- 纯 Python，不调 Pdg2Pic、不抢鼠标键盘，挂着跑一整批都行

## 这是什么

读秀、超星下载的电子书解压开来，通常是一堆 `!00001.pdg`、`000002.pdg`、`bok001.pdg`，上百个。原版 [Davy-Zhou/zip2pdf](https://github.com/Davy-Zhou/zip2pdf) 的办法是用 pywinauto 去点 Pdg2Pic.exe 的 GUI：程序运行时鼠标键盘被它占着，转换时间靠 `sleep` 瞎猜，一次还只能处理一本。

这个版本直接在 Python 里解析 PDG、合成 PDF，上面这些毛病都没了。

## PDG 是什么

PDG 不是图片格式，最常见的封装长这样：

```
[4 字节小端数据长度][1 字节类型码][真实图片数据 ...]
```

后面那段数据绝大多数时候就是标准的 JPEG / PNG / BMP / GIF / TIFF / WEBP。脚本会先直接看文件头魔数，不对再剥掉 5 字节头看，再不行就在文件里暴力扫一遍。类型码 `0x1B/0x1C/0x1D/0x28/0x29/0x2A` 是文本或目录页，不是位图，会跳过并在结果里列出来。

## 安装

Python 3.8+。

```bash
pip install -r scripts/requirements.txt
```

依赖：`pyzipper`（解 AES ZIP）、`img2pdf`（JPEG 无损嵌入）、`Pillow`（其他格式兜底）、`rarfile`（可选）。

RAR 需要外部工具，脚本会自己找：

- 把 `7z.exe` 或 `UnRAR.exe` 放到脚本同级的 `7-Zip/` 目录
- 或者直接装 7-Zip / WinRAR 并加入 PATH

## 用法

```bash
# 一本
python scripts/zip2pdf_pure.py "书.zip"

# 一堆，文件或目录都行
python scripts/zip2pdf_pure.py book1.zip book2.rar book3.cbz "D:\books"

# 用自己的密码表
python scripts/zip2pdf_pure.py -p my_passwords.txt book.zip

# 不带参数进交互模式，路径贴进去就行
python scripts/zip2pdf_pure.py
```

Windows 上可以直接把压缩包或文件夹拖到 `scripts/zip2pdf_pure.bat`，第一次跑会自动装依赖。

PDF 生成在压缩包同目录，同名 `.pdf`。已经有同名文件就自动加 `_1`、`_2`，不覆盖。

### 当 opencode skill 用

仓库本身就是一个 opencode skill，clone 到 skills 目录就行：

```powershell
git clone https://github.com/weixiaokuan123/pdg-zip-to-pdf.git "$env:USERPROFILE\.config\opencode\skills\pdg-zip-to-pdf"
```

之后说"把这个 PDG 压缩包转成 PDF"之类的，opencode 会自己读 `SKILL.md` 调脚本。

## 密码表

`scripts/passwords/passwords.txt` 自带一份中文电子书圈流传的常用密码表，约 4.9 万条。要加密码直接往文件末尾追加，一行一个。脚本会分别用 UTF-8 和 GB18030 编码试，中文密码也能命中。

压缩包密码不在表里，用 `-p your_passwords.txt` 指定自己的表。

## 常见问题

**`Module use of python38.dll conflicts with this version of Python`**

工作目录里混进了旧版 Python 的 DLL。最常见的情况是直接在原版 PyInstaller 打包的 zip2pdf 目录里跑脚本。`cd` 到别的目录再用绝对路径调脚本就行，脚本本身放哪都行。

**所有页面都因为"文本型 PDG"被跳过**

这是 2000 年以前的老式纯文本 PDG，里面是文字流不是扫描图。这种格式这个工具不渲染，请用原作者的 GUI 版 zip2pdf（Pdg2Pic.exe）。

**RAR 提示"未找到 UnRAR.exe 或 7z.exe"**

装 7-Zip 加进 PATH，或者把 `UnRAR.exe` / `7z.exe` 放到脚本同级的 `7-Zip/` 目录。

## 许可证

代码用 MIT。`scripts/passwords/passwords.txt` 来自互联网公开收集，版权归原作者；`7-Zip/` 里的二进制不随仓库分发，需要的话自己去 [7-zip.org](https://www.7-zip.org/) 或 [rarlab.com](https://www.rarlab.com/) 下。

## 致谢

- [@Davy-Zhou](https://github.com/Davy-Zhou/zip2pdf) 的原版工具和解压思路，密码表也是从那来的
- PDG 封装格式来自社区前辈的逆向整理
