# -*- coding: utf-8 -*-
"""
入力欄へ文字を入れる・消すのを速くした（2026-10-16 本人「応答遅いの気になる」）。

【分かったこと】MuMu は uiautomator2 の文字入力（AdbKeyboard）への切り替えを止める（2026-10-14 の記録: MuMuIMETrace: ime shell BLOCKED）。
d.clear_text() と d.send_keys() は先にその切り替えを5秒待ち、3回やり直してから、
- send_keys は「今選ばれている部品に直接入れる」やり方に切り替わって入る（約9秒）
- clear_text は代わりが無く、例外で終わる（約8秒）
送る1回あたり約17秒を捨てていた（実際のログ: 入力欄を押してから送るまで19秒）。

【直し方】はじめから今選ばれている部品を直接さわる（d(focused=True).set_text / clear_text）。入らなかったときだけ前のやり方。
⚠️ 実機には触らない。にせの端末で、遅いやり方を呼ばないことと、入らないときに前のやり方へ戻ることを確かめる。
"""
import os, re, sys, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A

FAILS = []
GRAVITY = "anonymous.sns.community.gravity"


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


class FocusedField:
    """d(focused=True) の代わり"""

    def __init__(self, device):
        self.device = device

    def set_text(self, text, timeout=None):
        self.device.calls.append("focused.set_text")
        if self.device.direct_broken:
            raise RuntimeError("UiObjectNotFoundError")
        if not self.device.direct_ignored:
            self.device.field = text or ""

    def clear_text(self, timeout=None):
        self.device.calls.append("focused.clear_text")
        if self.device.direct_broken:
            raise RuntimeError("UiObjectNotFoundError")
        self.device.field = ""


class FakeRoomInput:
    """音声ルームの入力のシートが開いた画面（入力欄と「送る」）。遅いやり方を呼んだら記録する"""

    def __init__(self, field="前の文字", direct_broken=False, direct_ignored=False):
        self.field = field
        self.calls = []
        self.direct_broken = direct_broken      # 部品を直接さわれない
        self.direct_ignored = direct_ignored    # さわれるが、文字が入らない
        self.sent = []

    def __call__(self, **selector):
        assert selector == {"focused": True}, selector
        return FocusedField(self)

    # --- 遅いやり方（MuMu では約8〜9秒） ---
    def clear_text(self):
        self.calls.append("d.clear_text")
        raise RuntimeError("AdbBroadcastError")

    def send_keys(self, text):
        self.calls.append("d.send_keys")
        self.field = text

    def set_clipboard(self, text, label=None):
        raise RuntimeError("java.lang.SecurityException")

    def shell(self, command):
        if "input" in str(command) and "tap" in str(command):
            self.sent.append(self.field)
            self.field = ""
        return type("R", (), {"output": ""})()

    def dump_hierarchy(self, compressed=True):
        shown = self.field.replace("&", "&amp;").replace('"', "&quot;").replace("\n", "&#10;") or "メッセージを送信"
        return ('<hierarchy>'
                f'<node class="android.widget.EditText" resource-id="{GRAVITY}:id/etText" text="{shown}" '
                f'package="{GRAVITY}" display-id="2" bounds="[147,896][433,948]" focused="true" />'
                f'<node class="android.widget.TextView" resource-id="{GRAVITY}:id/btnSend" text="送る" '
                f'package="{GRAVITY}" display-id="2" bounds="[433,904][511,941]" clickable="true" />'
                '</hierarchy>')

    def window_size(self):
        return 540, 960


