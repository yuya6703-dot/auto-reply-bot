# -*- coding: utf-8 -*-
"""
重複・上限・保留・AI の失敗（設計書/08 の T29・T31・T32。T11〜T13 の基本も。段階3）。音は鳴らさない。
"""
import time

from agent_harness import Agent, check, finish, make_event, wait_until
from agent.inbox import Inbox
from agent.llm.base import KIND_AUTH, KIND_OK, LLMError
from agent.llm.mock import MODE_ENGAGE, MODE_HOLD, MODE_SILENT, MODE_TIMEOUT
from agent.runtime import STATE_DEGRADED, STATE_IDLE

print("■ T29 重複イベントの防止（受付箱）")
box = Inbox(settle_seconds=0.0)
e1 = make_event("こんにちは", event_id="id-1", key="k-1")
check("1回目は受け付ける", box.submit(e1) is True)
check("同じ event_id は受け付けない", box.submit(make_event("こんにちは", event_id="id-1", key="k-2")) is False)
check("同じ key は受け付けない（画面を何度読んでも1回）", box.submit(make_event("こんにちは", event_id="id-2", key="k-1")) is False)
check("まとまりは1件", box.next_batch(0.1) == [e1])
small = Inbox(max_size=2, settle_seconds=10)
small.submit(make_event("a")); small.submit(make_event("b"))
check("上限を超えたら受け付けない", small.submit(make_event("c")) is False and small.pending_count() == 2)
check("区切りが来なければ空を返す（集めている途中）", small.next_batch(0.05) == [])
small.close()
check("閉じたら受け付けない", small.submit(make_event("d")) is False and small.next_batch(1.0) == [])

a = Agent(mode=MODE_SILENT)
same = make_event("同じ行", event_id="dup", key="dup-key")
check("T29 エージェントに同じ出来事を2回入れても", a.runtime.submit(same) is True and a.runtime.submit(same) is False)
a.wait_decisions(1)
time.sleep(0.3)
check("T29 処理は1回", len(a.decide_calls()) == 1 and a.store.count("events") == 1)
a.close()

print("■ T31 AI を呼ぶ回数の上限（1日）")
a = Agent(mode=MODE_SILENT, daily_call_limit=2)
for i in range(3):
    a.say(f"話題{i}")
    a.wait_decisions(i + 1)
check("T31 上限まで呼ぶ（2回）", len(a.decide_calls()) == 2, len(a.decide_calls()))
check("T31 超えたら AI を呼ばず記録だけ（R8）", a.decisions()[-1][3] == "R8")
check("T31 画面に知らせる", any("今日AIを呼べる回数（2回）に達しました" in n for n in a.notices), a.notices)
a.say("もう1回")
a.wait_decisions(4)
check("T31 知らせは1日1回だけ", sum("達しました" in n for n in a.notices) == 1)
a.close()

print("■ T32 発言の頻度の上限（1分に2回）")
a = Agent(mode=MODE_ENGAGE, min_gap_after_speaking=0.0)
# ⚠️ 毎回違う文にする。似た文は C4（直前とほぼ同じ）で落ちて、回数の上限まで届かない
a.mock.script_generate = [{"text": t, "emotion": "neutral"} for t in
                          ("いいね、それ。", "へえ、知らなかった。", "なるほど、そういうことか。", "それは大変だ。", "おつかれさま。")]
for i in range(5):
    a.say(f"質問{i}？", speaker=f"人{i}")
    a.wait_decisions(i + 1)
    a.wait_idle()
check("T32 喋るのは2回", len(a.speaker.spoken) == 2, a.speaker.spoken)
check("T32 残りは規則で記録だけ（R7。AI も呼ばない）",
      [d[3] for d in a.decisions()[2:]] == ["R7", "R7", "R7"] and len(a.decide_calls()) == 2, a.decisions())
a.close()

