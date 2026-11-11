# -*- coding: utf-8 -*-
"""
監視中にルームの画面でなくなったら、自動スクロールと入力を止め、音声ルームの画面に戻してから再開する。

2026-11-12 本人: 「（ミニプロフィールの）画面の時にエミュの自動スクロールが発動している場合、自動的に元の音声ルームの画面に
戻るようにしてほしい。他の画面になったときも同様に」「他の画面を検知したときに自動スクロールとキーボード入力を停止して
元の音声ルームに戻ってから停止を解除してまた動くようにしたい」

- 画面の積み重なりは `dumpsys activity activities` の「* Hist #N」の行で読む（fixtures/dumpsys_room_stack.txt は実物）
- ミニプロフィール（VoiceRoomPassportActivity）の実物の画面は fixtures/voiceroom_passport.xml（伏せ字済み。2026-10-22 の記録から）。
  開いているあいだは、画面の読み取りに後ろのチャット欄が出ない
- 監視の本体（_run_monitor）を、画面の積み重なりを持つにせの MuMu で回す。時計もにせ物にして、待ち時間を確かめる
"""
import os, sys, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A

FAILS = []
GRAVITY = "anonymous.sns.community.gravity"
CLS = f"{GRAVITY}/com.hiclub.android.gravity"
ROOM = f"{CLS}.metaverse.voiceroom.VoiceRoomActivity"
PASSPORT = f"{CLS}.metaverse.voiceroom.VoiceRoomPassportActivity"
MAIN = f"{CLS}.MainActivity"
WEB = f"{CLS}.web.WebViewActivity"


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


