@echo off
title COMPLY-MA - Facturation electronique DGI
setlocal EnableDelayedExpansion

rem ============================================================
rem  COMPLY-MA - Lanceur Windows
rem  Double-cliquez sur ce fichier pour demarrer le systeme.
rem ============================================================

set "APP_DIR=%~dp0"
set "HOST=127.0.0.1"
set "PORT=8000"
set "VENV_PY=%APP_DIR%.venv\Scripts\python.exe"

cd /d "%APP_DIR%"

echo.
echo  ============================================================
rem    COMPLY-MA - Facturation electronique conforme DGI Maroc
echo  ============================================================
echo.

rem ── 1. Python : venv d'abord, sinon installation automatique ─
if exist "%VENV_PY%" (
    set "PYTHON=%VENV_PY%"
    echo  [OK] Environnement virtuel trouve
) else (
    echo  [..] Environnement virtuel absent - installation...

    set "PYINSTALLER="
    where py >nul 2>nul && set "PYINSTALLER=py"
    if not defined PYINSTALLER (
        where python >nul 2>nul && set "PYINSTALLER=python"
    )
    if not defined PYINSTALLER (
        echo  [ERREUR] Python introuvable sur cette machine.
        echo           Installez Python 3.12 depuis https://www.python.org/downloads/
        echo           puis relancez ce fichier.
        pause
        exit /b 1
    )

    !PYINSTALLER! -m venv "%APP_DIR%.venv"
    if errorlevel 1 (
        echo  [ERREUR] Echec de creation du venv.
        pause
        exit /b 1
    )
    set "PYTHON=%VENV_PY%"

    echo  [..] Installation des dependances - 2 a 3 minutes...
    "%PYTHON%" -m pip install --quiet --upgrade pip
    "%PYTHON%" -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo  [ERREUR] Echec d'installation des dependances.
        pause
        exit /b 1
    )
    echo  [OK] Dependances installees
)

rem ── 2. Base de donnees : seed auto si absente ────────────────
if not exist "comply-ma.db" (
    echo  [..] Premiere execution - creation des donnees demo...
    set PYTHONIOENCODING=utf-8
    "%PYTHON%" seed_investor_demo.py
    if errorlevel 1 (
        echo  [WARN] Seed investor echoue - essai seed standard...
        "%PYTHON%" seed_demo.py
    )
    echo  [OK] Donnees pretes
)

rem ── 3. Liberation du port si une ancienne instance tourne ────
curl -s -m 2 http://%HOST%:%PORT%/health >nul 2>nul
if not errorlevel 1 (
    echo  [WARN] Un serveur tourne deja sur le port %PORT%.
    echo         Ouvrez http://%HOST%:%PORT% dans votre navigateur,
    echo         ou fermez l'ancienne instance puis relancez.
    pause
    start "" "http://%HOST%:%PORT%"
    exit /b 0
)

rem ── 4. Demarrage ─────────────────────────────────────────────
echo.
echo  ------------------------------------------------------------
echo   COMPLY-MA demarre...
echo   URL    : http://%HOST%:%PORT%
echo   Login  : owner / password
echo   Arret  : fermez cette fenetre ou Ctrl+C
echo  ------------------------------------------------------------
echo.

start "" "http://%HOST%:%PORT%"   rem ouvre le navigateur apres le boot

"%PYTHON%" -m uvicorn app.main:app --host %HOST% --port %PORT%

echo.
echo  Serveur arrete.
pause
