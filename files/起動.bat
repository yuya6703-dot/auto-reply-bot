@echo off
cd /d "%~dp0"
title 自動送信ボット

rem --- Python を探す ---
set "PYEXE="
set "PYWEXE="
where py >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=py -3"
    set "PYWEXE=pyw -3"
) else (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PYEXE=python"
        set "PYWEXE=pythonw"
    )
)
if not defined PYEXE (
    echo Python が見つかりませんでした。
    echo https://www.python.org/downloads/windows/ からインストールしてください。
    echo ※インストール時に "Add python.exe to PATH" にチェックを入れてください。
    pause
    exit /b 1
)

rem --- 初回のみ依存パッケージを導入 ---
if not exist ".deps_installed" (
    echo 初回起動のため、必要なパッケージをインストールします。しばらくお待ちください...
    %PYEXE% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo パッケージのインストールに失敗しました。
        pause
        exit /b 1
    )
    echo ok> ".deps_installed"
)

rem --- アプリ起動（コンソールは閉じて GUI だけ残す）---
start "" %PYWEXE% auto_reply_app.py
exit /b 0