def fixture(name):
    with open(os.path.join(_HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()


GUEST = fixture("voiceroom_guest.xml")
PASSPORT_XML = fixture("voiceroom_passport.xml")
MINIMIZED = fixture("voiceroom_minimized.xml")          # 小さくしたあとのホーム。右に丸 bpvVoiceRoom [412,650][540,778]
NO_BUBBLE = MINIMIZED.replace(":id/bpvVoiceRoom", ":id/x")
INPUT_SHEET = fixture("voiceroom_input_sheet.xml")     # チャットの入力のシート（etText・btnSend）
GIFT_SHEET = INPUT_SHEET.replace(":id/etText", ":id/x")  # 入力欄の無いシート（ギフト・人の情報など）

print("■ 画面の積み重なりを読む（実物）")
REAL = fixture("dumpsys_room_stack.txt")
check("ルームの画面の下に MainActivity", A.parse_display_history(REAL, 2) == [ROOM, MAIN], A.parse_display_history(REAL, 2))
check("「.Cls」の省略形も直す（ディスプレイ0のホーム）",
      A.parse_display_history(REAL, 0) == ["app.lawnchair/app.lawnchair.LawnchairLauncher"])
check("並べ直した区切り（Hist の行が無い）は空", A.parse_display_history(REAL, 5) == [])
check("無いディスプレイ・番号が分からないときは空", A.parse_display_history(REAL, 7) == [] and A.parse_display_history(REAL, None) == [])
check("読めなければ空", A.parse_display_history("", 2) == [] and A.parse_display_history("error", 2) == [])

print("■ どう戻すか（plan_room_return）")
plan = lambda history, xml: A.plan_room_return(history, xml, 2, GRAVITY)
check("ルームの画面でチャット欄が見える → そのまま", plan([ROOM, MAIN], GUEST) == (A.ROOM_OK, None))
check("ミニプロフィールの実物では、チャット欄は読めない", A.find_chat_list_bounds(PASSPORT_XML, 2) is None)
check("ルームの上にミニプロフィール → 戻る", plan([PASSPORT, ROOM, MAIN], PASSPORT_XML) == (A.ROOM_BACK, None))
check("2枚重なっていても戻る（1枚ずつ閉じる）", plan([WEB, PASSPORT, ROOM, MAIN], NO_BUBBLE) == (A.ROOM_BACK, None))
check("ルームとの間に別のアプリが挟まっていたら戻るを押さない",
      plan([PASSPORT, "com.example/com.example.Main", ROOM], PASSPORT_XML) == (A.ROOM_LOST, None))
check("入力欄の無いシート（ギフトなど）→ 戻るで閉じる", plan([ROOM, MAIN], GIFT_SHEET) == (A.ROOM_SHEET, None))
check("チャットの入力のシート → 触らない（打っている途中かもしれない）", plan([ROOM, MAIN], INPUT_SHEET) == (A.ROOM_TYPING, None))
check("ルームの画面でチャット欄もシートも無い → 今まで通り（ルームで戻るを押さない）",
      plan([ROOM, MAIN], NO_BUBBLE) == (A.ROOM_UNKNOWN, None))
check("小さくしている → 右の丸の真ん中を押す", plan([MAIN], MINIMIZED) == (A.ROOM_BUBBLE, (476, 714)), plan([MAIN], MINIMIZED))
check("ルームに入っていない（丸も無い）→ 止めて待つだけ", plan([MAIN], NO_BUBBLE) == (A.ROOM_LOST, None))
check("別のアプリが前 → 止めて待つだけ", plan(["com.example/com.example.Main"], GUEST) == (A.ROOM_LOST, None))
check("積み重なりが読めない → 今まで通り", plan([], GUEST) == (A.ROOM_UNKNOWN, None))
check("ルームを止める状態は4つ", A.ROOM_AWAY_ACTIONS == {A.ROOM_BACK, A.ROOM_SHEET, A.ROOM_BUBBLE, A.ROOM_LOST})


# ----------------------------------------------------------------------
# にせの時計と MuMu
CLOCK = [0.0]
A.time.sleep = lambda seconds: CLOCK.__setitem__(0, CLOCK[0] + max(seconds, 0.01))
A.time.monotonic = lambda: CLOCK[0]
A.time.time = lambda: 1_000_000.0 + CLOCK[0]

SCREENS = {                       # 名前: (画面のクラス, 画面の読み取り)
    "main": (MAIN, MINIMIZED), "main_nobubble": (MAIN, NO_BUBBLE), "room": (ROOM, GUEST),
    "passport": (PASSPORT, PASSPORT_XML), "gift": (ROOM, GIFT_SHEET), "typing": (ROOM, INPUT_SHEET),
    "web_stuck": (WEB, NO_BUBBLE),
}


class FakeMuMu:
    """
    画面の積み重なり（下から）を持つ。戻るで1枚閉じ（シートは閉じてルームへ）、丸を押すとルームが開く。
    ⚠️ ルームの画面・ホームで戻るを押したら danger に残す（ルームから出る・アプリが閉じる）
    """

    def __init__(self, worker, stack, end=30.0, script=(), dumpsys=True):
        self.worker, self.stack, self.end = worker, list(stack), end
        self.script = sorted(script, key=lambda s: s[0])      # [(時刻, 画面を変える関数)]
        self.dumpsys = dumpsys
        self.events, self.danger, self.history_reads = [], [], 0

    @property
    def top(self):
        return self.stack[-1]

    def _run_script(self):
        while self.script and self.script[0][0] <= CLOCK[0]:
            self.script.pop(0)[1](self)

    def dump_hierarchy(self, compressed=True):
        CLOCK[0] += 0.05
        self._run_script()
        if CLOCK[0] > self.end:
            self.worker.is_running = False
        return SCREENS[self.top][1]

    def window_size(self):
        return 540, 960

    def shell(self, cmd):
        self._run_script()
        if cmd.startswith("dumpsys activity activities"):
            if cmd == A.DUMPSYS_HISTORY_COMMAND:
                self.history_reads += 1
            if not self.dumpsys:
                return ""
            comps = [SCREENS[name][0] for name in reversed(self.stack)]
            lines = ["Display #2 (activities from top to bottom):",
                     f"    topResumedActivity=ActivityRecord{{1 u0 {comps[0]} t46}}"]
            lines += [f"    * Hist  #{len(comps) - 1 - i}: ActivityRecord{{{i} u0 {c} t46}}" for i, c in enumerate(comps)]
            lines += ["Display #0 (activities from top to bottom):",
                      "      * Hist  #0: ActivityRecord{9 u0 app.lawnchair/.LawnchairLauncher t2}"]
            return "\n".join(lines)
        parts = cmd.split()
        if parts[:3] == ["input", "-d", "2"]:
            if parts[3] == "keyevent" and parts[4] == str(A.ANDROID_KEYCODE_BACK):
                self.events.append(("back", self.top, CLOCK[0]))
                if self.top in ("room", "main", "main_nobubble"):
                    self.danger.append(self.top)
                    if len(self.stack) > 1:
                        self.stack.pop()
                elif self.top in ("gift", "typing"):
                    self.stack[-1] = "room"
                elif self.top != "web_stuck":
                    self.stack.pop()
            elif parts[3] == "tap":
                x, y = int(parts[4]), int(parts[5])
                self.events.append(("tap", self.top, CLOCK[0], (x, y)))
                if self.top == "main" and 412 <= x <= 540 and 650 <= y <= 778:
                    self.stack.append("room")
            elif parts[3] == "swipe":
                self.events.append(("swipe", self.top, CLOCK[0], int(parts[8])))
        return ""

    def kinds(self, kind):
        return [e for e in self.events if e[0] == kind]


def open_screen(name):
    return lambda fake: fake.stack.append(name)


def replace_top(name):
    def change(fake):
        fake.stack[-1] = name
    return change


def close_top(fake):
    fake.stack.pop()


def make_worker(package=GRAVITY, auto_scroll="1", settings=None):
    db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
    db.save_setting("mumu_target_package", package)
    db.save_setting("emulator_auto_scroll", auto_scroll)
    for key, value in (settings or {}).items():
        db.save_setting(key, value)
    set_id = db.get_keyword_sets()[0]["id"]
    for trigger in list(A.DEFAULT_KEYWORDS):
        db.delete_keyword(set_id, trigger)
    logs, notes, sent = [], [], []
    w = A.AutoReplyWorker(db, logs.append)
    w.agent_note = notes.append
    return w, logs, notes, sent


def run(stack, script=(), end=30.0, auto=True, package=GRAVITY, auto_scroll="1", dumpsys=True, queue_at=(), settings=None):
    """監視を end 秒（にせの時計）回す。queue_at=[(時刻, 文)] で手入力の送信を積む"""
    CLOCK[0] = 0.0
    w, logs, notes, sent = make_worker(package, auto_scroll, settings)
    w.is_running = True
    script = list(script) + [(t, (lambda text: lambda fake: w._manual_queue.append(text))(text)) for t, text in queue_at]
    fake = FakeMuMu(w, stack, end, script, dumpsys)
    w._connect_to_emulator = lambda: fake
    w._calculate_y_bounds = lambda d, y1, y2: (0, 960, 960)
    w._warn_if_target_app_not_foreground = lambda d: None
    w._perform_initial_scan = lambda d, a, b: None
    w._auto_dismiss_dialog = lambda d, all_nodes, xml_dump: False
    w._watch_foreground_change = lambda d: None
    w._restore_target_app_if_left = lambda d: None
    w._find_and_tap_input = lambda d, nodes, half_y, all_nodes=None: True
    w._send_reply = lambda d, text: sent.append((fake.top, str(text), CLOCK[0])) or True
    if auto:
        w._run_monitor(None, None, None, None)
    else:
        w._run_monitor(0, 0, 100, 100)
    return fake, logs, notes, sent, w


def first_index(logs, part):
    return next((i for i, m in enumerate(logs) if part in m), None)


for auto in (True, False):
    label = "範囲を選ばずに開始" if auto else "範囲を選んで開始"
    print(f"■ ミニプロフィールが開いたら止めて、戻るで閉じ、ルームに戻ってから再開する（{label}）")
    fake, logs, notes, sent, w = run(["main", "room"], script=[(5.0, open_screen("passport"))],
                                     queue_at=[(5.5, "テスト")], auto=auto)
    backs = fake.kinds("back")
    check("戻るを1回だけ、ミニプロフィールの上で押す", [b[1] for b in backs] == ["passport"], fake.events)
    check("開いてから3秒以上待ってから戻す（開いた直後・人が押した直後にすぐ閉じない）",
          backs and backs[0][2] >= 8.0, backs)
    check("ミニプロフィールの上ではなぞらない", not [e for e in fake.kinds("swipe") if e[1] != "room"],
          [e for e in fake.kinds("swipe") if e[1] != "room"])
    check("戻る前も後も、ルームではなぞる（自動スクロール）",
          any(e[2] < 5.0 for e in fake.kinds("swipe")) and any(e[2] > backs[0][2] for e in fake.kinds("swipe")) if backs else False)
    check("止めているあいだに積んだ手入力は、ルームに戻ってから送る",
          [(s[0], s[1]) for s in sent] == [("room", "テスト")] and sent[0][2] > backs[0][2] if backs and sent else False, sent)
    i_pause, i_back, i_resume = (first_index(logs, "⏸️ 音声ルームの画面ではない"), first_index(logs, "↩️"),
                                 first_index(logs, "▶️ 音声ルームの画面に戻った"))
    check("止める → 戻す → 再開 の順にログに出す", None not in (i_pause, i_back, i_resume) and i_pause < i_back < i_resume,
          (i_pause, i_back, i_resume))
    check("止めた理由に画面の名前を出す", any("VoiceRoomPassportActivity" in m for m in logs if "⏸️" in m))
    check("止めた・再開したは1回ずつ", sum("⏸️ 音声ルームの画面ではない" in m for m in logs) == 1
          and sum("▶️ 音声ルームの画面に戻った" in m for m in logs) == 1)
    check("AIタブの判断のログにも出す", any("⏸️" in n for n in notes) and any("▶️" in n for n in notes), notes)
    check("ルームの画面で戻るを押していない", fake.danger == [], fake.danger)
    if auto:
        check("「チャット欄が見つかりません」より先に、止めた理由を出す",
              not any(m == A.CHAT_NOT_IN_ROOM for m in logs), [m for m in logs if "チャット欄" in m])

print("■ 入力の直前に、ルームの画面かを確かめる（3秒ごとの見張りの間に画面が変わっていても押さない）")
CLOCK[0] = 0.0
w, logs, notes, sent = make_worker()
fake = FakeMuMu(w, ["main", "room", "passport"])
w._target_display = "2"
w.is_running = True               # ⚠️ 止まっていると送信待ちを送らないので、「残した」が確かめにならない
taps = []
w._find_and_tap_input = lambda d, nodes, half_y, all_nodes=None: taps.append(fake.top) or True
w._send_reply = lambda d, text: sent.append(text) or True
w._restore_target_app_if_left = lambda d: None
w._scroll_down = lambda *a, **k: None
fc, ok = w._execute_reply(fake, [], 480, 0, 960, "こんにちは！", 0, 5)
check("返信: 入力欄を押さず、送らない", taps == [] and sent == [] and ok is False, (taps, sent))
check("返信: 失敗の回数に数えない（画面が違うだけ）", fc == 0)
check("返信: 次の周回で止めて戻すように、ルームの外と覚える", w._room_away is True and w._room_checked_at is None)
w._manual_queue.extend(["手入力1", "手入力2"])
fc, any_sent = w._drain_manual_sends(fake, [], 480, 0, 960, 0, 5)
check("手入力: 送らずに送信待ちに残す", sent == [] and list(w._manual_queue) == ["手入力1", "手入力2"] and not any_sent,
      list(w._manual_queue))
check("手入力: 「今は入力しません」と出す", any("今は入力しません" in m for m in logs), logs)
fake.stack.pop()
fc, any_sent = w._drain_manual_sends(fake, [], 480, 0, 960, 0, 5)
check("ルームに戻れば、積んだ順に送る", sent == ["手入力1", "手入力2"], sent)

print("■ 押す直前に読み直す（読んだあとにシートが閉じていたら、ルームの画面で戻るを押さない）")
CLOCK[0] = 100.0
w, logs, notes, sent = make_worker()
fake = FakeMuMu(w, ["main", "room"])       # シートはもう閉じている
w._target_display = "2"
w._room_state, w._room_away, w._room_away_since = (A.ROOM_SHEET, None, ROOM), True, 0.0
check("押さない", w._return_to_room_if_away(fake) is False and fake.events == [], fake.events)

print("■ ギフトなどのシートは戻るで閉じる。入力のシートは閉じない（打っている途中かもしれない）")
fake, logs, notes, sent, w = run(["main", "room"], script=[(5.0, replace_top("gift"))])
check("シートの上で戻るを1回", [b[1] for b in fake.kinds("back")] == ["gift"], fake.events)
check("シートを閉じたと出す", any("シートを、戻るで閉じます" in m for m in logs))
check("再開する", any("▶️ 音声ルームの画面に戻った" in m for m in logs))
fake, logs, notes, sent, w = run(["main", "room"], script=[(5.0, replace_top("typing")), (20.0, replace_top("room"))])
check("入力のシートでは戻るを押さない", fake.kinds("back") == [], fake.events)
check("止めたことにはしない（今まで通り「入力欄が開いている」と案内する）",
      not any("⏸️ 音声ルームの画面ではない" in m for m in logs) and A.CHAT_HIDDEN_BY_INPUT in logs,
      [m for m in logs if "⏸️" in m or "✍️" in m])

print("■ 小さくしたルームには、画面の右の丸を押して戻る")
fake, logs, notes, sent, w = run(["main"], queue_at=[(1.0, "おかえり")])
taps = fake.kinds("tap")
check("丸の真ん中を1回押す", [(t[1], t[3]) for t in taps] == [("main", (476, 714))], fake.events)
check("押したあとはルーム", fake.top == "room")
check("丸を押したと出してから再開する", first_index(logs, "🔼") is not None
      and first_index(logs, "🔼") < (first_index(logs, "▶️ 音声ルームの画面に戻った") or -1))
check("積んだ手入力はルームで送る", [(s[0], s[1]) for s in sent] == [("room", "おかえり")], sent)
check("ホームで戻るを押していない", fake.danger == [] and fake.kinds("back") == [])

print("■ ルームに入っていない（丸も無い）ときは、止めて待つだけ")
fake, logs, notes, sent, w = run(["main_nobubble"], queue_at=[(1.0, "送らない")], end=20.0)
check("何も押さない", fake.events == [] or not [e for e in fake.events if e[0] in ("back", "tap")], fake.events)
check("送らない", sent == [], sent)
check("ルームの画面になったら再開すると出す", any("音声ルームの画面になったら再開します" in m for m in logs),
      [m for m in logs if "⏸️" in m])

print("■ 自動スクロールが OFF なら、止めるだけでルームには戻さない（人が自分で戻すと再開）")
fake, logs, notes, sent, w = run(["main", "room"], script=[(5.0, open_screen("passport")), (15.0, close_top)],
                                 queue_at=[(6.0, "あとで")], auto_scroll="0")
check("戻るを押さない", fake.kinds("back") == [], fake.events)
check("OFF なので戻さないと出す", any("自動スクロールが OFF なので、ルームには戻しません" in m for m in logs),
      [m for m in logs if "⏸️" in m])
check("人がルームに戻したら再開して、積んだ手入力を送る",
      [(s[0], s[1]) for s in sent] == [("room", "あとで")] and sent[0][2] >= 15.0 if sent else False, sent)
check("なぞらない（OFF）", fake.kinds("swipe") == [])

print("■ 戻るが効かない画面では、5回でやめる")
fake, logs, notes, sent, w = run(["main", "room", "web_stuck"], end=60.0)
check("戻るは5回まで", len(fake.kinds("back")) == 5, len(fake.kinds("back")))
check("戻せなかったと1回だけ出す", sum("音声ルームの画面に戻せませんでした" in m for m in logs) == 1)
check("ルームで戻るを押していない", fake.danger == [])

print("■ GRAVITY 以外のアプリ・積み重なりが読めない端末では、今まで通り")
fake, logs, notes, sent, w = run(["main", "room", "passport"], package="com.example.other", queue_at=[(1.0, "そのまま")],
                                 auto=False, end=10.0)
check("ほかのアプリ: 積み重なりを読まない", fake.history_reads == 0, fake.history_reads)
check("ほかのアプリ: 止めずに送る（今まで通り）", [s[1] for s in sent] == ["そのまま"], sent)
fake, logs, notes, sent, w = run(["main", "room", "passport"], dumpsys=False, queue_at=[(1.0, "そのまま")],
                                 auto=False, end=10.0)
check("読めない: 何も押さない", not [e for e in fake.events if e[0] in ("back", "tap")], fake.events)
check("読めない: 止めない（今まで通り）", not any("⏸️ 音声ルームの画面ではない" in m for m in logs))

print("■ 自動スクロールの速さ（2026-11-12 本人「速度を指定設定保存できるように」→ 間隔となぞる速さの両方）")
fake, logs, notes, sent, w = run(["main", "room"], end=40.0)
swipes = fake.kinds("swipe")
gaps = [b[2] - a[2] for a, b in zip(swipes, swipes[1:])]
check("保存が無ければ今まで通り: 3秒あまりごとに、0.2秒でなぞる",
      swipes and all(3.0 <= g < 4.5 for g in gaps) and {s[3] for s in swipes} == {200}, (gaps, {s[3] for s in swipes}))
fake, logs, notes, sent, w = run(["main", "room"], end=40.0,
                                 settings={A.SCROLL_INTERVAL_SETTING: "10", A.SCROLL_SWIPE_SETTING: "0.6"})
swipes = fake.kinds("swipe")
gaps = [b[2] - a[2] for a, b in zip(swipes, swipes[1:])]
check("保存した間隔（10秒ごと）でなぞる", len(swipes) >= 3 and all(10.0 <= g < 11.5 for g in gaps), gaps)
check("保存した速さ（0.6秒かけて）でなぞる", {s[3] for s in swipes} == {600}, {s[3] for s in swipes})
check("ルームに戻す見張りは、間隔を長くしても3秒ごとのまま（ミニプロフィールはすぐ閉じる）",
      w.ROOM_CHECK_SECONDS == 3.0)
fake, logs, notes, sent, w = run(["main", "room"], end=30.0, settings={A.SCROLL_INTERVAL_SETTING: "60"},
                                 script=[(5.0, open_screen("passport"))])
backs = fake.kinds("back")
check("間隔を60秒にしても、ミニプロフィールは3秒あまりで閉じる", backs and backs[0][2] < 12.0, backs)

print()
print(f"結果: {'すべて通りました' if not FAILS else str(len(FAILS)) + ' 件失敗'}")
sys.exit(1 if FAILS else 0)
