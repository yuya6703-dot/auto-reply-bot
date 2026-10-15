# -*- coding: utf-8 -*-
"""
エージェントのログ（設計書/08 の 3章）。画面に出す前に、APIキーらしい文字列を必ず伏せる。

⚠️ 他の人の名前は伏せない（AIタブで判断の様子を見るため）。画面のログは保存されない。
   既存の logs 表（app_data.db）へ入れるのは、状態の変化と失敗の知らせだけにする（呼び出し側の on_notice）。
"""
from .api_keys import redact_secrets


class AuditLog:
    def __init__(self, sink, notice_sink=None):
        self._sink = sink                         # AIタブの判断のログ
        self._notice = notice_sink or sink        # 本人に知らせたいこと（メインのログにも出す）

    def write(self, line):
        try:
            self._sink(redact_secrets(line))
        except Exception:
            pass      # ログの失敗でエージェントを止めない

    def notice(self, line):
        self.write(line)
        if self._notice is not self._sink:
            try:
                self._notice(redact_secrets(line))
            except Exception:
                pass
