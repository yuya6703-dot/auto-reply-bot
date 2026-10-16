# -*- coding: utf-8 -*-
"""
オーナーの自己分析を読む・気づいたことを書き足す（2026-10-16 本人「俺であるオーナー情報については（自己分析のフォルダ）を参照したり、
情報を引き出したり、気づいたことや特徴、性格、他人に対する接し方や癖や言動行動パターンなどここに記録してほしい」）。

⚠️ 本人の本物のフォルダには触らない（一時フォルダに作り物のメモを置く）。模擬の AI・通信しない。テストの内容は作り物。
"""
import os, tempfile, time

from agent_harness import Agent, check, finish, make_event, wait_until
from agent.events import SOURCE_GRAVITY
from agent.config import AgentConfig
from agent.llm.mock import MODE_ENGAGE, MODE_SILENT
from agent.owner_profile import NOTES_FILE, OwnerProfile


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


folder = tempfile.mkdtemp()
write(os.path.join(folder, "自己分析.md"), "# 自己分析（作り物）\n- 作ったものの理由を書き残す\n- 反復に強い\n")
write(os.path.join(folder, "画像.png"), "読まない")
profile = OwnerProfile(lambda: folder)

print("■ フォルダを読む")
check("既定はOFF", AgentConfig().owner_profile_enabled is False)
text = profile.source_text()
check(".md / .txt を読む（ほかは読まない）", "反復に強い" in text and "読まない" not in text)
fp = profile.fingerprint()
check("中身が変わったかの目印", fp.startswith("自己分析.md:"))
check("フォルダが無ければ何もしない", OwnerProfile(lambda: "").source_text() == "" and OwnerProfile(lambda: "").fingerprint() == "")

print("■ 気づいたことを書き足す")
check("日付の見出しの下に書き足す", profile.append_notes(["人の話を最後まで聞く", "  "], at=time.time()) == 1)
notes_path = os.path.join(folder, NOTES_FILE)
body = open(notes_path, encoding="utf-8").read()
check("「AIが気づいたこと.md」（推定と書く・消してよい）", "推定" in body and f"## {time.strftime('%Y-%m-%d')}" in body
      and "- 人の話を最後まで聞く" in body)
profile.append_notes(["冗談で場を和ませる"])
check("同じ日の見出しは1回", open(notes_path, encoding="utf-8").read().count("## ") == 1)
check("これまでの気づきを読める（同じことを書かないため）", profile.recent_notes() == ["- 人の話を最後まで聞く", "- 冗談で場を和ませる"])
check("書き足したファイルは、読むときは最後（本人が書いたものが先）", profile._files() == ["自己分析.md", NOTES_FILE])

print("■ エージェントの中で: 読んでまとめる")
a = Agent(mode=MODE_SILENT, start=False, owner_profile_enabled=True, owner_names="オーナー", memory_enabled=True,
          summarize_min_lines=1, summarize_quiet_seconds=0.2, summarize_interval_seconds=999)
a.runtime.deps.owner_profile = profile
a.runtime.start()
a.runtime._maybe_read_owner_profile(force=True)
req = [r for r in a.mock.requests if r.purpose == "profile"]
check("フォルダの中身を AI にまとめさせる（個人を特定できることは書かせない）", req and "反復に強い" in req[0].messages[0].content
      and "個人を特定できることは書かない" in req[0].system)
check("まとめを覚える", "（模擬）ものづくりが好き" in a.store.load_note("owner_profile_summary"))
a.runtime._maybe_read_owner_profile(force=True)
check("変わっていなければ読み直さない", len([r for r in a.mock.requests if r.purpose == "profile"]) == 1)
write(os.path.join(folder, "追加.txt"), "- 夜型")
a.runtime._maybe_read_owner_profile(force=True)
check("ファイルが変わったら読み直す", len([r for r in a.mock.requests if r.purpose == "profile"]) == 2)
a.mock.mode = MODE_ENGAGE
a.say("こんばんは", speaker="はなこ")
check("オーナーがいない会話には人物像を渡さない", wait_until(lambda: len(a.decide_calls()) >= 1, 5.0)
      and "## オーナーについて" not in a.decide_calls()[-1].messages[0].content)
a.say("ただいま", speaker="オーナー")
check("オーナーが会話にいれば、人物像を渡す（ルームで話題にしない）", wait_until(
    lambda: any("## オーナーについて" in r.messages[0].content and "話題にしない" in r.messages[0].content
                for r in a.decide_calls()), 5.0))

print("■ エージェントの中で: 会話の整理のときに、オーナーについて気づいたことを書き足す")
a.mock.mode = MODE_SILENT
a.mock.script_summarize = [{"memories": [], "owner_notes": ["話の最後に必ずお礼を言う", "最近病院に通っているらしい"]}]
a.runtime.submit(make_event("今日はありがとね", speaker="オーナー", source=SOURCE_GRAVITY))     # 整理は GRAVITY の会話から
check("整理を頼むときに、オーナーについて気づいたことも聞く（これまでの気づきも見せる）", wait_until(
    lambda: any(r.purpose == "summarize" and "owner_notes" in r.messages[0].content
                and "人の話を最後まで聞く" in r.messages[0].content for r in a.mock.requests), 8.0))
check("気づいたことを書き足す（繊細な事柄は書かない）", wait_until(
    lambda: "話の最後に必ずお礼を言う" in open(notes_path, encoding="utf-8").read(), 5.0)
      and "病院" not in open(notes_path, encoding="utf-8").read())
check("判断のログに", any("オーナーについて気づいたことを書き足しました" in line for line in a.logs))
a.close()

a = Agent(mode=MODE_SILENT, start=False, owner_profile_enabled=False, owner_names="オーナー")
a.runtime.deps.owner_profile = profile
a.runtime.start()
a.runtime._maybe_read_owner_profile(force=True)
check("OFFなら読まない", not any(r.purpose == "profile" for r in a.mock.requests))
a.close()

finish()