print("■ C5 判断の間に上限に達したら喋らない")
a = Agent(mode=MODE_ENGAGE, min_gap_after_speaking=0.0, max_utterances_per_minute=1)
a.mock.delay_seconds = 0.3
a.say("ねえ？")
wait_until(lambda: len(a.mock.requests) >= 1)
a.runtime._utterance_times.append(time.time())     # 判断の途中で、上限を使い切った（別の発言があった）
check("C5 喋らない", a.wait_decisions(1) and wait_until(lambda: a.utterance_rows() != [])
      and a.utterance_rows()[-1][1] == "dropped:C5" and a.speaker.spoken == [], a.utterance_rows())
a.close()

print("■ 保留")
a = Agent(mode=MODE_HOLD, hold_max_seconds=30)
a.say("どうしよう")
check("AI の保留は少し後に見直す", a.wait_decisions(1) and a.decisions()[-1][0] == "hold")
a.mock.mode = MODE_HOLD
check("保留は1回まで（2回目の保留は沈黙）", wait_until(lambda: len(a.decide_calls()) == 2, 6.0)
      and a.wait_decisions(2) and a.decisions()[-1][0] == "hold"
      and wait_until(lambda: any("保留は1回まで" in line for line in a.logs)), a.logs[-3:])
a.close()
a = Agent(mode=MODE_ENGAGE, hold_max_seconds=0.3, min_gap_after_speaking=30.0)
a.runtime._last_utterance_end = time.time()
a.say("いまの話？")
check("規則の保留（R6）", a.wait_decisions(1) and a.decisions()[-1][3] == "R6")
a.say("ねえねえ")
time.sleep(0.5)
a.runtime._last_utterance_end = time.time() - 60
a.say("聞いてる？")
check("保留したまま古くなった出来事は記録だけにする",
      wait_until(lambda: any("古くなった" in line for line in a.logs)), a.logs[-4:])
check("新しい出来事だけで判断する", wait_until(lambda: len(a.decide_calls()) == 1)
      and [e["text"] for e in a.decide_calls()[0].hints["events"]] == ["聞いてる？"], a.decide_calls())
a.close()

print("■ AI の失敗が続いたら AI を呼ばない状態へ（T11〜T13 の基本）")
a = Agent(mode=MODE_TIMEOUT, degraded_after_failures=3, degraded_check_seconds=0.3)
a.mock.behavior = "server"           # 回復の確認（ping）も、しばらくは失敗する
for i in range(3):
    a.say(f"話{i}")
    a.wait_decisions(i + 1)
    a.wait_idle()
check("T11 3回続けて失敗したら AI を呼ばない状態", wait_until(lambda: a.runtime.state == STATE_DEGRADED), a.runtime.state)
check("T10 1回の判断で再試行は1回（合わせて6回）", len(a.decide_calls()) == 6, len(a.decide_calls()))
calls = len(a.decide_calls())
a.say("話3")
check("T11 4件目は AI を呼ばずに記録だけ（R2）", a.wait_decisions(4) and a.decisions()[-1][3] == "R2"
      and len(a.decide_calls()) == calls)
a.mock.behavior = KIND_OK
a.mock.mode = MODE_SILENT
check("T12 確認が通れば戻る", wait_until(lambda: a.runtime.state == STATE_IDLE, 3.0), a.runtime.state)
check("T12 戻ったことを知らせる", any("使えるようになりました" in n for n in a.notices))
a.close()

a = Agent(mode=MODE_SILENT)
a.mock.script_decide = [LLMError(KIND_AUTH)]
a.say("ねえ")
check("T13 認証の失敗は再試行しない", a.wait_decisions(1) and len(a.decide_calls()) == 1)
check("T13 すぐ AI を呼ばない状態へ・キーを確かめるよう知らせる",
      wait_until(lambda: a.runtime.state == STATE_DEGRADED)
      and any("APIキーを確かめてください" in n for n in a.notices), a.notices)
a.close()

finish()
