"""База знаний: версионный поиск по пунктам Инструкции и формирование ответа.

Поиск — BM25 по стемам (без внешних зависимостей, работает полностью локально).
Ответ — либо дословная выдержка из пунктов (по умолчанию, галлюцинации невозможны),
либо локальная LLM (Ollama), которой разрешено отвечать только по найденным пунктам.
Интерфейс KnowledgeBase.search() можно заменить на векторный поиск (Qdrant, pgvector) без правок диалога.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("docgen.kb")

STOP = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня
еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя
ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда
кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда
можно при наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем
хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между""".split())


# Слова-паразиты запросов, не несущие смысла для поиска
STOP |= {"делать", "сделать", "нужно", "нужен", "нужна", "надо", "должен", "следует", "подскажите", "скажите", "пожалуйста",
         "сколько", "дается", "какие", "какой", "какая", "каково", "каков", "какова", "должны", "должна", "нужны"}
# Грубые синонимы на уровне стемов (в продакшене заменяются эмбеддингами)
SYN = {"верну": "возвр", "вернут": "возвр", "вернет": "возвр", "согла": "визир", "виза": "визир"}


def stems(text: str) -> list[str]:
    """Грубый стемминг для русского: нижний регистр, ё→е, усечение до 5 символов."""
    words = re.findall(r"[a-zа-я0-9]+", text.lower().replace("ё", "е"))
    out = [w[:5] for w in words if len(w) > 2 and w not in STOP]
    return [SYN.get(w, w) for w in out]


def mask_pii(text: str) -> str:
    """Маскирует контакты и номера документов перед отправкой в языковую модель."""
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", text)
    text = re.sub(r"\+?\d[\d\s()\-]{8,}\d", "[номер]", text)
    return text


@dataclass
class Chunk:
    id: str
    doc: str
    version: str
    point: str
    title: str
    text: str
    plain: str = ""
    template: str | None = None
    access: list = field(default_factory=list)  # пусто = доступно всем ролям
    status: str = "active"
    filename: str | None = None
    section: str | None = None
    paragraph: int | None = None


@dataclass
class Hit:
    chunk: Chunk
    score: float
    relevance: int  # 0..100: доля слов запроса (с весом по редкости), найденных в пункте

    def public(self) -> dict:
        c = self.chunk
        snippet = c.text if len(c.text) <= 240 else c.text[:237].rstrip() + "…"
        return {"id": c.id, "doc": c.doc, "version": c.version, "point": c.point,
                "title": c.title, "relevance": self.relevance, "snippet": snippet,
                "source": c.filename or c.doc, "section": c.section or c.point,
                "paragraph": c.paragraph}


class KnowledgeBase:
    def __init__(self, path: Path, min_relevance: int | None = None):
        self.path = Path(path)
        self.min_relevance = min_relevance if min_relevance is not None else int(os.getenv("MIN_RELEVANCE", "45"))
        self.meta: dict = {}
        self.docs: list[dict] = []
        self.chunks: list[Chunk] = []
        self.load()

    def load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.meta = data.get("meta", {})
        self.docs = data.get("docs", [])
        self.chunks = [Chunk(**c) for c in data["chunks"]]
        active = [c for c in self.chunks if c.status == "active"]
        self._tf = {c.id: Counter(stems(c.text) + stems(c.title) * 2) for c in active}
        self._len = {k: sum(v.values()) for k, v in self._tf.items()}
        self._avg = (sum(self._len.values()) / len(self._len)) if self._len else 1
        self._df = Counter(t for tf in self._tf.values() for t in tf)
        self._active = {c.id: c for c in active}
        log.info("База знаний загружена: %d активных пунктов", len(active))

    def _idf(self, term: str) -> float:
        n, df = len(self._active) or 1, self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def is_too_vague(self, query: str) -> bool:
        return len(set(stems(query))) < 2

    def search(self, query: str, role: str, top_k: int = 3) -> list[Hit]:
        q = list(dict.fromkeys(stems(query)))
        if not q:
            return []
        total_idf = sum(self._idf(t) for t in q)
        hits = []
        for cid, c in self._active.items():
            if c.access and role not in c.access:  # ролевая модель: чужие пункты не участвуют в поиске
                continue
            tf, dl = self._tf[cid], self._len[cid]
            score = matched = 0.0
            for t in q:
                if t in tf:
                    idf = self._idf(t)
                    score += idf * tf[t] * 2.5 / (tf[t] + 1.5 * (0.25 + 0.75 * dl / self._avg))
                    matched += idf
            if score > 0:
                hits.append(Hit(c, score, round(100 * matched / total_idf)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def documents(self) -> list[dict]:
        return self.docs


class ExtractiveAnswerer:
    """Ответ только из текста найденных пунктов: ничего не придумывает."""

    def answer(self, question: str, hits: list[Hit]) -> str:
        lines = ["Вот что сказано в инструкции:"]
        for h in hits[:2]:
            c = h.chunk
            lines.append(f"• п. {c.point} — {c.text}")
            if c.plain:
                lines.append(f"   Простыми словами: {c.plain}")
        return "\n".join(lines)


class OllamaAnswerer:
    """Локальная LLM через Ollama. Данные не покидают контур; запрос маскируется от персональных данных."""

    SYSTEM = (
        "Ты помощник сотрудника по внутренним инструкциям. Отвечай ТОЛЬКО на основе приведённых пунктов. "
        "Объясняй простым языком, коротко. Всегда указывай номер пункта в формате «п. 3.4»; "
        "если для источника доступны имя файла, раздел и номер абзаца, укажи их в ссылке на источник. "
        "Если в пунктах нет ответа, напиши ровно: «Информации в базе знаний недостаточно». Ничего не добавляй от себя."
    )

    def __init__(self, url: str, model: str, fallback: ExtractiveAnswerer, timeout: int = 60):
        self.url, self.model, self.fallback, self.timeout = url.rstrip("/"), model, fallback, timeout

    def answer(self, question: str, hits: list[Hit]) -> str:
        context = "\n".join(
            f"Источник: файл {h.chunk.filename or h.chunk.doc}; раздел {h.chunk.section or h.chunk.point}; "
            f"абзац {h.chunk.paragraph if h.chunk.paragraph is not None else 'не указан'}; "
            f"п. {h.chunk.point} ({h.chunk.title}): {h.chunk.text}"
            for h in hits
        )
        body = json.dumps({
            "model": self.model, "stream": False, "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": self.SYSTEM},
                {"role": "user", "content": f"Пункты инструкции:\n{context}\n\nВопрос: {mask_pii(question)}"},
            ],
        }).encode()
        try:
            req = urllib.request.Request(f"{self.url}/api/chat", body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                text = json.loads(r.read())["message"]["content"].strip()
            if text:
                return text
        except Exception:
            log.exception("LLM недоступна, отвечаю дословной выдержкой")
        return self.fallback.answer(question, hits)


def make_answerer() -> ExtractiveAnswerer | OllamaAnswerer:
    base = ExtractiveAnswerer()
    url, model = os.getenv("LLM_URL"), os.getenv("LLM_MODEL")
    return OllamaAnswerer(url, model, base) if url and model else base
