# -*- coding: utf-8 -*-
"""
キーワードのペアの「対象」（どこに出た文字に反応するか）と、返信ワードの {名前} を確かめる。

2026-10-15 本人と（全部任せる）: 範囲の文字を全部拾うと、人の名前・席番号・広告・ルーム名にワードが含まれていても
反応する。チャット欄の行を意味で読み（parse_chat_rows）、ペアごとに対象を選べるようにした。
既存のペアは「すべての文字（今まで通り）」のまま動きを変えない。

監視の本体（_run_monitor）は、伏せ字にした実物の音声ルームの画面（fixtures/voiceroom_guest.xml）を返す
にせの端末で何周か回す。送る操作だけ記録に置き換え、選び方・名前の差し込み・二重送信の防ぎ方は本物を通す。
"""
import os, sys, sqlite3, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A

FAILS = []
GRAVITY = "anonymous.sns.community.gravity"


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


def fixture(name):
    with open(os.path.join(_HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()


GUEST = fixture("voiceroom_guest.xml")
# この画面のチャット欄（上から）:
#   発言  伏せ字3「伏せ字4」
#   お知らせ 伏せ字5が音声ルームに参加しました
#   お知らせ 伏せ字3さんが音声ルームにいいねをしました
#   発言  伏せ字3「伏せ字6」
#   お知らせ ルーム名を伏せ字1に変更しました

print("■ 名前の整え方・差し込み")
check("末尾の「..」を取る", A.clean_display_name("ながいなま..") == "ながいなま")
check("末尾の「…」と空白を取る", A.clean_display_name(" なまえ… ") == "なまえ")
check("途中の点は残す", A.clean_display_name("a..b") == "a..b")
check("{名前} を置き換える", A.render_reply("{名前}さん、いらっしゃい！", "たろう..") == "たろうさん、いらっしゃい！")
check("名前が読めないときは空", A.render_reply("{名前}さん", "") == "さん")
check("{名前} が無ければそのまま", A.render_reply("よろしくお願いします！", "たろう") == "よろしくお願いします！")
check("今まで通りのペアでも、参加のお知らせから名前を読む", A.name_in_text("たろう..が音声ルームに参加しました") == "たろう..")
check("ルーム名の変更は名前にしない", A.name_in_text("ルーム名をあそびばに変更しました") == "")

print("■ チャット欄の行の目印")
rows = A.parse_chat_rows(GUEST, 2)
check("発言は「名前: 本文」", A.chat_row_key(rows[0]) == "伏せ字3: 伏せ字4", A.chat_row_key(rows[0]))
check("お知らせは文言そのもの", A.chat_row_key(rows[1]) == "伏せ字5が音声ルームに参加しました")
clipped = dict(rows[0], name="")
check("名前が画面の上で切れた発言は、目印に使わない（流れて名前が切れると目印が変わるため）",
      A.chat_row_key(clipped) is None)

print("■ 対象ごとに当たる行")
hit = lambda target, word="伏せ字", y_min=0, y_max=960, ignore=(): [
    (key, name) for key, _, name in A.match_keyword_rows(rows, target, word, y_min, y_max, ignore)]
check("発言の本文だけ: 名前やお知らせの「伏せ字」には当たらない",
      hit(A.KEYWORD_TARGET_MESSAGE) == [("伏せ字3: 伏せ字4", "伏せ字3"), ("伏せ字3: 伏せ字6", "伏せ字3")],
      hit(A.KEYWORD_TARGET_MESSAGE))
check("発言の本文だけ: 名前だけに含まれる文字には当たらない", hit(A.KEYWORD_TARGET_MESSAGE, "伏せ字3") == [])
check("お知らせの行だけ: 発言には当たらない",
      [k for k, _ in hit(A.KEYWORD_TARGET_NOTICE)] == ["伏せ字5が音声ルームに参加しました",
                                                    "伏せ字3さんが音声ルームにいいねをしました",
                                                    "ルーム名を伏せ字1に変更しました"], hit(A.KEYWORD_TARGET_NOTICE))
check("［参加したとき］: 参加のお知らせだけ。名前は参加した人",
      hit("join", word="") == [("伏せ字5が音声ルームに参加しました", "伏せ字5")], hit("join", word=""))
check("［ルームにいいねしたとき］: 名前はいいねした人",
      hit("like", word="") == [("伏せ字3さんが音声ルームにいいねをしました", "伏せ字3")])
check("［ルーム名を変えたとき］: 名前は空（新しいルーム名は名前ではない）",
      hit("rename", word="") == [("ルーム名を伏せ字1に変更しました", "")])
check("［マイクをもらったとき］: この画面には無い", hit("mic", word="") == [])
check("監視範囲の外の行は数えない（参加のお知らせは y=501）", hit("join", word="", y_min=600) == [])
check("無視する言葉を含む行は、文字で反応する対象では除く",
      hit(A.KEYWORD_TARGET_NOTICE, word="伏せ字", ignore=("いいねをしました",))
      == [("伏せ字5が音声ルームに参加しました", "伏せ字5"), ("ルーム名を伏せ字1に変更しました", "")])

print("■ データベース: 古い形からの移し替え（既存のペアは今まで通り）")
path = os.path.join(tempfile.mkdtemp(), "old.db")
with sqlite3.connect(path) as conn:
    conn.execute("CREATE TABLE keyword_sets (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, "
                 "enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE keywords (set_id INTEGER, trigger_word TEXT, reply_message TEXT, "
                 "enabled INTEGER DEFAULT 1, PRIMARY KEY (set_id, trigger_word))")
    conn.execute("INSERT INTO keyword_sets (name) VALUES ('デフォルト')")
    conn.execute("INSERT INTO keywords VALUES (1, 'こんにちは', 'こんにちは！', 1)")
db = A.DatabaseManager(path)
check("既存のペアは「すべての文字」", db.get_keywords_in_set(1) == [
    {"trigger": "こんにちは", "reply": "こんにちは！", "enabled": True, "target": A.KEYWORD_TARGET_ANY}],
      db.get_keywords_in_set(1))
db.upsert_keyword(1, "［参加したとき］", "{名前}さん、いらっしゃい！", target="join")
db.upsert_keyword(1, "かわいい", "ありがとう", target=A.KEYWORD_TARGET_MESSAGE)
check("対象を付けて保存できる", db.get_active_keyword_targets() == {
    "こんにちは": "any", "［参加したとき］": "join", "かわいい": "message"}, db.get_active_keyword_targets())
db.upsert_keyword(1, "かわいい", "ありがとう！")
check("対象を省いて更新したら、今の対象のまま", db.get_active_keyword_targets()["かわいい"] == "message")
db.set_keyword_enabled(1, "かわいい", False)
check("無効なペアは入らない", "かわいい" not in db.get_active_keyword_targets())
db.save_setting(A.KEYWORD_AUTO_REPLY_SETTING, "0")
check("自動返信がOFFなら空", db.get_active_keyword_targets() == {})


# ----------------------------------------------------------------------
# 監視の本体を、にせの端末で回す
A.time.sleep = lambda seconds: None


class FakeRoom:
    """伏せ字にした実物の音声ルームの画面を返し続ける。rounds 周読んだら監視を止める"""

    def __init__(self, worker, xml, rounds):
        self.worker, self.xml, self.rounds, self.reads = worker, xml, rounds, 0

    def dump_hierarchy(self, compressed=True):
        self.reads += 1
        if self.reads > self.rounds:
            self.worker.is_running = False
        return self.xml

    def window_size(self):
        return 540, 960


def run_monitor(pairs, rounds=3, xml=GUEST, auto=False):
    """
    pairs: [(検知ワード, 返信ワード, 対象)]。送った文の一覧とログを返す。
    auto=True なら範囲を選ばずに開始する（チャット欄の枠を監視範囲にする）
    """
    db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
    db.save_setting("mumu_target_package", GRAVITY)
    db.save_setting("cooldown_enabled", "0")
    set_id = db.get_keyword_sets()[0]["id"]
    for trigger, _ in list(A.DEFAULT_KEYWORDS.items()):
        db.delete_keyword(set_id, trigger)
    for trigger, reply, target in pairs:
        db.upsert_keyword(set_id, trigger, reply, target=target)
    logs, sent = [], []
    w = A.AutoReplyWorker(db, logs.append)
    w.is_running = True
    room = FakeRoom(w, xml, rounds)
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
    if auto:
        w._run_monitor(None, None, None, None)
    else:
        w._run_monitor(0, 0, 100, 100)
    return sent, logs, w


print("■ 監視: ［参加したとき］に {名前} を差し込んで返し、同じお知らせには二度返さない")
sent, logs, w = run_monitor([("［参加したとき］", "{名前}さん、いらっしゃい！", "join")], rounds=4)
check("参加した人の名前で1回だけ返す", sent == ["伏せ字5さん、いらっしゃい！"], sent)
check("ログにお知らせの行を出す", any("🎯 検知!【［参加したとき］】" in m for m in logs), logs[-6:])
check("送った文を自分の発言として覚える", w._is_own_manual_text("伏せ字9: 伏せ字5さん、いらっしゃい！"))

print("■ 監視: 「発言の本文だけ」は、名前やお知らせに同じ文字があっても反応しない")
sent, logs, w = run_monitor([("伏せ字", "はい", A.KEYWORD_TARGET_MESSAGE)], rounds=4)
check("発言2件に、上から順に1回ずつ返す", sent == ["はい", "はい"], sent)
check("1件目は上の発言", any("ログ:「伏せ字3: 伏せ字4」" in m for m in logs), [m for m in logs if "🎯" in m])

print("■ 監視: 今まで通りのペアは、範囲の文字を全部見る（名前・お知らせにも反応する）")
sent, logs, w = run_monitor([("伏せ字", "はい", A.KEYWORD_TARGET_ANY)], rounds=12)
check("発言の2件より多く反応する（今まで通り）", len(sent) > 2, sent)

print("■ 監視: 今まで通りのペアでも、参加のお知らせなら {名前} が入る")
sent, logs, w = run_monitor([("が音声ルームに参加しました", "{名前}さん、よろしく！", A.KEYWORD_TARGET_ANY)])
check("参加した人の名前が入る", sent == ["伏せ字5さん、よろしく！"], sent)

print("■ 監視: 対象を選んだペアが無ければ、チャット欄の行は読まない（今まで通りの重さ）")
calls = []
real_parse = A.parse_chat_rows
A.parse_chat_rows = lambda *a, **k: calls.append(1) or real_parse(*a, **k)
run_monitor([("こんにちは", "こんにちは！", A.KEYWORD_TARGET_ANY)])
check("読んでいない", calls == [], len(calls))
run_monitor([("［参加したとき］", "いらっしゃい", "join")])
check("対象を選んだペアがあれば読む", len(calls) > 0)
A.parse_chat_rows = real_parse

# ----------------------------------------------------------------------
# 範囲を選ばずに開始（2026-10-15 本人「箱と値そのものを検知するなら範囲選択は要らないのでは」）
print("■ チャット欄の枠を見つける")
# ⚠️ 上端は画面で変わる（この画面は248、2026-10-14 の実物は159）。決め打ちせず毎回探す理由
check("ゲストの画面のチャット欄", A.find_chat_list_bounds(GUEST, 2) == (0, 248, 423, 877), A.find_chat_list_bounds(GUEST, 2))
check("ルームを小さくしたホーム画面には無い", A.find_chat_list_bounds(fixture("voiceroom_minimized.xml"), 2) is None)

print("■ 範囲を選ばずに開始: チャット欄の枠の中だけを見る")
sent, logs, w = run_monitor([("［参加したとき］", "{名前}さん、いらっしゃい！", "join")], auto=True)
check("参加した人に返す", sent == ["伏せ字5さん、いらっしゃい！"], sent)
check("チャット欄を見つけたとログに出す", any("チャット欄を見つけました" in m for m in logs), logs[:6])
check("範囲を選ばずに始めたことになっている", w._auto_range is True)
# 「ゲスト（1人）」はチャット欄と同じ高さの右側（x=441〜527）にある。上下だけで絞ると拾ってしまう
sent, logs, w = run_monitor([("ゲスト", "x", A.KEYWORD_TARGET_ANY)], auto=True)
check("チャット欄の右の「ゲスト（N人）」には反応しない（左右でも絞る）", sent == [], sent)
check("範囲の外で見つけても「範囲を選び直して」とは言わない", not any("範囲外" in m for m in logs), logs[-4:])
sent, logs, w = run_monitor([("ゲスト", "x", A.KEYWORD_TARGET_ANY)])
check("（比べ: 範囲を選んだときは今まで通り上下だけで絞るので反応する）", sent == ["x"], sent)

print("■ 範囲を選ばずに開始: チャット欄が無い画面では、何も検知せずに待つ")
sent, logs, w = run_monitor([("伏せ字", "x", A.KEYWORD_TARGET_ANY)], xml=fixture("voiceroom_minimized.xml"), auto=True)
check("何も送らない（前の枠のまま、ホーム画面の文字に反応しない）", sent == [], sent)
check("待っていることを1回だけログに出す", sum("チャット欄が見つかりません" in m for m in logs) == 1,
      [m for m in logs if "チャット欄" in m])

print("■ 入力欄は部品の名前(etText)で探す（チャット欄の発言を押さない）")
# チャット欄のいちばん下の発言を「メッセージください」にする。以前の探し方（下半分で『メッセージ』を含むもの）は、
# チャット欄の部品が入力欄より先に並ぶので、この発言を押していた
tricky = GUEST.replace('text="伏せ字6"', 'text="メッセージください"')
w = A.AutoReplyWorker(A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db")), lambda m: None)
w.db.save_setting("mumu_target_package", GRAVITY)
w._update_target_display(tricky)
_, _, nodes, all_nodes = w._extract_chat_texts(tricky, 0, 960)
taps = []
w._tap = lambda d, x, y: taps.append((x, y)) or True
w._check_after_action = lambda d, what: None
w._find_and_tap_input(FakeRoom(w, tricky, 99), nodes, 480, all_nodes=all_nodes)
check("入力欄(etText [21,884][238,931])の中央を押す", taps == [(129.5, 907.5)], taps)

print()
if FAILS:
    print(f"失敗 {len(FAILS)} 件: {FAILS}")
    sys.exit(1)
print("すべて成功")
