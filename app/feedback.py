"""Локальное хранилище обратной связи для безопасного улучшения ответов."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zа-яё0-9]{3,}", text.lower().replace("ё", "е"))
    return {word[:7] for word in words}


def _mask_pii(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", text)
    return re.sub(r"\+?\d[\d\s()\-]{8,}\d", "[номер]", text)


class FeedbackStore:
    """JSONL-хранилище.

    Отрицательная оценка без исправления сохраняется для аналитики.
    В ответы попадают только записи с явным исправлением пользователя.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def add(
        self,
        *,
        session_id: str,
        role: str,
        question: str,
        answer: str,
        rating: str,
        correction: str = "",
        sources: list[dict] | None = None,
    ) -> dict:
        if rating not in {"positive", "negative"}:
            raise ValueError("rating must be positive or negative")
        correction = correction.strip()[:2000]
        record = {
            "id": uuid.uuid4().hex,
            "created_at": int(time.time()),
            "session_id": session_id,
            "role": role,
            "question": _mask_pii(question.strip()[:4000]),
            "answer": _mask_pii(answer.strip()[:6000]),
            "rating": rating,
            "correction": _mask_pii(correction),
            "sources": sources or [],
            "status": "active" if correction else "review",
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def find_corrections(self, question: str, limit: int = 3) -> list[dict]:
        query = _tokens(question)
        if not query or not self.path.exists():
            return []
        matches: list[tuple[float, dict]] = []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("status") != "active" or not record.get("correction"):
                continue
            candidate = _tokens(record.get("question", ""))
            if not candidate:
                continue
            score = len(query & candidate) / max(len(query | candidate), 1)
            if score >= 0.35:
                matches.append((score, record))
        matches.sort(key=lambda item: (item[0], item[1].get("created_at", 0)), reverse=True)
        return [record for _, record in matches[:limit]]

    def list_recent(self, limit: int = 100) -> list[dict]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        result = []
        for line in lines[-limit:]:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(result))
