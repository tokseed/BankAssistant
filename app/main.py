"""REST API для встраиваемого виджета. Запуск: uvicorn app.main:app"""
from __future__ import annotations

import hmac
import asyncio
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from threading import Lock

# Load local .env before reading configuration. Existing environment variables win.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .dialog import Engine
from .compliance import ALLOWED_SUFFIXES, MAX_DRAFT_BYTES, review_draft
from .feedback import FeedbackStore
from .ingest import document_slug, read_lines, split_document, split_points
from .knowledge import KnowledgeBase, make_answerer
from .render import BASE_DIR, load_templates, render_document

logging.basicConfig(level=logging.INFO)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OUT_DIR = Path(os.getenv("OUTPUT_DIR", Path(tempfile.gettempdir()) / "docgen"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

# CORS: "*" для тестов; в проде список адресов портала, например "https://portal.corp.local"
ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]

# Авторизация: AUTH_TOKENS="токен1:employee,токен2:manager,токен3:expert".
# Портал выдаёт виджету токен (data-token). Пусто → открытый демо-режим с ролью employee.
TOKENS = dict(p.split(":", 1) for p in os.getenv("AUTH_TOKENS", "").split(",") if ":" in p)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

app = FastAPI(title="Помощник по регламентам: API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Token"],
    expose_headers=["Content-Disposition"],
    allow_credentials=False,
    max_age=600,
)

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "cross-origin")
    return response

kb = KnowledgeBase(Path(os.getenv("KB_PATH", BASE_DIR / "kb" / "chunks.json")))
WIDGET_CONFIG_PATH = Path(os.getenv("WIDGET_CONFIG_PATH", BASE_DIR / "config" / "widget.json"))
WIDGET_CONFIG_LOCK = Lock()
WIDGET_CONFIG_DEFAULT = {
    "theme": "medium",
    "color": "",
    "title": "Банк",
}
FEEDBACK_STORE = FeedbackStore(
    Path(os.getenv("FEEDBACK_PATH", BASE_DIR / "feedback" / "feedback.jsonl"))
)
engine = Engine(
    load_templates(),
    renderer=lambda tpl, answers, sid: render_document(tpl, answers, OUT_DIR, sid),
    kb=kb,
    answerer=make_answerer(),
    ttl=int(os.getenv("SESSION_TTL", "1800")),
    feedback_store=FEEDBACK_STORE,
)


def current_role(authorization: str | None = Header(None)) -> str:
    if not TOKENS:
        return "employee"
    token = (authorization or "").removeprefix("Bearer ").strip()
    for known, role in TOKENS.items():
        if hmac.compare_digest(known, token):
            return role
    raise HTTPException(401, "Нужна авторизация")


class StartIn(BaseModel):
    template_id: str | None = None


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class FeedbackIn(BaseModel):
    rating: str = Field(pattern="^(positive|negative)$")
    correction: str = Field(default="", max_length=2000)
    answer_id: str = Field(default="", max_length=64)


class WidgetConfigIn(BaseModel):
    theme: str = Field(default="medium")
    color: str = Field(default="")
    title: str = Field(default="Банк", max_length=80)


