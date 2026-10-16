# -*- coding: utf-8 -*-
"""
長期記憶ファイル（agent/memory/journal.py。2026-10-16 本人「アカウント別にチャットした会話の内容を長期記憶ファイルに保存して欲しい」）。
本人の決定: 自分のアカウントごと＋相手ごと / 会話の全文と要約の両方 / 読めるファイル（メモ帳で開ける）。

一時フォルダに書く。音は鳴らさない・通信しない（模擬の AI）。
⚠️ 守り: OFFなら書かない（既定）・起動前からあった行は書かない・書けなくてもエージェントは止まらない・
   アカウントが違えば、同じ名前の相手でも記憶もファイルも分ける
⚠️ テストの名前・内容は作り物（リポジトリは公開）。
"""
import os, tempfile, time

from agent_harness import Agent, check, finish, wait_until
from agent.config import AgentConfig
from agent.events import AgentEvent, KIND_CHAT_MESSAGE, KIND_CHAT_NOTICE, SOURCE_GRAVITY, SOURCE_TEST, new_event_id
from agent.llm.mock import MODE_ENGAGE
from agent.memory.journal import ConversationJournal, LOG_HEAD, SUMMARY_HEAD, safe_name
from agent.memory.recall import MemoryKeeper
from agent.memory.store import AgentStore

DAY = time.strftime("%Y-%m-%d")


def gravity(text, speaker="たろう", account="テスト垢", kind=KIND_CHAT_MESSAGE, is_self=False, backlog=False,
            source=SOURCE_GRAVITY):
    return AgentEvent(event_id=new_event_id(), kind=kind, source=source, key=new_event_id(), speaker=speaker,
                      text=text, observed_at=time.time(), meta={"backlog": backlog, "account": account}, is_self=is_self)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def journal(enabled=True):
    root = os.path.join(tempfile.mkdtemp(), "AIの記憶")
    state = {"on": enabled}
    return ConversationJournal(root, lambda: state["on"]), root, state


print("■ ファイルの名前")
check("Windows で使えない文字は「_」", safe_name('a/b\\c:d*e?"f<g>h|i') == "a_b_c_d_e__f_g_h_i")
check("末尾の点・空白は除く（Windows で消えてしまう）", safe_name("なまえ. ") == "なまえ")
check("空なら代わりの名前", safe_name("  ") == "名前不明" and safe_name("", "アカウント不明") == "アカウント不明")
check("長すぎる名前は40字まで", len(safe_name("あ" * 100)) == 40)
check("絵文字はそのまま（メモ帳で読める）", safe_name("テストちゃ👼") == "テストちゃ👼")

print("■ OFFなら何も書かない（既定）")
check("設定の既定はOFF", AgentConfig().journal_enabled is False)
j, root, state = journal(enabled=False)
j.record_events([gravity("こんばんは")])
j.record_reply("テスト垢", "たろう", "こんばんは", "voice")
j.write_summaries("テスト垢", {"people": {"たろう": ["- 猫が好き"]}, "room": []})
check("フォルダも作らない", not os.path.exists(root))

print("■ その日の全文と、相手ごとのファイル")
j, root, state = journal()
j.record_events([
    gravity("前からあった行", backlog=True),
    gravity("こんばんは"),
    gravity("いらっしゃい", speaker="テストちゃ👼", is_self=True),
    gravity("はなこが音声ルームに参加しました", speaker="はなこ", kind=KIND_CHAT_NOTICE),
    gravity("2行の\n発言", speaker="はなこ"),
    gravity("手入力の欄から", source=SOURCE_TEST),
])
day_file = os.path.join(root, "テスト垢", "会話の記録", DAY + ".md")
text = read(day_file)
check("自分のアカウントのフォルダに、日ごとのファイル", os.path.exists(day_file))
check("発言を届いた順に、時刻・名前つきで", text.index("たろう: こんばんは") < text.index("テストちゃ👼（自分）: いらっしゃい")
      < text.index("（お知らせ）はなこが音声ルームに参加しました"), text)
