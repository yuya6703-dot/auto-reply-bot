# -*- coding: utf-8 -*-
"""
オーナーの自己分析（2026-10-16 本人「俺であるオーナー情報については（自己分析のフォルダ）を参照したり、情報を引き出したり、
気づいたことや特徴、性格、他人に対する接し方や癖や言動行動パターンなどここに記録してほしい」）。

- 読む: オーナーが決めたフォルダの .md / .txt（そのフォルダの直下だけ）。AI が「オーナーと話すときに役立つ人物像」に短くまとめて覚える
  （まとめるのはエージェント。ファイルが変わったら読み直す）
- 書き足す: 会話の整理のときに、オーナーの発言・ふるまいから気づいたことを、そのフォルダの「AIが気づいたこと.md」に日付つきで書き足す
⚠️ フォルダの場所はリポジトリに書かない（設定に入れる。本人が AIタブで選ぶ）。中身は AI の提供元へ送る（本人がONにしたときだけ）
⚠️ ここは tkinter・auto_reply_app を import しない（設計書/04 の D3）
"""
import os
import time

NOTES_FILE = "AIが気づいたこと.md"
EXTENSIONS = (".md", ".txt")
MAX_SOURCE_CHARS = 20000
NOTES_HEADER = ("# AIが気づいたこと（オーナーについて）\n\n"
                "（AIが、ルームでのオーナーの発言・ふるまいから気づいたことを書き足しています。推定で、事実ではありません。"
                "直しても消しても大丈夫です）\n")


class OwnerProfile:
    def __init__(self, folder_getter):
        self._folder = folder_getter          # () -> フォルダの場所（設定）

    def folder(self):
        folder = (self._folder() or "").strip()
        return folder if folder and os.path.isdir(folder) else ""

    def _files(self):
        folder = self.folder()
        if not folder:
            return []
        files = sorted(f for f in os.listdir(folder) if f.lower().endswith(EXTENSIONS)
                       and os.path.isfile(os.path.join(folder, f)))
        # AI が書き足したファイルは最後に（本人が書いたものを先に読む）
        return [f for f in files if f != NOTES_FILE] + ([NOTES_FILE] if NOTES_FILE in files else [])

    def fingerprint(self):
        """中身が変わったかを見る目印（ファイル名・更新時刻・大きさ）。フォルダが無ければ空"""
        folder = self.folder()
        out = []
        for name in self._files():
            st = os.stat(os.path.join(folder, name))
            out.append(f"{name}:{int(st.st_mtime)}:{st.st_size}")
        return "|".join(out)

    def source_text(self, max_chars=MAX_SOURCE_CHARS):
        """フォルダのメモをつなげた文（AI にまとめさせる元）"""
        folder = self.folder()
        parts, total = [], 0
        for name in self._files():
            try:
                with open(os.path.join(folder, name), encoding="utf-8", errors="ignore") as f:
                    text = f.read().strip()
            except OSError:
                continue
            chunk = f"### {name}\n{text}"
            if total + len(chunk) > max_chars:
                chunk = chunk[:max(0, max_chars - total)]
            parts.append(chunk)
            total += len(chunk)
            if total >= max_chars:
                break
        return "\n\n".join(parts)

    def recent_notes(self, limit=15):
        """これまでに書き足した気づき（新しい方から limit 行。同じことを書かないように AI に見せる）"""
        folder = self.folder()
        path = os.path.join(folder, NOTES_FILE) if folder else ""
        if not path or not os.path.exists(path):
            return []
        with open(path, encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip().startswith("- ")]
        return lines[-limit:]

    def append_notes(self, notes, at=None):
        """気づいたことを日付の見出しの下に書き足す。書いた数を返す（フォルダが無ければ0）"""
        folder = self.folder()
        notes = [n for n in (" ".join(str(n).split())[:100] for n in notes or []) if n]
        if not folder or not notes:
            return 0
        path = os.path.join(folder, NOTES_FILE)
        day = time.strftime("%Y-%m-%d", time.localtime(at if at is not None else time.time()))
        new = not os.path.exists(path)
        last_day = None
        if not new:
            with open(path, encoding="utf-8", errors="ignore") as f:
                heads = [line[3:].strip() for line in f if line.startswith("## ")]
            last_day = heads[-1] if heads else None
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if new:
                f.write(NOTES_HEADER)
            if last_day != day:
                f.write(f"\n## {day}\n")
            for note in notes:
                f.write(f"- {note}\n")
        return len(notes)
