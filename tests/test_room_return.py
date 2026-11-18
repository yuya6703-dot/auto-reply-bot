# -*- coding: utf-8 -*-
"""
監視中にルームの画面でなくなったら、自動スクロールと入力を止め、音声ルームの画面に戻してから再開する。
自動スクロールの間隔・なぞる速さを保存できる。

2026-11-12 本人: 「（ミニプロフィールの）画面の時にエミュの自動スクロールが発動している場合、自動的に元の音声ルームの画面に
戻るようにしてほしい。他の画面になったときも同様に」「他の画面を検知したときに自動スクロールとキーボード入力を停止して
元の音声ルームに戻ってから停止を解除してまた動くようにしたい」「自動スクロールの速度を指定設定保存できるようにしてほしい」
（間隔・なぞる速さの両方）

- ミニプロフィール（VoiceRoomPassportActivity）の実物の画面は fixtures/voiceroom_passport.xml（伏せ字済み。2026-10-22 の記録から）。
  開いているあいだは、画面の読み取りに後ろのチャット欄が出ない
- 画面の積み重なりは `dumpsys activity activities` の「* Hist #N」の行で読む（fixtures/dumpsys_room_stack.txt は実物）
- 監視の本体（_run_monitor）を、画面の積み重なりを持つにせの MuMu で回す。時計もにせ物にして、待ち時間を確かめる。
  確かめるのは外から見える動き（どの画面で何を押したか・どの画面で送ったか・ログ）。
  ⚠️ 前半（監視の本体）は前の版（v1.12.2）のコードでも動く形にしてある（直す前に正しい理由で落ちることを確かめるため）。
     新しく足した関数を直接確かめるのは後半
"""
import os, re, sys, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A

FAILS = []
GRAVITY = "anonymous.sns.community.gravity"
OTHER = "com.example.other"
CLS = f"{GRAVITY}/com.hiclub.android.gravity"
ROOM = f"{CLS}.metaverse.voiceroom.VoiceRoomActivity"
PASSPORT = f"{CLS}.metaverse.voiceroom.VoiceRoomPassportActivity"
MAIN = f"{CLS}.MainActivity"
WEB = f"{CLS}.web.WebViewActivity"
# 保存する設定の名前（利用者の app_data.db に残る。変えると前の版で保存した値を読めなくなる）
INTERVAL_KEY, SWIPE_KEY = "emulator_scroll_interval", "emulator_scroll_swipe_seconds"


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
# 別のアプリが前に出た画面。⚠️ GRAVITY の部品（チャット欄 rvMessages など）を名前だけ残した画面にしない
# （別のアプリにチャット欄は無い。残すと「チャット欄は見えている」ことになり、実物と違う順番で動く）
OTHER_XML = NO_BUBBLE.replace(GRAVITY, OTHER)

# ----------------------------------------------------------------------
# にせの時計と MuMu
CLOCK = [0.0]
A.time.sleep = lambda seconds: CLOCK.__setitem__(0, CLOCK[0] + max(seconds, 0.01))
A.time.monotonic = lambda: CLOCK[0]
A.time.time = lambda: 1_000_000.0 + CLOCK[0]

ANNOUNCE = fixture("voiceroom_announcement.xml")      # チャット欄にアナウンスの画像（押せる ivNotice [37,408][386,757]）
# チャット欄の、なぞり始めの高さ（751）の横一列が全部、押せる部品でふさがっている画面（作り物）
BLOCKED = GUEST.replace("</hierarchy>", f'<node index="0" text="" resource-id="{GRAVITY}:id/x" class="android.view.View" '
                        f'package="{GRAVITY}" clickable="true" long-clickable="false" bounds="[0,700][540,800]" '
                        'display-id="2" /></hierarchy>')
SCREENS = {                       # 名前: (画面のクラス, 画面の読み取り)
    "main": (MAIN, MINIMIZED), "main_nobubble": (MAIN, NO_BUBBLE), "room": (ROOM, GUEST),
    "passport": (PASSPORT, PASSPORT_XML), "gift": (ROOM, GIFT_SHEET), "typing": (ROOM, INPUT_SHEET),
    "web_stuck": (WEB, NO_BUBBLE), "other": (f"{OTHER}/{OTHER}.Main", OTHER_XML),
    "room_notice": (ROOM, ANNOUNCE), "room_blocked": (ROOM, BLOCKED),
}


def pressable_at(xml, x, y):
    """その画面で (x, y) にある、押せる・長押しできる部品の resource-id（テストの側で読む。アプリの関数は使わない）"""
    import xml.etree.ElementTree as ET
    hits = []
    for node in ET.fromstring(xml).iter("node"):
        if node.get("display-id") != "2":
            continue
        if node.get("clickable") != "true" and node.get("long-clickable") != "true":
            continue
        m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
        if m:
            l, tp, r, b = map(int, m.groups())
            if l <= x <= r and tp <= y <= b:
                hits.append((node.get("resource-id") or "").split("/")[-1])
    return hits
BUBBLE = (412, 650, 540, 778)


