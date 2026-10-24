"""REST API для встраиваемого виджета. Запуск: uvicorn app.main:app"""
from __future__ import annotations

import hmac
import asyncio
import logging
import os
import tempfile
from pathlib import Path

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
from .knowledge import GigaChatAnswerer, KnowledgeBase, OpenAIAnswerer, make_answerer
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
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Token"],
    expose_headers=["Content-Disposition"],
    allow_credentials=False,
)

kb = KnowledgeBase(Path(os.getenv("KB_PATH", BASE_DIR / "kb" / "chunks.json")))
engine = Engine(
    load_templates(),
    renderer=lambda tpl, answers, sid: render_document(tpl, answers, OUT_DIR, sid),
    kb=kb,
    answerer=make_answerer(),
    ttl=int(os.getenv("SESSION_TTL", "1800")),
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


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(body: ChatIn, role: str = Depends(current_role)):
    """Temporary direct AI chat without the knowledge-base workflow."""
    if not isinstance(engine.answerer, (OpenAIAnswerer, GigaChatAnswerer)):
        raise HTTPException(503, "AI API не настроен")
    try:
        message = await asyncio.to_thread(engine.answerer.chat, body.message)
        return {"message": message}
    except TimeoutError:
        raise HTTPException(504, "AI API не ответил вовремя")
    except Exception:
        logging.getLogger("docgen.api").exception("AI chat request failed")
        raise HTTPException(502, "AI API недоступен")


@app.get("/api/templates")
def templates(role: str = Depends(current_role)):
    return engine.list_templates(role)


@app.get("/api/kb/documents")
def kb_documents(role: str = Depends(current_role)):
    """Какие документы и версии сейчас в базе знаний."""
    return kb.documents()


@app.post("/api/documents/review")
async def review_document(
    file: UploadFile = File(...),
    role: str = Depends(current_role),
):
    """Проверить черновик DOCX/TXT/MD по доступным пунктам Инструкции."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Поддерживаются только .docx, .txt и .md")

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


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
