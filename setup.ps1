# ADIF setup - Windows PowerShell. Run from the repository root:
#     .\setup.ps1
#
# If this is blocked by execution policy, use setup.cmd instead - batch files
# are not subject to the signing rule.
#
# NOTE: this file must keep CRLF line endings. PowerShell 5.1 mis-parses
# multi-line constructs in LF-only files.

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "ADIF setup" -ForegroundColor Cyan
Write-Host ("=" * 60)

if (-not (Test-Path "requirements.txt")) {
    Write-Host ""
    Write-Host "ERROR: run this from the repository root." -ForegroundColor Red
    Write-Host "You should see README.md, requirements.txt and src\ in this folder."
    Write-Host "Current folder: $(Get-Location)"
    exit 1
}

$python = $null
foreach ($v in @("3.12", "3.11")) {
    & py -$v --version 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $python = "py -$v"; break }
}

if (-not $python) {
    Write-Host ""
    Write-Host "ERROR: neither Python 3.12 nor 3.11 was found." -ForegroundColor Red
    Write-Host "Installed versions:"
    py --list
    Write-Host ""
    Write-Host "Install one with:  winget install Python.Python.3.12"
    Write-Host "Then close and reopen PowerShell so PATH refreshes."
    exit 1
}

Write-Host ""
Write-Host "Using $python" -ForegroundColor Green

if (Test-Path ".venv") {
    Write-Host "Virtual environment already exists - reusing it."
} else {
    Write-Host "Creating virtual environment..."
    Invoke-Expression "$python -m venv .venv"
}

Write-Host "Installing dependencies (this takes a minute)..."
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet

Write-Host ""
Write-Host "Running tests..." -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" -m pytest -q

Write-Host ""
Write-Host ("=" * 60)
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Activate the environment in this shell:"
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Then try:"
Write-Host "    python -m scripts.check_environment"
Write-Host "    python -m scripts.demo"
Write-Host "    uvicorn src.api.main:app --reload"
Write-Host "        then open http://127.0.0.1:8000/review"
Write-Host ""
Write-Host "If activation is blocked, run once:"
Write-Host "    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned"
Write-Host ""
