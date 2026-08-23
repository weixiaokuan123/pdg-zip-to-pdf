# zip2pdf_pure.ps1 - PDG 压缩包转 PDF 的便捷启动器
# 用法：
#   1) 把压缩包/目录拖到此 .ps1 上
#   2) 命令行：powershell -ExecutionPolicy Bypass -File zip2pdf_pure.ps1 book.zip book2.rar

param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Inputs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyScript = Join-Path $ScriptDir "zip2pdf_pure.py"

# 选择一个不与任何 PyInstaller 残留 DLL 冲突的工作目录
$WorkDir = $env:TEMP
Set-Location $WorkDir

function Test-Python($exe) {
    try {
        $v = & $exe -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return $true }
    } catch {}
    return $false
}

function Test-Deps($exe) {
    & $exe -c "import pyzipper, img2pdf, PIL" 2>$null
    return $LASTEXITCODE -eq 0
}

# 找一个可用的 Python
$Python = $null
foreach ($cand in @("python", "python3", "py")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) {
        if (Test-Python $cmd.Source) { $Python = $cmd.Source; break }
    }
}
if (-not $Python) {
    Write-Host "[错误] 未找到 Python，请先安装 Python 3.8+" -ForegroundColor Red
    Read-Host "按回车退出"; exit 1
}

# 检查依赖；缺了就尝试装到用户目录
if (-not (Test-Deps $Python)) {
    Write-Host "[*] 首次运行，正在安装依赖（pyzipper/img2pdf/Pillow/rarfile）..." -ForegroundColor Yellow
    $req = Join-Path $ScriptDir "requirements.txt"
    try {
        & $Python -m pip install --user -r $req
    } catch {
        Write-Host "[!] pip 安装失败，尝试创建临时 venv..." -ForegroundColor Yellow
        $VenvDir = Join-Path $env:TEMP "zip2pdf-venv"
        if (-not (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
            & $Python -m venv $VenvDir
        }
        $Python = Join-Path $VenvDir "Scripts\python.exe"
        & $Python -m pip install -r $req
    }
}

if (-not $Inputs -or $Inputs.Count -eq 0) {
    Write-Host "请输入压缩包/目录路径（多个用空格分隔，可拖拽），直接回车退出：" -ForegroundColor Cyan
    $line = Read-Host
    if ($line) { $Inputs = $line -split '\s+(?=(?:[^"]*"[^"]*")*[^"]*$)' | ForEach-Object { $_.Trim('"') } }
}

if (-not $Inputs -or $Inputs.Count -eq 0) { exit 0 }

Write-Host "[*] 工作目录: $WorkDir" -ForegroundColor Green
& $Python $PyScript @Inputs
$code = $LASTEXITCODE

Write-Host ""
if ($code -eq 0) {
    Write-Host "[完成] 全部转换结束" -ForegroundColor Green
} else {
    Write-Host "[结束] 有任务失败，退出码 $code" -ForegroundColor Yellow
}
Read-Host "按回车退出"
exit $code
