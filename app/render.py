"""Загрузка конфигурации шаблонов и генерация .docx через docxtpl."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"


def load_templates() -> dict[str, dict]:
    data = json.loads((TEMPLATES_DIR / "templates.json").read_text(encoding="utf-8"))
    return {t["id"]: t for t in data["templates"]}


def _deadline_default(a: dict) -> dict:
    # Необязательное поле пропущено → в бланке печатаем понятную фразу, а не пустоту
    return {"deadline": a.get("deadline") or "не установлен"}


# Вычисляемые поля для конкретных шаблонов: id шаблона -> функция(answers) -> dict
HOOKS = {"memo": _deadline_default}


def build_context(template: dict, answers: dict) -> dict:
    ctx = dict(answers)
    # Дополнительный контекст может приходить от диалога/RAG без изменения шаблона.
    for key in ("context", "_context", "rag_context", "_rag_context"):
        extra = answers.get(key)
        if isinstance(extra, dict):
            ctx.update(extra)
    ctx["today"] = date.today().strftime("%d.%m.%Y")
    ctx["has_deadline"] = bool(ctx.get("deadline"))
    rows = ctx.get("items") or ctx.get("rows") or []
    ctx["items"] = rows if isinstance(rows, list) else []
    ctx["has_items"] = bool(ctx["items"])
    # Доступно в docxtpl как {% if conditions.has_deadline %} и
    # {% for row in tables.items %}.
    ctx["conditions"] = {
        "has_deadline": ctx["has_deadline"],
        "has_items": ctx["has_items"],
    }
    ctx["tables"] = {"items": ctx["items"]}
    hook = HOOKS.get(template["id"])
    if hook:
        ctx.update(hook(ctx))
    return ctx


def render_document(template: dict, answers: dict, out_dir: Path, session_id: str) -> Path:
    from docxtpl import DocxTemplate  # импорт здесь, чтобы тесты диалога не требовали docxtpl

    tpl = DocxTemplate(str(TEMPLATES_DIR / template["file"]))
    tpl.render(build_context(template, answers), autoescape=True)  # autoescape: & < > в данных не ломают XML
    out = out_dir / f"{session_id}.docx"
    tpl.save(str(out))
    return out
