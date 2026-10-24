"""Unit tests for ingestion metadata, retrieval helpers, and SQL Server logging.

Run with: pytest tests/test_rag.py
"""
from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db_logging import initialize_logging_table, log_query
from app.dialog import Engine
from app.ingest import read_lines, split_points_with_locations
from app.knowledge import Chunk, ExtractiveAnswerer, Hit, KnowledgeBase
from app.rag import OllamaEmbeddings, search_faiss, split_documents
from app.render import load_templates


def test_docx_reader_and_point_locations(tmp_path: Path) -> None:
    """DOCX text is extracted without python-docx and keeps paragraph positions."""
    document = tmp_path / "instruction.docx"
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>1. Scope</w:t></w:r></w:p>
        <w:p><w:r><w:t>Continuation</w:t></w:r></w:p>
        <w:p><w:r><w:t>2. Approval</w:t><w:tab/><w:t>one day</w:t></w:r></w:p>
      </w:body>
    </w:document>"""
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", xml)

    assert read_lines(document) == ["1. Scope", "Continuation", "2. Approval\tone day"]
    assert split_points_with_locations(read_lines(document)) == [
        ("1", "Scope Continuation", 1),
        ("2", "Approval\tone day", 3),
    ]


def test_split_documents_preserves_citation_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """LangChain splitting must retain source fields supplied to each document."""
    class FakeSplitter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def split_documents(self, documents):
            return documents

    monkeypatch.setitem(sys.modules, "langchain_text_splitters", types.SimpleNamespace(
        RecursiveCharacterTextSplitter=FakeSplitter
    ))
    document = types.SimpleNamespace(page_content="text", metadata={"filename": "x.docx", "paragraph": 4})
    assert split_documents([document], chunk_size=100, chunk_overlap=10) == [document]
    with pytest.raises(ValueError, match="chunk_size"):
        split_documents([document], chunk_size=10, chunk_overlap=10)


def test_search_faiss_returns_stable_citations() -> None:
    document = types.SimpleNamespace(
        page_content="Approval takes one day.",
        metadata={"chunk_id": "doc-v2-3.4", "filename": "instruction.docx", "section": "3.4", "paragraph": 12},
    )
    store = types.SimpleNamespace(similarity_search_with_score=lambda query, k: [(document, 0.125)])

    assert search_faiss(store, "approval", top_k=1) == [{
        "id": "doc-v2-3.4", "text": "Approval takes one day.", "source": "instruction.docx",
        "section": "3.4", "paragraph": 12, "metadata": document.metadata, "score": 0.125,
    }]
    with pytest.raises(ValueError, match="positive"):
        search_faiss(store, "approval", top_k=0)


def test_ollama_embeddings_use_embed_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"embeddings": [[0.5, 1]]}'

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, json.loads(request.data), timeout))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    embeddings = OllamaEmbeddings("http://ollama:11434/", "nomic-embed-text", timeout=3)
    assert embeddings.embed_documents(["first", "second"]) == [[0.5, 1.0], [0.5, 1.0]]
    assert requests == [
        ("http://ollama:11434/api/embed", {"model": "nomic-embed-text", "input": "first"}, 3),
        ("http://ollama:11434/api/embed", {"model": "nomic-embed-text", "input": "second"}, 3),
    ]


class FakeCursor:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, sql, *params):
        self.calls.append((sql, params))


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_sql_logging_records_metadata_and_execution_time() -> None:
    connection = FakeConnection()
    initialize_logging_table(connection)
    log_query(connection, "Where is approval?", ["doc-v2-3.4"], "ok",
              [{"source": "instruction.docx", "section": "3.4", "paragraph": 12}], 8.5)

    assert connection.commits == 2
    insert_sql, params = connection.cursor_instance.calls[-1]
    assert "retrieved_chunk_metadata" in insert_sql
    assert params[1:4] == ("Where is approval?", "doc-v2-3.4", "ok")
    assert json.loads(params[4]) == [{"source": "instruction.docx", "section": "3.4", "paragraph": 12}]
    assert params[5] == 8.5


def test_sql_logging_validates_inputs() -> None:
    connection = FakeConnection()
    with pytest.raises(ValueError, match="2000"):
        log_query(connection, "x" * 2001, [], "ok")
    with pytest.raises(ValueError, match="status"):
        log_query(connection, "query", [], "")


def test_engine_uses_vector_results_and_logs_retrieval() -> None:
    kb = KnowledgeBase(ROOT / "kb" / "chunks.json")
    chunk = Chunk(
        id="vector-1", doc="Instruction", version="1.0", point="7.2", title="Vector source",
        text="The vector index found this instruction.", filename="instruction.docx", section="7.2", paragraph=20,
    )
    logged = []

    def vector_search(query: str, role: str) -> list[Hit]:
        assert (query, role) == ("How long does approval take?", "employee")
        return [Hit(chunk, 0.1, 91)]

    def query_logger(query: str, hits: list[Hit], elapsed_ms: float, status: str) -> None:
        logged.append((query, hits[0].chunk.id, elapsed_ms, status))

    engine = Engine(
        load_templates(), lambda *_args: Path("unused.docx"), kb, ExtractiveAnswerer(),
        vector_search=vector_search, query_logger=query_logger,
    )
    session_id = engine.start()["session_id"]
    response = engine.handle(session_id, "How long does approval take?")

    assert response["sources"] == [{
        "id": "vector-1", "doc": "Instruction", "version": "1.0", "point": "7.2",
        "title": "Vector source", "relevance": 91, "snippet": "The vector index found this instruction.",
        "source": "instruction.docx", "section": "7.2", "paragraph": 20,
    }]
    assert logged[0][0:2] == ("How long does approval take?", "vector-1")
    assert logged[0][2] >= 0 and logged[0][3] == "ok"