def worker():
    w = A.AutoReplyWorker(A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db")), lambda m: None)
    w.db.save_setting("mumu_target_package", GRAVITY)
    w._target_display = "2"
    w._clipboard_paste_available = False      # この MuMu では貼り付けが使えない（分かったあとの状態）
    w._check_after_action = lambda d, what: None
    return w


A.time.sleep = lambda seconds: None
TEXT = "テストさん、おはよう。\n今起きたよ😊"

print("■ 入れる: 遅いやり方を呼ばない")
d = FakeRoomInput(field="")
w = worker()
check("入ったと返す", w._type_reply_text(d, TEXT) is True)
check("今選ばれている部品に直接入れる（改行もそのまま）", d.field == TEXT, repr(d.field))
check("d.send_keys（約9秒）を呼ばない", "d.send_keys" not in d.calls, d.calls)

print("■ 消す: 遅いやり方を呼ばない")
d = FakeRoomInput(field="前に打ちかけた文字")
w._clear_input(d)
check("入力欄が空になる", d.field == "", repr(d.field))
check("d.clear_text（約8秒・しかも失敗）を呼ばない", "d.clear_text" not in d.calls, d.calls)

print("■ 送る（消す → 入れる → 「送る」）の全体")
d = FakeRoomInput(field="前に打ちかけた文字")
w = worker()
check("送れたと返す", w._send_reply(d, TEXT) is True)
check("送った文は、前の文字が混ざらず、入れた文だけ", d.sent == [TEXT], d.sent)
check("遅いやり方を1回も呼ばない", not any(c.startswith("d.") for c in d.calls), d.calls)

print("■ 直接さわれないとき・入らないときは、前のやり方へ戻る")
d = FakeRoomInput(field="", direct_broken=True)
w = worker()
check("部品が見つからなければ d.send_keys で入れる", w._type_reply_text(d, TEXT) is True and d.calls[-1] == "d.send_keys"
      and d.field == TEXT, d.calls)
d = FakeRoomInput(field="", direct_ignored=True)
check("直接入れても文字が入らなければ d.send_keys で入れる", w._type_reply_text(d, TEXT) is True and d.calls[-1] == "d.send_keys"
      and d.field == TEXT, d.calls)
d = FakeRoomInput(field="消せない文字", direct_broken=True)
w._clear_input(d)
check("消すのに失敗しても止まらない（そのあとの入れ方が中身を置き換える）", d.calls == ["focused.clear_text"], d.calls)

print("■ メンションは、文を入れてからアイコンをダブルタップし、そのまま送る（2026-10-22 実機で確かめた順番）")
# 本人「メンションを文字入力じゃなくてアイコンダブルタップにしてって言ったのに改善してない」「アイコンダブルタップしたらアプリ側で
# 自動で文字入力されるのよ」。10/22 まではダブルタップのあとに「@名前 ＋文」で入力欄を丸ごと入れ直していて、青いメンションが
# ただの文字になっていた。実機: 下の入力欄に「てすと」→ ダブルタップ → シートが開いて「てすと@名前.. 」（文の後ろに本物のメンション）
with open(os.path.join(_HERE, "fixtures", "voiceroom_guest.xml"), encoding="utf-8") as f:
    ROOM = f.read()


class FakeMentionRoom:
    """音声ルーム。下の入力欄に文を入れられ、アイコンをダブルタップ（2回のタップを1回の shell で）すると、
    GRAVITY がシートを開いて文の後ろに「@名前 」を付ける。シートの「送る」で送る"""

    def __init__(self, inserts=True, opens_page=False, sheet_open=False, extra_input=False, shift_after_text=False,
                 fail_first=False, wrong_person=False, sheet_on_text=False, sheet_sticks=False):
        self.commands, self.calls, self.sent = [], [], []
        self.inserts, self.opens_page, self.sheet_open, self.extra_input = inserts, opens_page, sheet_open, extra_input
        self.shift_after_text, self.fail_first, self.wrong_person = shift_after_text, fail_first, wrong_person
        # 2026-10-24 実機: 下の入力欄に文を入れると、フォーカスが入ってキーボードと入力のシートが開く（10/22 は開かなかった）
        self.sheet_on_text, self.sheet_sticks = sheet_on_text, sheet_sticks
        self.page = False
        self.field = ""
        self.text_set = False
        self.double_taps = 0

    def icon(self):
        """その人のアイコンの真ん中（文を入れたあとにチャット欄が動く画面では、下へずれる）"""
        return (49, 706) if (self.shift_after_text and self.text_set) else (49, 646)

    def __call__(self, **selector):
        room = self

        class Field:
            def set_text(self, text, timeout=None):
                room.calls.append(("set_text", dict(selector), text))
                room.field = text or ""
                room.text_set = room.text_set or bool(text)
                if room.sheet_on_text and text and not room.sheet_open:
                    room.sheet_open = True
                return True

            def clear_text(self, timeout=None):
                room.calls.append(("clear_text", dict(selector)))
                room.field = ""
        return Field()

    def shell(self, command):
        command = str(command)
        self.commands.append(command)
        self.calls.append(("shell", command))
        taps = re.findall(r"input -d 2 tap (\d+) (\d+)", command)
        if len(taps) == 2 and taps[0] == taps[1] and "; sleep" in command and "&" not in command:   # 順番に2回（ダブルタップ）
            self.double_taps += 1
            if self.sheet_open:
                # シートが開いていると、1回目はシートを閉じるだけ、2回目がふつうのタップになってミニプロフィールが開く
                self.sheet_open, self.page = False, True
            elif tuple(map(int, taps[0])) != self.icon():
                pass                       # ずれた所を押した（何も起きない）
            elif self.fail_first and self.double_taps == 1:
                pass                       # 1回目はダブルタップと受け取られなかった
            elif self.opens_page:
                self.page = True
            elif self.inserts:
                self.sheet_open = True
                self.field += "@別の人 " if self.wrong_person else "@伏せ字3 "
        elif "keyevent 4" in command:      # 戻る: 開いているページ・シート（とキーボード）を閉じる。入れた文は下の入力欄に残る
            if self.page:
                self.page = False
            elif not self.sheet_sticks:
                self.sheet_open = False
        elif self.sheet_open and "tap 472 922" in command:      # シートの「送る」
            self.sent.append(self.field)
            self.field, self.sheet_open = "", False
        return type("R", (), {"output": ""})()

    def dump_hierarchy(self, compressed=True):
        if self.page:      # 画面いっぱいのページ（他の人のプロフィールなど）。入力欄も、後ろのチャット欄も無い
            return (f'<hierarchy><node resource-id="{GRAVITY}:id/tvUserName" text="伏せ字3" package="{GRAVITY}" '
                    'display-id="2" bounds="[0,100][540,160]" /></hierarchy>')
        shown = self.field.replace("&", "&amp;").replace('"', "&quot;") or "メッセージを送信"
        if self.sheet_open:   # シートが開くと、画面の読み取りにはシートの部品しか出ない（後ろのチャット欄は読めない）
            return ('<hierarchy>'
                    f'<node resource-id="{GRAVITY}:id/design_bottom_sheet" package="{GRAVITY}" display-id="2" bounds="[0,884][540,960]" />'
                    f'<node class="android.widget.EditText" resource-id="{GRAVITY}:id/etText" text="{shown}" package="{GRAVITY}" '
                    'display-id="2" bounds="[147,896][433,948]" focused="true" />'
                    f'<node class="android.widget.TextView" resource-id="{GRAVITY}:id/btnSend" text="送る" package="{GRAVITY}" '
                    'display-id="2" bounds="[433,904][511,941]" clickable="true" /></hierarchy>')
        xml = ROOM.replace('text="メッセージを送信"', f'text="{shown}"')
        if self.shift_after_text and self.text_set:      # 新しい発言が来て、チャット欄の行が下へずれた
            xml = xml.replace("[21,618][78,675]", "[21,678][78,735]")
        if self.extra_input:   # GRAVITY を2つ開いていて、別の画面にも入力欄がある
            xml = xml.replace("</hierarchy>", f'<node class="android.widget.EditText" resource-id="{GRAVITY}:id/etText" '
                                              'text="メッセージを送信" package="{GRAVITY}" display-id="3" bounds="[0,0][9,9]" /></hierarchy>')
        return xml

    def window_size(self):
        return 540, 960


notes = []
w = worker()
w.agent_note = notes.append
d = FakeMentionRoom()
check("送れたと返す", w._send_with_mention(d, "こんばんは！", "伏せ字3") is True, (notes, d.calls))
check("文の後ろに本物のメンションが付いた形で送る", d.sent == ["こんばんは！@伏せ字3 "], d.sent)
tap_at = next(i for i, c in enumerate(d.calls) if c[0] == "shell" and "tap 49 646" in c[1])
texts = [i for i, c in enumerate(d.calls) if c[0] in ("set_text", "clear_text")]
check("文を入れるのは、ダブルタップの前の1回だけ（下の入力欄へ。シートは開かない）",
      len(texts) == 1 and texts[0] < tap_at and d.calls[texts[0]][2] == "こんばんは！"
      and "resourceIdMatches" in d.calls[texts[0]][1], d.calls)
check("⚠️ ダブルタップのあとは、入力欄を書き直さない（書き直すと青いメンションがただの文字になる）",
      all(c[0] == "shell" for c in d.calls[tap_at:]), d.calls[tap_at:])
check("その人のいちばん新しい発言のアイコンを、すばやく2回タップする（1回の shell で、裏で走らせず順番に。2026-10-23）",
      d.calls[tap_at][1].count("input -d 2 tap 49 646") == 2 and "; sleep 0.05;" in d.calls[tap_at][1]
      and "&" not in d.calls[tap_at][1], d.calls[tap_at])
check("判断のログに", any("メンションが付きました" in n for n in notes), notes)
d = FakeMentionRoom()
check("その人の発言がチャット欄に見えなければ、何もさわらない（メンションなしで送る）",
      w._send_with_mention(d, "こんばんは", "いない人") is None and d.calls == [] and "見えないので" in notes[-1])
d = FakeMentionRoom(sheet_open=True)
check("入力のシートが開いていたら（後ろのアイコンの位置が分からない）、さわらない",
      w._send_with_mention(d, "こんばんは", "伏せ字3") is None and d.calls == [])
d = FakeMentionRoom(extra_input=True)
check("入力欄がいくつもある（GRAVITY を複数開いている）ときは、どの欄に入るか分からないのでさわらない",
      w._send_with_mention(d, "こんばんは", "伏せ字3") is None and d.calls == [])
d = FakeMentionRoom(opens_page=True)
check("ダブルタップでプロフィールなどのページが開いたら、戻るでルームに帰る（何も送らない）",
      w._send_with_mention(d, "こんばんは", "伏せ字3") is None and d.sent == []
      and any("input -d 2 keyevent 4" in c for c in d.commands) and "メンションが付かなかった" in notes[-1], d.commands)
d = FakeMentionRoom(inserts=False)
check("何も開かず、ルームの入力欄が見えたままなら、戻るは押さない（ルームから出てしまう）",
      w._send_with_mention(d, "こんばんは", "伏せ字3") is None and not any("keyevent 4" in c for c in d.commands), d.commands)
# 2026-10-23 本人「アイコンのダブルタップできてないよ」「間髪入れずにダブルタップしないとメンションにならない」
d = FakeMentionRoom(shift_after_text=True)
check("文を入れたあとにチャット欄が動いても、押す直前に測り直した位置をダブルタップする",
      w._send_with_mention(d, "こんばんは", "伏せ字3") is True and d.sent == ["こんばんは@伏せ字3 "]
      and any("input -d 2 tap 49 706" in c for c in d.commands), d.commands)
d = FakeMentionRoom(fail_first=True)
check("1回目でメンションが付かなければ、もう1回だけダブルタップする", w._send_with_mention(d, "こんばんは", "伏せ字3") is True
      and d.double_taps == 2 and d.sent == ["こんばんは@伏せ字3 "] and any("もう1回" in n for n in notes), (d.double_taps, notes[-2:]))
d = FakeMentionRoom(inserts=False)
w._send_with_mention(d, "こんばんは", "伏せ字3")
check("2回やっても付かなければ、そこでやめる（3回目はしない）", d.double_taps == 2, d.double_taps)
d = FakeMentionRoom(wrong_person=True)
check("⚠️ 別の人へのメンションが付いたら、送らない（入力欄を空にして、メンションなしで送り直す）",
      w._send_with_mention(d, "こんばんは", "伏せ字3") is None and d.sent == [] and d.field == ""
      and "別の人" in notes[-1], (d.sent, d.field, notes[-1:]))
# 2026-10-24 リリース前の実機: 文を入れると入力のシートが開くようになっていた。開いたままだとチャット欄が読めず、
# 押す直前の測り直しでダブルタップせずに抜けていた（3回とも「メンションが付かなかった」・1〜2秒で終わる）。
# 戻る1回でシートもキーボードも閉じ、文は下の入力欄に残る（実機で確かめた）
d = FakeMentionRoom(sheet_on_text=True)
check("文を入れてシートが開いたら、戻る1回で閉じてからダブルタップし、メンション付きで送る",
      w._send_with_mention(d, "こんばんは", "伏せ字3") is True and d.sent == ["こんばんは@伏せ字3 "], (notes[-2:], d.commands))
backs = [i for i, c in enumerate(d.calls) if c[0] == "shell" and "keyevent 4" in c[1]]
taps = [i for i, c in enumerate(d.calls) if c[0] == "shell" and "tap 49 646" in c[1]]
check("戻るは1回だけ、ダブルタップの前（シートが無いのに押すとルームから出る）", len(backs) == 1 and taps and backs[0] < taps[0],
      d.calls)
check("文は入れ直さない（入れるのは1回だけ）", sum(c[0] == "set_text" for c in d.calls) == 1, d.calls)
d = FakeMentionRoom(sheet_on_text=True, sheet_sticks=True)
check("戻るでシートが閉じなければ、ダブルタップしない（メンションなしで送る。戻るを何度も押さない）",
      w._send_with_mention(d, "こんばんは", "伏せ字3") is None and d.double_taps == 0 and d.sent == []
      and sum("keyevent 4" in c for c in d.commands) == 1, d.commands)
w.is_running = True
w.is_alive = lambda: True
ok, _ = w.enqueue_agent_text("こんばんは", mention="伏せ字3")
check("AIの文には、メンションする相手を付けて積む", ok and w._manual_queue[-1].mention == "伏せ字3"
      and w._manual_queue[-1] == "こんばんは")

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
