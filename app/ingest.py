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
import zipfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

POINT_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+(\S.*)$")


def read_lines(path: Path) -> list[str]:
    if path.suffix.lower() == ".docx":
        # A DOCX is a ZIP archive; reading its main XML avoids python-docx's
        # object model overhead and preserves the paragraph boundaries used below.
        try:
            with zipfile.ZipFile(path) as archive:
                with archive.open("word/document.xml") as document_xml:
                    root = ET.parse(document_xml).getroot()
        except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
            raise ValueError(f"Cannot read DOCX document {path}: {exc}") from exc

        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        lines: list[str] = []
        for paragraph in root.iter(f"{namespace}p"):
            parts: list[str] = []
            for node in paragraph.iter():
                if node.tag == f"{namespace}t" and node.text:
                    parts.append(node.text)
                elif node.tag in (f"{namespace}tab", f"{namespace}br", f"{namespace}cr"):
                    parts.append("\t" if node.tag == f"{namespace}tab" else " ")
            lines.append("".join(parts))
        return lines
    return path.read_text(encoding="utf-8").splitlines()


def split_points(lines: list[str]) -> list[tuple[str, str]]:
    return [(number, text) for number, text, _ in split_points_with_locations(lines)]


def split_points_with_locations(lines: list[str]) -> list[tuple[str, str, int]]:
    """Split numbered sections and retain their one-based source line/paragraph."""
    points: list[list[str | int]] = []
    for paragraph, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        m = POINT_RE.match(line)
        if m and not re.fullmatch(r"\d{4}", m[1]):  # «2026 году» — не пункт
            points.append([m[1], m[2].strip(), paragraph])
        elif points:
            points[-1][1] += " " + line.strip()
    return [(number, text, paragraph) for number, text, paragraph in points]


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

    source_path = Path(a.file)
    pts = split_points_with_locations(read_lines(source_path))
    slug = re.sub(r"\W+", "", a.doc.lower())[:6] + "-v" + a.version
    for n, text, paragraph in pts:
        data["chunks"].append({
            "id": f"{slug}-{n}", "doc": a.doc, "version": a.version, "point": n, "title": title_of(text),
            "text": text, "plain": "", "template": None, "access": [], "status": "active",
            "filename": source_path.name, "section": n, "paragraph": paragraph,
        })
    data["docs"].append({"doc": a.doc, "version": a.version, "status": "active", "date": date.today().isoformat()})
    kb_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Загружено пунктов: {len(pts)}; версия {a.version} активна, прежние версии «{a.doc}» в архиве.")


if __name__ == "__main__":
    main()