class ShellResult(str):
    """uiautomator2 の d.shell() の戻り値と同じく .output で中身を読める（_target_still_shown は .output を読む）"""

    @property
    def output(self):
        return str(self)


class FakeMuMu:
    """
    画面の積み重なり（下から）を持つ。戻るで1枚閉じ（シートは閉じてルームへ）、丸を押すとルームが開く。
    delay 秒たってから押した操作が効く（MuMu が重いとき）。⚠️ 押した操作は、押した順に、効く時刻の画面に届く。
    ルームの画面・ホームに届いた戻る（ルームから出る・アプリが閉じる）と、ルームの画面に届いたタップ（席などを押す）は danger に残す
    """

    def __init__(self, worker, stack, end=30.0, script=(), dumpsys=True, delay=0.0, traps=None, open_on_read=None,
                 fail_every=0, open_on_touch=None):
        self.worker, self.stack, self.end, self.dumpsys, self.delay = worker, list(stack), end, dumpsys, delay
        self.script = sorted(script, key=lambda s: s[0])      # [(時刻, 画面を変える関数)]
        self.pending = []                                     # [(効く時刻, 操作, 位置)]
        self.events, self.danger, self.history_reads, self.dumps, self.shell_log = [], [], 0, [], []
        self.traps = dict(traps or {})          # {N: 画面を変える関数} N回目に積み重なりを読まれる直前に画面を変える
        self.open_on_read = open_on_read        # (時刻, 画面の名前) その時刻のあと、初めて積み重なりを読まれる直前に開く
        self.open_on_touch = open_on_touch      # (時刻, 画面の名前) その時刻のあと、初めて積み重なりを読まれるか、なぞられる直前に開く
        self.fail_every = fail_every            # N回に1回、画面の読み取りがエラーになる（たまのエラー）
        self.window_size_calls = 0

    @property
    def top(self):
        return self.stack[-1]

    def _settle(self):
        while True:
            due = [(t, "script", f) for t, f in self.script[:1]] + [(t, k, p) for t, k, p in self.pending[:1]]
            due = [x for x in due if x[0] <= CLOCK[0]]
            if not due:
                return
            first = min(due, key=lambda x: x[0])
            if first[1] == "script":
                self.script.pop(0)[1](self)
            else:
                self.pending.pop(0)
                self._apply(first[1], first[2])

    def _apply(self, kind, where):
        top = self.top
        if kind == "back":
            if top in ("room", "main", "main_nobubble"):
                self.danger.append(("back", top))
                if len(self.stack) > 1:
                    self.stack.pop()
            elif top in ("gift", "typing"):
                self.stack[-1] = "room"
            elif top != "web_stuck":
                self.stack.pop()
        elif kind == "tap":
            x, y = where
            if top == "main" and BUBBLE[0] <= x <= BUBBLE[2] and BUBBLE[1] <= y <= BUBBLE[3]:
                self.stack.append("room")
            elif top in ("room", "gift", "typing"):
                self.danger.append(("tap", top, where))

    def _press(self, kind, where=None):
        self.events.append((kind, self.top, CLOCK[0]) + ((where,) if where else ()))
        last = self.pending[-1][0] if self.pending else 0.0
        self.pending.append((max(CLOCK[0] + self.delay, last + 0.01), kind, where))
        self._settle()

    def dump_hierarchy(self, compressed=True):
        CLOCK[0] += 0.05
        self._settle()
        self.dumps.append(CLOCK[0])
        if CLOCK[0] > self.end:
            self.worker.is_running = False
        if self.fail_every and len(self.dumps) % self.fail_every == 0:
            raise RuntimeError("テスト用のたまのエラー")
        return SCREENS[self.top][1]

    def window_size(self):
        self.window_size_calls += 1
        return 540, 960

    def app_start(self, package, *args, **kwargs):
        self.events.append(("app_start", package, CLOCK[0]))
        if self.top == "other" and package == GRAVITY:
            self.stack.pop()

    def shell(self, cmd):
        self._settle()
        self.shell_log.append(cmd)
        if self.open_on_touch and CLOCK[0] >= self.open_on_touch[0] and ("Hist" in cmd or " swipe " in cmd):
            self.stack.append(self.open_on_touch[1])
            self.open_on_touch = None
        if cmd.startswith("dumpsys activity activities"):
            if "Hist" in cmd:
                self.history_reads += 1
                if self.history_reads in self.traps:
                    self.traps.pop(self.history_reads)(self)
                if self.open_on_read and CLOCK[0] >= self.open_on_read[0]:
                    self.stack.append(self.open_on_read[1])
                    self.open_on_read = None
            if not self.dumpsys:
                return ShellResult("")
            comps = [SCREENS[name][0] for name in reversed(self.stack)]
            lines = ["Display #2 (activities from top to bottom):",
                     f"    topResumedActivity=ActivityRecord{{1 u0 {comps[0]} t46}}"]
            lines += [f"    * Hist  #{len(comps) - 1 - i}: ActivityRecord{{{i} u0 {c} t46}}" for i, c in enumerate(comps)]
            lines += ["Display #0 (activities from top to bottom):",
                      "      topResumedActivity=ActivityRecord{9 u0 app.lawnchair/.LawnchairLauncher t2}",
                      "      * Hist  #0: ActivityRecord{9 u0 app.lawnchair/.LawnchairLauncher t2}"]
            # 実物と同じく grep で絞る（「grep topResumedActivity」なら前面の行だけ。下に積まれた GRAVITY は出ない）
            if "| grep" in cmd:
                words = re.findall(r"-e '([^']+)'", cmd) or [cmd.split("| grep", 1)[1].split()[-1]]
                lines = [line for line in lines if any(word in line for word in words)]
            return ShellResult("\n".join(lines))
        parts = cmd.split()
        if parts[:3] == ["input", "-d", "2"]:
            if parts[3] == "keyevent" and parts[4] == str(A.ANDROID_KEYCODE_BACK):
                self._press("back")
            elif parts[3] == "tap":
                self._press("tap", (int(parts[4]), int(parts[5])))
            elif parts[3] == "swipe":
                self.events.append(("swipe", self.top, CLOCK[0], int(parts[8]), (int(parts[4]), int(parts[5]))))
                CLOCK[0] += int(parts[8]) / 1000      # 実物の input swipe も、なぞり終えるまで戻ってこない
        return ShellResult("")

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


