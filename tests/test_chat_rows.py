# -*- coding: utf-8 -*-
"""
音声ルームのチャット欄を「意味で読む」関数（parse_chat_rows）の検証。実機は使わない。
fixtures/ の画面は 2026-10-11 に MuMu のゲストの画面から取ったもの（伏せ字済み。同じ名前は同じ伏せ字）。
⚠️ 今の自動返信はこの関数を使っていない（監視範囲の文字を読む作りのまま）。後の開発の土台。
"""
import os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A

FAILS = []

def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)

def fixture(name):
    with open(os.path.join(_HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()


print("■ お知らせの文言の見分け方")
check("参加", A.chat_notice_kind("ゆうが音声ルームに参加しました") == ("join", "ゆう"))
# 実物では、名前と「さんが」の間に空白が入る名前があった。仮の名前で同じ形にしてある
check("いいね（名前の後ろの空白は除く）",
      A.chat_notice_kind("テ ス ト 。 さんが音声ルームにいいねをしました") == ("like", "テ ス ト 。"))
check("マイク", A.chat_notice_kind("ゆうがマイクをもらいました") == ("mic", "ゆう"))
check("ルーム名の変更（何に変えたか）", A.chat_notice_kind("ルーム名を雑談部屋に変更しました") == ("rename", "雑談部屋"))
check("知らない文言", A.chat_notice_kind("ゆうがギフトを贈りました") == ("", ""))

print("■ 人の発言とお知らせ（ゲストの画面）")
rows = A.parse_chat_rows(fixture("voiceroom_guest.xml"), display=2)
kinds = [(r["kind"], r["notice"]) for r in rows]
check("上から 発言・参加・いいね・発言・ルーム名の変更", kinds == [
    ("message", ""), ("notice", "join"), ("notice", "like"), ("message", ""), ("notice", "rename")], kinds)
check("画面の端で切れて文字の無い行は返さない（実物の1行目）", len(rows) == 5, len(rows))
check("発言は名前と本文を組にして読む", rows[0]["name"] and rows[0]["text"] and rows[0]["name"] != rows[0]["text"], rows[0])
check("2つの発言は同じ人", rows[0]["name"] == rows[3]["name"], (rows[0]["name"], rows[3]["name"]))
check("いいねをしたのは、発言した人", rows[2]["subject"] == rows[0]["name"], (rows[2]["subject"], rows[0]["name"]))
check("他の人の参加には「ようこそ！」が付く", rows[1]["welcome"] is True)
check("発言には「ようこそ！」は付かない", rows[0]["welcome"] is False)
check("ルーム名の変更は、変えた後の名前を読む", rows[4]["subject"] == A.text_by_id(
      fixture("voiceroom_guest.xml"), "tvTitle", display=2), (rows[4]["subject"],))

print("■ アナウンス（アナウンスのあるルーム）")
rows = A.parse_chat_rows(fixture("voiceroom_announcement.xml"), display=2)
kinds = [(r["kind"], r["notice"]) for r in rows]
check("上から アナウンス・参加・ルーム名の変更", kinds == [
    ("announcement", ""), ("notice", "join"), ("notice", "rename")], kinds)
check("アナウンスは見出しの名前と本文を読む", rows[0]["name"] and rows[0]["text"], rows[0])
check("⚠️ 本文は発言と同じIDでも、アナウンスとして読む（tvUser があるため）",
      "tvContent" in rows[0]["parts"] and "tvUser" in rows[0]["parts"], rows[0]["parts"])
check("自分の参加には「ようこそ！」が付かない", rows[1]["welcome"] is False)

print("■ チャット欄の外は読まない（今の自動返信が拾っていた席番号・広告など）")
for name in ("voiceroom_guest.xml", "voiceroom_announcement.xml"):
    texts = " ".join(r["text"] + " " + r["name"] for r in A.parse_chat_rows(fixture(name), display=2))
    check(f"{name}: 席番号・「ゲスト（1人）」・「あと1日」を含まない",
          not any(word in texts for word in ("ゲスト（", "あと1日")) and not any(
              r["text"] in ("3", "5", "6") for r in A.parse_chat_rows(fixture(name), display=2)), texts)

print("■ チャット欄の無い画面")
check("タスク画面では空", A.parse_chat_rows(fixture("task_center_top.xml"), display=2) == [])

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
