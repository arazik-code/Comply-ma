@echo off
title COMPLY-MA - Reset Demo Investisseurs + Demarrage
setlocal EnableDelayedExpansion

rem ============================================================
rem  COMPLY-MA - DEMO INVESTISSEURS
rem  Reinitialise la base avec les donnees de demo "propres"
rem  puis demarre le systeme. Ideal avant chaque enregistrement.
rem ============================================================

set "APP_DIR=%~dp0"
set "HOST=127.0.0.1"
set "PORT=8000"
set "VENV_PY=%APP_DIR%.venv\Scripts\python.exe"

cd /d "%APP_DIR%"
set PYTHONIOENCODING=utf-8

echo.
echo  ============================================================
echo    COMPLY-MA - REINITIALISATION DEMO INVESTISSEURS
echo  ============================================================
echo.

if not exist "%VENV_PY%" (
    echo  [ERREUR] Environnement absent. Lancez start.bat d'abord.
    pause
    exit /b 1
)
set "PYTHON=%VENV_PY%"

rem ── Arreter le serveur existant ──────────────────────────────
curl -s -m 2 http://%HOST%:%PORT%/health >nul 2>nul
if not errorlevel 1 (
    echo  [..] Arret de l'instance en cours...
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
        taskkill /F /PID %%p >nul 2>nul
    )
    timeout /t 2 /nobreak >nul
)

rem ── Reinitialiser la base ────────────────────────────────────
echo  [..] Suppression de l'ancienne base...
if exist "comply-ma.db" del /q "comply-ma.db"

echo  [..] Creation des donnees demo investisseurs...
"%PYTHON%" seed_investor_demo.py
if errorlevel 1 (
    echo  [ERREUR] Echec du seed.
    pause
    exit /b 1
)

echo.
echo  ------------------------------------------------------------
echo   Demo prete - demarrage...
echo   URL    : http://%HOST%:%PORT%
echo   Login  : owner / password
echo  ------------------------------------------------------------
echo.

start "" "http://%HOST%:%PORT%"
"%PYTHON%" -m uvicorn app.main:app --host %HOST% --port %PORT%

pause
