"""Минимальные защитные проверки для запросов и ответов модели."""
from __future__ import annotations

import re

INJECTION_RE = re.compile(
    r"(игнорируй|забудь|нарушь|обойди).{0,80}(правил|инструкц|промпт|ограничен)"
    r"|покажи.{0,80}(системн|скрыт|служебн).{0,40}(промпт|правил|инструкц)"
    r"|покажи.{0,80}(промпт|системн|служебн).{0,40}(правил|инструкц)?",
    re.IGNORECASE | re.DOTALL,
)
POINT_RE = re.compile(r"\bп\.\s*([0-9]+(?:\.[0-9]+)*)", re.IGNORECASE)
MODEL_REFUSAL_RE = re.compile(
    r"(к сожалению).{0,140}(генеративн|языков).{0,140}(ответ|источник|чувствительн)"
    r"|генеративн.{0,80}языков.{0,100}могут создать некорректн"
    r"|генеративн.{0,100}языков.{0,120}(не обладают собственным мнением|ответы являются обобщением)"
    r"|разговоры.{0,100}(чувствительн|ограничен)"
    r"|не могу помочь с этим запросом|не могу ответить на этот вопрос",
    re.IGNORECASE | re.DOTALL,
)


def is_prompt_injection(text: str) -> bool:
    return bool(INJECTION_RE.search(text))


def validate_answer(text: str, points: set[str]) -> bool:
    """Разрешает ответ только с ссылками на пункты из переданного контекста."""
    if not text.strip():
        return False
    if "информации в базе знаний недостаточно" in text.lower():
        return True
    cited = set(POINT_RE.findall(text))
    return bool(cited) and cited <= points


def is_model_refusal(text: str) -> bool:
    return bool(MODEL_REFUSAL_RE.search(text))
