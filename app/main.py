"""REST API для встраиваемого виджета. Запуск: uvicorn app.main:app"""
from __future__ import annotations

import hmac
import logging
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .dialog import Engine
from .knowledge import Chunk, Hit, KnowledgeBase, make_answerer, mask_pii
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


def make_vector_retriever() -> tuple[
    Callable[[str, str], list[Hit]] | None,
    Callable[[Any, list[Chunk]], None] | None,
    Any | None,
]:
    """Configure optional local Ollama embeddings and a persisted FAISS index."""
    if os.getenv("RAG_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        return None, None, None
    from .rag import OllamaEmbeddings, initialize_faiss, search_faiss

    base_url = os.getenv("EMBEDDING_URL") or os.getenv("LLM_URL")
    model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    embeddings = OllamaEmbeddings(base_url or "", model)
    active_chunks = [chunk for chunk in kb.chunks if chunk.status == "active"]
    index_dir = Path(os.getenv("FAISS_INDEX_DIR", BASE_DIR / "faiss_index"))
    store = initialize_faiss(active_chunks, embeddings, index_dir)
    store_ref = {"value": store, "chunks": {chunk.id: chunk for chunk in active_chunks}}
    max_distance = float(os.getenv("RAG_MAX_DISTANCE", "1.5"))
    top_k = max(1, int(os.getenv("RAG_TOP_K", "4")))

    def retrieve(query: str, role: str) -> list[Hit]:
        results = search_faiss(
            store_ref["value"], query, top_k=max(1, int(store_ref["value"].index.ntotal))
        )
        hits = []
        seen_ids = set()
        for result in results:
            chunk = store_ref["chunks"].get(result["id"])
            if not chunk or chunk.id in seen_ids or (chunk.access and role not in chunk.access):
                continue
            distance = result["score"]
            if distance > max_distance:
                continue
            seen_ids.add(chunk.id)
            relevance = max(0, min(100, round(100 / (1 + distance))))
            hits.append(Hit(replace(chunk, text=result["text"]), distance, relevance))
        return hits[:top_k]

    def replace_index(replacement: Any, records: list[Chunk]) -> None:
        store_ref.update(value=replacement, chunks={chunk.id: chunk for chunk in records})

    return retrieve, replace_index, embeddings


vector_retriever = None
replace_vector_index = None
embedding_model = None
try:
    vector_retriever, replace_vector_index, embedding_model = make_vector_retriever()
except Exception:
    # The existing BM25 knowledge search remains available if optional RAG setup fails.
    logging.exception("Vector RAG initialization failed; using the built-in BM25 search")


def make_query_logger() -> Callable[[str, list[Hit], float, str], None] | None:
    if not os.getenv("SQLSERVER_CONNECTION_STRING"):
        return None
    from .db_logging import connect_sql_server, initialize_logging_table, log_query

    table_initialized = False

    def write_query(query: str, hits: list[Hit], elapsed_ms: float, status: str) -> None:
        nonlocal table_initialized
        connection = connect_sql_server()
        try:
            if not table_initialized:
                initialize_logging_table(connection)
                table_initialized = True
            metadata = [
                {"id": hit.chunk.id, "source": hit.chunk.filename or hit.chunk.doc,
                 "section": hit.chunk.section or hit.chunk.point, "paragraph": hit.chunk.paragraph,
                 "score": hit.score}
                for hit in hits
            ]
            log_query(connection, mask_pii(query), [hit.chunk.id for hit in hits], status,
                      metadata, elapsed_ms)
        finally:
            connection.close()

    return write_query


query_logger = make_query_logger()
engine = Engine(
    load_templates(),
    renderer=lambda tpl, answers, sid: render_document(tpl, answers, OUT_DIR, sid),
    kb=kb,
    answerer=make_answerer(),
    ttl=int(os.getenv("SESSION_TTL", "1800")),
    vector_search=vector_retriever,
    query_logger=query_logger,
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


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/templates")
def templates(role: str = Depends(current_role)):
    return engine.list_templates(role)


@app.get("/api/kb/documents")
def kb_documents(role: str = Depends(current_role)):
    """Какие документы и версии сейчас в базе знаний."""
    return kb.documents()


@app.post("/api/admin/kb/reload")
def kb_reload(x_admin_token: str | None = Header(None)):
    """Применить новую версию Инструкции без перезапуска (после python -m app.ingest)."""
    if not ADMIN_TOKEN or not hmac.compare_digest(ADMIN_TOKEN, x_admin_token or ""):
        raise HTTPException(403, "Нет доступа")
    kb.load()
    if embedding_model is not None:
        try:
            from .rag import rebuild_faiss_index

            index_dir = Path(os.getenv("FAISS_INDEX_DIR", BASE_DIR / "faiss_index"))
            records = [chunk for chunk in kb.chunks if chunk.status == "active"]
            store = rebuild_faiss_index(records, embedding_model, index_dir)
            # Replace the closure's backing store without changing Engine's interface.
            if replace_vector_index is not None:
                replace_vector_index(store, records)
        except Exception:
            logging.exception("Could not rebuild FAISS index after knowledge base reload")
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
