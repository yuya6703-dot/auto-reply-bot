# -*- coding: utf-8 -*-
"""
AI が決めた話し方を、読み上げツール（VOICEVOX / AivisSpeech）に渡す形にする
（2026-10-16 本人「AIAPIで声を出すのではなくて、連携してる読み上げツールをAIAPIが話し方を調整した上で読み上げツールで話す仕組みにしたい」）。

- 声を作るのは読み上げツール（今までも同じ）。AI は文ごとに「声の様子（スタイル）・速さ・抑揚・高さ・間・大きさ」を選ぶだけ
- スタイルは、今の声と同じキャラのスタイル（ノーマル・喜び・怒り など）から選ぶ。AI が選ばなければ、感情から近いものを探す
- 速さ・抑揚・高さ・間・大きさは、エンジンの audio_query の speedScale・intonationScale・pitchScale・pauseLengthScale・
  volumeScale に入れる（同日 本人「声の抑揚とかもAIが調整できるようにしてね」）。範囲を決めて、それより外には出さない。
  エンジンが知らない項目（古い版に pauseLengthScale が無い など）は入れない。AivisSpeech の intonationScale は「感情表現の強さ」として効く
⚠️ ここは tkinter・auto_reply_app を import しない（設計書/04 の D3）
"""

SPEED_RANGE = (0.85, 1.25)
INTONATION_RANGE = (0.7, 1.4)
PITCH_RANGE = (-0.08, 0.08)      # 声の高さ（0 がふつう。大きく変えると別人に聞こえる）
PAUSE_RANGE = (0.7, 1.4)         # 句読点などの間の長さ（1.0 がふつう）
VOLUME_RANGE = (0.85, 1.15)      # 声の大きさ（1.0 がふつう。読み上げの音量にかける）
TEMPO_RANGE = (0.8, 1.2)         # 話し方の緩急（AivisSpeech の tempoDynamicsScale。VOICEVOX には無いので入れない）
ADJUST_KEYS = {"speed": ("speedScale", SPEED_RANGE, 1.0), "intonation": ("intonationScale", INTONATION_RANGE, 1.0),
               "pitch": ("pitchScale", PITCH_RANGE, 0.0), "pause": ("pauseLengthScale", PAUSE_RANGE, 1.0),
               "volume": ("volumeScale", VOLUME_RANGE, 1.0), "tempo": ("tempoDynamicsScale", TEMPO_RANGE, 1.0)}
# 感情 → 近いスタイルの名前（キャラによってスタイルの名前が違うので、候補を順に探す）
EMOTION_STYLE_HINTS = {
    "joy": ("喜び", "うれしい", "嬉しい", "楽しい", "たのしい", "あまあま", "ハイテンション", "元気"),
    "sad": ("悲しみ", "かなしい", "悲しい", "泣き", "なみだめ", "しょんぼり"),
    "angry": ("怒り", "おこ", "ツンツン", "怒"),
    "surprise": ("驚き", "びっくり"),
    "calm": ("ノーマル", "おちつき", "落ち着き", "ふつう", "通常"),
    "neutral": ("ノーマル", "ふつう", "通常"),
}


def clamp(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return round(min(high, max(low, value)), 2)


def choose_style(style_names, style=None, emotion=None):
    """使えるスタイルの名前から、AI が選んだもの（無ければ感情に近いもの）を返す。合うものが無ければ None"""
    names = list(style_names or [])
    if style and style in names:
        return style
    if style:
        for name in names:                 # 「喜び」と「喜び（強）」のような違いは近い方を使う
            if style in name or name in style:
                return name
    for hint in EMOTION_STYLE_HINTS.get(emotion or "", ()):
        for name in names:
            if hint in name:
                return name
    return None


def speech_adjust(**values):
    """読み上げツールの audio_query に入れる値（speed・intonation・pitch・pause・volume。変えないなら None）"""
    adjust = {}
    for name, value in values.items():
        if name not in ADJUST_KEYS or value is None:
            continue
        key, (low, high), normal = ADJUST_KEYS[name]
        value = clamp(value, low, high)
        if value is not None and value != normal:
            adjust[key] = value
    return adjust or None
