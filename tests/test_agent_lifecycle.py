# -*- coding: utf-8 -*-
"""
起動・終了・緊急停止・再起動・壊れた記録（設計書/08 の T36〜T39。段階3）。音は鳴らさない。
"""
import os, tempfile, time

from agent_harness import Agent, check, finish, wait_until
from agent.llm.mock import MODE_ENGAGE, MODE_SILENT
from agent.memory.store import OPEN_OK, OPEN_RECREATED, OPEN_RESTORED, AgentStore
from agent.persona import Persona
from agent.runtime import STATE_EMERGENCY, STATE_IDLE, STATE_SPEAKING, STATE_STOPPED

print("■ T36 終了時の後片付け")
a = Agent(mode=MODE_ENGAGE)
a.mock.delay_seconds = 10.0
a.say("ねえ？")
wait_until(lambda: len(a.mock.requests) >= 1)
t0 = time.monotonic()
a.runtime.stop()
check("T36 判断の途中で止めても、すぐスレッドが終わる", a.runtime.join(1.0) and time.monotonic() - t0 < 1.0)
check("T36 止めたら AI の結果は捨てる（喋らない）", a.speaker.spoken == [] and a.runtime.state == STATE_STOPPED)
check("T36 止めた後は出来事を受け付けない", a.say("まだいる？") is False)
a.store.close()

a = Agent(mode=MODE_ENGAGE, play_seconds=10.0)
a.say("ねえ？")
check("喋っている", wait_until(lambda: a.runtime.state == STATE_SPEAKING))
a.runtime.stop()
time.sleep(0.2)
check("「止める」は喋っている文を最後まで（すぐには切らない）", a.runtime._thread.is_alive())
a.runtime._speech_cancel.cancel()          # アプリの終了では、読み上げの停止（speech_service.shutdown）がここを止める
check("T36 再生が止まればスレッドが終わる", a.runtime.join(1.0) and a.speaker.cancelled == ["テストさん、それ面白いね。もう少し聞かせて。"])
a.store.close()

print("■ T37 緊急停止")
# ⚠️ 途中で止めた発言も「喋った」に数える（R6 の間が空く）。再開の確認のため、ここでは間を0にする
a = Agent(mode=MODE_ENGAGE, play_seconds=10.0, min_gap_after_speaking=0.0)
a.say("ねえ？")
wait_until(lambda: a.runtime.state == STATE_SPEAKING)
t0 = time.monotonic()
a.runtime.emergency_stop()
check("T37 喋っている途中でもすぐ止まる", wait_until(lambda: len(a.speaker.cancelled) == 1, 0.5)
      and time.monotonic() - t0 < 0.5)
check("T37 待っている読み上げも止める（音声サービスの停止を呼ぶ）", a.speaker.stop_all_calls == 1)
check("T37 状態は緊急停止中", a.runtime.state == STATE_EMERGENCY)
check("T37 新しい出来事を受け付けない", a.say("もしもし？") is False)
time.sleep(0.5)
check("T37 何も喋らない・AI も呼ばない", a.speaker.spoken == [] and len(a.decide_calls()) == 1)
a.speaker.play_seconds = 0.0
a.runtime.resume()
check("T37 手で再開すると戻る", wait_until(lambda: a.runtime.state == STATE_IDLE) and a.say("戻った？", speaker="B") is True
      and wait_until(lambda: len(a.speaker.spoken) == 1))
a.close()

a = Agent(mode=MODE_SILENT, start=False)
a.runtime.emergency_stop()
check("T37 止まっているときに緊急停止しても困らない", a.runtime.state == STATE_EMERGENCY)
ok, message = a.runtime.start()
check("T37 緊急停止中は始められない（再開を押すよう言う）", ok is False and "再開" in message)
a.runtime.resume()
check("T37 再開すると止まった状態に戻る", a.runtime.state == STATE_STOPPED and a.runtime.start()[0] is True)
a.close()

