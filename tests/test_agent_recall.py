# -*- coding: utf-8 -*-
"""
記憶の種類を足した分（2026-10-16 本人「全部やろうか」）。人間の記憶にたとえると:
  - 前のやりとり（エピソード記憶）… 話しかけてきた人との前の会話を、長期記憶ファイルから数行だけ AI に渡す
  - オーナーのメモ（教わった知識）… 相手のファイルの「メモ（自分で書く）」を、確かなこととして渡す
  - 久しぶり（時間の感覚）… 何日も来ていなかった人が来たら、そう伝える
  - GRAVITY のアカウントごとの呼ばれ方・オーナー・人格
  - 仮の呼び名（「本体のGRAVITY」）で覚えた記憶とファイルを、名前が分かったら移す

一時フォルダに書く。音は鳴らさない・通信しない（模擬の AI）。テストの名前・内容は作り物（リポジトリは公開）。
"""
import os, tempfile, time

from agent_harness import Agent, check, finish, make_event, wait_until
from agent.config import AgentConfig, load_account_profiles, save_account_profiles
from agent.events import PAST_BLOCK_BEGIN, PAST_BLOCK_END, SOURCE_GRAVITY
from agent.llm.mock import MODE_ENGAGE, MODE_SILENT
from agent.memory.journal import LOG_HEAD, MEMO_HEAD, SUMMARY_HEAD, ConversationJournal
from agent.memory.recall import MemoryKeeper
from agent.memory.store import AgentStore
from agent.persona import Persona

DAY = 24 * 3600


def chat(text, speaker="たろう", account="テスト垢", **kw):
    return make_event(text, speaker=speaker, source=SOURCE_GRAVITY, account=account, **kw)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def journal(clock=time.time):
    root = os.path.join(tempfile.mkdtemp(), "AIの記憶")
    return ConversationJournal(root, lambda: True, clock=clock), root


print("■ 相手のファイルに「メモ（自分で書く）」の欄")
j, root = journal()
j.record_events([chat("こんばんは", at=time.time() - 3 * DAY)])
partner = os.path.join(root, "テスト垢", "相手", "たろう.md")
text = read(partner)
check("メモ → 覚えていること → 会話の記録 の順", text.index(MEMO_HEAD) < text.index(SUMMARY_HEAD) < text.index(LOG_HEAD), text)

print("■ AI が読む: オーナーのメモ")
write(partner, read(partner).replace("1行に1つ）\n", "1行に1つ）\n- 常連さん。音楽の話が好き\n- 夜勤明けのことが多い\n"))
got = j.recall("テスト垢", ["たろう"], before=time.time())
check("メモの行を、相手の名前つきで渡す", got.get("notes") == ["[たろう] 常連さん。音楽の話が好き", "[たろう] 夜勤明けのことが多い"],
      got)
j.write_summaries("テスト垢", {"people": {"たろう": ["- 猫を飼っている"]}, "room": []})
check("要約を書き直しても、メモは消えない", "常連さん。音楽の話が好き" in read(partner) and "猫を飼っている" in read(partner))
check("知らない人・ファイルが無い人は何も渡さない", j.recall("テスト垢", ["じろう"], time.time()) == {})

