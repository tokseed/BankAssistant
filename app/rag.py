"""Optional LangChain and FAISS helpers for document-grounded retrieval.

The existing JSON/BM25 knowledge base remains the default application path.
These helpers are independent so deployments can enable vector retrieval when
an embedding provider and the optional dependencies are configured.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)
DEFAULT_INDEX_DIR = Path(__file__).resolve().parent.parent / "faiss_index"


def chunk_documents(records: Iterable[Any]) -> list[Any]:
    """Convert app knowledge chunks to LangChain Documents with citation metadata."""
    try:
        from langchain_core.documents import Document
    except ImportError as exc:
        raise RuntimeError("Install langchain-core to prepare documents for vector search") from exc
    documents = []
    for record in records:
        metadata = {
            "chunk_id": record.id,
            "filename": getattr(record, "filename", None) or record.doc,
            "section": getattr(record, "section", None) or record.point,
            "paragraph": getattr(record, "paragraph", None),
            "doc": record.doc,
            "version": record.version,
            "access": list(getattr(record, "access", []) or []),
        }
        documents.append(Document(page_content=record.text, metadata=metadata))
    return documents


def split_documents(documents: Iterable[Any], chunk_size: int = 500, chunk_overlap: int = 50) -> list[Any]:
    """Split LangChain Documents, carrying filename and paragraph metadata forward."""
    if chunk_size <= 0 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("Require chunk_size > chunk_overlap >= 0")
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError as exc:
        raise RuntimeError("Install langchain-text-splitters to use document chunking") from exc
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return splitter.split_documents(list(documents))


def create_faiss_index(documents: Iterable[Any], embeddings: Any, index_dir: Path = DEFAULT_INDEX_DIR) -> Any:
    """Build and persist a FAISS index. Documents should include citation metadata."""
    docs = list(documents)
    if not docs:
        raise ValueError("Cannot create a FAISS index without documents")
    try:
        from langchain_community.vectorstores import FAISS
    except ImportError as exc:
        raise RuntimeError("Install langchain-community and faiss-cpu to use vector search") from exc
    try:
        store = FAISS.from_documents(docs, embeddings)
        store.save_local(str(index_dir))
    except Exception:
        log.exception("Failed to create or save FAISS index at %s", index_dir)
        raise
    return store


def load_faiss_index(embeddings: Any, index_dir: Path = DEFAULT_INDEX_DIR) -> Any:
    """Load a locally persisted FAISS index (only load indexes from trusted sources)."""
    try:
        from langchain_community.vectorstores import FAISS
    except ImportError as exc:
        raise RuntimeError("Install langchain-community and faiss-cpu to use vector search") from exc
    if not (index_dir / "index.faiss").is_file():
        raise FileNotFoundError(f"FAISS index not found in {index_dir}")
    try:
        return FAISS.load_local(str(index_dir), embeddings, allow_dangerous_deserialization=True)
    except Exception:
        log.exception("Failed to load FAISS index from %s", index_dir)
        raise


def search_faiss(store: Any, query: str, top_k: int = 4) -> list[dict[str, Any]]:
    """Return chunks with stable IDs and citation metadata alongside similarity scores."""
    if top_k < 1:
        raise ValueError("top_k must be positive")
    try:
        matches = store.similarity_search_with_score(query, k=top_k)
    except Exception:
        log.exception("FAISS similarity search failed")
        raise
    results = []
    for document, score in matches:
        metadata = dict(document.metadata or {})
        results.append({
            "id": metadata.get("chunk_id"), "text": document.page_content,
            "source": metadata.get("filename"), "section": metadata.get("section"),
            "paragraph": metadata.get("paragraph"), "metadata": metadata, "score": float(score),
        })
    return results


class OllamaEmbeddings:
    """Minimal LangChain-compatible embedding client for a local Ollama server."""

    def __init__(self, base_url: str, model: str, timeout: float = 60.0):
        if not base_url or not model:
            raise ValueError("An embedding base URL and model are required")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _embed(self, text: str) -> list[float]:
        payload = json.dumps({"model": self.model, "input": text}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embed", payload, {"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read())
            vector = data["embeddings"][0]
            if not vector or not all(isinstance(value, (int, float)) for value in vector):
                raise ValueError("Embedding response contained an invalid vector")
            return [float(value) for value in vector]
        except Exception:
            log.exception("Ollama embedding request failed")
            raise

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def initialize_faiss(records: Iterable[Any], embeddings: Any, index_dir: Path = DEFAULT_INDEX_DIR) -> Any:
    """Load an existing local index or create and persist one from knowledge records."""
    index_dir = Path(index_dir)
    if (index_dir / "index.faiss").is_file():
        return load_faiss_index(embeddings, index_dir)
    records = list(records)
    if not records:
        raise ValueError("Cannot initialize FAISS without knowledge records")
    return create_faiss_index(split_documents(chunk_documents(records)), embeddings, index_dir)


def rebuild_faiss_index(records: Iterable[Any], embeddings: Any, index_dir: Path = DEFAULT_INDEX_DIR) -> Any:
    """Rebuild and persist an index after the active knowledge base changes."""
    return create_faiss_index(split_documents(chunk_documents(records)), embeddings, Path(index_dir))