print("■ 静かなときに自分から話すか考える（既定OFF。2026-10-16）")
a = Agent(mode=MODE_SILENT, initiative_enabled=True, initiative_quiet_seconds=0.3,
          initiative_min_gap_seconds=60.0, initiative_activity_seconds=30.0)
a.say("こんばんは")
check("しばらく静かになったら、考える（AIを呼ぶ）", wait_until(lambda: len(a.decide_calls()) == 2, 4.0)
      and "話題を出すか" in a.decide_calls()[-1].messages[0].content, len(a.decide_calls()))
check("考えたことを判断のログに出す", any("自分から話すか考えます" in line for line in a.logs))
time.sleep(1.5)
check("15分（ここでは60秒）に1回まで", len(a.decide_calls()) == 2, len(a.decide_calls()))
a.close()
a = Agent(mode=MODE_SILENT, initiative_quiet_seconds=0.3)
a.say("こんばんは")
time.sleep(1.5)
check("OFFなら考えない", len(a.decide_calls()) == 1)
a.close()
a = Agent(mode=MODE_SILENT, initiative_enabled=True, initiative_quiet_seconds=0.3)
time.sleep(1.0)
check("やりとりが無い場では考えない（独り言を言わない）", a.decide_calls() == [])
a.close()

print("■ T38 再起動")
a = Agent(mode=MODE_SILENT)
a.say("前回の話", speaker="A")
a.wait_decisions(1)
a.store.save_persona(Persona(name="テストの人格", summary="とても静か"))
a.close()
b = Agent(path=a.path, mode=MODE_SILENT)
check("T38 起動しただけでは反応しない（AI を呼ばない）", (time.sleep(0.3) or b.decide_calls() == []))
before = len(b.decisions())           # 前回の判断も同じ記録に入っている
b.say("今回の話", speaker="B")
b.wait_decisions(before + 1)
user = b.decide_calls()[0].messages[0].content
check("T38 直近の出来事が窓に戻る（直近の会話に入る）", "A: 前回の話" in user, user[:300])
check("T38 人格が残っている", b.runtime.persona.name == "テストの人格" and "とても静か" in user)
b.close()

print("■ T39 記録（agent_data.db）が壊れている")
folder = tempfile.mkdtemp()
path = os.path.join(folder, "agent_data.db")
with open(path, "wb") as f:
    f.write(b"this is not a sqlite database" * 100)
store = AgentStore(path)
check("T39 バックアップが無ければ空で作り直す", store.open() == OPEN_RECREATED and store.count("events") == 0)
check("T39 壊れたものは名前を変えて残す", any(n.startswith("agent_data.db.broken_") for n in os.listdir(folder)))
a = Agent(path=path, mode=MODE_SILENT)
a.say("バックアップ前の話")
a.wait_decisions(1)
check("1日1回バックアップを作る", a.store.backup_daily() is True and a.store.backup_daily() is False)
check("バックアップは backup/ に置く", os.listdir(os.path.join(folder, "backup"))[0].startswith("agent_data_"))
a.close()
store.close()
with open(path, "r+b") as f:
    f.seek(0)
    f.write(b"\x00" * 200)
store = AgentStore(path)
check("T39 壊れていたらバックアップから戻す", store.open() == OPEN_RESTORED)
check("T39 戻した記録が読める", store.count("events") == 1)
store.close()
store = AgentStore(path)
check("戻した後は普通に開ける", store.open() == OPEN_OK)
store.close()

print("■ 保存期間（他の人の発言は7日で消す）")
now = time.time()
clock = {"t": now - 8 * 24 * 3600}
old = AgentStore(os.path.join(tempfile.mkdtemp(), "agent_data.db"), clock=lambda: clock["t"])
old.open()
from agent_harness import make_event
old.add_events([make_event("8日前の発言", at=clock["t"])])
old.add_usage("mock", "mock-1", "decide", 1, 1, 0, 0.0, True, None, "t")
clock["t"] = now
old.purge()
check("7日を過ぎた出来事は消す", old.count("events") == 0)
check("利用量の記録は残す（1年）", old.count("usage_records") == 1)
old.close()

finish()
