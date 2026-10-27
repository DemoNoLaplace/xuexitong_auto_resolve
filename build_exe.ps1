$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venv = Join-Path $PSScriptRoot ".venv-build"
if (-not (Test-Path $venv)) {
    python -m venv $venv
}
. "$venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

python -m PyInstaller `
    --noconfirm --clean --onefile `
    --name chaoxing-flow `
    --paths . `
    --collect-all uiautomation `
    --collect-all comtypes `
    --collect-all pymupdf `
    --add-data "chaoxing_flow\font_ref.npz;chaoxing_flow" `
    --hidden-import lxml.etree `
    --exclude-module onnxruntime `
    --exclude-module cv2 `
    --exclude-module pandas `
    --exclude-module matplotlib `
    --exclude-module langchain `
    --exclude-module pydantic `
    --exclude-module IPython `
    launcher.py

if (-not (Test-Path "dist")) {
    New-Item -ItemType Directory dist | Out-Null
}
if (Test-Path "dist\answer_banks") {
    Remove-Item -Recurse -Force "dist\answer_banks"
}
Copy-Item -Recurse -Force answer_banks dist\answer_banks
Copy-Item -Force README.md dist\README.md
Copy-Item -Force config.example.env dist\config.example.env
Copy-Item -Force docs\使用说明.md dist\使用说明.md

Write-Host ""
Write-Host "生成完成: $PSScriptRoot\dist\chaoxing-flow.exe"
Write-Host "发布前请确认 dist 目录中没有 .env 文件。"
