# -*- coding: utf-8 -*-
"""
GRAVITYの実際の入力欄で、改行入りの文字がどう入るかを確かめる（実機テスト）。

⚠️ 送信ボタンは押さない。入れて・読み戻して・消すだけなので、ルームには何も投稿されない。
   uiautomator2 の send_keys は ADB_KEYBOARD_INPUT_TEXT をブロードキャストして
   IMEに commitText させる方式で、KEYCODE_ENTER を打たないため改行では送信されない。

前提: MuMuが起動していて、GRAVITYの音声ルームが表示されていること。
実行: python tests/test_live_newline.py
"""
import os, re, sys, html, time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A
import uiautomator2 as u2

# ⚠️ 接続先を決め打ちしない。MuMuはインスタンスごとにポートが変わる
#   （2026-08は 192.168.1.7:5555、2026-09は 127.0.0.1:16416 だった）
mumu = A.MuMuController(lambda m: print("  ", m))
if not mumu.is_available():
    print("MuMuManager.exe が見つかりません。MuMuを入れた環境で実行してください。")
    sys.exit(1)

index = mumu.resolve_index()
info = mumu.get_info(index)
if not (info and mumu.is_android_ready(info)):
    print("MuMuのAndroidが起動していません。起動してから実行してください。")
    sys.exit(1)

addr = mumu.get_adb_address(info)
print(f"接続先: {addr}")
d = u2.connect(addr)

re_node = re.compile(r'<node\s+([^>]+)>')

def find_input():
    """GRAVITYの入力欄を (ディスプレイ番号, 座標, 今の表示文字) で返す"""
    xml = d.dump_hierarchy(compressed=True)
    for node in re_node.findall(xml):
        cls = re.search(r'class="([^"]+)"', node)
        if not (cls and "EditText" in cls.group(1)):
            continue
        pkg = re.search(r'package="([^"]+)"', node)
        if not (pkg and "gravity" in pkg.group(1)):
            continue
        disp = re.search(r'display-id="([^"]+)"', node)
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        txt = re.search(r'text="([^"]*)"', node)
        return (int(disp.group(1)) if disp else 0,
                tuple(int(v) for v in b.groups()),
                html.unescape(txt.group(1)) if txt else "")
    return None

found = find_input()
if not found:
    print("入力欄が見つかりません（GRAVITYの音声ルームが出ているか確認してください）")
    sys.exit(1)

display, (x1, y1, x2, y2), placeholder = found
cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
print(f"入力欄: display={display} 中心=({cx},{cy}) 現在の表示={placeholder!r}")

# ⚠️ 入力は display を指定しないと既定の画面0へ飛ぶ。MuMuは画面を複数持つ
d.shell(f"input -d {display} tap {cx} {cy}")
time.sleep(1.0)

TEST = "テスト1行目\nテスト2行目"
print(f"\n打ち込む文字: {TEST!r}")
d.send_keys(TEST)
time.sleep(1.0)

got = find_input()[2]
print(f"入力欄に入った文字: {got!r}")

norm = lambda s: re.sub(r"\s+", "", s or "")
results = {
    "改行がそのまま保たれる": "\n" in got,
    "文字が全部入る": norm(TEST) in norm(got),
    "勝手に送信されない": got not in ("", placeholder),
}
print("\n--- 判定 ---")
for name, ok in results.items():
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")

# 後片付け: 入れた文字を消し、開いていればキーボードを閉じる
d.clear_text()
time.sleep(0.5)
print(f"\n消したあとの入力欄: {find_input()[2]!r}")
out = d.shell("dumpsys input_method").output
if any("mInputShown=true" in l.replace(" ", "") for l in out.splitlines()):
    d.shell(f"input -d {display} keyevent 4")
    print("キーボードを閉じました。")

sys.exit(0 if all(results.values()) else 1)