def run(stack, script=(), end=30.0, auto=True, package=GRAVITY, auto_scroll="1", dumpsys=True, queue_at=(),
        settings=None, delay=0.0, watch_foreground=False, pairs=(), traps=None, open_on_read=None, fail_every=0,
        open_on_touch=None):
    """監視を end 秒（にせの時計）回す。queue_at=[(時刻, 文)] で手入力の送信を積む。pairs=[(検知ワード, 返信ワード)]"""
    CLOCK[0] = 0.0
    w, logs, notes, sent = make_worker(package, auto_scroll, settings)
    if pairs:
        set_id = w.db.get_keyword_sets()[0]["id"]
        for trigger, reply in pairs:
            w.db.upsert_keyword(set_id, trigger, reply)
    w.is_running = True
    script = list(script) + [(t, (lambda text: lambda fake: w._manual_queue.append(text))(text)) for t, text in queue_at]
    fake = FakeMuMu(w, stack, end, script, dumpsys, delay, traps, open_on_read, fail_every, open_on_touch)
    w._connect_to_emulator = lambda: fake
    w._calculate_y_bounds = lambda d, y1, y2: (0, 960, 960)
    w._warn_if_target_app_not_foreground = lambda d: None
    w._perform_initial_scan = lambda d, a, b: None
    w._auto_dismiss_dialog = lambda d, all_nodes, xml_dump: False
    if not watch_foreground:
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
          bool(backs) and 8.0 <= backs[0][2] < 10.0, backs)
    check("ミニプロフィールの上ではなぞらない", not [e for e in fake.kinds("swipe") if e[1] != "room"],
          [e for e in fake.kinds("swipe") if e[1] != "room"])
    check("戻る前も後も、ルームではなぞる（自動スクロール）",
          any(e[2] < 5.0 for e in fake.kinds("swipe")) and any(e[2] > backs[0][2] for e in fake.kinds("swipe"))
          if backs else False, fake.kinds("swipe"))
    check("止めているあいだに積んだ手入力は、ルームに戻ってから送る",
          [(s[0], s[1]) for s in sent] == [("room", "テスト")] and sent[0][2] > backs[0][2] if backs and sent else False,
          sent)
    i_pause, i_back, i_resume = (first_index(logs, "⏸️ 音声ルームの画面ではない"), first_index(logs, "↩️"),
                                 first_index(logs, "▶️ 音声ルームの画面に戻った"))
    check("止める → 戻す → 再開 の順にログに出す", None not in (i_pause, i_back, i_resume) and i_pause < i_back < i_resume,
          (i_pause, i_back, i_resume))
    check("止めた理由に画面の名前を出す", any("VoiceRoomPassportActivity" in m for m in logs if "⏸️" in m),
          [m for m in logs if "⏸️" in m])
    check("止めた・再開したは1回ずつ", sum("⏸️ 音声ルームの画面ではない" in m for m in logs) == 1
          and sum("▶️ 音声ルームの画面に戻った" in m for m in logs) == 1)
    check("AIタブの判断のログにも出す", any("⏸️" in n for n in notes) and any("▶️" in n for n in notes), notes)
    check("ルームの画面で戻るを押していない", fake.danger == [], fake.danger)

print("■ ミニプロフィールがいつ開いても、「チャット欄が見つかりません」より先に止めた理由を出す（開く時刻を0.1秒ずつずらす）")
bad = []
for i in range(30):
    opened = 5.0 + i * 0.1
    fake, logs, notes, sent, w = run(["main", "room"], script=[(opened, open_screen("passport"))], end=opened + 6.0)
    i_pause = first_index(logs, "⏸️ 音声ルームの画面ではない")
    if i_pause is None or A.CHAT_NOT_IN_ROOM in logs[:i_pause] or fake.danger:
        bad.append((round(opened, 2), i_pause, A.CHAT_NOT_IN_ROOM in logs, fake.danger))
check("30通りすべて", bad == [], bad[:3])

