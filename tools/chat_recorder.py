# -*- coding: utf-8 -*-
"""
音声ルームのチャット欄を見張り、まだ見たことのない形の行が出たら記録する（読むだけ。押す・なぞる操作はしない）。

なぜ要るか:
  チャット欄の行は、人の発言・お知らせ・アナウンスなど何種類もあり、ギフトや画像の発言のように
  人の多いルームで時々しか出ない形もある。その場で1回画面を読むだけでは集まらないので、
  MuMuでふつうに音声ルームにいる間、裏で見張って集める（2026-10-11 本人の希望）。

使い方:
    python tools/chat_recorder.py              # 30分見張る
    python tools/chat_recorder.py 120          # 120分見張る（Ctrl+C でいつでも止められる）

記録の置き場所: recordings/chat/（⚠️ .gitignore で除外。リポジトリには入らない）
  ・新しい形の行が出たときの画面のダンプ（*.xml）
  ・見た行の一覧と、形ごとの件数（summary_*.json）
⚠️ 記録には他の人の名前や発言がそのまま入っている。テストに使うときは必ず
   tests/make_fixture.py で伏せ字にしてから tests/fixtures/ に置くこと。

自動返信の監視と同時に動かしてよい（読むだけなので、画面の操作は混ざらない）。
"""
import datetime
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "files"))
import adbutils                      # noqa: E402
import uiautomator2 as u2            # noqa: E402
import auto_reply_app as A           # noqa: E402

OUT_DIR = os.path.join(_ROOT, "recordings", "chat")
INTERVAL_SECONDS = 3.0


def connect(db):
    """MuMuに問い合わせたadbの接続先へつなぐ。⚠️ 決め打ちしない（開くたびに変わる）。MuMuやアプリは起動しない"""
    mumu = A.MuMuController(print, manager_path=db.get_setting("mumu_manager_path", "") or "")
    address = None
    if mumu.is_available():
        info = mumu.get_info(db.get_setting("mumu_instance_index", "") or None)
        if mumu.is_android_ready(info):
            address = mumu.get_adb_address(info)
    if address:
        try:
            adbutils.adb.connect(address, timeout=3.0)
        except Exception:
            pass
    serials = [dev.serial for dev in adbutils.adb.device_list()]
    if not serials:
        sys.exit("MuMuにつながりません。MuMuを起動してから、もう一度実行してください。")
    serial = address if address in serials else serials[0]
    print(f"🔌 {serial} につなぎました")
    return adbutils.adb.device(serial), u2.connect(serial)


def main():
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    db = A.DatabaseManager(A.DB_FILE)
    reader = A.AutoReplyWorker(db, lambda m: None)   # ディスプレイ番号の割り出しだけに使う（つながない）
    dev, d = connect(db)

    shapes = {}       # (種類, お知らせの種類, 部品の並び) → {"count", "examples", "file"}
    seen_rows = set()
    unknown_notices = []
    waiting_shown = False
    end = time.time() + minutes * 60
    print(f"👀 {minutes:g}分間、音声ルームのチャット欄を見張ります（読むだけ）。Ctrl+C で止められます。")
    try:
        while time.time() < end:
            xml = d.dump_hierarchy()
            display = reader._update_target_display(xml)
            component = A.parse_display_activity(dev.shell("dumpsys activity activities"), display)
            if not A.is_voice_room_screen(component):
                if not waiting_shown:
                    print("⏸️ 音声ルームの画面ではないので、開くまで待っています...")
                    waiting_shown = True
                time.sleep(INTERVAL_SECONDS)
                continue
            waiting_shown = False
            for row in A.parse_chat_rows(xml, display):
                content = (row["kind"], row["name"], row["text"], row["notice"])
                if content in seen_rows:
                    continue
                seen_rows.add(content)
                key = (row["kind"], row["notice"], row["parts"])
                shape = shapes.get(key)
                if shape is None:
                    name = f"{stamp}_{len(shapes) + 1:02d}_{row['kind']}{'_' + row['notice'] if row['notice'] else ''}.xml"
                    with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as f:
                        f.write(xml)
                    shape = shapes[key] = {"count": 0, "examples": [], "file": name}
                    label = row["kind"] + (f"（{row['notice']}）" if row["notice"] else "")
                    print(f"🆕 新しい形の行: {label}  部品: {' / '.join(row['parts'])}")
                    print(f"     例: {row['name'] + '：' if row['name'] else ''}{row['text'][:40]!r}  → {name}")
                shape["count"] += 1
                if len(shape["examples"]) < 5:
                    shape["examples"].append({"name": row["name"], "text": row["text"], "subject": row["subject"],
                                              "welcome": row["welcome"]})
                if row["kind"] == A.CHAT_KIND_NOTICE and not row["notice"]:
                    unknown_notices.append(row["text"])
                    print(f"❓ まだ知らないお知らせの文言: {row['text'][:60]!r}")
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n⏹️ 止めました。")

    summary = {
        "recorded_at": stamp,
        "minutes": minutes,
        "rows_seen": len(seen_rows),
        "shapes": [{"kind": k[0], "notice": k[1], "parts": list(k[2]), **v} for k, v in shapes.items()],
        "unknown_notices": unknown_notices,
    }
    path = os.path.join(OUT_DIR, f"summary_{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(f"\n📋 見た行 {len(seen_rows)} 件 / 形 {len(shapes)} 種類 / 知らないお知らせ {len(unknown_notices)} 件")
    for item in summary["shapes"]:
        label = item["kind"] + (f"（{item['notice']}）" if item["notice"] else "")
        print(f"   {item['count']:4} 件  {label}  {' / '.join(item['parts'])}")
    print(f"記録: {path}")


if __name__ == "__main__":
    main()