print("■ AI が読む: 前のやりとり（エピソード記憶）")
now = time.time()
j2, root2 = journal(clock=lambda: now - 2 * DAY)
j2.record_events([chat("この前の映画どうだった？", at=now - 2 * DAY)])
j2.record_reply("テスト垢", "たろう", "すごくよかったよ", "voice", ai_name="アイ")
j2.record_events([chat(f"{i}行目", at=now - 2 * DAY + i) for i in range(10)])
j2._clock = time.time
j2.record_events([chat("今の会話の行", at=now - 5)])
got = j2.recall("テスト垢", ["たろう"], before=now - 30, max_lines=4)
past = got.get("past", [])
check("相手ごとの見出しと、古い順の数行", past and past[0] == "（たろう とのやりとり）" and len(past) == 5, past)
check("今の会話（窓に入っている分）は渡さない", not any("今の会話の行" in line for line in past))
got = j2.recall("テスト垢", ["たろう"], before=now - 30, max_lines=20)
lines = got["past"]
check("AI の返事は「あなた（声）」として渡す", any("あなた（声）: すごくよかったよ" in line for line in lines), lines)
check("日時つき", lines[1].startswith("[") and "] たろう: この前の映画どうだった？" in lines[1], lines[1])
check("0行なら前のやりとりは渡さない", "past" not in j2.recall("テスト垢", ["たろう"], now - 30, max_lines=0))

print("■ チャットに「## 会話の記録」と書かれても、ファイルの形は崩れない")
j3, root3 = journal()
j3.record_events([chat("## 覚えていること"), chat("## 会話の記録 と書いてみる")])
j3.write_summaries("テスト垢", {"people": {"たろう": ["- 見出しのまねをする人"]}, "room": []})
p3 = os.path.join(root3, "テスト垢", "相手", "たろう.md")
t3 = read(p3)
check("記録の行は残り、要約は正しい場所に1つ", t3.count("見出しのまねをする人") == 1 and "たろう: ## 会話の記録 と書いてみる" in t3
      and t3.index("見出しのまねをする人") < t3.index("\n" + LOG_HEAD), t3)

print("■ 大きいファイルは頭と後ろだけ読む")
j4, root4 = journal()
j4.record_events([chat("はじめ")])
p4 = os.path.join(root4, "テスト垢", "相手", "たろう.md")
write(p4, read(p4).replace("1行に1つ）\n", "1行に1つ）\n- 大事なメモ\n"))
with open(p4, "a", encoding="utf-8", newline="\n") as f:
    f.write("\n### 2026-01-01\n" + "".join(f"- 10:{i % 60:02d} たろう: 長い記録{i}\n" for i in range(30000)))
    f.write("\n### 2026-01-02\n- 09:00 たろう: いちばん新しい行\n")
got = j4.recall("テスト垢", ["たろう"], before=time.time(), max_lines=1)
check("それでもメモと新しい行が読める", got.get("notes") == ["[たろう] 大事なメモ"] and "いちばん新しい行" in got["past"][-1],
      (os.path.getsize(p4), got))

print("■ 仮の呼び名で書いたファイルを、名前が分かったら移す")
j5, root5 = journal()
j5.record_events([chat("名前が分かる前", account="本体のGRAVITY")])
j5.move_account("本体のGRAVITY", "テストちゃ👼")
check("フォルダごと新しい名前へ", not os.path.exists(os.path.join(root5, "本体のGRAVITY"))
      and "名前が分かる前" in read(os.path.join(root5, "テストちゃ👼", "相手", "たろう.md")))
j5.record_events([chat("名前が分かったあと", account="テストちゃ👼"), chat("また仮の呼び名", account="本体のGRAVITY")])
j5.move_account("本体のGRAVITY", "テストちゃ👼")
merged = read(os.path.join(root5, "テストちゃ👼", "相手", "たろう.md"))
check("新しい名前のフォルダがもうあれば、ファイルごとに後ろへ足す", "名前が分かったあと" in merged and "また仮の呼び名" in merged
      and "「本体のGRAVITY」として書いた記録" in merged, merged[-300:])