check("改行は「 / 」にして1行に", "はなこ: 2行の / 発言" in text, text)
check("起動前からあった行は書かない", "前からあった行" not in text)
check("GRAVITY のチャット以外は書かない", "手入力の欄から" not in text)
held = gravity("保留から戻った")
j.record_events([held])
j.record_events([held])
check("保留から戻った出来事（同じもの）は2度書かない", read(day_file).count("保留から戻った") == 1)
partner = os.path.join(root, "テスト垢", "相手", "たろう.md")
ptext = read(partner)
check("話した相手ごとのファイル", os.path.exists(partner) and os.path.exists(os.path.join(root, "テスト垢", "相手", "はなこ.md")))
check("相手のファイルは「覚えていること」と「会話の記録」に分かれる",
      ptext.index(SUMMARY_HEAD) < ptext.index(LOG_HEAD) < ptext.index("たろう: こんばんは"), ptext)
check("相手のファイルに日の見出し", f"### {DAY}" in ptext)
check("自分の発言・お知らせで相手のファイルは作らない",
      sorted(os.listdir(os.path.join(root, "テスト垢", "相手"))) == ["たろう.md", "はなこ.md"])

print("■ AI の返事")
j.record_reply("テスト垢", "たろう", "たろうさん、こんばんは", "voice", ai_name="アイ")
j.record_reply("テスト垢", "たろう", "チャットで返事", "chat", ai_name="アイ")
text, ptext = read(day_file), read(partner)
check("声で答えたら、その日の全文にも（チャット欄に出ないので）", "アイ（AI・声）: たろうさん、こんばんは" in text, text)
check("チャットで答えたら、その日の全文には書かない（チャット欄に出た行で書かれる）", "チャットで返事" not in text)
check("相手のファイルには両方", "アイ（AI・声）: たろうさん、こんばんは" in ptext and "アイ（AI・チャット）: チャットで返事" in ptext)
check("同じ日の見出しは1回だけ", ptext.count(f"### {DAY}") == 1, ptext)

print("■ 名前が切れて出ても同じファイル")
j.record_events([gravity("切れた", speaker="ながいなまえのひと"), gravity("続き", speaker="ながいなまえ..")])
folder = os.path.join(root, "テスト垢", "相手")
check("前に作った同じ人のファイルを使う", "ながいなまえ.md" not in os.listdir(folder)
      and "ながいなまえ: 続き" in read(os.path.join(folder, "ながいなまえのひと.md")), os.listdir(folder))

print("■ 要約（覚えていること）を書き直す")
j.write_summaries("テスト垢", {"people": {"たろう": ["- 猫を飼っている（2026-10-16）"], "じろう": ["- 初めて見た"]},
                              "room": ["- この場: 夜はゲームの話が多い"]})
j.write_summaries("テスト垢", {"people": {"たろう": ["- 猫を2匹飼っている（2026-10-17）"]}, "room": []})
ptext = read(partner)
check("相手のファイルの「覚えていること」を新しい要約にする", "猫を2匹飼っている" in ptext and "猫を飼っている（" not in ptext, ptext)
check("会話の記録はそのまま", "たろう: こんばんは" in ptext and "アイ（AI・チャット）: チャットで返事" in ptext)
check("要約は会話の記録より前", ptext.index("猫を2匹飼っている") < ptext.index(LOG_HEAD))
check("まだ話していない人の要約だけでもファイルを作る", "初めて見た" in read(os.path.join(folder, "じろう.md")))
room = os.path.join(root, "テスト垢", "この場とAI自身.md")
check("この場とAI自身のファイル（毎回書き直す）", os.path.exists(room) and "（まだありません）" in read(room))
j.record_events([gravity("要約のあとの発言")])
ptext = read(partner)
check("書き直したあとも、会話の記録の続きに書ける", ptext.rstrip().endswith("たろう: 要約のあとの発言")
      and ptext.count(SUMMARY_HEAD) == 1, ptext[-200:])

