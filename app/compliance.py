"""Проверка черновиков документов по активным пунктам базы знаний."""
from __future__ import annotations

import re
from pathlib import Path

from .ingest import read_lines
from .knowledge import Hit, KnowledgeBase, stems

MAX_DRAFT_BYTES = 5 * 1024 * 1024
ALLOWED_SUFFIXES = {".docx", ".pdf", ".txt", ".md"}
POINT_LINE_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+(.+)$")


def _draft_sections(path: Path) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, str]] = []
    current_point: str | None = None
    current: list[str] = []
    for line in read_lines(path):
        text = " ".join(line.split())
        if not text:
            continue
        match = POINT_LINE_RE.match(text)
        if match:
            if current:
                sections.append((current_point, " ".join(current)))
            current_point = match.group(1)
            current = [match.group(2).strip()]
        elif current:
            current.append(text)
        else:
            sections.append((None, text))
    if current:
        sections.append((current_point, " ".join(current)))
    return sections


def _best_hit(kb: KnowledgeBase, text: str, role: str) -> Hit | None:
    hits = kb.search(text, role, top_k=1)
    return hits[0] if hits else None


def review_draft(path: Path, kb: KnowledgeBase, role: str = "employee") -> dict:
    sections = _draft_sections(path)
    checked: list[dict] = []
    recommendations: list[str] = []
    matched = 0

    for point, text in sections:
        hit = _best_hit(kb, text, role)
        if hit and hit.relevance >= kb.min_relevance:
            matched += 1
            item = {
                "draft_point": point,
                "text": text,
                "status": "matched",
                "relevance": hit.relevance,
                "source": hit.public(),
            }
            if point and point != hit.chunk.point:
                recommendations.append(
                    f"Проверьте пункт {point}: он сопоставлен с п. {hit.chunk.point} "
                    f"(релевантность {hit.relevance}%)."
                )
        else:
            item = {
                "draft_point": point,
                "text": text,
                "status": "unmatched",
                "relevance": hit.relevance if hit else 0,
                "source": hit.public() if hit else None,
            }
            recommendations.append(
                f"Для фрагмента{f' п. {point}' if point else ''} "
                "не найдено достаточное основание в активной базе знаний. "
                "Проверьте формулировку и добавьте ссылку на пункт Инструкции."
            )
        checked.append(item)

    return {
        "status": "reviewed",
        "document": path.name,
        "role": role,
        "summary": {
            "sections": len(sections),
            "matched": matched,
            "unmatched": len(sections) - matched,
            "compliance_percent": round(100 * matched / len(sections)) if sections else 0,
        },
        "checks": checked,
        "recommendations": recommendations,
    }
