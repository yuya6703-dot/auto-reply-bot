# -*- coding: utf-8 -*-
"""
回帰テスト: 手入力で何通も送ったあと、先に送った自分の発言へ自動返信しないこと。

【不具合】(v1.7.0)
手入力で送った文は「自分の発言」として覚えておき、自動返信の対象から外している。
しかし覚えておく件数が10件しかなく、送信待ちには20件まで積める。
11通以上送ると、**先に送った分が記録から溢れて「他人の発言」に戻る**。
その文に検知ワードが含まれていて、まだ画面に残っていると、自分の発言へ自動返信する。

【なぜ今まで表面化しにくかったか】
v1.7.0では手入力を1件ずつしか送れず、11回繰り返す必要があった。
v1.8.0で長文を分けて「まとめて送信」できるようにすると、11通以上はごく普通の使い方になる。

⚠️ 模擬しているのはエミュレータ（外部依存）だけ。
   「自分の発言か」を判定するロジックは本物を通している。
"""
import os, sys, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "files"))
import auto_reply_app as A

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


class FakeDevice:
    """画面を読む部分だけを持つ、最小限のエミュレータ役"""
    def dump_hierarchy(self, compressed=True):
        return "<hierarchy/>"


def make_running_worker():
    db = A.DatabaseManager(os.path.join(tempfile.mkdtemp(), "t.db"))
    w = A.AutoReplyWorker(db, lambda m: None)
    w.is_running = True
    w.thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()
    # 送信そのものは検証対象ではないので、成功したことにして先へ進める
    w._execute_reply = lambda d, nodes, half_y, y1, y2, text, fc, thr, all_nodes=None: (fc, True)
    w._update_target_display = lambda xml: None
    w._extract_chat_texts = lambda xml, a, b: ([], [], "nodes", "all")
    return w


# 長文を分けて送る現実的な件数。GRAVITYの250文字制限があるため、
# 3000文字ほどの文章は12通前後に分かれる。
CHUNKS = [f"長文の{i}通目です。よろしくお願いします" for i in range(1, 13)]
TRIGGER = "よろしくお願いします"

print(f"\n[1] {len(CHUNKS)}通に分けて送ったあと、1通目がまだ画面に残っている場合")
w = make_running_worker()
# ⚠️ 1件ずつ積む。修正前(v1.7.0)にも存在する入口を使うことで、
#    同じテストを修正前のコードでも実行でき、不具合の証拠になる。
for chunk in CHUNKS:
    accepted, _ = w.enqueue_manual_text(chunk)
    assert accepted, chunk
check("全部受け付けられる", len(w._manual_queue) == len(CHUNKS), len(w._manual_queue))

w._drain_manual_sends(FakeDevice(), "nodes", 100, 0, 200, 0, 5, all_nodes="all")
check("全部送り終える", w._manual_queue == [], w._manual_queue)

first_on_screen = f"自分: {CHUNKS[0]}"
last_on_screen = f"自分: {CHUNKS[-1]}"

check("最初に送った1通目を、自分の発言だと覚えている",
      w._is_own_manual_text(first_on_screen) is True,
      f"覚えている件数={len(w._recent_manual_texts)}")
check("最後に送った分も、自分の発言だと覚えている",
      w._is_own_manual_text(last_on_screen) is True)

print("\n[2] 自動返信の対象から外れていること（利用者から見た動作）")
# 画面に自分の12通が並んでいて、全部に検知ワードが含まれている状況
matched = [(f"自分: {c}", 100 + i) for i, c in enumerate(CHUNKS)]
matched.append(("他人: よろしくお願いします", 999))

pending = w._select_pending_replies(matched, {}, "こちらこそ！", "", 0)
targets = [t for t, _ in pending]

check("自分が送った分には1つも返信しない",
      all(not t.startswith("自分:") for t in targets), targets)
check("他人の発言にはきちんと返信する",
      targets == ["他人: よろしくお願いします"], targets)

print("\n[3] 覚えておく件数が、一度に送れる件数と揃っていること")
check("記録の上限 == 送信待ちの上限",
      A.AutoReplyWorker.MAX_RECENT_MANUAL_TEXTS == A.AutoReplyWorker.MAX_MANUAL_QUEUE,
      (A.AutoReplyWorker.MAX_RECENT_MANUAL_TEXTS, A.AutoReplyWorker.MAX_MANUAL_QUEUE))
check("一度に送れる件数を送っても溢れない",
      A.AutoReplyWorker.MAX_RECENT_MANUAL_TEXTS >= A.AutoReplyWorker.MAX_MANUAL_QUEUE)

print("\n" + "=" * 50)
if FAILS:
    print(f"FAILED {len(FAILS)}件: {FAILS}")
    sys.exit(1)
print("すべて通りました")
