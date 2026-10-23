"""配布zipを確かめる（zipの形・同梱物・exe内のモジュール・分離した環境での起動）。リリースのときに使う。

usage: python tests/release_verify_dist.py <zip> <work_dir> <expected_version>
           [--old-src DIR] [--allow-error-log REGEX] [--screenshot PNG] [--strict-paths] [--symbols A,B,...]

- PyInstaller の読み取り用の関数を使うので、PyInstaller の入った Python で動かす（CIと同じ 3.11 の venv など）。
- 起動は LOCALAPPDATA・APPDATA・TEMP・USERPROFILE・PATH を一時フォルダ等に差し替えて行い、
  本人のアプリ（更新の置き場所 %LOCALAPPDATA%\\AutoReplyTool など）と共有しない。
  ⚠️ 起動時に「適用待ちの更新が無ければ pending_update を消す」ので、差し替えずに起動すると本人のアプリの準備物を消しうる。
- --old-src は前の版の auto_reply_app.py を置いたフォルダ（git show v1.8.0:files/auto_reply_app.py > DIR/auto_reply_app.py）。
  前の版の DatabaseManager で設定を作ってから起動し、引き継げるかを見る。
- 画面に窓が10秒ほど出て、閉じるボタンと同じ操作で閉じる。
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import importlib.util
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
ap.add_argument("zip")
ap.add_argument("work")
ap.add_argument("version")
ap.add_argument("--old-src", help="前の版の auto_reply_app.py があるフォルダ。あれば前の版の設定を置いてから起動する")
ap.add_argument("--screenshot", help="起動した窓を撮って保存するPNGのパス")
ap.add_argument("--strict-paths", action="store_true", help="手元のパス（ユーザー名など）が1つでもあれば失敗にする（CIのzip用）")
ap.add_argument("--allow-error-log", help="error_log.txt に出てよい行（正規表現）。無ければ1行でも失敗")
# ⚠️ リリースのたびに、その版で足した機能の名前（関数名・ボタンの文言など）に差し替える
ap.add_argument("--symbols", default=",".join([
    "acquire_single_instance", "もう起動しています", "_send_with_mention", "_close_sheet_keeping_text",
    "room_input_focused", "_check_hearing_route", "_owner_mic_problem", "on_agent_reconsider_toggled",
    "GRAVITYの顔で表す", "UnifiedLog", "on_log_filter_changed", "build_search_api_section",
    "🔎 ウェブ検索・ニュース（Tavily）",
]), help="exe の本体に入っているはずの名前（カンマ区切り）。既定は v1.11.0 で足したもの")
a = ap.parse_args()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXE = "自動送信ボット.exe"
TITLE = f"(v{a.version})"
fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(label)
    return cond


raw = open(a.zip, "rb").read()
print(f"zip: {a.zip}\n     {len(raw):,} bytes  sha256={hashlib.sha256(raw).hexdigest()}")

# ---------------------------------------------------------------- [1] zip
print("\n[1] zipの形と同梱物（アプリの自動更新と同じ zipfile で読む）")
BAD_NAME = re.compile(
    r"(^|/)(app_data\.db.*|agent_data\.db.*|error_log\.txt|tailscale\.(key|crt)|self\.(key|crt)|\.env"
    r"|開発ログ\.md|GRAVITY画面部品\.md|RELEASE_README\.md|[^/]+\.spec|auto_reply_app\.py)$"
    r"|(^|/)(recordings|tests|設計書|tools|backup|AIの記憶)/|^_internal/agent/|(^|/)AIが気づいたこと\.md$")
KEY = re.compile(rb"AIza[0-9A-Za-z_\-]{35}")
PRIVATE_KEY = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
# 手元のパス: このPCのユーザー名と、リポジトリの1つ上のフォルダ名。⚠️ 名前はここに書かない（リポジトリは公開）。
# 前後がパスの区切りのときだけ数える。名前だけで探すと、adb.exe や PIL の _imagingft にある
# Brotli の決まった単語表（スペイン語などの単語を区切らずに続けた並び）に当たる（2026-10-15 に誤検知した）。
_local_words = [w for w in (os.environ.get("USERNAME", ""), os.path.basename(os.path.dirname(REPO))) if len(w) >= 3]
_local_alts = []
for _w in _local_words:
    for _enc, _sep in (("utf-8", rb"[\\/]"), ("utf-16-le", rb"(?:\\\x00|/\x00)")):
        _local_alts.append(_sep + re.escape(_w.encode(_enc)) + _sep)
LOCAL_PATH = re.compile(b"|".join(_local_alts), re.I) if _local_alts else None
with zipfile.ZipFile(a.zip) as z:
    infos = z.infolist()
    names = [i.filename for i in infos]
    exes = [i for i in infos if i.filename.endswith(".exe") and "/" not in i.filename]
    check("いちばん上の exe は 自動送信ボット.exe だけ", [i.filename for i in exes] == [EXE], str([i.filename for i in exes]))
    check("exe名に UTF-8 の印が付いている（zipfile で日本語名のまま読める）", bool(exes) and bool(exes[0].flag_bits & 0x800))
    check("_internal/app_icon.ico が入っている", "_internal/app_icon.ico" in names)
    bad = [n for n in names if BAD_NAME.search(n)]
    check("利用者のデータ・秘密・開発用のファイルが入っていない", not bad, str(bad[:10]))
    found = {"key": [], "private": [], "path": []}
    for i in infos:
        if i.is_dir():
            continue
        b = z.read(i)
        if KEY.search(b):
            found["key"].append(i.filename)
        if PRIVATE_KEY.search(b):
            found["private"].append(i.filename)
        if LOCAL_PATH is not None and LOCAL_PATH.search(b):
            found["path"].append(i.filename)
    check("Google の API キーの形をした文字列が無い", not found["key"], str(found["key"][:5]))
    # cryptography 自身のPEM判定用の文字列は鍵の実体ではない（開発ログ 2026-09-25 追記3 の 4）
    real_pk = [n for n in found["private"] if "cryptography" not in n]
    check("秘密鍵が無い（cryptography 自身の判定用の文字列は除く）", not real_pk, str(found["private"][:5]))
    if a.strict_paths:
        check("手元のパス（ユーザー名・フォルダ名）が入っていない", not found["path"], str(found["path"][:5]))
    else:
        print(f"  info 手元のパスを含むファイル: {len(found['path'])}（手元のビルドでは出てよい） {found['path'][:3]}")
    total = sum(i.file_size for i in infos)
    print(f"  info ファイル {len(infos)} 個・展開後 {total/1e6:.1f} MB")

# ---------------------------------------------------------------- [2] exe の中
print("\n[2] exe の中に今回の機能が入っているか")
from PyInstaller.archive.readers import CArchiveReader  # noqa: E402

app_dir = os.path.join(a.work, "app")
shutil.rmtree(app_dir, ignore_errors=True)
os.makedirs(app_dir)
with zipfile.ZipFile(a.zip) as z:
    z.extractall(app_dir)
exe_path = os.path.join(app_dir, EXE)
pkg = CArchiveReader(exe_path)
script = pkg.extract("auto_reply_app")
check("本体のスクリプト auto_reply_app が入っている", bool(script))
SYMBOLS = [s for s in a.symbols.split(",") if s]
missing = [s for s in SYMBOLS if s.encode("utf-8") not in script]
check(f"本体に今回の機能の名前が全部ある（{len(SYMBOLS)}個）", not missing, str(missing))
check(f"本体の版が {a.version}", f'{a.version}'.encode() in script)
pyz = pkg.open_embedded_archive("PYZ.pyz")
mods = set(pyz.toc)
# files/agent/ の .py から、入っているはずのモジュール名を作る（決め打ちにすると、足したモジュールの漏れに気付けない）
# ⚠️ リポジトリの作業中のフォルダを見るので、リリースしたコミットを取り出したフォルダから動かすこと
AGENT = []
_agent_root = os.path.join(REPO, "files")
for _root, _dirs, _files in os.walk(os.path.join(_agent_root, "agent")):
    _dirs[:] = [d for d in _dirs if d != "__pycache__"]
    for _f in _files:
        if _f.endswith(".py"):
            _rel = os.path.relpath(os.path.join(_root, _f), _agent_root)[:-3].replace(os.sep, ".")
            AGENT.append(_rel[:-len(".__init__")] if _rel.endswith(".__init__") else _rel)
AGENT.sort()
check("files/agent/ のモジュールの一覧を作れた", bool(AGENT), _agent_root)
miss_mods = [m for m in AGENT if m not in mods]
check(f"AIまわりのモジュール {len(AGENT)} 個が全部入っている", not miss_mods, str(miss_mods))
for m in ("sqlite3", "ssl", "urllib.request", "sounddevice", "customtkinter", "uiautomator2", "cryptography",
          "pyaudiowpatch"):
    if not check(f"ライブラリ {m} が入っている", m in mods):
        pass
# PCのスピーカーの音をループバックで取る PyAudioWPatch は、中の PortAudio（拡張モジュール _portaudiowpatch）が無いと
# import で落ちる（v1.10.0）。⚠️ この拡張はパッケージの外（いちばん上）に置かれ、`import _portaudiowpatch` で読まれる
pa_pyd = [n for n in names if re.search(r"^_internal/_portaudiowpatch[^/]*\.pyd$", n)]
check("PyAudioWPatch の中身（_internal/_portaudiowpatch*.pyd）が入っている", bool(pa_pyd),
      str([n for n in names if "portaudiowpatch" in n.lower()][:5]))
if pa_pyd:
    # 配布物の .pyd そのものを読み込み、今の既定の出力のループバックの機材を見つけられるか（音は取らない・鳴らさない）
    probe = (
        "import os, sys; sys.path.insert(0, sys.argv[1]); import _portaudiowpatch, pyaudiowpatch as p; "
        "assert os.path.samefile(os.path.dirname(_portaudiowpatch.__file__), sys.argv[1]), _portaudiowpatch.__file__; "
        "a = p.PyAudio(); w = a.get_host_api_info_by_type(p.paWASAPI); "
        "s = a.get_device_info_by_index(w['defaultOutputDevice']); "
        "print(any(s['name'] in d['name'] for d in a.get_loopback_device_info_generator())); a.terminate()")
    r = subprocess.run([sys.executable, "-c", probe, os.path.join(app_dir, "_internal")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("配布物の _portaudiowpatch を読み込んで、今の既定の出力のループバックが見つかる",
          r.returncode == 0 and r.stdout.strip().endswith("True"), (r.stdout + r.stderr)[-300:])

# ---------------------------------------------------------------- [3] 起動
print("\n[3] 分離した環境で起動する")
iso = os.path.join(a.work, "iso_env")
shutil.rmtree(iso, ignore_errors=True)
for d in ("LocalAppData", "AppData", "Temp", "Home"):
    os.makedirs(os.path.join(iso, d))
KEEP = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE",
        "NUMBER_OF_PROCESSORS", "OS", "USERNAME", "USERDOMAIN", "COMPUTERNAME", "PROGRAMDATA",
        "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "PUBLIC"}
env = {k: v for k, v in os.environ.items() if k.upper() in KEEP}
sysroot = env.get("SYSTEMROOT", r"C:\Windows")
env["PATH"] = ";".join([os.path.join(sysroot, "System32"), sysroot, os.path.join(sysroot, "System32", "Wbem"),
                        os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0")])
env["LOCALAPPDATA"] = os.path.join(iso, "LocalAppData")
env["APPDATA"] = os.path.join(iso, "AppData")
env["TEMP"] = env["TMP"] = os.path.join(iso, "Temp")
env["USERPROFILE"] = os.path.join(iso, "Home")

real_pending = os.path.join(os.environ.get("LOCALAPPDATA", ""), "AutoReplyTool")


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


real_before = snapshot(real_pending)

db_path = os.path.join(app_dir, "app_data.db")
before_rows = None
if a.old_src:
    sys.path.insert(0, a.old_src)
    spec = importlib.util.spec_from_file_location("app_old", os.path.join(a.old_src, "auto_reply_app.py"))
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    sys.path.remove(a.old_src)
    odb = old.DatabaseManager(db_name=db_path)
    ok, msg, sid = odb.create_keyword_set("挨拶セット")
    odb.upsert_keyword(sid, "こんにちは", "こんにちは！ようこそ")
    odb.upsert_keyword(sid, "おやすみ", "おやすみなさい\n2行目")
    odb.set_keyword_enabled(sid, "おやすみ", False)
    odb.save_setting("manual_send_box_count", "5")
    odb.create_timer_preset("休憩", 900)
    with sqlite3.connect(db_path) as c:
        before_rows = sorted(c.execute("SELECT set_id, trigger_word, reply_message, enabled FROM keywords"))
    print(f"  info 前の版（{old.APP_VERSION}）の設定を置いた: ペア {len(before_rows)} 件")

user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass
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


proc = subprocess.Popen([exe_path], cwd=app_dir, env=env)
title, hwnd = None, None
deadline = time.time() + 40
while time.time() < deadline and proc.poll() is None:
    for h, t in windows_of(proc.pid):
        if TITLE in t:
            title, hwnd = t, h
    if title:
        break
    time.sleep(0.5)
check("起動して窓が出る", title is not None, f"exit={proc.poll()}")
if title:
    check(f"窓の題に版 {TITLE} が出る", TITLE in title, title)
    print(f"  info 窓の題: {title}")
    time.sleep(10)  # 起動後の処理（読み上げの復帰 0.3秒・更新の確認 1.5秒）を待つ
    check("10秒後も動いている", proc.poll() is None, f"exit={proc.poll()}")
    if a.screenshot:
        try:
            grab(hwnd, a.screenshot)
            print(f"  info 窓を撮った: {a.screenshot}")
        except Exception as e:
            print(f"  info 窓を撮れなかった: {e}")
    others = [t for h, t in windows_of(proc.pid) if h != hwnd]
    check("エラーなどの別の窓が出ていない", not others, str(others))
    # 同じフォルダの2つ目は、アプリの窓を作らずに「もう起動しています」と知らせて終わる（v1.11.0。2つが同じ MuMu を取り合った）
    second = subprocess.Popen([exe_path], cwd=app_dir, env=env)
    notice = []
    deadline2 = time.time() + 30
    while time.time() < deadline2 and second.poll() is None and not notice:
        notice = [(h, t) for h, t in windows_of(second.pid) if t]
        time.sleep(0.5)
    check("同じフォルダの2つ目はアプリの窓を作らない（知らせの窓だけ）",
          bool(notice) and all(TITLE not in t for _, t in notice), str([t for _, t in notice]))
    for h, _ in notice:
        user32.PostMessageW(h, 0x0010, 0, 0)       # 知らせを閉じる（OK と同じく終わる）
    try:
        second.wait(15)
        check("2つ目は知らせを閉じると終わる", True)
    except subprocess.TimeoutExpired:
        check("2つ目は知らせを閉じると終わる", False, str([t for _, t in windows_of(second.pid)]))
        second.kill()
    check("1つ目はそのまま動いている", proc.poll() is None, f"exit={proc.poll()}")
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE（ふつうに閉じる）
    try:
        proc.wait(20)
        check("閉じるボタンと同じ操作で終わる", True)
    except subprocess.TimeoutExpired:
        check("閉じるボタンと同じ操作で終わる", False, str([t for _, t in windows_of(proc.pid)]))
        proc.kill()
else:
    proc.kill()

err_log = os.path.join(app_dir, "error_log.txt")
if os.path.exists(err_log):
    lines = [ln for ln in open(err_log, encoding="utf-8", errors="replace").read().splitlines() if ln.strip()]
    for ln in lines:
        print(f"  info error_log.txt: {ln}")
    # safe_print はどんな文も error_log.txt に書く（v1.8.0 から同じ作り）。--allow-error-log で設定の移行のお知らせだけ許す
    allowed = re.compile(a.allow_error_log) if a.allow_error_log else None
    unexpected = [ln for ln in lines if not (allowed and allowed.search(ln))]
    check("error_log.txt に想定外の行が無い", not unexpected, str(unexpected[:5]))
else:
    check("error_log.txt が作られていない", True)
check("設定（app_data.db）は exe と同じフォルダにできる", os.path.exists(db_path))
check("AIの記録（agent_data.db）は使うまで作られない", not os.path.exists(os.path.join(app_dir, "agent_data.db")))
if os.path.exists(db_path):
    with sqlite3.connect(db_path) as c:
        logs = [r[0] for r in c.execute("SELECT message FROM logs ORDER BY id")]
        cols = [r[1] for r in c.execute("PRAGMA table_info(keywords)")]
        if before_rows is not None:
            check("前の版の設定に target 列が足された", "target" in cols, str(cols))
            after = sorted(c.execute("SELECT set_id, trigger_word, reply_message, enabled FROM keywords"))
            check("前の版のペアがそのまま（有効/無効・改行も）", after == before_rows, f"{after} != {before_rows}")
            check("既存のペアは「すべての文字（今まで通り）」",
                  all(t == "any" for (t,) in c.execute("SELECT target FROM keywords")))
            check("前の版の設定値がそのまま",
                  c.execute("SELECT value FROM settings WHERE key='manual_send_box_count'").fetchone() == ("5",))
    upd = [m for m in logs if "最新です" in m or "新しいバージョン" in m or "アップデート" in m]
    print(f"  info 起動中のログ {len(logs)} 行。更新の確認: {upd[-1] if upd else '（記録なし）'}")
    errs = [m for m in logs if re.search(r"エラー|失敗|Traceback|Exception", m)]
    check("起動中のログにエラー・失敗が無い", not errs, str(errs[:5]))
real_after = snapshot(real_pending)
check("本人の %LOCALAPPDATA%\\AutoReplyTool に触れていない", real_before == real_after)

print("\nすべて成功" if not fails else f"\n失敗 {len(fails)} 件: {fails}")
sys.exit(1 if fails else 0)