def read_widget_config() -> dict[str, str]:
    """Returns persisted widget defaults, falling back safely for a new install."""
    with WIDGET_CONFIG_LOCK:
        try:
            raw = json.loads(WIDGET_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
    return {
        "theme": raw.get("theme") if raw.get("theme") in {"light", "dark", "medium"} else WIDGET_CONFIG_DEFAULT["theme"],
        "color": raw.get("color") if isinstance(raw.get("color"), str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", raw["color"]) else "",
        "title": str(raw.get("title") or WIDGET_CONFIG_DEFAULT["title"])[:80],
    }


def write_widget_config(config: dict[str, str]) -> dict[str, str]:
    WIDGET_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = WIDGET_CONFIG_PATH.with_suffix(".tmp")
    with WIDGET_CONFIG_LOCK:
        temp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(WIDGET_CONFIG_PATH)
    return config


def require_admin(x_admin_token: str | None) -> None:
    if ADMIN_TOKEN and not hmac.compare_digest(ADMIN_TOKEN, x_admin_token or ""):
        raise HTTPException(403, "Нет доступа")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/widget-config")
@app.get("/api/config/widget")
@app.get("/api/config")
def widget_config():
    """Public defaults read by the embedded widget when attributes are omitted."""
    return read_widget_config()


@app.put("/api/widget-config")
@app.put("/api/config/widget")
@app.put("/api/config")
def update_widget_config(body: WidgetConfigIn, x_admin_token: str | None = Header(None)):
    """Saves the defaults used by newly embedded widgets."""
    require_admin(x_admin_token)
    theme = body.theme.lower().strip()
    color = body.color.strip()
    title = body.title.strip()
    if theme not in {"light", "dark", "medium"}:
        raise HTTPException(422, "Тема должна быть light, dark или medium")
    if color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise HTTPException(422, "Акцентный цвет должен быть в формате #RRGGBB")
    if not title:
        raise HTTPException(422, "Укажите заголовок виджета")
    return write_widget_config({"theme": theme, "color": color, "title": title})


@app.get("/api/kb/status")
def kb_status(role: str = Depends(current_role)):
    """Summary for the settings page; does not expose inaccessible chunks."""
    visible = [chunk for chunk in kb.chunks if not chunk.access or role in chunk.access]
    docs = []
    for document in kb.documents():
        doc = document.get("doc", "")
        version = document.get("version", "")
        chunks = sum(1 for chunk in visible if chunk.doc == doc and chunk.version == version)
        docs.append({**document, "chunks": chunks})
    return {
        "status": "ready",
        "engine": "local_rag",
        "documents": docs,
        "total_chunks": len(visible),
        "active_chunks": sum(1 for chunk in visible if chunk.status == "active"),
    }


@app.post("/api/chat")
async def chat(body: ChatIn, role: str = Depends(current_role)):
    """Direct chat endpoint that uses the same local knowledge search as sessions."""
    try:
        hits = await asyncio.to_thread(engine.kb.search, body.message, role)
        good = [hit for hit in hits if hit.relevance >= engine.kb.min_relevance]
        if not good:
            general_chat = getattr(engine.answerer, "general_chat", None)
            if general_chat is not None:
                return {
                    "message": await asyncio.to_thread(general_chat, body.message),
                    "sources": [],
                }
            return {
                "message": "В базе знаний нет информации по этому вопросу. "
                "Уточните название документа или пункт инструкции.",
                "sources": [],
            }
        message = await asyncio.to_thread(engine.answerer.answer, body.message, good)
        return {"message": message, "sources": [hit.public() for hit in good]}
    except Exception:
        logging.getLogger("docgen.api").exception("Knowledge chat request failed")
        raise HTTPException(500, "Не удалось выполнить поиск по базе знаний")


@app.get("/api/templates")
def templates(role: str = Depends(current_role)):
    return engine.list_templates(role)


@app.get("/api/document-types")
def document_types(role: str = Depends(current_role)):
    """Типы документов для быстрых кнопок в чате."""
    return engine.document_types(role)


@app.get("/api/kb/documents")
def kb_documents(role: str = Depends(current_role)):
    """Какие документы и версии сейчас в базе знаний."""
    return kb.documents()


@app.get("/api/kb/articles")
def kb_articles(role: str = Depends(current_role)):
    return [
        {
            "id": chunk.id,
            "doc": chunk.doc,
            "version": chunk.version,
            "point": chunk.point,
            "title": chunk.title,
            "text": chunk.text,
            "plain": chunk.plain,
        }
        for chunk in kb.chunks
        if chunk.status == "active" and (not chunk.access or role in chunk.access)
    ]


@app.get("/api/kb/search")
def kb_search(q: str = "", role: str = Depends(current_role)):
    query = q.strip()
    if not query:
        return []
    return [hit.public() for hit in kb.search(query, role, top_k=12)]


@app.post("/api/admin/kb/upload")
async def kb_upload(
    file: UploadFile = File(...),
    doc: str = "Загруженная инструкция",
    version: str = "1.0",
    x_admin_token: str | None = Header(None),
):
    if ADMIN_TOKEN and not hmac.compare_digest(ADMIN_TOKEN, x_admin_token or ""):
        raise HTTPException(403, "Нет доступа")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".docx", ".pdf", ".txt", ".md"}:
        raise HTTPException(415, "Поддерживаются только .docx, .pdf, .txt и .md")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp_path = Path(temp.name)
            total = 0
            while chunk := await file.read(64 * 1024):
                total += len(chunk)
                if total > MAX_DRAFT_BYTES:
                    raise HTTPException(413, "Файл слишком большой: максимум 5 МБ")
                temp.write(chunk)
        points = split_points(read_lines(temp_path))
        if not points:
            raise HTTPException(422, "В документе не найдены нумерованные пункты")
        data = json.loads(kb.path.read_text(encoding="utf-8"))
        for item in data["chunks"]:
            if item["doc"] == doc and item["status"] == "active":
                item["status"] = "archived"
        for item in data["docs"]:
            if item["doc"] == doc and item["status"] == "active":
                item["status"] = "archived"
        slug = document_slug(doc)
        for point, text in points:
            data["chunks"].append({
                "id": f"{slug}-v{version}-{point}",
                "doc": doc,
                "version": version,
                "point": point,
                "title": text[:90],
                "text": text,
                "plain": "",
                "template": None,
                "access": [],
                "status": "active",
            })
        data["docs"].append({"doc": doc, "version": version, "status": "active"})
        kb.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        kb.load()
        return {"status": "reloaded", "document": doc, "version": version, "points": len(points)}
    except HTTPException:
        raise
    except (OSError, ValueError, KeyError, RuntimeError):
        logging.getLogger("docgen.api").exception("Knowledge upload failed")
        raise HTTPException(422, "Не удалось прочитать документ")
    finally:
        await file.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)


