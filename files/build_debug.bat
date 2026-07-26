@echo off
echo ============================================
echo  Debug Build (console window will be shown)
echo ============================================
echo.
echo This build shows a console window so that any
echo error messages are visible when you run the exe.
echo Once the problem is fixed, use the normal release
echo build process (GitHub Actions) for the real build.
echo.

pip install pyinstaller

pyinstaller --noconfirm --onefile ^
  --name "auto_reply_app_debug" ^
  --collect-all customtkinter ^
  --collect-all adbutils ^
  --collect-all uiautomator2 ^
  --collect-all pyautogui ^
  --collect-all pygetwindow ^
  --collect-all PIL ^
  --hidden-import "PIL._tkinter_finder" ^
  auto_reply_app.py

echo.
echo ============================================
echo  Done: dist\auto_reply_app_debug.exe
echo ============================================
echo.
echo Please run dist\auto_reply_app_debug.exe and
echo check the error message shown in the console.
echo.
pause