print("■ 入力の直前に、ルームの画面かを確かめる（3秒ごとの見張りの間に画面が変わっていても押さない）")
for what in ("返信", "手入力"):
    CLOCK[0] = 0.0
    w, logs, notes, sent = make_worker()
    fake = FakeMuMu(w, ["main", "room", "passport"])
    w._target_display = "2"
    w.is_running = True               # ⚠️ 止まっていると送信待ちを送らないので、「残した」が確かめにならない
    taps = []
    w._find_and_tap_input = lambda d, nodes, half_y, all_nodes=None: taps.append(fake.top) or True
    w._send_reply = lambda d, text: sent.append((fake.top, text)) or True
    w._restore_target_app_if_left = lambda d: None
    w._scroll_down = lambda *a, **k: None
    if what == "返信":
        fc, ok = w._execute_reply(fake, [], 480, 0, 960, "こんにちは！", 0, 5)
        check("返信: ミニプロフィールの上で入力欄を押さず、送らない", taps == [] and sent == [] and ok is False, (taps, sent))
        check("返信: 失敗の回数に数えない（画面が違うだけ）", fc == 0, fc)
    else:
        w._manual_queue.extend(["手入力1", "手入力2"])
        fc, any_sent = w._drain_manual_sends(fake, [], 480, 0, 960, 0, 5)
        check("手入力: 送らずに送信待ちに残す", sent == [] and list(w._manual_queue) == ["手入力1", "手入力2"],
              (sent, list(w._manual_queue)))
    check(f"{what}: 「今は入力しません」と出す", any("今は入力しません" in m for m in logs), logs[-3:])

print("■ 取り出したあとに断られた手入力・AIの文は、送信待ちの先頭に戻す（消さない。2026-11-14 見直し）")
# 送信待ちから取り出す前の確かめ（1回目に読む）ではルーム、取り出してから押す前の確かめ（2回目に読む）までの間に
# ミニプロフィールが開いた場合
CLOCK[0] = 0.0
w, logs, notes, sent = make_worker()
fake = FakeMuMu(w, ["main", "room"], traps={2: open_screen("passport")})
w._target_display = "2"
w.is_running = True
w._find_and_tap_input = lambda d, nodes, half_y, all_nodes=None: True
w._send_reply = lambda d, text: sent.append((fake.top, text)) or True
w._restore_target_app_if_left = lambda d: None
w._scroll_down = lambda *a, **k: None
w._manual_queue.extend(["手入力1", "手入力2"])
fc, any_sent = w._drain_manual_sends(fake, [], 480, 0, 960, 0, 5)
check("取り出したあとに画面が変わった（この確かめの形になっている）", fake.top == "passport" and fake.history_reads == 2,
      (fake.stack, fake.history_reads))
check("送らずに、取り出した文を送信待ちの先頭に戻す", sent == [] and list(w._manual_queue) == ["手入力1", "手入力2"],
      (sent, list(w._manual_queue)))
check("「失敗しました」とは出さない（送っていない）", not any("失敗しました" in m for m in logs), logs[-3:])
fake.stack.pop()
# 次の周回の始めと同じく、見張り（_room_gate）がルームの画面に戻ったことを読んでから送る
check("次の周回の見張りで、ルームの画面に戻ったと分かる", w._room_gate(fake, fake.dump_hierarchy()) is False)
fc, any_sent = w._drain_manual_sends(fake, [], 480, 0, 960, 0, 5)
check("ルームに戻れば、積んだ順に送る", [s[1] for s in sent] == ["手入力1", "手入力2"], sent)

print("■ メンション付きのAIの文を戻すときは、メンションを外す・緊急停止のあとなら戻さない（2026-11-14 実機での押し方の見直し）")
for case in ("メンションを外して戻す", "緊急停止のあとは戻さない"):
    CLOCK[0] = 0.0
    w, logs, notes, sent = make_worker()
    fake = FakeMuMu(w, ["main", "room"], traps={2: open_screen("passport")})
    w._target_display = "2"
    w.is_running = True
    w.agent_note = notes.append
    w._find_and_tap_input = lambda d, nodes, half_y, all_nodes=None: True
    w._send_reply = lambda d, text: sent.append((fake.top, str(text))) or True
    w._restore_target_app_if_left = lambda d: None
    w._scroll_down = lambda *a, **k: None
    tried = []

    def mention_failed(d, text, name, w=w, case=case):
        # ダブルタップでメンションが付かなかった（ミニプロフィールが開いた）。緊急停止はその途中で押された
        tried.append(name)
        if case == "緊急停止のあとは戻さない":
            w.discard_agent_texts()
        return None
    w._send_with_mention = mention_failed
    item = A.AgentChatText("こんばんは")
    item.mention = "伏せ字3"
    w._manual_queue.append(item)
    w._drain_manual_sends(fake, [], 480, 0, 960, 0, 5)
    queue = list(w._manual_queue)
    if case == "メンションを外して戻す":
        check("メンションを試したAIの文は、メンションを外して先頭に戻す（AIの文の印は残す）",
              tried == ["伏せ字3"] and len(queue) == 1 and isinstance(queue[0], A.AgentChatText)
              and str(queue[0]) == "こんばんは" and not queue[0].mention and sent == [], (tried, queue, sent))
    else:
        check("取り出したあとに緊急停止が押されたAIの文は、戻さずに捨てる", queue == [] and sent == [], (queue, sent))
        check("送らなかったと、ログと AI の判断のログに出す",
              any("緊急停止" in m for m in logs) and any("緊急停止" in n for n in notes), (logs[-2:], notes[-2:]))

