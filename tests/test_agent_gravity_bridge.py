# -*- coding: utf-8 -*-
"""
GRAVITY のチャット欄の行を AI の出来事にする橋（GravityChatBridge。段階5、設計書/08 の T30）。

伏せ字にした実物の音声ルームの画面（fixtures/voiceroom_guest.xml）を使う。音は鳴らさない・通信しない。
監視の本体（_run_monitor）を にせの端末で回し、キーワード自動返信が今まで通り動くことも確かめる。
"""
import os, tempfile

from agent_harness import Agent, check, finish, wait_until
import auto_reply_app as A
from agent.llm.mock import MODE_ENGAGE

_HERE = os.path.dirname(os.path.abspath(__file__))
GRAVITY = "anonymous.sns.community.gravity"


def fixture(name):
    with open(os.path.join(_HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()


GUEST = fixture("voiceroom_guest.xml")
ROWS = A.parse_chat_rows(GUEST, 2)
# 上から: 発言 伏せ字3「伏せ字4」 / 参加 伏せ字5 / いいね 伏せ字3 / 発言 伏せ字3「伏せ字6」 / ルーム名の変更


def msg(name, text):
    return {"kind": A.CHAT_KIND_MESSAGE, "name": name, "text": text, "notice": "", "subject": "",
            "welcome": False, "box": (0, 0, 1, 1), "parts": ()}


got = []
bridge = A.GravityChatBridge(got.extend)

print("■ 最初の画面は「前からあった」")
first = bridge.on_rows(ROWS)
check("5行すべて渡す（発言2・お知らせ3）", len(first) == 5 and [e.kind for e in first] ==
      ["chat_message", "chat_notice", "chat_notice", "chat_message", "chat_notice"], [e.kind for e in first])
check("すべて backlog（反応しない）", all(e.backlog for e in first))
check("発言は名前と本文", (first[0].speaker, first[0].text) == ("伏せ字3", "伏せ字4"))
check("参加・いいねのお知らせは、誰がを speaker に", first[1].speaker == "伏せ字5" and first[2].speaker == "伏せ字3")
check("ルーム名の変更は speaker なし", first[4].speaker is None)
check("出どころは gravity・目印は一意", all(e.source == "gravity" for e in first) and len({e.key for e in first}) == 5)

print("■ T30 同じ画面を何周読んでも、新しい出来事は生まれない")
for _ in range(5):
    bridge.on_rows(ROWS)
check("T30 5周読んでも増えない", len(got) == 5, len(got))

print("■ 新しい行")
rows2 = ROWS + [msg("伏せ字7", "こんばんは")]
new = bridge.on_rows(rows2)
check("下に増えた1行だけ渡す", len(new) == 1 and new[0].text == "こんばんは" and not new[0].backlog, new)
rows3 = rows2 + [msg("伏せ字7", "こんばんは")]
new = bridge.on_rows(rows3)
check("同じ人が同じ文をもう一度言ったら、2つ目も新しい行", len(new) == 1 and not new[0].backlog)
rows4 = rows3[1:]
check("上へ流れて消えただけなら何も渡さない", bridge.on_rows(rows4) == [])
rows5 = [msg("伏せ字8", "昔の発言")] + rows4
new = bridge.on_rows(rows5)
check("⚠️ 上へ戻して出てきた昔の行は「前からあった」（今さら反応しない）", len(new) == 1 and new[0].backlog)
new = bridge.on_rows([msg("伏せ字9", "別のルームの発言"), msg("伏せ字9", "もう1つ")])
check("画面が丸ごと変わったら「前からあった」", len(new) == 2 and all(e.backlog for e in new))

print("■ 自分の発言・読めない行")
bridge.reset()
bridge.on_rows([])
new = bridge.on_rows([msg("自分の名前", "いらっしゃい！"), msg("伏せ字3", "どうも")],
                     is_own_text=lambda text: text == "いらっしゃい！")
check("空のチャット欄の次に出た行は新しい行", len(new) == 2 and not any(e.backlog for e in new))
check("自分が送った文は is_self", new[0].is_self and not new[1].is_self)
cut = dict(msg("", "名前が切れた発言"))
announcement = {"kind": A.CHAT_KIND_ANNOUNCEMENT, "name": "伏せ字3", "text": "アナウンス", "notice": "", "subject": "",
                "welcome": False, "box": (0, 0, 1, 1), "parts": ()}
bridge.reset()
check("名前が切れた発言・アナウンスは渡さない", bridge.on_rows([cut, announcement]) == [])
long_row = msg("伏せ字3", "あ" * 1000)
bridge.reset()
check("長すぎる本文は300字まで", len(bridge.on_rows([long_row])[0].text) == 300)

print("■ このアカウントの名前の発言は自分の発言（2026-10-15）")
mine = A.GravityChatBridge(lambda events: None, self_names=lambda: ["テストちゃ👼"])
mine.on_rows([])
new = mine.on_rows([msg("テストちゃ👼", "こんばんは"), msg("テストちゃ..", "名前が切れて出た"), msg("テストちゃん", "別の人"),
                    {"kind": A.CHAT_KIND_NOTICE, "name": "", "text": "テストちゃ👼さんが音声ルームにいいねをしました",
                     "notice": "like", "subject": "テストちゃ👼", "welcome": False, "box": (0, 0, 1, 1), "parts": ()},
                    {"kind": A.CHAT_KIND_NOTICE, "name": "", "text": "伏せ字5が音声ルームに参加しました",
                     "notice": "join", "subject": "伏せ字5", "welcome": False, "box": (0, 0, 1, 1), "parts": ()}])
check("アカウント名の発言は is_self", new[0].is_self)
check("名前が切れて出ても（先頭が同じなら）is_self", new[1].is_self)
check("似ているが違う名前は他の人", not new[2].is_self)
check("自分がしたこと（いいね）のお知らせも自分のこと", new[3].is_self and not new[4].is_self)

print("■ ルームの様子（ルーム名・人数・席・アナウンス。2026-10-16）")
rooms = []
b2 = A.GravityChatBridge(lambda events: None, on_room=rooms.append)
info = A.read_room_info(GUEST, 2)
check("ルームの画面から読む（押さない）", info == {"name": "伏せ字1", "permission": "プライベート音声ルーム",
                                                 "guests": "ゲスト（1人）", "seated": 4, "empty_seats": 2,
                                                 "muted_seats": 1, "my_mic": "on"}, info)
muted_screen = GUEST.replace('roomerBtnMicrophone" class="android.widget.ImageButton" package="anonymous.sns.community.gravity" '
                             'content-desc="" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" '
                             'focused="false" scrollable="false" long-clickable="false" password="false" selected="false"',
                             'roomerBtnMicrophone" class="android.widget.ImageButton" package="anonymous.sns.community.gravity" '
                             'content-desc="" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" '
                             'focused="false" scrollable="false" long-clickable="false" password="false" selected="true"')
check("下の帯のマイクのボタンが selected なら、AIのマイクはミュート（2026-10-16）", muted_screen != GUEST
      and A.read_room_info(muted_screen, 2)["my_mic"] == "muted")
check("ルームの画面でなければ読まない", A.read_room_info(fixture("voiceroom_minimized.xml"), 2) is None)
announce_rows = A.parse_chat_rows(fixture("voiceroom_announcement.xml"), 2)
b2.on_room(info, announce_rows)
check("アナウンスの行の本文も渡す", rooms and rooms[-1]["announcement"] == "伏せ字4", rooms)
b2.on_room(info, ROWS)
check("変わらなければ知らせない（アナウンスが流れて見えなくなっても覚えている）", len(rooms) == 1)
b2.on_room(dict(info, guests="ゲスト（2人）"), ROWS)
check("人数が変わったら知らせる", len(rooms) == 2 and rooms[-1]["guests"] == "ゲスト（2人）")

print("■ AI へつなぐ: 前からあった行には反応せず、新しい行で判断する")
a = Agent(mode=MODE_ENGAGE)
bridge = A.GravityChatBridge(lambda events: [a.runtime.submit(e) for e in events])
bridge.on_rows(ROWS)
check("前からあった行は記録だけ（R3。AI を呼ばない）", a.wait_decisions(1) and a.decisions()[-1][3] == "R3"
      and a.decide_calls() == [], a.decisions())
bridge.on_rows(ROWS + [msg("伏せ字7", "アイ、聞こえる？")])
check("新しい行で AI が判断して喋る", wait_until(lambda: len(a.speaker.spoken) == 1), a.logs[-3:])
check("AI には前からあった行も直近の会話として渡る", "伏せ字3: 伏せ字4" in a.decide_calls()[0].messages[0].content)
a.runtime.set_room_info({"name": "伏せ字1", "guests": "ゲスト（1人）", "seated": 4, "empty_seats": 2, "announcement": ""})
bridge.on_rows(ROWS + [msg("伏せ字7", "アイ、聞こえる？"), msg("伏せ字8", "アイちゃん、ルームどう？")])
check("ルームの様子も AI に渡る", wait_until(lambda: len(a.decide_calls()) == 2)
      and "ルーム名: 伏せ字1" in a.decide_calls()[-1].messages[0].content)
a.close()


# ----------------------------------------------------------------------
print("■ 監視の本体から AI へ渡す（キーワード自動返信は今まで通り）")
A.time.sleep = lambda seconds: None


class FakeRoom:
    """screens を順に返す（最後の画面を繰り返す）。rounds 周読んだら監視を止める"""

    def __init__(self, worker, screens, rounds):
        self.worker, self.screens, self.rounds, self.reads = worker, screens, rounds, 0

    def dump_hierarchy(self, compressed=True):
        self.reads += 1
        if self.reads > self.rounds:
            self.worker.is_running = False
        return self.screens[min(self.reads - 1, len(self.screens) - 1)]

    def window_size(self):
        return 540, 960


def run_monitor(pairs, screens, rounds, bridge):
    db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
    db.save_setting("mumu_target_package", GRAVITY)
    db.save_setting("cooldown_enabled", "0")
    set_id = db.get_keyword_sets()[0]["id"]
    for trigger in list(A.DEFAULT_KEYWORDS):
        db.delete_keyword(set_id, trigger)
    for trigger, reply, target in pairs:
        db.upsert_keyword(set_id, trigger, reply, target=target)
    logs, sent = [], []
    w = A.AutoReplyWorker(db, logs.append)
    w.is_running = True
    room = FakeRoom(w, screens, rounds)
    w._connect_to_emulator = lambda: room
    w._calculate_y_bounds = lambda d, y1, y2: (0, 960, 960)
    w._warn_if_target_app_not_foreground = lambda d: None
    w._perform_initial_scan = lambda d, a, b: None
    w._auto_dismiss_dialog = lambda d, all_nodes, xml_dump: False
    w._watch_foreground_change = lambda d: None
    w._scroll_down = lambda *a, **k: None

    def fake_execute(d, nodes, half_y, y1, y2, text, fc, thr, all_nodes=None):
        sent.append(text)
        return fc, True
    w._execute_reply = fake_execute
    w.set_agent_bridge(bridge)
    w._run_monitor(0, 0, 100, 100)
    return sent, logs, w


# 2つ目の画面: いちばん下の行（ルーム名の変更）が、新しい参加のお知らせに変わった（下に新しい行が出た）
JOINED = GUEST.replace("ルーム名を伏せ字1に変更しました", "伏せ字7が音声ルームに参加しました")
assert JOINED != GUEST
received = []
bridge = A.GravityChatBridge(received.extend)
sent, logs, w = run_monitor([("［参加したとき］", "{名前}さん、いらっしゃい！", "join")],
                            [GUEST, GUEST, GUEST, JOINED], rounds=8, bridge=bridge)
fresh = [e for e in received if not e.backlog]
check("始めた時点の5行は「前からあった」", len([e for e in received if e.backlog]) == 5, len(received))
check("新しい参加のお知らせを1回だけ AI へ渡す", [e.text for e in fresh] == ["伏せ字7が音声ルームに参加しました"], fresh)
check("キーワード自動返信は今まで通り（2人に1回ずつ）", sent == ["伏せ字5さん、いらっしゃい！", "伏せ字7さん、いらっしゃい！"], sent)
rooms = []
bridge = A.GravityChatBridge(lambda events: None, on_room=rooms.append)
run_monitor([("出てこない言葉", "x", A.KEYWORD_TARGET_ANY)], [GUEST], rounds=3, bridge=bridge)
check("監視の本体からルームの様子が届く", rooms and rooms[0]["name"] == "伏せ字1", rooms)

received.clear()
off = A.GravityChatBridge(received.extend, active=lambda: False)
calls = []
real_parse = A.parse_chat_rows
A.parse_chat_rows = lambda *a, **k: calls.append(1) or real_parse(*a, **k)
run_monitor([("こんにちは", "こんにちは！", A.KEYWORD_TARGET_ANY)], [GUEST], rounds=3, bridge=off)
check("渡さない間は何も渡さない", received == [])
check("渡さない間は、今まで通りチャット欄の行を読まない（重さを変えない）", calls == [], len(calls))
on = A.GravityChatBridge(received.extend)
run_monitor([("こんにちは", "こんにちは！", A.KEYWORD_TARGET_ANY)], [GUEST], rounds=3, bridge=on)
check("渡すときは、今まで通りのペアだけでも行を読む", len(calls) > 0 and len(received) == 5)
A.parse_chat_rows = real_parse

own = []
mine = A.GravityChatBridge(own.extend)
SAID = GUEST.replace("伏せ字6", "伏せ字5さん、いらっしゃい！")
run_monitor([("［参加したとき］", "{名前}さん、いらっしゃい！", "join")], [GUEST.replace("伏せ字6", "x"), SAID],
            rounds=6, bridge=mine)
said = [e for e in own if e.text == "伏せ字5さん、いらっしゃい！"]
check("自動返信で送った文がチャット欄に出たら、AI には自分の発言として渡す", said and all(e.is_self for e in said), said)

print("■ チャットしているGRAVITYのアカウント（長期記憶ファイル。2026-10-16）")
learned = []
acc = A.GravityChatBridge(lambda events: None, account=lambda: "テスト垢",
                          on_own_name=lambda name, text: learned.append((name, text)))
old = acc.on_rows([msg("テストちゃ👼", "前からあった自分の文")], is_own_text=lambda text: True)
check("起動前からあった行では、名前を覚えない", learned == [] and old[0].backlog)
new = acc.on_rows([msg("テストちゃ👼", "前からあった自分の文"), msg("テストちゃ👼", "送った文"), msg("伏せ字5", "他の人の文")],
                  is_own_text=lambda text: text == "送った文")
check("出来事に、今チャットしているGRAVITYのアカウントの名前を付ける",
      old[0].meta["account"] == "テスト垢" and all(e.meta["account"] == "テスト垢" for e in new))
check("自分が送った文の新しい行の、名前と本文を知らせる", learned == [("テストちゃ👼", "送った文")], learned)
tmp = A.GravityChatBridge(lambda events: None, account=lambda: ("本体のGRAVITY", False))
tmp.on_rows([])
ev = tmp.on_rows([msg("伏せ字5", "こんにちは")])
check("名前がまだ分からない（仮の呼び名）ことも出来事に付ける", ev[0].meta["account"] == "本体のGRAVITY"
      and ev[0].meta["account_named"] is False and new[0].meta["account_named"] is True)


class FakeShell:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def shell(self, command):
        self.calls += 1
        return type("R", (), {"output": self.text})()


db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
db.save_setting("mumu_target_package", GRAVITY)
w = A.AutoReplyWorker(db, lambda message: None)
dev = FakeShell(fixture("dumpsys_activities_clone.txt"))
w._target_display = 16
w._update_agent_account(dev)
check("今の画面のアカウントを見分ける（アプリ複製はユーザー10〜）", w.agent_account_user == "10", w.agent_account_user)
w._update_agent_account(dev)
check("同じ画面なら、毎周回は読み直さない", dev.calls == 1)
w._agent_account_checked_at -= A.AutoReplyWorker.AGENT_ACCOUNT_RECHECK_SECONDS + 1
w._update_agent_account(dev)
check("1分たったら読み直す（同じ画面で別のアカウントに替えたとき）", dev.calls == 2)
w._recent_manual_texts.append("こんばんは")
w._remember_own_text("伏せ字5さん、いらっしゃい！")
check("送った文とまったく同じ本文か（手入力・AI・自動返信）",
      w.was_sent_exactly("こんばんは") and w.was_sent_exactly(" 伏せ字5さん、いらっしゃい！ "))
check("含むだけでは数えない（他の人の「こんばんは、みなさん」）", not w.was_sent_exactly("こんばんは、みなさん")
      and not w.was_sent_exactly(""))

finish()
