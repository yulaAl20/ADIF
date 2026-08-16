@echo off
REM ADIF setup - Windows. Run from the repository root:  setup.cmd
REM Batch rather than PowerShell on purpose: .cmd files are not subject to
REM the execution-policy signing rule that blocks downloaded .ps1 scripts.

setlocal
echo.
echo ADIF setup
echo ============================================================

if not exist requirements.txt (
    echo ERROR: run this from the repository root.
    echo You should see README.md, requirements.txt and src\ in this folder.
    echo Current folder: %CD%
    exit /b 1
)

set PYEXE=
for %%V in (3.12 3.11) do (
    if not defined PYEXE (
        py -%%V --version >nul 2>&1 && set PYEXE=py -%%V
    )
)

if not defined PYEXE (
    echo ERROR: neither Python 3.12 nor 3.11 was found.
    echo Installed versions:
    py --list
    echo.
    echo Install one with:  winget install Python.Python.3.12
    echo Then close and reopen this window so PATH refreshes.
    exit /b 1
)

echo.
echo Using %PYEXE%

if exist .venv (
    echo Virtual environment already exists - reusing it.
) else (
    echo Creating virtual environment...
    %PYEXE% -m venv .venv || exit /b 1
)

echo Installing dependencies ^(this takes a minute^)...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet || exit /b 1

echo.
echo Running tests...
.venv\Scripts\python.exe -m pytest -q
if errorlevel 1 (
    echo.
    echo Tests failed. Send the output above.
    exit /b 1
)

echo.
echo ============================================================
echo Setup complete.
echo.
echo Activate the environment in this window:
echo     .venv\Scripts\activate.bat
echo.
echo Then try:
echo     python -m scripts.check_environment
echo     python -m scripts.demo
echo     uvicorn src.api.main:app --reload
echo         then open http://127.0.0.1:8000/review
echo.
endlocal