print("■ なぞる直前にミニプロフィールが開いても、その上をなぞらない（開く時刻を0.05秒ずつずらす。2026-11-14 実機での押し方の見直し）")
# 0.2秒ごとになぞる設定で、周回の始めに画面を読んだあと、なぞる直前（積み重なりを読む・なぞる、のどちらかの直前）に開く
bad, resumed = [], 0
for i in range(60):
    opened = round(3.0 + i * 0.05, 2)
    fake, logs, notes, sent, w = run(["main", "room"], settings={INTERVAL_KEY: "0.2", SWIPE_KEY: "0.05"},
                                     open_on_touch=(opened, "passport"), end=opened + 5.0)
    on_passport = [e for e in fake.events if e[0] in ("swipe", "tap") and e[1] == "passport"]
    if on_passport:
        bad.append((opened, on_passport[:1]))
    backs = fake.kinds("back")
    if backs and any(e[0] == "swipe" and e[1] == "room" and e[2] > backs[0][2] for e in fake.events):
        resumed += 1
check("60通りすべて、ミニプロフィールの上ではなぞらない", bad == [], bad[:3])
check("60通りすべて、戻るで閉じてルームに戻ったら、またなぞる", resumed == 60, resumed)

print("■ なぞり始めは、押せる部品の無い所から（重いときにタップとして届いても何も押さない。2026-11-14 実機での押し方の見直し）")
for screen, label in (("room", "ゲストの画面（吹き出しが x 86〜304）"), ("room_notice", "アナウンスの画像（x 37〜386）がある画面")):
    fake, logs, notes, sent, w = run(["main", screen], settings={INTERVAL_KEY: "0.5", SWIPE_KEY: "0.05"}, end=10.0)
    swipes = fake.kinds("swipe")
    pressed = [(e[4], pressable_at(SCREENS[screen][1], *e[4])) for e in swipes if pressable_at(SCREENS[screen][1], *e[4])]
    check(f"{label}: なぞり始めに押せる部品が無い", bool(swipes) and pressed == [], (len(swipes), pressed[:2], swipes[:1]))
fake, logs, notes, sent, w = run(["main", "room_blocked"], settings={INTERVAL_KEY: "0.5", SWIPE_KEY: "0.05"}, end=10.0)
check("なぞり始めの高さの横一列が全部押せる部品でふさがっていたら、なぞらない", fake.kinds("swipe") == [], fake.kinds("swipe")[:2])

print("■ 入力の直前にルームの外と分かった周回は、なぞらない（開く時刻を0.05秒ずつずらす。2026-11-14 見直し）")
# 0.2秒ごとになぞる設定で、手入力を積んだ直後に読むときにミニプロフィールが開く。見張り（周回の始め）の読み取りに
# 当たるときと、入力の直前の確かめに当たるときがある。どちらでも、ミニプロフィールの上をなぞったり送ったりしない
bad, jit_hits = [], 0
for i in range(60):
    queued = round(3.0 + i * 0.05, 2)
    fake, logs, notes, sent, w = run(["main", "room"], auto=False, queue_at=[(queued, "あとで")], end=queued + 6.0,
                                     settings={INTERVAL_KEY: "0.2", SWIPE_KEY: "0.05"}, open_on_read=(queued, "passport"))
    on_passport = [e for e in fake.events if e[0] in ("swipe", "tap") and e[1] == "passport"]
    if on_passport or [s for s in sent if s[0] != "room"]:
        bad.append((queued, on_passport[:2], sent))
    if any("今は入力しません" in m for m in logs):
        jit_hits += 1
check("60通りすべて、ミニプロフィールの上ではなぞらず送らない", bad == [], bad[:2])
check("入力の直前の確かめで見つかった形も試している", jit_hits >= 1, jit_hits)

print("■ ルームの外で送らなかった自動返信は、ルームに戻ったらすぐ返す（送ったことにしない。2026-11-14 見直し）")
# 1回目の読み取りは周回の始めの見張り（ルーム）、2回目は返信の入力の直前の確かめ。その間にミニプロフィールが開く
fake, logs, notes, sent, w = run(["main", "room"], pairs=[("が音声ルームに参加しました", "いらっしゃい")],
                                 traps={2: open_screen("passport")}, end=14.0)
backs = fake.kinds("back")
check("入力の直前に見つけて、そのときは送らない", any("今は入力しません" in m for m in logs) and not [s for s in sent if s[0] != "room"],
      (sent, [m for m in logs if "⏸️" in m]))
check("ミニプロフィールを閉じてルームに戻ったら、すぐ返す（15秒待たない）",
      bool(backs) and [(s[0], s[1]) for s in sent] == [("room", "いらっしゃい")] and sent[0][2] - backs[0][2] < 3.0,
      (backs, sent))

