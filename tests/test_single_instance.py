# -*- coding: utf-8 -*-
"""
同じフォルダのアプリを2つ同時に動かさない（2026-10-23 本人「ツールによる音声ルームの挙動がおかしい」）。
実物: 同じ auto_reply_app.py が前の日から動いたまま、もう1つ起動されていて、2つが同じ MuMu を見て判断・入力・送信し、
シートや入力欄を取り合っていた。画面は作らない（main の確かめでは、作ろうとしたら記録する）。
"""
import os
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(os.path.dirname(_HERE), "files")
sys.path.insert(0, FILES)
import auto_reply_app as A  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


print("■ フォルダごとの「起動中」の印")
folder = tempfile.mkdtemp()
check("1つ目は起動できる", A.acquire_single_instance(folder, wait_seconds=0) is True)
t0 = time.monotonic()
check("同じフォルダの2つ目は起動できない（少し待ってからあきらめる）", A.acquire_single_instance(folder, wait_seconds=0.6) is False
      and time.monotonic() - t0 >= 0.5)
check("別のフォルダなら起動できる（リリースの確かめで、配布版を横で起動するため）",
      A.acquire_single_instance(tempfile.mkdtemp(), wait_seconds=0) is True)

print("■ 別のプロセスが起動中なら起動できない・終われば起動できる（自動アップデートの入れ替え）")
other = tempfile.mkdtemp()
child = subprocess.Popen([sys.executable, "-c",
                          "import sys, time; sys.path.insert(0, sys.argv[1]); import auto_reply_app as A; "
                          "print(A.acquire_single_instance(sys.argv[2], wait_seconds=0), flush=True); time.sleep(2.5)",
                          FILES, other], stdout=subprocess.PIPE, text=True)
held = child.stdout.readline().strip()
check("（別のプロセスが印を持った）", held == "True", held)
check("別のプロセスが動いている間は起動できない", A.acquire_single_instance(other, wait_seconds=0.3) is False)
t0 = time.monotonic()
check("前のアプリが閉じるのを待てば起動できる", A.acquire_single_instance(other, wait_seconds=8) is True
      and time.monotonic() - t0 < 8, round(time.monotonic() - t0, 1))
child.wait(10)

print("■ 2つ目は画面を作らずに知らせて終わる")
made, shown = [], []
A.acquire_single_instance = lambda base_dir, wait_seconds=3.0: False
A.App = lambda: made.append("App")
A.messagebox.showinfo = lambda title, message: shown.append(message)
A.main()
check("画面（App）を作らない", made == [], made)
check("「もう起動しています」と知らせる（同じMuMuを取り合うため）", shown and "もう起動しています" in shown[0]
      and "MuMu" in shown[0], shown)

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
