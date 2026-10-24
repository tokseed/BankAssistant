"""Optional SQL Server logging for queries, retrieved source metadata, and execution time."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterable

log = logging.getLogger(__name__)


def connect_sql_server(connection_string: str | None = None) -> Any:
    """Open a pyodbc connection using an explicit string or SQLSERVER_CONNECTION_STRING."""
    connection_string = connection_string or os.getenv("SQLSERVER_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("Set SQLSERVER_CONNECTION_STRING or pass connection_string")
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError("Install pyodbc to use SQL Server logging") from exc
    try:
        return pyodbc.connect(connection_string)
    except Exception:
        log.exception("Could not connect to SQL Server")
        raise


def initialize_logging_table(connection: Any) -> None:
    """Create the append-only query log table if it does not exist."""
    sql = """
    IF OBJECT_ID(N'dbo.RagQueryLog', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.RagQueryLog (
            id BIGINT IDENTITY(1,1) PRIMARY KEY,
            created_at DATETIME2 NOT NULL,
            input_query NVARCHAR(2000) NOT NULL,
            retrieved_chunk_ids NVARCHAR(MAX) NOT NULL,
            status NVARCHAR(32) NOT NULL,
            retrieved_chunk_metadata NVARCHAR(MAX) NULL,
            execution_time_ms FLOAT NULL
        )
    END
    IF COL_LENGTH(N'dbo.RagQueryLog', N'retrieved_chunk_metadata') IS NULL
        ALTER TABLE dbo.RagQueryLog ADD retrieved_chunk_metadata NVARCHAR(MAX) NULL;
    IF COL_LENGTH(N'dbo.RagQueryLog', N'execution_time_ms') IS NULL
        ALTER TABLE dbo.RagQueryLog ADD execution_time_ms FLOAT NULL;
    """
    try:
        cursor = connection.cursor()
        cursor.execute(sql)
        connection.commit()
    except Exception:
        connection.rollback()
        log.exception("Could not initialize RagQueryLog table")
        raise


def log_query(
    connection: Any,
    input_query: str,
    retrieved_chunk_ids: Iterable[str],
    status: str,
    retrieved_chunk_metadata: Iterable[dict[str, Any]] = (),
    execution_time_ms: float | None = None,
) -> None:
    """Write query execution details; callers should avoid sending sensitive query text."""
    if len(input_query) > 2000:
        raise ValueError("input_query exceeds the 2000 character logging limit")
    if not status or len(status) > 32:
        raise ValueError("status must contain 1 to 32 characters")
    chunk_ids = ",".join(str(chunk_id) for chunk_id in retrieved_chunk_ids)
    try:
        cursor = connection.cursor()
        metadata_json = json.dumps(list(retrieved_chunk_metadata), ensure_ascii=False)
        cursor.execute(
            "INSERT INTO dbo.RagQueryLog "
            "(created_at, input_query, retrieved_chunk_ids, status, retrieved_chunk_metadata, execution_time_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            datetime.now(timezone.utc).replace(tzinfo=None), input_query, chunk_ids,
            status, metadata_json, execution_time_ms,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        log.exception("Could not write RAG query log row")
        raise