print("■ 止めているあいだのたまのエラーで、自動停止しない（2026-11-14 見直し）")
for auto, dumpsys, label in ((False, True, "範囲を選んで開始・ミニプロフィールで止めている"),
                             (True, False, "範囲を選ばずに開始・積み重なりが読めずチャット欄が無い")):
    fake, logs, notes, sent, w = run(["main", "room"], script=[(2.0, open_screen("passport"))], auto=auto, dumpsys=dumpsys,
                                     auto_scroll="0", fail_every=8, end=60.0)
    errors = sum("エラーが発生しました" in m for m in logs)
    check(f"{label}: たまのエラーがあっても、最後まで動き続ける",
          errors >= 5 and not any("自動停止します" in m for m in logs) and fake.dumps[-1] > 59.0,
          (errors, [m for m in logs if "自動停止" in m], fake.dumps[-1]))

print("■ なぞるたびに画面の大きさを読まない（d.window_size() は adb で読む。2026-11-14 見直し）")
fake, swipes_log, notes, sent, w = run(["main", "room"], settings={INTERVAL_KEY: "0.2", SWIPE_KEY: "0.05"}, end=20.0)
check("20秒で60回以上なぞっても、画面の大きさを読むのは数回だけ",
      len(fake.kinds("swipe")) >= 60 and fake.window_size_calls <= 3, (len(fake.kinds("swipe")), fake.window_size_calls))

print("■ なぞった直後に別のアプリが前に出たら、「スクロールの直後」と名指しする（2026-11-14 見直し）")
fake, logs, notes, sent, w = run(["main", "room"], end=8.0)
first_swipe = fake.kinds("swipe")[0][2] if fake.kinds("swipe") else 3.0
fake, logs, notes, sent, w = run(["main", "room"], script=[(round(first_swipe + 0.25, 2), open_screen("other"))], end=10.0)
check("「【スクロール】の直後に対象アプリが表示から消えました」と出す",
      any("【スクロール】の直後に対象アプリが表示から消えました" in m for m in logs), [m for m in logs if "🔀" in m or "⏸️" in m])
fake, logs, notes, sent, w = run(["main", "room"], script=[(round(first_swipe + 2.5, 2), open_screen("other"))], end=10.0)
check("なぞってしばらくたってから出たときは、スクロールのせいにしない",
      not any("【スクロール】の直後" in m for m in logs) and any("⏸️ 音声ルームの画面ではない" in m for m in logs),
      [m for m in logs if "🔀" in m or "⏸️" in m])

print("■ 押す直前に読み直す（読んだあとにシートが閉じたら、ルームの画面で戻るを押さない。閉じる時刻を0.01秒ずつずらす）")
fake, logs, notes, sent, w = run(["main", "room"], script=[(5.0, replace_top("gift"))], end=15.0)
backs = fake.kinds("back")
check("（基準）閉じなければ、シートの上で戻るを1回", [b[1] for b in backs] == ["gift"], fake.events)
pressed_at = backs[0][2] if backs else 9.0
before = [t for t in fake.dumps if t < pressed_at]
loop_read = before[-2] if len(before) >= 2 else pressed_at - 0.05    # 決めた周回の読み取り（その次が押す直前の読み直し）
hit, bad = 0, []
for i in range(41):
    closed = round(pressed_at - 0.30 + i * 0.01, 2)
    fake, logs, notes, sent, w = run(["main", "room"], script=[(5.0, replace_top("gift")), (closed, replace_top("room"))],
                                     end=closed + 5.0)
    if fake.danger:
        bad.append((closed, fake.danger))
    if loop_read < closed <= pressed_at and not fake.kinds("back"):
        hit += 1                    # 周回の読み取りでは開いていたのに、押す直前に閉じていた → 押さなかった
check("どの時刻に閉じても、ルームの画面で戻るを押さない", bad == [], bad[:3])
check("読んでから押すまでの間に閉じた時刻も試している", hit >= 1, (loop_read, pressed_at, hit))

print("■ MuMu が重く、押してから画面が変わるまで2秒かかっても、2回目を押さない")
fake, logs, notes, sent, w = run(["main", "room"], script=[(5.0, open_screen("passport"))], delay=2.0, end=25.0)
check("戻るは1回だけ", [b[1] for b in fake.kinds("back")] == ["passport"], fake.events)
check("2回目の戻るがルームに届いていない（ルームから出ない）", fake.danger == [], fake.danger)
check("閉じたら再開する", any("▶️ 音声ルームの画面に戻った" in m for m in logs) and fake.top == "room", fake.stack)
fake, logs, notes, sent, w = run(["main"], delay=2.0, end=25.0)
check("小さくしたルーム: 丸は1回だけ押す", len(fake.kinds("tap")) == 1, fake.kinds("tap"))
check("小さくしたルーム: 開いたルームの同じ位置（席など）を押していない", fake.danger == [], fake.danger)
check("小さくしたルーム: 開いたら再開する", any("▶️ 音声ルームの画面に戻った" in m for m in logs) and fake.top == "room")

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
check("何も押さない", not [e for e in fake.events if e[0] in ("back", "tap")], fake.events)
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

