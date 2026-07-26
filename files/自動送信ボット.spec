# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['PIL._tkinter_finder']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('adbutils')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('uiautomator2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyautogui')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pygetwindow')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# このアプリが使わない重量級ライブラリを明示的に除外する。
# PyInstallerは環境にインストールされているパッケージを import解析で拾ってしまうため、
# 開発PCに別プロジェクト用の easyocr / torch などが入っていると巻き込まれ、
# 成果物が 838MB まで膨らんでいた（うち約410MBがこれらの不要ライブラリ）。
# 配布zipのサイズは自動更新のダウンロード時間に直結するので除外しておく。
#
# 補足: このアプリが pyautogui から使うのは size() だけで、
# numpy/cv2 を使う画像認識機能(locateOnScreen等)は使っていない。
# pyscreeze 側の numpy/cv2 の import は try で囲まれているため、除外しても動作する。
excludes = [
    'torch', 'torchvision', 'scipy', 'pandas', 'matplotlib', 'numpy',
    'easyocr', 'skimage', 'sklearn', 'cv2', 'altair',
    'IPython', 'notebook', 'jupyter', 'pytest',
]


a = Analysis(
    ['auto_reply_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='自動送信ボット',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='自動送信ボット',
)
