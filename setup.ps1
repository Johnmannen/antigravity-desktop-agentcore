# Setup script for Antigravity Desktop AgentCore (Windows PowerShell)
param(
    [switch]$WithVoice
)

$ErrorActionPreference = "Stop"
Write-Host "=== Antigravity Desktop AgentCore Setup ===" -ForegroundColor Cyan

if (-not (Test-Path ".venv")) {
    Write-Host "[1/5] Creating Python virtual environment (.venv)..."
    python -m venv .venv
}

$py = ".\.venv\Scripts\python.exe"
$pip = ".\.venv\Scripts\pip.exe"

Write-Host "[2/5] Installing core Python dependencies..."
& $pip install --upgrade pip
& $pip install -r requirements.txt

if ($WithVoice -and (Test-Path "requirements-voice.txt")) {
    Write-Host "[2b/5] Installing optional voice proxy dependencies..."
    & $pip install -r requirements-voice.txt
}

Write-Host "[3/5] Installing Playwright Chromium browser..."
& $py -m playwright install chromium

Write-Host "[4/5] Initializing .env and memory templates..."
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "  Created .env from .env.example (fill in your API keys)."
}
if (-not (Test-Path "memory\profile.json") -and (Test-Path "memory\profile.example.json")) {
    Copy-Item "memory\profile.example.json" "memory\profile.json"
}
if (-not (Test-Path "memory\projects.json") -and (Test-Path "memory\projects.example.json")) {
    Copy-Item "memory\projects.example.json" "memory\projects.json"
}
if (-not (Test-Path "AGENTS.md") -and (Test-Path "AGENTS.template.md")) {
    Copy-Item "AGENTS.template.md" "AGENTS.md"
}

Write-Host "[5/5] Verifying system health..."
& $py tools/system_health.py

Write-Host "Setup complete! Next: connect Google Antigravity Desktop (Remote Control) and Chrome DevTools MCP." -ForegroundColor Green
