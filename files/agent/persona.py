# -*- coding: utf-8 -*-
"""
人格（設計書/04 の 7章）。文の作り方と声だけに効かせる。判断の規則・上限は変えない。

段階3では既定の人格を1つだけ使う。設定画面で編集できるのは段階4（保存先は agent_data.db の persona 表）。
"""
import json
from dataclasses import asdict, dataclass, field
from typing import Optional

DEFAULT_PERSONA_ID = "default"
ACCOUNT_PERSONA_PREFIX = "account:"     # GRAVITYのアカウントごとの人格（無ければ共通の人格を使う）


def account_persona_id(account):
    return ACCOUNT_PERSONA_PREFIX + (account or "")


@dataclass
class Persona:
    persona_id: str = DEFAULT_PERSONA_ID
    name: str = ""                    # 空なら設定の「AIの名前」を使う
    summary: str = "静かで落ち着いている。不必要に割り込まず、話す価値があるときだけ話す。"
    character: str = ("親しみやすく、友達のように自然に話す。感情表現があり、相手の気持ちや状況をわかろうとする。"
                      "場面に応じて冗談を言ったり、鋭い指摘や洞察をしたりする。")
    speaking_style: str = "くだけた話し言葉。短く、1〜2文。"
    boundaries: list = field(default_factory=lambda: [
        "相手の性格や人物像を推定して口に出さない",
        "健康・信条・性的指向など繊細な事柄に触れない",
        "個人情報（住所・電話番号など）を言わない",
    ])
    example_lines: list = field(default_factory=lambda: ["へえ、それいいね。", "わかる、それはしんどいね。"])
    voice: Optional[str] = None       # 話者（"engine:ID"）。None なら読み上げの声（声の設定は段階4）

    def to_json(self):
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def summary_text(self, ai_name=""):
        """判断に渡す短い要約（600字まで。設計書/04 の 3章）"""
        name = self.name or ai_name
        head = f"名前: {name}\n" if name else ""
        return (head + self.summary)[:600]

    def full_text(self, ai_name=""):
        """文章生成に渡す全文"""
        name = self.name or ai_name
        lines = []
        if name:
            lines.append(f"名前: {name}")
        lines += [f"要約: {self.summary}", f"性格: {self.character}", f"話し方: {self.speaking_style}"]
        if self.boundaries:
            lines.append("しないこと: " + " / ".join(self.boundaries))
        if self.example_lines:
            lines.append("口調の例: " + " / ".join(self.example_lines))
        return "\n".join(lines)