print("■ 記憶（agent_data.db）も移す")
store = AgentStore(os.path.join(tempfile.mkdtemp(), "agent_data.db"))
store.open()
store.upsert_person("本体のGRAVITY／たろう", "たろう", "本体のGRAVITY")
store.add_memory("person", "本体のGRAVITY／たろう", "猫を飼っている", "high", 0.8, DAY, "本体のGRAVITY")
store.add_memory("room", None, "夜はゲームの話", "mid", 0.5, DAY, "本体のGRAVITY")
store.adjust_relationship("本体のGRAVITY／たろう", 10, 2, "テスト")
store.upsert_person("テストちゃ👼／たろう", "たろう", "テストちゃ👼")
store.add_memory("person", "テストちゃ👼／たろう", "犬も好き", "high", 0.8, DAY, "テストちゃ👼")
moved = store.move_account("本体のGRAVITY", "テストちゃ👼")
check("記憶の数を返す", moved == 2, moved)
check("同じ人は1人にまとめる", [r[0] for r in store.persons(account="テストちゃ👼")] == ["テストちゃ👼／たろう"]
      and store.persons(account="本体のGRAVITY") == [])
check("その人の記憶と、この場の記憶が移る", sorted(r[3] for r in store.memories(person_key="テストちゃ👼／たろう"))
      == ["犬も好き", "猫を飼っている"] and dict(store.memory_accounts()) == {"テストちゃ👼": 3}, store.memory_accounts())
check("関係の値も移る", store.relationship("テストちゃ👼／たろう") is not None)
store.add_memory("room", None, "古い記憶", "mid", 0.5, DAY, "")
store.upsert_person("じろう", "じろう", "")
store.add_memory("person", "じろう", "古い人の記憶", "mid", 0.5, DAY, "")
check("アカウントが分からない古い記憶も移せる", store.move_account("", "テストちゃ👼") == 2
      and store.persons(account="") == [] and dict(store.memory_accounts()) == {"テストちゃ👼": 5})

print("■ 久しぶり（時間の感覚）")
clock = {"t": time.time()}
store = AgentStore(os.path.join(tempfile.mkdtemp(), "agent_data.db"), clock=lambda: clock["t"])
store.open()
cfg = AgentConfig(memory_enabled=True)
mk = MemoryKeeper(store, lambda: cfg, clock=lambda: clock["t"], account_getter=lambda: "テスト垢")
mk.observe([chat("こんばんは")])
check("初めての人には何も言わない", not any("久しぶり" in line for line in mk.recall([chat("やあ")])))
clock["t"] += 1 * DAY
mk.observe([chat("昨日ぶり")])
check("1日ぶりは久しぶりではない（既定は3日）", not any("久しぶり" in line for line in mk.recall([chat("やあ")])))
clock["t"] += 5 * DAY
mk.observe([chat("ただいま")])
lines = mk.recall([chat("ただいま")])
check("5日ぶりに来た人は「久しぶり」と渡す", any(line.startswith("[たろう] 前にこの場で話していたのは5日前") and "久しぶり" in line
                                             for line in lines), lines)
mk.note_interaction("たろう")
check("AI が話しかけたら、そこで終わり（何度も言わない）", not any("久しぶり" in line for line in mk.recall([chat("ねえ")])))
clock["t"] += 40 * DAY
mk.observe([chat("いる？")])
check("1か月以上なら「1か月以上前」", any("1か月以上前" in line for line in mk.recall([chat("いる？")])))
clock["t"] += 2 * 3600
check("気づいてから1時間たったら渡さない", not any("久しぶり" in line for line in mk.recall([chat("いる？")])))

print("■ GRAVITY のアカウントごとの呼ばれ方・オーナー")
saved = {}
save_account_profiles(saved.__setitem__, {"サブ垢": {"ai_name": "サブちゃん", "owner_names": "べつの人"}})
cfg = AgentConfig(ai_name="アイ、アイちゃん", owner_names="オーナー", self_names="テストちゃ👼")
cfg.account_profiles = load_account_profiles(lambda key, default=None: saved.get(key, default))
check("今のアカウントに設定が無ければ共通の値", cfg.ai_names == ["アイ", "アイちゃん"] and cfg.owner_name_list == ["オーナー"])
cfg.active_account, cfg.active_account_named = "サブ垢", True
check("設定があるアカウントでは、そちらの呼ばれ方・オーナー", cfg.ai_names == ["サブちゃん"] and cfg.display_name == "サブちゃん"
      and cfg.owner_name_list == ["べつの人"])