print("■ 別のアプリが前に出たら、止めて待ち、今まで通り見張る（自動起動が ON なら開き直す）")
for auto in (True, False):
    fake, logs, notes, sent, w = run(["main", "room"], script=[(5.0, open_screen("other"))], queue_at=[(6.0, "戻ったら")],
                                     settings={"mumu_auto_launch": "1"}, watch_foreground=True, auto=auto, end=40.0)
    label = "範囲を選ばずに開始" if auto else "範囲を選んで開始"
    check(f"{label}: 表示から消えたと知らせて、GRAVITY を開き直す",
          any("監視対象のアプリが表示から消えました" in m for m in logs) and [e[1] for e in fake.kinds("app_start")] == [GRAVITY],
          (fake.kinds("app_start"), [m for m in logs if "消えました" in m]))
    check(f"{label}: 別のアプリの上では送らず、戻ってから送る", [(s[0], s[1]) for s in sent] == [("room", "戻ったら")], sent)
    check(f"{label}: 別のアプリの上ではなぞらず、何も押さない",
          not [e for e in fake.events if e[0] in ("swipe", "back", "tap") and e[1] == "other"], fake.events)

print("■ GRAVITY 以外のアプリ・積み重なりが読めない端末では、今まで通り")
# ⚠️ 監視するアプリの画面（その部品のあるディスプレイ）を出しておく。GRAVITY の画面だけだと、ディスプレイが決まらずに
#    パッケージの守りまで届かず、守りを外しても通ってしまう（2026-11-14 見直し）
fake, logs, notes, sent, w = run(["other"], package=OTHER, queue_at=[(1.0, "そのまま")], auto=False, end=10.0)
check("ほかのアプリ: 監視するアプリの画面のディスプレイが決まっている（守りまで届く）", w._target_display == "2", w._target_display)
check("ほかのアプリ: 積み重なりを読まない", fake.history_reads == 0, fake.history_reads)
check("ほかのアプリ: 止めずに送る（今まで通り）", [s[1] for s in sent] == ["そのまま"], sent)
fake, logs, notes, sent, w = run(["main", "room", "passport"], dumpsys=False, queue_at=[(1.0, "そのまま")],
                                 auto=False, end=10.0)
check("読めない: 何も押さない", not [e for e in fake.events if e[0] in ("back", "tap")], fake.events)
check("読めない: 止めない（今まで通り）", not any("⏸️ 音声ルームの画面ではない" in m for m in logs))

print("■ 自動スクロールの速さ（2026-11-12 本人「速度を指定設定保存できるように」→ 間隔となぞる速さの両方。"
      "2026-11-14 本人「今以上に早くできるようにしてほしい」）")


def scroll_run(settings=None, end=40.0):
    """ルームの画面で監視を回し、(にせのMuMu, なぞった記録, なぞり始めどうしの間隔, なぞった時間ms) を返す"""
    fake, logs, notes, sent, w = run(["main", "room"], end=end, settings=settings)
    swipes = fake.kinds("swipe")
    return fake, swipes, [round(b[2] - a[2], 2) for a, b in zip(swipes, swipes[1:])], {s[3] for s in swipes}


fake, swipes, gaps, durations = scroll_run()
check("保存が無ければ今まで通り: 3秒ごとに、0.2秒でなぞる（なぞり始めから次のなぞり始めまで3秒あまり）",
      bool(swipes) and all(3.0 <= g < 3.5 for g in gaps) and durations == {200}, (gaps, durations))
fake, swipes, gaps, durations = scroll_run({INTERVAL_KEY: "10", SWIPE_KEY: "0.6"})
check("保存した間隔（10秒ごと）でなぞる", len(swipes) >= 3 and all(10.0 <= g < 10.5 for g in gaps), gaps)
check("保存した速さ（0.6秒かけて）でなぞる", durations == {600}, durations)
fake, swipes, gaps, durations = scroll_run({INTERVAL_KEY: "0.5", SWIPE_KEY: "0.05"}, end=20.0)
check("今より速く: 0.5秒ごと・とても速い（0.05秒）で、本当に0.5秒あまりごとになぞる（前は待ちが足されて1.5秒ほどだった）",
      len(swipes) >= 25 and all(0.5 <= g < 0.75 for g in gaps) and durations == {50}, (gaps[:6], durations, len(swipes)))
fake, swipes, gaps, durations = scroll_run({INTERVAL_KEY: "0.2", SWIPE_KEY: "0.05"}, end=20.0)
check("今より速く: 0.2秒ごとまで縮められる", len(swipes) >= 50 and all(0.2 <= g < 0.4 for g in gaps), (gaps[:6], len(swipes)))
app_checks = [c for c in fake.shell_log if "grep topResumedActivity" in c]
check("なぞるたびに、アプリが消えていないかを確かめない（3秒に1回。なぞる回数が増えても重くしない）",
      0 < len(app_checks) <= 20 / 3 + 2, len(app_checks))
