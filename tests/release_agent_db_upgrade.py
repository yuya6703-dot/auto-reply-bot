"""前の版の AgentStore で作った agent_data.db（AIタブの記録）を、今のコードで開いても中身が変わらないかを確かめる。リリースの前に使う。

usage: python tests/release_agent_db_upgrade.py <old_files_dir> <work_dir>
  old_files_dir: 前の版の files/ 一式（git archive v1.9.0 files | tar -x -C DIR → DIR/files）

- v1.9.0 の agent_data.db は表の版 1（記憶の表・アカウントの列・予定の列が無い）。今の版は 4。
  開くと表と列を足すだけで、使った回数・費用（1日・1か月の上限の数え方に効く）・人格・判断の記録が変わらないことを見る。
- 2回開いても変わらない（列を2回足そうとして落ちない）ことも見る。
- 前の版と今の版は同じ名前のパッケージ（agent）なので、前の版で作る所は別のプロセスで動かす。
"""
import json
import os
import sqlite3
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
NEW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "files")

OLD_WRITER = r'''
import sys
sys.path.insert(0, sys.argv[1])
from agent.memory.store import AgentStore, SCHEMA_VERSION
from agent.persona import Persona
s = AgentStore(sys.argv[2])
s.open()
s.save_persona(Persona(name="テスト", summary="前の版で保存した要約", example_lines=["前の版の口調"]))
for i in range(3):
    s.add_usage("gemini", "gemini-test", "decide", 100 + i, 20, 0, 0.001, True, "", f"turn{i}")
s.add_usage("gemini", "gemini-test", "generate", 50, 10, 0, 0.0005, False, "timeout", "turn9")
s.close()
print(SCHEMA_VERSION)
'''

fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(label)


def dump(path, tables):
    out = {}
    with sqlite3.connect(path) as c:
        for t in tables:
            out[t] = c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
    return out


def columns(path, table):
    with sqlite3.connect(path) as c:
        return [r[1] for r in c.execute(f"PRAGMA table_info({table})")]


old_files, work = sys.argv[1:3]
os.makedirs(work, exist_ok=True)
db = os.path.join(work, "agent_data.db")
for suffix in ("", "-journal", "-wal", "-shm"):
    try:
        os.remove(db + suffix)
    except FileNotFoundError:
        pass

made = subprocess.run([sys.executable, "-c", OLD_WRITER, old_files, db], capture_output=True, text=True, encoding="utf-8")
check("前の版の AgentStore で作れた", made.returncode == 0, made.stderr[-500:])
print(f"前の版の表の版: {made.stdout.strip()}")
KEPT = ("usage_records", "persona")
before = dump(db, KEPT)
old_schema = made.stdout.strip()
if old_schema == "1":
    check("前の版では記憶の表が無い（版1の形で作れている）", "account" not in columns(db, "memories") if columns(db, "memories") else True)
else:
    # v1.10.0 から前の版の表の版はもう 4。表の形が変わらない版の上げでも、記録がそのままかは下で同じように見る
    with sqlite3.connect(db) as _c:
        _v = _c.execute("SELECT * FROM schema_version").fetchall() if "schema_version" in [
            r[0] for r in _c.execute("SELECT name FROM sqlite_master WHERE type='table'")] else None
    check(f"前の版の形（表の版 {old_schema}）で作れている", _v is None or _v == [(int(old_schema),)], _v)

sys.path.insert(0, NEW_DIR)
from agent.memory.store import AgentStore, SCHEMA_VERSION, OPEN_OK  # noqa: E402

for round_no in (1, 2):
    s = AgentStore(db)
    status = s.open()
    check(f"{round_no}回目: 今のコードで開ける（壊れたとみなして作り直さない）", status == OPEN_OK, status)
    check(f"{round_no}回目: 使った回数・費用・人格がそのまま", dump(db, KEPT) == before)
    persona = s.load_persona("default")
    check(f"{round_no}回目: 前の版の人格を読める", persona is not None and persona.summary == "前の版で保存した要約"
          and persona.example_lines == ["前の版の口調"], persona)
    calls, cost = s.usage_since(0)
    check(f"{round_no}回目: 1日・1か月の上限の数え方に、前の版の分も入る", calls == 4 and abs(cost - 0.0035) < 1e-9, (calls, cost))
    check(f"{round_no}回目: 記憶の表と、アカウント・予定の列が足されている",
          {"account", "due_at", "done"} <= set(columns(db, "memories")) and "account" in columns(db, "persons"))
    with sqlite3.connect(db) as c:
        version = c.execute("SELECT version FROM schema_version").fetchall()
    check(f"{round_no}回目: 表の版は {SCHEMA_VERSION}（1行だけ）", version == [(SCHEMA_VERSION,)], version)
    s.add_memory("person", "たろう", "前の版から更新したあとの記憶", "high", 0.5, 3600, account="acc")
    check(f"{round_no}回目: 新しい記憶を書ける", any(m for m in s.memories(account="acc")))
    s.close()

print()
if fails:
    print(f"FAILED {len(fails)}件: {fails}")
    sys.exit(1)
print("すべて通りました")
