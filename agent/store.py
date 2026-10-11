"""Cloudflare D1 persistence for conversations, provider history, and metrics."""

from __future__ import annotations

import ast
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from cloudflare import Cloudflare

from . import config
from .d1_schema import EXPECTED_COLUMNS, EXPECTED_INDEX, SCHEMA_STATEMENTS


class D1StoreError(RuntimeError):
    """A safe-to-display summary of a D1 configuration or request failure."""


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _decode_container(value: Any) -> Any:
    if not isinstance(value, str) or value[:1] not in {"[", "{"}:
        return value
    try:
        return json.loads(value)
    except ValueError:
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value


def _as_row(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return {str(key): item for key, item in dumped.items()}
    raise D1StoreError("Cloudflare D1 returned an unexpected row shape.")


def extract_d1_query_batches(response: Any) -> list[list[dict[str, Any]]]:
    """Normalize Cloudflare SDK and raw REST query envelopes."""
    query_results = _decode_container(_field(response, "result", response))
    if not isinstance(query_results, list):
        query_results = [query_results]

    batches: list[list[dict[str, Any]]] = []
    for query_result in query_results:
        if _field(query_result, "success", True) is False:
            raise D1StoreError("Cloudflare D1 reported an unsuccessful query.")
        rows = _decode_container(_field(query_result, "results", []))
        if rows is None:
            rows = []
        elif isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise D1StoreError("Cloudflare D1 returned an unexpected result shape.")
        batches.append([_as_row(row) for row in rows])
    return batches


def extract_d1_query_rows(response: Any) -> list[dict[str, Any]]:
    """Return rows from a single D1 query response."""
    return [row for batch in extract_d1_query_batches(response) for row in batch]


@dataclass
class D1Database:
    account_id: str
    api_token: str
    database_id: str
    _client: Any | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_env(cls) -> D1Database:
        account_id, api_token, database_id = config.d1_settings()
        return cls(account_id, api_token, database_id)

    @property
    def available(self) -> bool:
        return bool(self.account_id and self.api_token and self.database_id)

    def _require_available(self) -> None:
        if not self.available:
            raise D1StoreError(
                "Cloudflare D1 is not configured. Set CLOUDFLARE_ACCOUNT_ID, "
                "CLOUDFLARE_API_TOKEN, and CLOUDFLARE_D1_DATABASE_ID."
            )

    def _cloudflare_client(self) -> Any:
        self._require_available()
        if self._client is None:
            self._client = Cloudflare(api_token=self.api_token)
        return self._client

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        try:
            response = self._cloudflare_client().d1.database.query(
                account_id=self.account_id,
                database_id=self.database_id,
                sql=sql,
                params=params or [],
            )
        except D1StoreError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            suffix = f" with status {status}" if status else ""
            raise D1StoreError(f"Cloudflare D1 request failed{suffix}.") from exc
        return extract_d1_query_rows(response)

    def batch(
        self, statements: list[tuple[str, list[Any]]]
    ) -> list[list[dict[str, Any]]]:
        try:
            response = self._cloudflare_client().d1.database.query(
                account_id=self.account_id,
                database_id=self.database_id,
                batch=[{"sql": sql, "params": params} for sql, params in statements],
            )
        except D1StoreError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            suffix = f" with status {status}" if status else ""
            raise D1StoreError(f"Cloudflare D1 batch failed{suffix}.") from exc
        batches = extract_d1_query_batches(response)
        if len(batches) != len(statements):
            raise D1StoreError("Cloudflare D1 returned an incomplete batch result.")
        return batches

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


_database: Any | None = None


def _db() -> Any:
    global _database
    if _database is None:
        _database = D1Database.from_env()
    return _database


def initialize() -> dict[str, Any]:
    database = _db()
    for statement in SCHEMA_STATEMENTS:
        database.query(statement)
    return verify_schema()


def verify_schema() -> dict[str, Any]:
    database = _db()
    tables: dict[str, list[str]] = {}
    for table, expected in EXPECTED_COLUMNS.items():
        rows = database.query(f'PRAGMA table_info("{table}")')
        columns = {str(row.get("name")) for row in rows if row.get("name")}
        missing = expected - columns
        if missing:
            names = ", ".join(sorted(missing))
            raise D1StoreError(
                f"Cloudflare D1 table {table} is missing columns: {names}."
            )
        tables[table] = sorted(columns)

    foreign_keys = database.query('PRAGMA foreign_key_list("messages")')
    cascade = any(
        row.get("table") == "conversations"
        and row.get("from") == "conversation_id"
        and str(row.get("on_delete", "")).upper() == "CASCADE"
        for row in foreign_keys
    )
    if not cascade:
        raise D1StoreError(
            "Cloudflare D1 messages.conversation_id is missing ON DELETE CASCADE."
        )

    indexes = database.query('PRAGMA index_list("messages")')
    index_names = {str(row.get("name")) for row in indexes if row.get("name")}
    if EXPECTED_INDEX not in index_names:
        raise D1StoreError(f"Cloudflare D1 is missing index {EXPECTED_INDEX}.")

    count_rows = database.query("SELECT COUNT(*) AS count FROM conversations")
    conversation_count = int(count_rows[0]["count"]) if count_rows else 0
    return {
        "tables": tables,
        "indexes": sorted(index_names),
        "foreign_key_cascade": True,
        "conversation_count": conversation_count,
        "seed_data_required": False,
    }


def create() -> dict[str, str]:
    item = {"id": uuid.uuid4().hex, "title": "New conversation"}
    _db().query(
        "INSERT INTO conversations(id, title) VALUES(?, ?)",
        [item["id"], item["title"]],
    )
    return item


def listing() -> list[dict[str, Any]]:
    return _db().query(
        "SELECT id, title, created_at, updated_at FROM conversations "
        "ORDER BY created_at DESC, rowid DESC"
    )


def get(cid: str) -> dict[str, Any] | None:
    rows = _db().query(
        """
        SELECT c.id, c.title, c.history, m.payload AS message_payload
        FROM conversations AS c
        LEFT JOIN messages AS m ON m.conversation_id = c.id
        WHERE c.id = ?
        ORDER BY m.id
        """,
        [cid],
    )
    if not rows:
        return None
    try:
        history = json.loads(rows[0]["history"])
        messages = [
            json.loads(row["message_payload"])
            for row in rows
            if row.get("message_payload") is not None
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise D1StoreError("Cloudflare D1 contains invalid conversation JSON.") from exc
    return {
        "id": rows[0]["id"],
        "title": rows[0]["title"],
        "history": history,
        "messages": messages,
    }


def save(
    cid: str,
    user: dict[str, Any],
    assistant: dict[str, Any],
    history: list[dict[str, Any]],
) -> None:
    _db().batch(
        [
            (
                """
                INSERT INTO messages(conversation_id, payload)
                VALUES(?, ?), (?, ?)
                """,
                [
                    cid,
                    json.dumps(user),
                    cid,
                    json.dumps(assistant),
                ],
            ),
            (
                """
                UPDATE conversations
                SET history = ?,
                    title = CASE
                        WHEN title = 'New conversation' THEN ?
                        ELSE title
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                [json.dumps(history), str(user["content"])[:60], cid],
            ),
        ]
    )


def rename(cid: str, title: str) -> dict[str, str] | None:
    existing = _db().query("SELECT id FROM conversations WHERE id = ?", [cid])
    if not existing:
        return None
    _db().query(
        "UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [title, cid],
    )
    return {"id": cid, "title": title}


def update_evaluation(cid: str, message_id: str, evaluation: dict) -> bool:
    """Update operator metadata only; never alter provider history or newer turns."""
    batches = _db().batch([
        ("""UPDATE messages SET payload = json_set(payload, '$.evaluation', json(?))
           WHERE conversation_id = ? AND json_extract(payload, '$.id') = ?
           AND json_extract(payload, '$.role') = 'assistant' RETURNING id""",
         [json.dumps(evaluation), cid, message_id]),
        ("""UPDATE benchmark_results SET payload = json_set(payload, '$.evaluation', json(?))
            WHERE json_extract(payload, '$.conversation_id') = ?
            AND json_extract(payload, '$.message_id') = ?""",
         [json.dumps(evaluation), cid, message_id]),
    ])
    return bool(batches[0])


def delete(cid: str) -> None:
    _db().query("DELETE FROM conversations WHERE id = ?", [cid])


def create_benchmark(run: dict, cells: list[dict]) -> None:
    # Keep batches bounded; a whole catalogue has hundreds of cells.
    _db().query("INSERT INTO benchmark_runs(id, payload) VALUES(?, ?)",
                [run["id"], json.dumps(run)])
    for offset in range(0, len(cells), 40):
        _db().batch([("INSERT INTO benchmark_results(run_id, cell_id, payload) VALUES(?, ?, ?)",
                      [run["id"], cell["id"], json.dumps(cell)]) for cell in cells[offset:offset + 40]])


def save_benchmark(run: dict) -> None:
    _db().query("UPDATE benchmark_runs SET payload = ? WHERE id = ?",
                [json.dumps(run), run["id"]])


def save_benchmark_cell(run_id: str, cell: dict) -> None:
    # Chat owns its assessment, including explanations requested while the
    # coordinator is finishing this cell. Never overwrite that newer metadata.
    _db().query("""UPDATE benchmark_results SET payload = CASE
                WHEN ? IS NOT NULL AND EXISTS (
                    SELECT 1 FROM messages WHERE conversation_id = ?
                    AND json_extract(payload, '$.id') = ?)
                THEN json_set(json(?), '$.evaluation', json((
                    SELECT json_extract(payload, '$.evaluation') FROM messages
                    WHERE conversation_id = ? AND json_extract(payload, '$.id') = ?)))
                ELSE json(?) END WHERE run_id = ? AND cell_id = ?""",
                [cell.get("conversation_id"), cell.get("conversation_id"), cell.get("message_id"),
                 json.dumps(cell), cell.get("conversation_id"), cell.get("message_id"),
                 json.dumps(cell), run_id, cell["id"]])


def save_benchmark_chat(run_id: str, cell: dict, title: str, user: dict,
                        assistant: dict, history: list[dict]) -> None:
    """Publish a diagnosis and its matrix link together, before grading begins."""
    cid = cell["conversation_id"]
    _db().batch([
        ("INSERT INTO conversations(id, title, history) VALUES(?, ?, ?)",
         [cid, title, json.dumps(history)]),
        ("INSERT INTO messages(conversation_id, payload) VALUES(?, ?), (?, ?)",
         [cid, json.dumps(user), cid, json.dumps(assistant)]),
        ("UPDATE benchmark_results SET payload = ? WHERE run_id = ? AND cell_id = ?",
         [json.dumps(cell), run_id, cell["id"]]),
    ])


def save_benchmark_cells(run_id: str, cells: list[dict]) -> None:
    for offset in range(0, len(cells), 40):
        _db().batch([("UPDATE benchmark_results SET payload = ? WHERE run_id = ? AND cell_id = ?",
                      [json.dumps(cell), run_id, cell["id"]]) for cell in cells[offset:offset + 40]])


def benchmark_listing() -> list[dict]:
    rows = _db().query("SELECT json_remove(payload, '$.system_prompt') AS payload "
                       "FROM benchmark_runs ORDER BY created_at DESC, rowid DESC LIMIT 50")
    return [json.loads(row["payload"]) for row in rows]


def get_benchmark(run_id: str, detail: bool = True) -> dict | None:
    rows = _db().query("SELECT payload FROM benchmark_runs WHERE id = ?", [run_id])
    if not rows:
        return None
    run = json.loads(rows[0]["payload"])
    # Matrix polling must not download hundreds of full tool traces/rubrics.
    payload = "payload" if detail else """json_set(json_remove(payload, '$.content', '$.tools', '$.stats',
        '$.evaluation.rubric', '$.evaluation.grading', '$.evaluation.criteria',
        '$.evaluation.context', '$.evaluation.question', '$.evaluation.answer',
        '$.evaluation.raw_result', '$.evaluation.explanation'), '$.stats', json_object(
            'cost_usd', json_extract(payload, '$.stats.cost_usd'),
            'usage_complete', json_extract(payload, '$.stats.usage_complete'),
            'model_calls', json_extract(payload, '$.stats.model_calls')),
        '$.evaluation.explanation', CASE WHEN json_type(payload, '$.evaluation.explanation') = 'object'
            THEN json_object('status', json_extract(payload, '$.evaluation.explanation.status'),
                             'cost_usd', json_extract(payload, '$.evaluation.explanation.cost_usd'))
            ELSE NULL END)"""
    run["cells"] = [json.loads(row["payload"]) for row in _db().query(
        f"SELECT {payload} AS payload FROM benchmark_results WHERE run_id = ? ORDER BY cell_id", [run_id])]
    return run


def get_benchmark_cell(run_id: str, cell_id: str) -> dict | None:
    rows = _db().query("SELECT payload FROM benchmark_results WHERE run_id = ? AND cell_id = ?",
                       [run_id, cell_id])
    return json.loads(rows[0]["payload"]) if rows else None


def save_benchmark_evaluation(run_id: str, cell_id: str, evaluation: dict) -> None:
    _db().query("""UPDATE benchmark_results SET payload = json_set(payload, '$.evaluation', json(?))
                   WHERE run_id = ? AND cell_id = ?""", [json.dumps(evaluation), run_id, cell_id])


def interrupt_benchmarks() -> None:
    """Recover metadata only. A restart never launches a model or network command."""
    _db().query("""UPDATE benchmark_runs SET payload = json_set(payload, '$.status', 'interrupted',
                   '$.error', 'Server restarted. Check the testbed before starting a new run.')
                   WHERE json_extract(payload, '$.status') IN ('starting', 'running', 'stopping', 'pausing')""")
    _db().query("""UPDATE benchmark_results SET payload = json_set(payload, '$.status', 'interrupted',
                   '$.error', 'Server restarted before this cell finished.')
                   WHERE json_extract(payload, '$.status') IN ('pending', 'running', 'grading')""")
    _db().query("""UPDATE benchmark_results SET payload = json_set(payload,
                   '$.evaluation.status', 'error', '$.evaluation.error', 'Grading interrupted by server restart.')
                   WHERE json_extract(payload, '$.status') = 'interrupted'
                   AND json_extract(payload, '$.evaluation.status') = 'pending'""")
    _db().query("""UPDATE benchmark_results SET payload = json_set(payload,
                   '$.evaluation.explanation.status', 'error',
                   '$.evaluation.explanation.error', 'Explanation interrupted by server restart.')
                   WHERE json_extract(payload, '$.evaluation.explanation.status') = 'pending'""")


def close() -> None:
    global _database
    if _database is not None and hasattr(_database, "close"):
        _database.close()
    _database = None
