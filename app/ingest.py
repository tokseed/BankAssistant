"""Загрузка (или обновление) Инструкции в базу знаний с версионностью.

  python -m app.ingest Инструкция_v2.docx --doc "Инструкция по документообороту" --version 2.0

Файл .docx/.txt/.md режется на пункты по нумерации («3.4. Текст…»). Старая версия того же документа
не удаляется, а получает статус archived: поиск идёт только по active, история сохраняется.
После загрузки вызовите POST /api/admin/kb/reload (или перезапустите сервис).
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

POINT_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+(\S.*)$")


def read_lines(path: Path) -> list[str]:
    if path.suffix.lower() == ".docx":
        from docx import Document
        return [p.text for p in Document(str(path)).paragraphs]
    return path.read_text(encoding="utf-8").splitlines()


def split_points(lines: list[str]) -> list[tuple[str, str]]:
    points: list[list[str]] = []
    for line in lines:
        if not line.strip():
            continue
        m = POINT_RE.match(line)
        if m and not re.fullmatch(r"\d{4}", m[1]):  # «2026 году» — не пункт
            points.append([m[1], m[2].strip()])
        elif points:
            points[-1][1] += " " + line.strip()
    return [(n, t) for n, t in points]


def title_of(text: str) -> str:
    first = re.split(r"(?<=[.:;])\s", text, maxsplit=1)[0]
    return first if len(first) <= 90 else first[:87].rstrip() + "…"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--doc", required=True, help="название документа")
    ap.add_argument("--version", required=True)
    ap.add_argument("--kb", default=str(Path(__file__).resolve().parent.parent / "kb" / "chunks.json"))
    a = ap.parse_args()

    kb_path = Path(a.kb)
    data = json.loads(kb_path.read_text(encoding="utf-8")) if kb_path.exists() else {"meta": {}, "docs": [], "chunks": []}

    for c in data["chunks"]:
        if c["doc"] == a.doc and c["status"] == "active":
            c["status"] = "archived"
    for d in data["docs"]:
        if d["doc"] == a.doc and d["status"] == "active":
            d["status"] = "archived"

    pts = split_points(read_lines(Path(a.file)))
    slug = re.sub(r"\W+", "", a.doc.lower())[:6] + "-v" + a.version
    for n, text in pts:
        data["chunks"].append({
            "id": f"{slug}-{n}", "doc": a.doc, "version": a.version, "point": n, "title": title_of(text),
            "text": text, "plain": "", "template": None, "access": [], "status": "active",
        })
    data["docs"].append({"doc": a.doc, "version": a.version, "status": "active", "date": date.today().isoformat()})
    kb_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Загружено пунктов: {len(pts)}; версия {a.version} активна, прежние версии «{a.doc}» в архиве.")


if __name__ == "__main__":
    main()
