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

SCHEMA_VERSION = 1
FILE_NAME = "agent_data.db"
BACKUP_PREFIX = "agent_data_"
BACKUP_KEEP = 7

DAY = 24 * 3600
RETENTION = {"events": 7 * DAY, "turns": 30 * DAY, "decisions": 30 * DAY,
             "utterances": 30 * DAY, "usage_records": 365 * DAY}
_TIME_COLUMN = {"events": "observed_at", "turns": "started_at", "decisions": "created_at",
                "utterances": "started_at", "usage_records": "at"}

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
        """保存期間を過ぎたものを消す"""
        with self._lock:
            now = self._clock()
            for table, keep in RETENTION.items():
                self._conn.execute(f"DELETE FROM {table} WHERE {_TIME_COLUMN[table]} < ?", (now - keep,))
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
        if table not in RETENTION and table != "persona":
            raise ValueError(table)
        with self._lock:
            return self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
