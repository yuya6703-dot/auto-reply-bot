# -*- coding: utf-8 -*-
"""
v1.7.0で足した「キーワード自動返信のON/OFF」と「手入力して送る」の検証。
実機もGUIも使わず、ロジックだけを確かめる。
"""
import os, sys, time, tempfile

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

def new_db():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    return A.DatabaseManager(path)

def new_worker(db):
    logs = []
    w = A.AutoReplyWorker(db, lambda m: logs.append(m))
    return w, logs


# ---------------------------------------------------------------
print("\n[1] キーワード自動返信のマスタースイッチ")
db = new_db()
set_id = db.get_keyword_sets()[0]["id"]
db.upsert_keyword(set_id, "テスト検知", "テスト返信")

# 初期化時に既定のキーワードが1件入るため、それも含めた状態を基準にする
on_state = db.get_active_keywords()
check("既定(未設定)ではONとして扱う", "テスト検知" in on_state, on_state)

db.save_setting(A.KEYWORD_AUTO_REPLY_SETTING, "0")
check("OFFなら空を返す", db.get_active_keywords() == {}, db.get_active_keywords())

db.save_setting(A.KEYWORD_AUTO_REPLY_SETTING, "1")
check("ONに戻すと元の組み合わせがそのまま復活する",
      db.get_active_keywords() == on_state, db.get_active_keywords())

# OFFにしてもセット/ペアの有効フラグは書き換えない、を確かめる
db.save_setting(A.KEYWORD_AUTO_REPLY_SETTING, "0")
rows = db.get_keywords_in_set(set_id)
check("OFFにしてもペアの☑は維持される", all(r["enabled"] == 1 for r in rows), rows)
check("OFFにしてもペアそのものは消えない", len(rows) == 2, rows)


# ---------------------------------------------------------------
print("\n[2] 手入力の受付 (enqueue_manual_text)")
db = new_db()
w, logs = new_worker(db)

ok, msg = w.enqueue_manual_text("やあ")
check("監視していなければ断る", ok is False and "監視中ではない" in msg, msg)

# 監視中のふりをする
w.is_running = True
w.thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()

ok, msg = w.enqueue_manual_text("   ")
check("空白だけなら断る", ok is False and "入力されていません" in msg, msg)

ok, msg = w.enqueue_manual_text("  こんにちは  ")
check("前後の空白は落として受け付ける", ok is True and w._manual_queue == ["こんにちは"], w._manual_queue)

ok, msg = w.enqueue_manual_text("2つ目")
check("2件目は順番待ちとして知らせる", ok is True and "順番待ち2件" in msg, msg)

for i in range(A.AutoReplyWorker.MAX_MANUAL_QUEUE):
    w.enqueue_manual_text(f"詰める{i}")
ok, msg = w.enqueue_manual_text("あふれる")
check("上限を超えたら断る", ok is False and "たまっています" in msg, msg)
check("上限を超えて積まれない", len(w._manual_queue) == A.AutoReplyWorker.MAX_MANUAL_QUEUE,
      len(w._manual_queue))



# ---------------------------------------------------------------
print("\n[3] 自分が手入力した文へ自動返信しない")
db = new_db()
w, logs = new_worker(db)
w._recent_manual_texts = ["おはよう、今日もよろしく"]

check("自分の手入力を含む行は自分のものと判定する",
      w._is_own_manual_text("ユーザーA: おはよう、今日もよろしく") is True)
check("無関係な行は自分のものではない",
      w._is_own_manual_text("ユーザーB: こんばんは") is False)

matched = [("ユーザーA: おはよう、今日もよろしく", 100), ("ユーザーB: おはよう", 200)]
pending = w._select_pending_replies(matched, {}, "返信ワード", "", 0)
check("自分の手入力した行は返信対象から外れる",
      [t for t, _ in pending] == ["ユーザーB: おはよう"], pending)


# ---------------------------------------------------------------
print("\n[4] 改行があっても「入らなかった」と誤判定しない")
db = new_db()
w, logs = new_worker(db)

class FakeDevice:
    def __init__(self, shown): self.shown = shown
w._current_input_text = lambda d: d.shown

check("アプリが改行を捨てても入った扱いにする",
      w._input_text_matches(FakeDevice("あいうえお"), "あい\nうえお") is True)
check("全く違う文字なら入っていないと判定する",
      w._input_text_matches(FakeDevice("ぜんぜん違う"), "あい\nうえお") is False)
check("空の入力欄なら入っていないと判定する",
      w._input_text_matches(FakeDevice(""), "あいうえお") is False)
check("改行が保たれていても入った扱いにする",
      w._input_text_matches(FakeDevice("あい\nうえお"), "あい\nうえお") is True)


# ---------------------------------------------------------------
print("\n[5] 送信待ちを積んだ順に送り切る")
db = new_db()
w, logs = new_worker(db)
w.is_running = True
w.thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()

sent = []
redumps = []

def fake_execute(d, nodes, half_y, y1, y2, text, fc, thr, all_nodes=None):
    sent.append((text, nodes))
    return fc, True

class FakeD:
    def dump_hierarchy(self, compressed=True):
        redumps.append(1)
        return "<xml/>"

