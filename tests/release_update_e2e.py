"""公開中の前の版の配布物を分離した環境で動かし、自動アップデートで新しい版に入れ替わるかを確かめる。リリースの後に使う。

usage: python tests/release_update_e2e.py <old_zip> <new_zip> <work_dir> <old_src_dir> <old_version> <new_version>
           [--allow-error-log REGEX]
  old_src_dir: 前の版の auto_reply_app.py を置いたフォルダ（git show v1.8.0:files/auto_reply_app.py > DIR/auto_reply_app.py）

- 新しい版を GitHub で公開した後でないと動かない（前の版は「最新のリリース」を見に行く）。
  ログインなしの GitHub API を、1回の起動で1回使う（1時間に60回まで）。
- 前の版は起動の1.5秒後に最新のリリースを確かめ、新しければ裏でダウンロードして
  （%LOCALAPPDATA%\\AutoReplyTool\\pending_update）、終了するときに PowerShell と robocopy で差し替える。
  差し替える前に ~\\AutoReplyTool_Backups へバックアップの zip を作るので、閉じてから終わるまで数十秒かかる。
  ⚠️ 閉じた後、終わる前に強制終了すると差し替えが起きない（2026-10-15 に20秒で打ち切って一度失敗した）。
- LOCALAPPDATA・APPDATA・TEMP・USERPROFILE・PATH を一時フォルダ等に差し替えて動かし、本人のアプリと共有しない。
- 待っている間に前の版の窓を撮る（作業フォルダの old_*.png）。用意されなかったときは、画面のログに理由が出る。
- 画面に、前の版の窓・「適用しています」・PowerShell の窓・新しい版の窓が順に出て、自動で閉じる（1〜2分）。
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
for name in ("old_zip", "new_zip", "work", "old_src", "old_version", "new_version"):
    ap.add_argument(name)
ap.add_argument("--allow-error-log", help="error_log.txt に出てよい行（正規表現）。無ければ1行でも失敗")
a = ap.parse_args()
old_zip, new_zip, work, old_src, old_version, new_version = (
    a.old_zip, a.new_zip, a.work, a.old_src, a.old_version, a.new_version)
EXE = "自動送信ボット.exe"
fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"  {detail}" if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(label)
    return cond


def log(msg):
    print(f"  ..   {time.strftime('%H:%M:%S')} {msg}", flush=True)


user32 = ctypes.windll.user32
EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def windows_of(pid):
    found = []

    def cb(hwnd, _):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            found.append((hwnd, buf.value))
        return True
    user32.EnumWindows(EnumProc(cb), 0)
    return found


def grab(hwnd, path):
    """窓を PrintWindow で撮る（ほかの窓に隠れていても撮れる）"""
    from PIL import Image
    gdi32 = ctypes.windll.gdi32
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)  # PW_RENDERFULLCONTENT

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]
    bih = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bih), 0)
    Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).save(path)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)


def wait_title(proc, text, timeout):
    end = time.time() + timeout
    while time.time() < end and proc.poll() is None:
        for h, t in windows_of(proc.pid):
            if text in t:
                return h, t
        time.sleep(0.5)
    return None, None


def sha(b):
    return hashlib.sha256(b).hexdigest()


# --- 分離した環境
shutil.rmtree(work, ignore_errors=True)
app_dir = os.path.join(work, "app")
iso = os.path.join(work, "iso_env")
for d in ("LocalAppData", "AppData", "Temp", "Home"):
    os.makedirs(os.path.join(iso, d))
KEEP = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE",
        "NUMBER_OF_PROCESSORS", "OS", "USERNAME", "USERDOMAIN", "COMPUTERNAME", "PROGRAMDATA",
        "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "PUBLIC"}
env = {k: v for k, v in os.environ.items() if k.upper() in KEEP}
sysroot = env.get("SYSTEMROOT", r"C:\Windows")
# 更新のスクリプトは "powershell" を名前で呼び、robocopy を使う。どちらも Windows の中にある
env["PATH"] = ";".join([os.path.join(sysroot, "System32"), sysroot, os.path.join(sysroot, "System32", "Wbem"),
                        os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0")])
env["LOCALAPPDATA"] = os.path.join(iso, "LocalAppData")
env["APPDATA"] = os.path.join(iso, "AppData")
env["TEMP"] = env["TMP"] = os.path.join(iso, "Temp")
env["USERPROFILE"] = os.path.join(iso, "Home")
pending_dir = os.path.join(env["LOCALAPPDATA"], "AutoReplyTool", "pending_update")
manifest_path = os.path.join(pending_dir, "manifest.json")
real_tool_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "AutoReplyTool")


def snapshot(path):
    out = {}
    for root, _, files in os.walk(path):
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
                out[p] = (st.st_size, st.st_mtime_ns)
            except OSError:
                pass
    return out


real_before = snapshot(real_tool_dir)

print(f"[1] 公開中の v{old_version} を置き、v{old_version} で作った設定を入れる")
with zipfile.ZipFile(old_zip) as z:
    z.extractall(app_dir)
with zipfile.ZipFile(new_zip) as z:
    new_exe_hash = sha(z.read(EXE))
old_exe_hash = sha(open(os.path.join(app_dir, EXE), "rb").read())
check(f"v{old_version} と新しい版の exe は中身が違う", old_exe_hash != new_exe_hash)
sys.path.insert(0, old_src)
spec = importlib.util.spec_from_file_location("app_old", os.path.join(old_src, "auto_reply_app.py"))
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
sys.path.remove(old_src)
db_path = os.path.join(app_dir, "app_data.db")
odb = old.DatabaseManager(db_name=db_path)
ok, msg, sid = odb.create_keyword_set("挨拶セット")
odb.upsert_keyword(sid, "こんにちは", "こんにちは！ようこそ")
odb.upsert_keyword(sid, "おやすみ", "おやすみなさい\n2行目")
odb.set_keyword_enabled(sid, "おやすみ", False)
odb.save_setting("manual_send_box_count", "5")
with sqlite3.connect(db_path) as c:
    before_rows = sorted(c.execute("SELECT set_id, trigger_word, reply_message, enabled FROM keywords"))
del odb

print(f"\n[2] v{old_version} を起動し、裏で新しい版を用意するまで待つ")
proc = subprocess.Popen([os.path.join(app_dir, EXE)], cwd=app_dir, env=env)
hwnd, title = wait_title(proc, f"(v{old_version})", 40)
check(f"v{old_version} が起動する", bool(title), f"exit={proc.poll()}")
log(f"窓の題: {title}")
manifest = None
start = time.time()
end = start + 240
shots = [15, 45, 120, 239]
while time.time() < end and proc.poll() is None:
    if shots and time.time() - start >= shots[0] and hwnd:
        path = os.path.join(work, f"old_{shots[0]:03d}s.png")
        try:
            grab(hwnd, path)
            log(f"撮った: {os.path.basename(path)}  窓: {[t for _, t in windows_of(proc.pid)]}")
        except Exception as e:
            log(f"撮れなかった: {e}")
        shots.pop(0)
    if os.path.exists(manifest_path):
        try:
            manifest = json.load(open(manifest_path, encoding="utf-8"))
            if os.path.isdir(manifest.get("source_dir", "")):
                break
        except (OSError, ValueError):
            manifest = None
    time.sleep(1)
check("新しい版をダウンロードして用意した（manifest）", bool(manifest), str(manifest))
if manifest and hwnd:
    try:
        grab(hwnd, os.path.join(work, "old_staged.png"))
    except Exception:
        pass
if manifest:
    log(f"用意した版: {manifest.get('version')}  展開先: {os.path.relpath(manifest.get('source_dir', ''), work)}")
    check(f"用意した版が v{new_version}", manifest.get("version") == f"v{new_version}", manifest.get("version"))
    staged_exe = os.path.join(manifest["source_dir"], EXE)
    check("用意したexeが、公開中のzipのexeと同じ",
          os.path.exists(staged_exe) and sha(open(staged_exe, "rb").read()) == new_exe_hash)

print(f"\n[3] v{old_version} を閉じる（終了時に差し替える）")
time.sleep(2)
if hwnd:
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE（閉じるボタンと同じ）
try:
    proc.wait(180)  # バックアップの zip を作ってから終わる。途中で強制終了すると差し替えが起きない
    check(f"v{old_version} が終了した", True)
except subprocess.TimeoutExpired:
    check(f"v{old_version} が終了した", False, str(windows_of(proc.pid)))
    proc.kill()
exe_path = os.path.join(app_dir, EXE)
end = time.time() + 180
replaced = False
while time.time() < end:
    try:
        replaced = sha(open(exe_path, "rb").read()) == new_exe_hash
    except OSError:
        replaced = False
    if replaced and not os.path.exists(pending_dir):
        break
    time.sleep(1)
check("アプリのフォルダの exe が新しい版に入れ替わった", replaced)
check("用意に使った一時フォルダ（pending_update）が片付いた", not os.path.exists(pending_dir))
backups = os.path.join(env["USERPROFILE"], "AutoReplyTool_Backups")
blist = os.listdir(backups) if os.path.isdir(backups) else []
check("差し替える前の版のバックアップが残る", bool(blist), backups)
log(f"バックアップ: {blist}")

print("\n[4] 入れ替わった版を起動する")
time.sleep(2)
proc2 = subprocess.Popen([exe_path], cwd=app_dir, env=env)
hwnd2, title2 = wait_title(proc2, f"(v{new_version})", 40)
check(f"起動して窓の題が (v{new_version})", bool(title2), f"exit={proc2.poll()} titles={windows_of(proc2.pid)}")
log(f"窓の題: {title2}")
time.sleep(8)
check("8秒後も動いている", proc2.poll() is None)
if hwnd2:
    user32.PostMessageW(hwnd2, 0x0010, 0, 0)
try:
    proc2.wait(60)
except subprocess.TimeoutExpired:
    proc2.kill()

print("\n[5] 設定とログ")
with sqlite3.connect(db_path) as c:
    after_rows = sorted(c.execute("SELECT set_id, trigger_word, reply_message, enabled FROM keywords"))
    box = c.execute("SELECT value FROM settings WHERE key='manual_send_box_count'").fetchone()
check(f"v{old_version} のペアがそのまま（有効/無効・改行も）", after_rows == before_rows, f"{after_rows} != {before_rows}")
check("設定値がそのまま", box == ("5",), str(box))
err = os.path.join(app_dir, "error_log.txt")
lines = [ln for ln in open(err, encoding="utf-8", errors="replace").read().splitlines() if ln.strip()] if os.path.exists(err) else []
for ln in lines:
    log(f"error_log.txt: {ln}")
allowed = re.compile(a.allow_error_log) if a.allow_error_log else None
unexpected = [ln for ln in lines if not (allowed and allowed.search(ln))]
check("error_log.txt に想定外の行が無い", not unexpected, str(unexpected[:5]))
check("本人の %LOCALAPPDATA%\\AutoReplyTool に触れていない", snapshot(real_tool_dir) == real_before)

print("\nすべて成功" if not fails else f"\n失敗 {len(fails)} 件: {fails}")
sys.exit(1 if fails else 0)
