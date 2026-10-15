"""前の版の DatabaseManager で作った app_data.db を、今のコードで開いても利用者のデータが変わらないかを確かめる。リリースの前に使う。

usage: python tests/release_db_upgrade.py <old_src_dir> <work_dir>
  old_src_dir: 前の版の auto_reply_app.py を置いたフォルダ（git show v1.8.0:files/auto_reply_app.py > DIR/auto_reply_app.py）

- 自動アップデートは app_data.db を上書きしないので、更新した人は前の版の設定のまま新しい版を起動する。
  新しい版が列を足す（ALTER TABLE）だけで、元の列の中身・セットとペアの有効/無効・設定値を変えないことを見る。
- 2回開いても変わらない（移し替えが2回走らない）ことも見る。
- 音は鳴らず、画面も出ない。配布物（exe）で同じことを見るのは release_verify_dist.py の --old-src。
"""
import importlib.util
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
old_dir, work = sys.argv[1:3]
NEW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "files")
fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(label)


def load(modname, d):
    sys.path.insert(0, d)
    try:
        spec = importlib.util.spec_from_file_location(modname, os.path.join(d, "auto_reply_app.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path.remove(d)


def dump(path):
    out = {}
    with sqlite3.connect(path) as c:
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
            rows = c.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()
            out[t] = (cols, rows)
    return out


os.makedirs(work, exist_ok=True)
db = os.path.join(work, "app_data.db")
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(db + suffix)
    except FileNotFoundError:
        pass

old = load("app_old", old_dir)
print(f"前の版: APP_VERSION={old.APP_VERSION}")
odb = old.DatabaseManager(db_name=db)
ok, msg, sid = odb.create_keyword_set("挨拶セット")
assert ok, msg
odb.upsert_keyword(sid, "こんにちは", "こんにちは！ようこそ")
odb.upsert_keyword(sid, "おやすみ", "おやすみなさい\n2行目")
odb.set_keyword_enabled(sid, "おやすみ", False)
ok, msg, sid2 = odb.create_keyword_set("無効のセット")
assert ok, msg
odb.upsert_keyword(sid2, "テスト", "返信")
odb.set_keyword_set_enabled(sid2, False)
odb.save_setting("keyword_auto_reply_enabled", "1")
odb.save_setting("manual_send_box_count", "5")
odb.save_setting("manual_send_char_limit", "250")
odb.save_setting("timer_hours", "1")
odb.create_timer_preset("休憩", 900)
odb.create_speech_phrase("よろしくお願いします")
odb.save_log(f"v{old.APP_VERSION} で書いたログ")
before = dump(db)
old_active = odb.get_active_keywords()
print(f"前の版の表: {sorted(before)}")

new = load("app_new", NEW_DIR)
print(f"今のコード: APP_VERSION={new.APP_VERSION}")
ndb = new.DatabaseManager(db_name=db)
after = dump(db)

for t, (cols, rows) in before.items():
    acols, arows = after.get(t, ([], []))
    missing_cols = [c for c in cols if c not in acols]
    check(f"{t}: 元の列が残る", not missing_cols, str(missing_cols))
    if missing_cols:
        continue
    idx = [acols.index(c) for c in cols]
    proj = sorted(tuple(r[i] for i in idx) for r in arows)
    if t == "logs":
        check("logs: 元の行は残る", all(r in proj for r in rows))
    else:
        check(f"{t}: 元の列の中身は全部そのまま", proj == sorted(rows), f"{proj} != {sorted(rows)}")
    added = [c for c in acols if c not in cols]
    if added:
        print(f"  info {t}: 足された列 {added}")
    if t == "keywords" and "target" in added:
        tcol = acols.index("target")
        check("keywords: 既存のペアは「すべての文字（今まで通り）」(target='any')", all(r[tcol] == "any" for r in arows), str(arows))
check("有効なキーワードが同じ", ndb.get_active_keywords() == old_active, f"{ndb.get_active_keywords()} vs {old_active}")
if hasattr(ndb, "get_active_keyword_targets"):
    check("対象の一覧も読める", set(ndb.get_active_keyword_targets()) == set(old_active), str(ndb.get_active_keyword_targets()))
sets = {s["name"]: s for s in ndb.get_keyword_sets()}
check("セットの有効・無効が保たれる", sets["挨拶セット"]["enabled"] and not sets["無効のセット"]["enabled"], str(sets))
pairs = {p["trigger"]: p for p in ndb.get_keywords_in_set(sets["挨拶セット"]["id"])}
check("ペアの無効が保たれる", pairs["おやすみ"]["enabled"] is False and pairs["こんにちは"]["enabled"] is True, str(pairs))
check("改行入りの返信ワードがそのまま", pairs["おやすみ"]["reply"] == "おやすみなさい\n2行目")
check("設定値がそのまま", ndb.get_setting("manual_send_box_count") == "5" and ndb.get_setting("timer_hours") == "1")
new.DatabaseManager(db_name=db)
check("2回目に開いても変わらない", dump(db) == after)
print("\nすべて成功" if not fails else f"\n失敗 {len(fails)} 件: {fails}")
sys.exit(1 if fails else 0)