print("■ アカウントごとに分ける")
j.record_events([gravity("別のアカウントで", account="複製の垢")])
check("同じ名前の相手でも、自分のアカウントが違えば別のファイル",
      "別のアカウントで" in read(os.path.join(root, "複製の垢", "相手", "たろう.md"))
      and "別のアカウントで" not in read(partner))
j.record_events([gravity("どこの", account="")])
check("アカウントが分からないときは「アカウント不明」", os.path.exists(os.path.join(root, "アカウント不明", "相手", "たろう.md")))

print("■ 記憶もアカウントごと")
store = AgentStore(os.path.join(tempfile.mkdtemp(), "agent_data.db"))
store.open()
cfg = AgentConfig(memory_enabled=True, summarize_min_lines=1)
current = {"account": "テスト垢"}
mk = MemoryKeeper(store, lambda: cfg, account_getter=lambda: current["account"])
mk.observe([gravity("猫を飼い始めた")])
mk.apply_summary({"memories": [{"scope": "person", "person": "たろう", "content": "猫を飼っている", "importance": 0.8}]},
                 ["たろう"])
current["account"] = "複製の垢"
mk.observe([gravity("犬が好き", account="複製の垢")])
mk.apply_summary({"memories": [{"scope": "person", "person": "たろう", "content": "犬が好き", "importance": 0.8}]},
                 ["たろう"])
check("別のアカウントの記憶は思い出さない", mk.recall([gravity("やあ")]) == ["[たろう] 犬が好き"], mk.recall([gravity("やあ")]))
current["account"] = "テスト垢"
check("元のアカウントに戻れば、そちらの記憶", mk.recall([gravity("やあ")]) == ["[たろう] 猫を飼っている"])
files = mk.summary_for_files()
check("ファイル用の要約も今のアカウントの分だけ", list(files["people"]) == ["たろう"]
      and files["people"]["たろう"][0].startswith("- 猫を飼っている"), files)
check("記憶の一覧ではアカウントが分かる", sorted(r[1] for r in store.memories_with_account(10)) == ["テスト垢", "複製の垢"])

print("■ エージェントの中で（模擬の AI）")
a = Agent(mode=MODE_ENGAGE, start=False)
j, root, state = journal()
a.runtime.deps.journal = j
a.runtime.start()
a.runtime.submit(gravity("こんばんは"))
check("OFFの間は書かない", wait_until(lambda: len(a.speaker.spoken) >= 1, 5.0) and not os.path.exists(root))
time.sleep(0.3)        # 1つ目の返事を書く（書かない）ところまで終わらせる
a.runtime.config.journal_enabled = True
a.runtime.submit(gravity("聞こえる？"))
partner = os.path.join(root, "テスト垢", "相手", "たろう.md")
check("ONにすると、発言とAIの返事を相手のファイルに", wait_until(
    lambda: os.path.exists(partner) and "たろう: 聞こえる？" in read(partner) and "（AI・声）" in read(partner), 8.0),
      (a.logs[-3:], os.path.exists(partner) and read(partner)))
check("出来事のアカウント（監視が見分けたもの）のフォルダに", os.listdir(root) == ["テスト垢"], os.listdir(root))
check("ONにする前の発言は入らない", "こんばんは" not in read(partner))
a.close()

a = Agent(mode=MODE_ENGAGE, start=False, journal_enabled=True)


class Broken:
    def __getattr__(self, name):
        def fail(*args):
            raise PermissionError("ファイルが開かれている")
        return fail


a.runtime.deps.journal = Broken()
a.runtime.start()
a.runtime.submit(gravity("書けなくても"))
a.runtime.submit(gravity("続ける", speaker="はなこ"))
check("書けなくても、エージェントは答え続ける", wait_until(lambda: len(a.speaker.spoken) >= 1, 5.0))
check("知らせるのは1回だけ", wait_until(lambda: sum("長期記憶ファイルに書けませんでした" in line for line in a.logs) == 1, 2.0)
      and sum("長期記憶ファイルに書けませんでした" in line for line in a.logs) == 1, a.logs)
a.close()

finish()
