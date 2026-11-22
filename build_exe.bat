@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Weather Tray - збірка exe

set PY=py
where py >nul 2>nul || set PY=python
where %PY% >nul 2>nul
if errorlevel 1 (
    echo Python не знайдено. Встанови Python 3 з python.org ^(з галочкою Add to PATH^).
    pause
    exit /b 1
)

echo Закриваю запущену програму ^(якщо вона працює^)...
taskkill /f /im WeatherTray.exe >nul 2>nul

echo.
echo Встановлюю PyInstaller...
%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 goto fail

echo.
echo Збираю exe...
if not exist "%~dp0WeatherTray.ico" goto noicon
echo Іконка: WeatherTray.ico знайдена, додаю в exe.
%PY% -m PyInstaller --noconfirm --clean --onefile --noconsole --name WeatherTray --version-file version_info.txt --icon "%~dp0WeatherTray.ico" --add-data "%~dp0WeatherTray.ico;." weather_tray.py
goto built
:noicon
echo УВАГА: файл WeatherTray.ico не знайдено поруч з build_exe.bat - збираю БЕЗ іконки!
%PY% -m PyInstaller --noconfirm --clean --onefile --noconsole --name WeatherTray --version-file version_info.txt weather_tray.py
:built
if errorlevel 1 goto fail

copy /y "dist\WeatherTray.exe" "WeatherTray.exe" >nul
if errorlevel 1 goto fail
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del /q WeatherTray.spec 2>nul

echo.
echo Оновлюю кеш іконок Windows...
ie4uinit.exe -ClearIconCache >nul 2>nul
ie4uinit.exe -show >nul 2>nul

echo.
echo Готово: WeatherTray.exe лежить поруч з цим файлом. Запусти його.
pause
exit /b 0

:fail
echo.
echo Помилка збірки. Прокрути вікно вгору й подивись повідомлення.
pause
exit /b 1