w._execute_reply = fake_execute
w._update_target_display = lambda xml: None
w._extract_chat_texts = lambda xml, a, b: ([], [], f"nodes{len(redumps)}", "all")

w.enqueue_manual_text("1件目")
w.enqueue_manual_text("2件目")
w.enqueue_manual_text("3件目")

fc, any_sent = w._drain_manual_sends(FakeD(), "nodes0", 100, 0, 200, 0, 5, all_nodes="all0")

check("1件でも送ったと返す", any_sent is True)
check("積んだ順に送る", [t for t, _ in sent] == ["1件目", "2件目", "3件目"], sent)
check("送信待ちは空になる", w._manual_queue == [], w._manual_queue)
check("2件目以降は画面を読み直してから送る",
      [n for _, n in sent] == ["nodes0", "nodes1", "nodes2"], sent)
check("最後の1件のあとは無駄に読み直さない", len(redumps) == 2, len(redumps))
check("送った文は自分のものとして覚える",
      w._recent_manual_texts == ["1件目", "2件目", "3件目"], w._recent_manual_texts)

# 覚える件数の上限
w._recent_manual_texts = []
w.is_running = True
for i in range(A.AutoReplyWorker.MAX_RECENT_MANUAL_TEXTS + 5):
    w.enqueue_manual_text(f"文{i}")
w._drain_manual_sends(FakeD(), "n", 100, 0, 200, 0, 5)
check("覚える件数には上限がある",
      len(w._recent_manual_texts) == A.AutoReplyWorker.MAX_RECENT_MANUAL_TEXTS,
      len(w._recent_manual_texts))


# ---------------------------------------------------------------
print("\n[6] 監視が止まったら送信待ちを流し込まない")
db = new_db()
w, logs = new_worker(db)
w.is_running = True
w.thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()
w.enqueue_manual_text("止まる直前の1件")
w._execute_reply = fake_execute
w.is_running = False
before = len(sent)
fc, any_sent = w._drain_manual_sends(FakeD(), "n", 100, 0, 200, 0, 5)
check("停止中は1件も送らない", any_sent is False and len(sent) == before, (any_sent, len(sent) - before))
check("送信待ちは残したままにする", w._manual_queue == ["止まる直前の1件"], w._manual_queue)


print("\n[7] まとめて積む (enqueue_manual_texts)")
db = new_db()
w, logs = new_worker(db)
w.is_running = True
w.thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()

n, msg = w.enqueue_manual_texts(["1通目", "2通目", "3通目"])
check("件数を返す", n == 3, (n, msg))
check("積んだ順が保たれる", w._manual_queue == ["1通目", "2通目", "3通目"], w._manual_queue)
check("順番に送ると知らせる", "3件を順番に送ります" in msg, msg)

w._manual_queue.clear()
n, msg = w.enqueue_manual_texts(["  ", "中身あり", "", "\n\n"])
check("空の欄は飛ばす", w._manual_queue == ["中身あり"], w._manual_queue)
check("残った1件だけ数える", n == 1, n)

w._manual_queue.clear()
n, msg = w.enqueue_manual_texts(["   ", ""])
check("全部空なら断る", n == 0 and "入力されていません" in msg, msg)

# ⚠️ ここが肝。長文を分けたものが途中まで送られてはいけない
w._manual_queue.clear()
room_filler = [f"埋める{i}" for i in range(A.AutoReplyWorker.MAX_MANUAL_QUEUE - 2)]
w.enqueue_manual_texts(room_filler)
before = list(w._manual_queue)
n, msg = w.enqueue_manual_texts(["分割1", "分割2", "分割3", "分割4"])
check("入り切らないなら1件も積まない", n == 0 and w._manual_queue == before, (n, len(w._manual_queue)))
check("理由を伝える", "途中まで送ると文章が切れて" in msg, msg)

# 1件だけのときは従来どおりの文言
w._manual_queue.clear()
w.enqueue_manual_texts([f"埋める{i}" for i in range(A.AutoReplyWorker.MAX_MANUAL_QUEUE)])
ok, msg = w.enqueue_manual_text("あふれる1件")
check("1件のときは満杯だと伝える", ok is False and "たまっています" in msg, msg)

check("覚える件数は送信待ちの上限と同じ",
      A.AutoReplyWorker.MAX_RECENT_MANUAL_TEXTS == A.AutoReplyWorker.MAX_MANUAL_QUEUE,
      (A.AutoReplyWorker.MAX_RECENT_MANUAL_TEXTS, A.AutoReplyWorker.MAX_MANUAL_QUEUE))


print("\n[8] GRAVITYの上限の既定値")
check("既定は250文字", A.MANUAL_SEND_DEFAULT_LIMIT == 250, A.MANUAL_SEND_DEFAULT_LIMIT)
check("入力欄の既定は3つ", A.MANUAL_SEND_DEFAULT_BOXES == 3, A.MANUAL_SEND_DEFAULT_BOXES)


print("\n" + "=" * 50)
if FAILS:
    print(f"FAILED {len(FAILS)}件: {FAILS}")
    sys.exit(1)
print("すべて通りました")
