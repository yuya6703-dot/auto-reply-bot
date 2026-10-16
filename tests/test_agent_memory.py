# -*- coding: utf-8 -*-
"""
記憶（人・この場・自分が言ったこと・人の印象・関係の値。設計書/07、2026-10-16 本人「全部やろうか」）。
本物の AgentRuntime と agent_data.db を、模擬の AI で動かす。通信しない。

⚠️ 守り（設計書/06 の 8章）を確かめる: OFFなら何も覚えない・会話に出てこない人のことは覚えない・繊細な事柄は覚えない・
   印象は推定として渡す・関係の値は1回に少しだけ動く・消せる・期限で消える
⚠️ テストの名前・内容は作り物（リポジトリは公開）。
"""
import os, tempfile, time

from agent_harness import Agent, check, finish, make_event, wait_until
from agent.config import AgentConfig
from agent.llm.mock import MODE_ENGAGE, MODE_SILENT
from agent.memory.recall import MemoryKeeper, is_sensitive, same_person
from agent.memory.store import AgentStore

print("■ 人の見分け")
check("切れた長い名前は同じ人", same_person("ながいなまえ", "ながいなまえの人"))
check("短い名前どうしは、先頭が同じでも別の人（ゆう / ゆうき）", not same_person("ゆう", "ゆうき"))
check("同じ名前は同じ人（「..」は除く）", same_person("たろう..", "たろう"))
check("繊細な事柄を見分ける", is_sensitive("最近病院に通っている") and is_sensitive("宗教の話") and not is_sensitive("猫が好き"))


def keeper(**config):
    store = AgentStore(os.path.join(tempfile.mkdtemp(), "agent_data.db"))
    store.open()
    cfg = AgentConfig(**config)
    return MemoryKeeper(store, lambda: cfg), store, cfg


print("■ OFFなら何も覚えない（既定）")
mk, store, cfg = keeper()
mk.observe([make_event("猫を飼い始めた", speaker="たろう")])
check("人も覚えない", store.persons() == [])
check("整理もしない", mk.due(9999) is False)
check("思い出しも渡さない", mk.recall([make_event("x", speaker="たろう")]) == [])

print("■ 覚える（整理の返事を記憶にする）")
mk, store, cfg = keeper(memory_enabled=True, summarize_min_lines=2)
mk.observe([make_event("猫を飼い始めた", speaker="たろう"), make_event("いいね！", speaker="はなこ")])
check("発言した人を覚える", {r[0] for r in store.persons()} == {"たろう", "はなこ"})
check("発言がたまって静かになったら整理する", mk.due(quiet_seconds=200) is True and mk.due(quiet_seconds=10) is False)
kept, dropped = mk.apply_summary({
    "memories": [
        {"scope": "person", "person": "たろう", "content": "最近猫を飼い始めた", "importance": 0.8, "confidence": "high"},
        {"scope": "room", "person": None, "content": "夜はゲームの話が多い", "importance": 0.5},
        {"scope": "self", "content": "たろうに猫の名前を聞くと約束した", "importance": 0.6},
        {"scope": "person", "person": "会話にいない人", "content": "作り話", "importance": 0.9},
        {"scope": "person", "person": "はなこ", "content": "最近病院に通っている", "importance": 0.9},
    ],
    "impressions": [{"person": "たろう", "content": "冗談が好きそう", "confidence": "low"}],
    "relationships": [{"person": "たろう", "warmth_delta": 5, "reason": "楽しく話した"}],
}, speakers=["たろう", "はなこ"])
contents = [r[3] for r in store.memories()]
check("人・この場・自分のことを覚える", {"最近猫を飼い始めた", "夜はゲームの話が多い", "たろうに猫の名前を聞くと約束した"} <= set(contents),
      contents)
check("会話に出てこない人のことは覚えない（作り話を防ぐ）", "作り話" not in contents)
check("繊細な事柄は覚えない（H5）", "最近病院に通っている" not in contents)
check("捨てた数を返す", (kept, dropped) == (3, 2), (kept, dropped))
check("印象は、推定がONのときだけ", not any(r[1] == "impression" for r in store.memories()))
check("関係の値は、ONのときだけ", store.relationships() == [])
check("整理したら、たまった数を戻す", mk.due(quiet_seconds=9999) is False)

