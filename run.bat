@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Виртуальное окружение не найдено.
    echo Сначала выполните шаги из README.md — раздел "Первый запуск".
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m src.main %*
