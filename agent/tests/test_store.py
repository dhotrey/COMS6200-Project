"""Cloudflare D1 persistence, exercised offline with the D1 SQLite dialect."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from agent import store


class SQLiteD1:
    """Small D1-compatible test double; production never opens local SQLite."""

    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def query(self, sql, params=None):
        with self.connection:
            cursor = self.connection.execute(sql, params or [])
            return [dict(row) for row in cursor.fetchall()]

    def batch(self, statements):
        results = []
        with self.connection:
            for sql, params in statements:
                cursor = self.connection.execute(sql, params)
                results.append([dict(row) for row in cursor.fetchall()])
        return results

    def close(self):
        self.connection.close()


@pytest.fixture
def database(monkeypatch):
    database = SQLiteD1()
    monkeypatch.setattr(store, "_database", database)
    yield database
    database.close()


def test_conversation_crud_and_schema(database):
    summary = store.initialize()
    assert summary["seed_data_required"] is False
    assert summary["conversation_count"] == 0
    assert summary["foreign_key_cascade"] is True

    first = store.create()
    second = store.create()
    assert [item["id"] for item in store.listing()] == [second["id"], first["id"]]
    assert store.get(first["id"]) == {
        "id": first["id"],
        "title": "New conversation",
        "history": [],
        "messages": [],
    }

    user = {"role": "user", "content": "Check h1 to h5"}
    assistant = {
        "role": "assistant",
        "content": "The path is healthy.",
        "tools": [],
        "stats": {"total_tokens": 12},
    }
    history = [user, {"role": "assistant", "content": assistant["content"]}]
    store.save(first["id"], user, assistant, history)

    saved = store.get(first["id"])
    assert saved["title"] == "Check h1 to h5"
    assert saved["messages"] == [user, assistant]
    assert saved["history"] == history

    store.delete(first["id"])
    assert store.get(first["id"]) is None
    assert (
        database.query(
            "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = ?",
            [first["id"]],
        )[0]["count"]
        == 0
    )


def test_extracts_cloudflare_sdk_query_envelope():
    response = {
        "result": [
            {
                "meta": {"rows_read": 2},
                "results": [{"id": "one"}, {"id": "two"}],
                "success": True,
            }
        ],
        "success": True,
    }
    assert store.extract_d1_query_rows(response) == [{"id": "one"}, {"id": "two"}]


def test_d1_database_uses_query_and_batch_api():
    calls = []

    class QueryAPI:
        def query(self, **kwargs):
            calls.append(kwargs)
            if "batch" in kwargs:
                return {
                    "result": [
                        {"results": [], "success": True},
                        {"results": [], "success": True},
                    ]
                }
            return {"result": [{"results": [{"value": 7}], "success": True}]}

    database = store.D1Database("account", "token", "database")
    database._client = SimpleNamespace(
        d1=SimpleNamespace(database=QueryAPI()),
        close=lambda: None,
    )

    assert database.query("SELECT ?", [7]) == [{"value": 7}]
    assert database.batch([("SELECT 1", []), ("SELECT 2", [])]) == [[], []]
    assert calls[0]["account_id"] == "account"
    assert calls[0]["database_id"] == "database"
    assert calls[1]["batch"] == [
        {"sql": "SELECT 1", "params": []},
        {"sql": "SELECT 2", "params": []},
    ]


def test_missing_d1_configuration_fails_without_network(monkeypatch):
    for key in (
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_D1_DATABASE_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    database = store.D1Database.from_env()
    with pytest.raises(store.D1StoreError, match="Cloudflare D1 is not configured"):
        database.query("SELECT 1")
