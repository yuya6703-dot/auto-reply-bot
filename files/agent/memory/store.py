# -*- coding: utf-8 -*-
"""
agent_data.db（設計書/07）。エージェントの記録（出来事・まとまり・判断・発言・利用量・人格）。

⚠️ 他の人の名前・発言がそのまま入る（判断に要るため）。だから
   - 保存期間を短くする（出来事7日、判断・発言30日。開くときと1日1回消す）
   - app_data.db とは別のファイルにする（設定と混ぜない。消すのも別にできる）
   - リポジトリに入れない（.gitignore）。自動更新でも上書きしない（robocopy の /XF）
壊れていたら退避して、backup/ の最新から戻す。だめなら空で作り直す（エージェントは記録なしで動く。T39）。
時刻は UTC の UNIX 秒で保存する。
"""
import json
import os
import shutil
import sqlite3
import threading
import time

from ..events import AgentEvent
from ..persona import Persona

SCHEMA_VERSION = 2     # 2: 記憶（persons・memories・relationships）を足した（2026-10-16）
FILE_NAME = "agent_data.db"
BACKUP_PREFIX = "agent_data_"
BACKUP_KEEP = 7

DAY = 24 * 3600
RETENTION = {"events": 7 * DAY, "turns": 30 * DAY, "decisions": 30 * DAY,
             "utterances": 30 * DAY, "usage_records": 365 * DAY}
_TIME_COLUMN = {"events": "observed_at", "turns": "started_at", "decisions": "created_at",
                "utterances": "started_at", "usage_records": "at"}

PERSON_KEEP = 180 * DAY     # 人は、最後に見てから180日で忘れる（その人の記憶と関係の値も）

OPEN_OK = "ok"
OPEN_RESTORED = "restored"       # 壊れていたのでバックアップから戻した
OPEN_RECREATED = "recreated"     # 壊れていて、戻せるバックアップも無かったので空で作った

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, kind TEXT, source TEXT, key TEXT, speaker_raw TEXT, text TEXT,
    observed_at REAL, meta TEXT, is_self INTEGER, turn_id TEXT);
CREATE INDEX IF NOT EXISTS idx_events_observed ON events(observed_at);
CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY, started_at REAL, event_ids TEXT, closed_at REAL, outcome TEXT);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, turn_id TEXT, action TEXT, reason TEXT, urgency REAL,
    decided_by TEXT, rule_id TEXT, model TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS utterances (
    id INTEGER PRIMARY KEY AUTOINCREMENT, turn_id TEXT, text TEXT, emotion TEXT, voice TEXT,
    status TEXT, started_at REAL, ended_at REAL);
CREATE TABLE IF NOT EXISTS usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, provider TEXT, model TEXT, purpose TEXT,
    input_tokens INTEGER, output_tokens INTEGER, cached_tokens INTEGER, estimated_cost REAL,
    ok INTEGER, error_kind TEXT, turn_id TEXT);
CREATE INDEX IF NOT EXISTS idx_usage_at ON usage_records(at);
CREATE TABLE IF NOT EXISTS persona (persona_id TEXT PRIMARY KEY, json TEXT);
CREATE TABLE IF NOT EXISTS persons (
    person_key TEXT PRIMARY KEY, display_name TEXT, first_seen REAL, last_seen REAL);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, person_key TEXT, content TEXT, confidence TEXT,
    importance REAL, created_at REAL, updated_at REAL, expires_at REAL, pinned INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS relationships (
    person_key TEXT PRIMARY KEY, familiarity REAL, warmth REAL, updated_at REAL, history TEXT);