fake, swipes, gaps, durations = scroll_run({INTERVAL_KEY: "0.5", SWIPE_KEY: "2"}, end=20.0)
check("前に保存した「2秒かけてなぞる」（いちばん遅い。なぞる2秒のあいだ監視も止まる）は使わず、0.2秒で0.5秒あまりごとになぞる",
      durations == {200} and len(swipes) >= 20 and all(0.5 <= g < 0.8 for g in gaps), (gaps[:6], durations, len(swipes)))
fake, swipes, gaps, durations = scroll_run({INTERVAL_KEY: "壊れた値", SWIPE_KEY: "9"})
check("保存した値が壊れている・範囲の外なら今まで通り（3秒・0.2秒）",
      bool(swipes) and durations == {200} and all(3.0 <= g < 3.5 for g in gaps), (gaps, durations))
fake, logs, notes, sent, w = run(["main", "room"], end=30.0, settings={INTERVAL_KEY: "60"},
                                 script=[(5.0, open_screen("passport"))])
backs = fake.kinds("back")
check("間隔を60秒にしても、ミニプロフィールは3秒あまりで閉じる", bool(backs) and backs[0][2] < 12.0, backs)

# ----------------------------------------------------------------------
# 新しく足した関数を直接確かめる
print("■ 画面の積み重なりを読む（実物）")
NEW = ("parse_display_history", "plan_room_return", "ROOM_OK", "ROOM_BACK", "ROOM_SHEET", "ROOM_BUBBLE",
       "ROOM_TYPING", "ROOM_LOST", "ROOM_UNKNOWN", "ROOM_AWAY_ACTIONS")
missing = [name for name in NEW if not hasattr(A, name)]
check("読む関数・戻り方を決める関数がある", missing == [], missing)
if not missing:
    REAL = fixture("dumpsys_room_stack.txt")
    check("ルームの画面の下に MainActivity", A.parse_display_history(REAL, 2) == [ROOM, MAIN], A.parse_display_history(REAL, 2))
    check("「.Cls」の省略形も直す（ディスプレイ0のホーム）",
          A.parse_display_history(REAL, 0) == ["app.lawnchair/app.lawnchair.LawnchairLauncher"])
    check("並べ直した区切り（Hist の行が無い）は空", A.parse_display_history(REAL, 5) == [])
    check("無いディスプレイ・番号が分からないときは空",
          A.parse_display_history(REAL, 7) == [] and A.parse_display_history(REAL, None) == [])
    check("読めなければ空", A.parse_display_history("", 2) == [] and A.parse_display_history("error", 2) == [])

    print("■ どう戻すか（plan_room_return）")
    plan = lambda history, xml: A.plan_room_return(history, xml, 2, GRAVITY)
    check("ルームの画面でチャット欄が見える → そのまま", plan([ROOM, MAIN], GUEST) == (A.ROOM_OK, None))
    check("ミニプロフィールの実物では、チャット欄は読めない", A.find_chat_list_bounds(PASSPORT_XML, 2) is None)
    check("ルームの上にミニプロフィール → 戻る", plan([PASSPORT, ROOM, MAIN], PASSPORT_XML) == (A.ROOM_BACK, None))
    check("2枚重なっていても戻る（1枚ずつ閉じる）", plan([WEB, PASSPORT, ROOM, MAIN], NO_BUBBLE) == (A.ROOM_BACK, None))
    check("ルームとの間に別のアプリが挟まっていたら戻るを押さない",
          plan([PASSPORT, f"{OTHER}/{OTHER}.Main", ROOM], PASSPORT_XML) == (A.ROOM_LOST, None))
    check("入力欄の無いシート（ギフトなど）→ 戻るで閉じる", plan([ROOM, MAIN], GIFT_SHEET) == (A.ROOM_SHEET, None))
    check("チャットの入力のシート → 触らない（打っている途中かもしれない）",
          plan([ROOM, MAIN], INPUT_SHEET) == (A.ROOM_TYPING, None))
    check("ルームの画面でチャット欄もシートも無い → 今まで通り（ルームで戻るを押さない）",
          plan([ROOM, MAIN], NO_BUBBLE) == (A.ROOM_UNKNOWN, None))
    check("小さくしている → 右の丸の真ん中を押す", plan([MAIN], MINIMIZED) == (A.ROOM_BUBBLE, (476, 714)), plan([MAIN], MINIMIZED))
    check("ルームに入っていない（丸も無い）→ 止めて待つだけ", plan([MAIN], NO_BUBBLE) == (A.ROOM_LOST, None))
    check("別のアプリが前 → 止めて待つだけ", plan([f"{OTHER}/{OTHER}.Main"], GUEST) == (A.ROOM_LOST, None))
    check("積み重なりが読めない → 今まで通り", plan([], GUEST) == (A.ROOM_UNKNOWN, None))
    check("ルームを止める状態は4つ", A.ROOM_AWAY_ACTIONS == {A.ROOM_BACK, A.ROOM_SHEET, A.ROOM_BUBBLE, A.ROOM_LOST})

print()
print(f"結果: {'すべて通りました' if not FAILS else str(len(FAILS)) + ' 件失敗'}")
sys.exit(1 if FAILS else 0)