@app.post("/api/documents/review")
async def review_document(
    file: UploadFile = File(...),
    role: str = Depends(current_role),
):
    """Проверить черновик PDF/DOCX/TXT/MD по доступным пунктам Инструкции."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Поддерживаются только .pdf, .docx, .txt и .md")

    temp_path: Path | None = None
    total = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp_path = Path(temp.name)
            while chunk := await file.read(64 * 1024):
                total += len(chunk)
                if total > MAX_DRAFT_BYTES:
                    raise HTTPException(413, "Файл слишком большой: максимум 5 МБ")
                temp.write(chunk)
        result = review_draft(temp_path, kb, role)
        result["document"] = file.filename
        return result
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError):
        logging.getLogger("docgen.api").exception("Draft review failed")
        raise HTTPException(422, "Не удалось прочитать или проверить документ")
    finally:
        await file.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)


@app.post("/api/sessions/{sid}/files")
async def upload_chat_file(
    sid: str,
    file: UploadFile = File(...),
    role: str = Depends(current_role),
):
    """Индексирует файл, загруженный из чата, в локальной базе знаний."""
    if not engine.has_session(sid, role):
        raise HTTPException(404, "Сессия не найдена или истекла")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt"}:
        raise HTTPException(415, "Поддерживаются только .pdf, .docx и .txt")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp_path = Path(temp.name)
            total = 0
            while chunk := await file.read(64 * 1024):
                total += len(chunk)
                if total > MAX_DRAFT_BYTES:
                    raise HTTPException(413, "Файл слишком большой: максимум 5 МБ")
                temp.write(chunk)

        # Проверяем документ до индексации: иначе поиск мог бы сопоставить
        # документ с самим собой и показать завышенное соответствие.
        review = review_draft(temp_path, kb, role)
        points = split_document(read_lines(temp_path))
        if not points:
            raise HTTPException(422, "В документе нет текста для индексации")

        doc = f"Загрузка из чата: {file.filename} ({role})"
        version = "chat-" + str(time.time_ns())
        data = json.loads(kb.path.read_text(encoding="utf-8"))
        for item in data["chunks"]:
            if item["doc"] == doc and item["status"] == "active":
                item["status"] = "archived"
        for item in data["docs"]:
            if item["doc"] == doc and item["status"] == "active":
                item["status"] = "archived"
        slug = document_slug(doc)
        for point, text in points:
            data["chunks"].append({
                "id": f"{slug}-v{version}-{point}",
                "doc": doc,
                "version": version,
                "point": point,
                "title": text[:90],
                "text": text,
                "plain": "",
                "template": None,
                "access": [role],
                "status": "active",
                "filename": file.filename,
            })
        data["docs"].append({"doc": doc, "version": version, "status": "active"})
        kb.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        kb.load()
        return {
            "messages": [
                f"Файл «{file.filename}» загружен и проиндексирован ({len(points)} фрагментов).",
                (
                    "Полный анализ завершён: соответствие "
                    f"{review['summary']['compliance_percent']}%. "
                    f"Проверено разделов: {review['summary']['sections']}; "
                    f"найдено оснований: {review['summary']['matched']}; "
                    f"без основания: {review['summary']['unmatched']}."
                ),
            ],
            "document": file.filename,
            "points": len(points),
            "review": review,
        }
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError):
        logging.getLogger("docgen.api").exception("Chat file indexing failed")
        raise HTTPException(422, "Не удалось прочитать или проиндексировать файл")
    finally:
        await file.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)


@app.post("/api/admin/kb/reload")
def kb_reload(x_admin_token: str | None = Header(None)):
    """Применить новую версию Инструкции без перезапуска (после python -m app.ingest)."""
    if not ADMIN_TOKEN or not hmac.compare_digest(ADMIN_TOKEN, x_admin_token or ""):
        raise HTTPException(403, "Нет доступа")
    kb.load()
    return {"status": "reloaded", "documents": kb.documents()}


@app.post("/api/sessions")
def create_session(body: StartIn = StartIn(), role: str = Depends(current_role)):
    try:
        return engine.start(body.template_id, role)
    except KeyError:
        raise HTTPException(404, "Шаблон не найден")
    except RuntimeError:
        raise HTTPException(503, "Сервер занят, попробуйте позже")


@app.post("/api/sessions/{sid}/messages")
def send_message(sid: str, body: MessageIn, role: str = Depends(current_role)):
    try:
        return engine.handle(sid, body.text, role)
    except KeyError:
        raise HTTPException(404, "Сессия не найдена или истекла")


@app.post("/api/sessions/{sid}/feedback")
def session_feedback(sid: str, body: FeedbackIn, role: str = Depends(current_role)):
    try:
        record = engine.record_feedback(
            sid, role, body.rating, body.correction, body.answer_id
        )
        return {
            "status": "saved",
            "learning": bool(record.get("correction")),
            "message": (
                "Спасибо. Исправление сохранено и будет использоваться "
                "в похожих вопросах."
                if record.get("correction")
                else "Спасибо. Оценка сохранена для анализа."
            ),
        }
    except KeyError:
        raise HTTPException(404, "Сессия не найдена или истекла")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError:
        raise HTTPException(503, "Обратная связь временно недоступна")


@app.get("/api/admin/feedback")
def feedback_list(
    limit: int = 100,
    x_admin_token: str | None = Header(None),
):
    require_admin(x_admin_token)
    return FEEDBACK_STORE.list_recent(max(1, min(limit, 500)))


@app.get("/api/sessions/{sid}/document")
def download(sid: str, role: str = Depends(current_role)):
    found = engine.document_path(sid, role)
    if not found:
        raise HTTPException(404, "Документ не найден или срок хранения истёк")
    path, name = found
    return FileResponse(path, media_type=DOCX, filename=name)


@app.get("/", include_in_schema=False)
def demo():
    return FileResponse(BASE_DIR / "static" / "demo.html")


@app.get("/chat", include_in_schema=False)
def chat():
    """Отдельный адрес для тестирования виджета и его тем."""
    return FileResponse(BASE_DIR / "static" / "chat.html")


@app.get("/settings", include_in_schema=False)
def settings():
    return FileResponse(BASE_DIR / "static" / "settings.html")


@app.get("/wiki", include_in_schema=False)
def wiki():
    return FileResponse(BASE_DIR / "static" / "wiki.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