"""


class AgentStore:
    def __init__(self, path, backup_dir=None, clock=time.time):
        self.path = path
        self.backup_dir = backup_dir or os.path.join(os.path.dirname(os.path.abspath(path)), "backup")
        self._clock = clock
        self._lock = threading.RLock()
        self._conn = None
        self.open_status = None

    # --- 開く・閉じる ---
    def open(self):
        """開く。壊れていたら退避してバックアップから戻す。戻り値は OPEN_*"""
        with self._lock:
            status = OPEN_OK
            try:
                self._conn = self._connect_checked(self.path)
            except sqlite3.DatabaseError:
                self._move_aside()
                restored = self._restore_latest_backup()
                status = OPEN_RESTORED if restored else OPEN_RECREATED
                self._conn = self._connect_checked(self.path)
            self._conn.executescript(_SCHEMA)
            if self._conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
                self._conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            else:
                # 表は CREATE IF NOT EXISTS で足りるので、番号だけ上げる
                self._conn.execute("UPDATE schema_version SET version = ? WHERE version < ?",
                                   (SCHEMA_VERSION, SCHEMA_VERSION))
            self._conn.commit()
            self.purge()
            self.open_status = status
            return status

    @staticmethod
    def _connect_checked(path):
        conn = sqlite3.connect(path, check_same_thread=False)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise sqlite3.DatabaseError("integrity_check に失敗")
        except sqlite3.DatabaseError:
            conn.close()
            raise
        return conn

    def _move_aside(self):
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(self._clock()))
        for suffix in ("", "-journal", "-wal", "-shm"):
            src = self.path + suffix
            if os.path.exists(src):
                try:
                    os.replace(src, f"{self.path}.broken_{stamp}{suffix}")
                except OSError:
                    try:
                        os.remove(src)
                    except OSError:
                        pass

    def _backups(self):
        if not os.path.isdir(self.backup_dir):
            return []
        names = sorted(n for n in os.listdir(self.backup_dir)
                       if n.startswith(BACKUP_PREFIX) and n.endswith(".db"))
        return [os.path.join(self.backup_dir, n) for n in names]

    def _restore_latest_backup(self):
        for backup in reversed(self._backups()):
            try:
                self._connect_checked(backup).close()
            except sqlite3.DatabaseError:
                continue
            shutil.copyfile(backup, self.path)
            return True
        return False

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def backup_daily(self):
        """1日1回、backup/agent_data_YYYYMMDD.db に写す（最大7世代）。写したら True"""
        with self._lock:
            if self._conn is None:
                return False
            day = time.strftime("%Y%m%d", time.localtime(self._clock()))
            dest = os.path.join(self.backup_dir, f"{BACKUP_PREFIX}{day}.db")
            if os.path.exists(dest):
                return False
            os.makedirs(self.backup_dir, exist_ok=True)
            target = sqlite3.connect(dest)
            try:
                self._conn.backup(target)
            finally:
                target.close()
            for old in self._backups()[:-BACKUP_KEEP]:
                try:
                    os.remove(old)
                except OSError:
                    pass
            return True

    def purge(self):
        """保存期間を過ぎたものを消す（記憶は期限、人は最後に見てから180日。消した人の記憶と関係も消す）"""
        with self._lock:
            now = self._clock()
            for table, keep in RETENTION.items():
                self._conn.execute(f"DELETE FROM {table} WHERE {_TIME_COLUMN[table]} < ?", (now - keep,))
            self._conn.execute("DELETE FROM memories WHERE pinned = 0 AND expires_at < ?", (now,))
            gone = [r[0] for r in self._conn.execute("SELECT person_key FROM persons WHERE last_seen < ?",
                                                    (now - PERSON_KEEP,))]
            for key in gone:
                self._forget_person(key)
            self._conn.commit()

    # --- 記憶（2026-10-16。⚠️ 他の人のことが入る。本人がONにしたときだけ書く・画面から消せる・期限で消える） ---
    def _forget_person(self, person_key):
        self._conn.execute("DELETE FROM memories WHERE person_key = ?", (person_key,))
        self._conn.execute("DELETE FROM relationships WHERE person_key = ?", (person_key,))
        self._conn.execute("DELETE FROM persons WHERE person_key = ?", (person_key,))

    def upsert_person(self, person_key, display_name):
        with self._lock:
            now = self._clock()
            row = self._conn.execute("SELECT display_name FROM persons WHERE person_key = ?", (person_key,)).fetchone()
            if row is None:
                self._conn.execute("INSERT INTO persons (person_key, display_name, first_seen, last_seen) VALUES (?, ?, ?, ?)",
                                   (person_key, display_name, now, now))
            else:
                # 切れていない（長い）名前を残す
                name = display_name if len(display_name or "") > len(row[0] or "") else row[0]
                self._conn.execute("UPDATE persons SET display_name = ?, last_seen = ? WHERE person_key = ?",
                                   (name, now, person_key))
            self._conn.commit()

    def persons(self):
        with self._lock:
            return self._conn.execute("SELECT person_key, display_name, first_seen, last_seen FROM persons"
                                      " ORDER BY last_seen DESC").fetchall()

    def add_memory(self, scope, person_key, content, confidence, importance, ttl_seconds):
        with self._lock:
            now = self._clock()
            same = self._conn.execute("SELECT id FROM memories WHERE scope = ? AND IFNULL(person_key, '') = ?"
                                      " AND content = ?", (scope, person_key or "", content)).fetchone()
            if same:      # 同じ内容は覚え直す（期限を延ばす）
                self._conn.execute("UPDATE memories SET updated_at = ?, expires_at = MAX(expires_at, ?) WHERE id = ?",
                                   (now, now + ttl_seconds, same[0]))
            else:
                self._conn.execute(
                    "INSERT INTO memories (scope, person_key, content, confidence, importance, created_at, updated_at,"
                    " expires_at, pinned) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (scope, person_key, content, confidence, importance, now, now, now + ttl_seconds))
            self._conn.commit()

    def memories(self, person_key=None, limit=200):
        """新しい順 [(id, scope, person_key, content, confidence, importance, updated_at, pinned)]"""
        with self._lock:
            if person_key is None:
                rows = self._conn.execute(
                    "SELECT id, scope, person_key, content, confidence, importance, updated_at, pinned FROM memories"
                    " ORDER BY updated_at DESC LIMIT ?", (limit,))
            else:
                rows = self._conn.execute(
                    "SELECT id, scope, person_key, content, confidence, importance, updated_at, pinned FROM memories"
                    " WHERE person_key = ? ORDER BY importance DESC, updated_at DESC LIMIT ?", (person_key, limit))
            return rows.fetchall()

    def delete_memory(self, memory_id):
        with self._lock:
            self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._conn.commit()

    def delete_all_memories(self):
        """記憶・人・関係の値を全部消す（出来事や判断の記録は残る）"""
        with self._lock:
            for table in ("memories", "relationships", "persons"):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()

    def relationship(self, person_key):
        with self._lock:
            row = self._conn.execute("SELECT familiarity, warmth, updated_at, history FROM relationships"
                                     " WHERE person_key = ?", (person_key,)).fetchone()
        if row is None:
            return None
        return {"familiarity": row[0], "warmth": row[1], "updated_at": row[2], "history": json.loads(row[3] or "[]")}

    def adjust_relationship(self, person_key, d_familiarity, d_warmth, reason):
        """関係の値を少しだけ動かす（なじみ 0〜100、温かさ -100〜100）。理由つきで直近20件を残す"""
        with self._lock:
            now = self._clock()
            current = self.relationship(person_key) or {"familiarity": 0.0, "warmth": 0.0, "history": []}
            familiarity = min(100.0, max(0.0, current["familiarity"] + d_familiarity))
            warmth = min(100.0, max(-100.0, current["warmth"] + d_warmth))
            history = (current["history"] + [{"at": now, "familiarity": d_familiarity, "warmth": d_warmth,
                                              "reason": reason[:40]}])[-20:]
            self._conn.execute(
                "INSERT OR REPLACE INTO relationships (person_key, familiarity, warmth, updated_at, history)"
                " VALUES (?, ?, ?, ?, ?)", (person_key, familiarity, warmth, now, json.dumps(history, ensure_ascii=False)))
            self._conn.commit()

    def relationships(self):
        with self._lock:
            return self._conn.execute(
                "SELECT r.person_key, IFNULL(p.display_name, r.person_key), r.familiarity, r.warmth, r.updated_at"
                " FROM relationships r LEFT JOIN persons p ON p.person_key = r.person_key"
                " ORDER BY r.updated_at DESC").fetchall()

    def reset_relationships(self):
        with self._lock:
            self._conn.execute("DELETE FROM relationships")
            self._conn.commit()

    # --- 書く ---
    def add_events(self, events, turn_id=None):
        with self._lock:
            self._conn.executemany(
                "INSERT OR IGNORE INTO events (event_id, kind, source, key, speaker_raw, text, observed_at,"
                " meta, is_self, turn_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(e.event_id, e.kind, e.source, e.key, e.speaker, e.text, e.observed_at,
                  json.dumps(dict(e.meta), ensure_ascii=False), int(e.is_self), turn_id) for e in events])
            self._conn.commit()

    def add_turn(self, turn_id, event_ids, started_at):
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO turns (turn_id, started_at, event_ids) VALUES (?, ?, ?)",
                               (turn_id, started_at, json.dumps(list(event_ids))))
            self._conn.commit()

    def close_turn(self, turn_id, outcome):
        with self._lock:
            self._conn.execute("UPDATE turns SET closed_at = ?, outcome = ? WHERE turn_id = ?",
                               (self._clock(), outcome, turn_id))
            self._conn.commit()

    def add_decision(self, decision):
        with self._lock:
            self._conn.execute(
                "INSERT INTO decisions (turn_id, action, reason, urgency, decided_by, rule_id, model, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (decision.turn_id, decision.action, decision.reason, decision.urgency, decision.decided_by,
                 decision.rule_id, decision.model, self._clock()))
            self._conn.commit()

    def add_utterance(self, turn_id, text, emotion, voice, status, started_at, ended_at):
        with self._lock:
            self._conn.execute(
                "INSERT INTO utterances (turn_id, text, emotion, voice, status, started_at, ended_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)", (turn_id, text, emotion, voice, status, started_at, ended_at))
            self._conn.commit()

    def add_usage(self, provider, model, purpose, input_tokens, output_tokens, cached_tokens,
                  estimated_cost, ok, error_kind, turn_id):
        with self._lock:
            self._conn.execute(
                "INSERT INTO usage_records (at, provider, model, purpose, input_tokens, output_tokens,"
                " cached_tokens, estimated_cost, ok, error_kind, turn_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self._clock(), provider, model, purpose, input_tokens, output_tokens, cached_tokens,
                 estimated_cost, int(ok), error_kind, turn_id))
            self._conn.commit()

    def save_persona(self, persona):
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO persona (persona_id, json) VALUES (?, ?)",
                               (persona.persona_id, persona.to_json()))
            self._conn.commit()

    # --- 読む ---
    def load_persona(self, persona_id):
        with self._lock:
            row = self._conn.execute("SELECT json FROM persona WHERE persona_id = ?", (persona_id,)).fetchone()
        return Persona.from_json(row[0]) if row else None

    def usage_since(self, since):
        """since 以降に AI を呼んだ回数と、費用の見積もりの合計"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(estimated_cost), 0) FROM usage_records WHERE at >= ?",
                (since,)).fetchone()
        return int(row[0]), float(row[1])

    def recent_events(self, since):
        """since 以降の出来事（再起動後に直近の窓へ戻す。反応はしないので backlog の印を付ける）"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_id, kind, source, key, speaker_raw, text, observed_at, meta, is_self FROM events"
                " WHERE observed_at >= ? ORDER BY observed_at", (since,)).fetchall()
        events = []
        for event_id, kind, source, key, speaker, text, at, meta, is_self in rows:
            try:
                meta = json.loads(meta) if meta else {}
            except ValueError:
                meta = {}
            meta["backlog"] = True
            events.append(AgentEvent(event_id, kind, source, key, speaker, text, at, meta, bool(is_self)))
        return events

    def recent_decisions(self, limit=20):
        with self._lock:
            return self._conn.execute(
                "SELECT turn_id, action, reason, decided_by, rule_id, created_at FROM decisions"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def count(self, table):
        if table not in RETENTION and table not in ("persona", "persons", "memories", "relationships"):
            raise ValueError(table)
        with self._lock:
            return self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