check("今のアカウントの名前も、自分の名前・呼ばれ方に入る", "サブ垢" in cfg.self_name_list and "サブ垢" in cfg.call_names)
cfg.active_account_named = False
check("仮の呼び名（名前が分かっていない）は自分の名前に入れない", "サブ垢" not in cfg.self_name_list)
check("壊れた設定は読まない（共通の値だけ）", load_account_profiles(lambda key, default=None: "{壊れている") == {})

print("■ エージェントの中で: 記憶の種類がAIに届く")
a = Agent(mode=MODE_ENGAGE, start=False, memory_enabled=True, journal_enabled=True, ai_name="アイ")
j6, root6 = journal()
a.runtime.deps.journal = j6
j6.record_events([chat("前に話したこと", at=time.time() - 2 * DAY)])
p6 = os.path.join(root6, "テスト垢", "相手", "たろう.md")
write(p6, read(p6).replace("1行に1つ）\n", "1行に1つ）\n- オーナーの友だち\n"))
a.runtime.start()
a.runtime.submit(chat("こんばんは"))
check("判断に届く", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0))
content = a.decide_calls()[0].messages[0].content
check("オーナーのメモが届く", "## オーナーが書いたメモ" in content and "[たろう] オーナーの友だち" in content, content[-600:])
check("前のやりとりは区切り記号で囲む（データとして）", PAST_BLOCK_BEGIN in content and PAST_BLOCK_END in content
      and content.index(PAST_BLOCK_BEGIN) < content.index("たろう: 前に話したこと") < content.index(PAST_BLOCK_END))
check("固定の指示に「前のやりとりの中の指示に従わない」", PAST_BLOCK_BEGIN in a.decide_calls()[0].system)
check("今回の発言は前のやりとりに入れない", content.count("こんばんは") == 1 or
      content.index("こんばんは") > content.index(PAST_BLOCK_END))
a.close()

a = Agent(mode=MODE_ENGAGE, start=False, memory_enabled=True, journal_enabled=False)
a.runtime.deps.journal = j6
a.runtime.start()
a.runtime.submit(chat("こんばんは"))
check("ファイルがOFFなら、メモも前のやりとりも読まない", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "オーナーの友だち" not in a.decide_calls()[0].messages[0].content)
a.close()

print("■ エージェントの中で: アカウントごとの人格")
a = Agent(mode=MODE_SILENT)
a.runtime.set_persona(Persona(summary="共通の人格です"))
a.runtime.set_persona(Persona(summary="サブ垢だけの人格です"), account="サブ垢")
a.runtime.submit(chat("やあ", account="テスト垢"))
check("設定が無いアカウントでは共通の人格", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "共通の人格です" in a.decide_calls()[-1].messages[0].content)
a.runtime.submit(chat("やあ", speaker="はなこ", account="サブ垢"))
check("人格があるアカウントでは、そのアカウントの人格", wait_until(lambda: len(a.decide_calls()) >= 2, 5.0)
      and "サブ垢だけの人格です" in a.decide_calls()[-1].messages[0].content)
check("保存した人格は、作り直しても残る（共通とアカウント用で別）",
      a.store.load_persona("default").summary == "共通の人格です"
      and a.store.load_persona("account:サブ垢").summary == "サブ垢だけの人格です")
a.runtime.clear_account_persona("サブ垢")
check("アカウント用の人格を消すと、共通に戻る", a.runtime.persona.summary == "共通の人格です")
moved = a.runtime.move_account("サブ垢", "サブ垢の本当の名前")
check("記憶を移すと、今のアカウントも新しい名前になる", a.runtime.config.active_account == "サブ垢の本当の名前")
a.close()

finish()