print("■ 思い出す")
lines = mk.recall([make_event("ただいま", speaker="たろう")])
check("今回の発言者の記憶を先に", lines and lines[0] == "[たろう] 最近猫を飼い始めた", lines)
check("この場・自分のことも", "[この場] 夜はゲームの話が多い" in lines and "[あなた自身] たろうに猫の名前を聞くと約束した" in lines, lines)
check("知らない人だけのときも、この場のことは渡す", "[この場] 夜はゲームの話が多い" in mk.recall([make_event("はじめまして", speaker="じろう")]))
check("思い出しても、知らない人を新しく覚えない", "じろう" not in {r[0] for r in store.persons()})

print("■ 人の印象・関係の値（ONのとき）")
mk, store, cfg = keeper(memory_enabled=True, impressions_enabled=True, relationships_enabled=True)
mk.observe([make_event("こんばんは", speaker="たろう")])
mk.apply_summary({"memories": [],
                  "impressions": [{"person": "たろう", "content": "冗談が好きそう", "confidence": "low"},
                                  {"person": "たろう", "content": "政治の話が好き", "confidence": "mid"}],
                  "relationships": [{"person": "たろう", "warmth_delta": 9, "reason": "楽しく話した"}]}, ["たろう"])
lines = mk.recall([make_event("やあ", speaker="たろう")])
check("印象は「推定・確からしさ」を付けて渡す", "[たろう・印象（推定・確からしさ低）] 冗談が好きそう" in lines, lines)
check("繊細な事柄の印象は覚えない", not any("政治" in line for line in lines))
rel = store.relationship("たろう")
check("温かさは1回に2までしか動かない", rel and rel["warmth"] == 2.0, rel)
check("関係は数値でなく言葉で渡す", any("あなたとは: まだあまり話していない・やりとりはふつう" in line for line in lines), lines)
for _ in range(30):
    mk.note_interaction("たろう")
check("話しかけるたびに、なじみが少し上がる（上限100）", store.relationship("たろう")["familiarity"] == 60.0)
check("なじみが上がると言葉も変わる", any("よく話す" in line for line in mk.recall([make_event("やあ", speaker="たろう")])))

print("■ 消す・期限")
mid = store.memories()[0][0]
store.delete_memory(mid)
check("1件消せる", all(r[0] != mid for r in store.memories()))
store.delete_all_memories()
check("全部消せる（人・関係も）", store.memories() == [] and store.persons() == [] and store.relationships() == [])
clock = {"t": time.time()}
old = AgentStore(os.path.join(tempfile.mkdtemp(), "agent_data.db"), clock=lambda: clock["t"])
old.open()
old.upsert_person("たろう", "たろう")
old.add_memory("person", "たろう", "猫が好き", "high", 0.4, 30 * 24 * 3600)
old.add_memory("room", None, "大事なこと", "high", 0.9, 180 * 24 * 3600)
clock["t"] += 31 * 24 * 3600
old.purge()
check("期限を過ぎた記憶は消える（重要なものは長く残る）", [r[3] for r in old.memories()] == ["大事なこと"])
clock["t"] += 181 * 24 * 3600
old.purge()
check("最後に見てから180日たった人は忘れる", old.persons() == [])

print("■ エージェントの中で（模擬の AI）")
a = Agent(mode=MODE_SILENT, memory_enabled=True, summarize_min_lines=2, summarize_quiet_seconds=0.3,
          summarize_interval_seconds=999)
a.mock.script_summarize = [{"memories": [{"scope": "person", "person": "たろう", "content": "猫を飼っている",
                                          "importance": 0.8, "confidence": "high"}]}]
a.say("猫を飼い始めた", speaker="たろう")
a.say("いいね", speaker="はなこ")
check("会話が静かになったら整理する（AIを呼ぶ）", wait_until(lambda: any("覚えておくことを整理しました（新しく1件）" in line
                                                       for line in a.logs), 5.0), a.logs[-3:])
check("利用量に「整理」として数える", wait_until(lambda: a.runtime.today_usage()[0] >= 2))
a.mock.mode = MODE_ENGAGE
a.say("ただいま", speaker="たろう")
check("次の判断に「覚えていること」が入る", wait_until(lambda: len(a.decide_calls()) >= 2)
      and "[たろう] 猫を飼っている" in a.decide_calls()[-1].messages[0].content)
check("「印象は推定。口に出さない」と固定の指示に書く", "本人に向かって言わないでください" in a.decide_calls()[-1].system)
a.close()
a = Agent(mode=MODE_SILENT, summarize_min_lines=1, summarize_quiet_seconds=0.1)
a.say("猫を飼い始めた", speaker="たろう")
time.sleep(1.0)
check("OFFなら整理しない（AIを呼ばない）", a.runtime.today_usage()[0] == 1 and a.store.persons() == [])
a.close()

finish()
