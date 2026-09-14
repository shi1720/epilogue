"""Small transactional document store for durable demo accounts and spending limits.

Firestore is used on Cloud Run. Local development uses SQLite with the same
transaction contract, so isolation and concurrency tests exercise real storage.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path


class LocalStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS documents (key TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.conn.commit()
        self.lock = threading.RLock()

    def get(self, key):
        with self.lock:
            row = self.conn.execute("SELECT data FROM documents WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else {}

    def transact(self, keys, transform):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                values = [self.get(key) for key in keys]
                result = transform(values)
                for key, value in zip(keys, values, strict=True):
                    self.conn.execute("INSERT OR REPLACE INTO documents VALUES (?, ?)", (key, json.dumps(value)))
                self.conn.commit()
                return result
            except BaseException:
                self.conn.rollback()
                raise

    def put(self, key, value):
        self.transact([key], lambda rows: rows[0].update(value))


@lru_cache(maxsize=1)
def firebase_app():
    import firebase_admin
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app()


class FirestoreStore:
    def __init__(self):
        from firebase_admin import firestore
        self.db = firestore.client(app=firebase_app(), database_id=os.environ.get("EPILOGUE_FIRESTORE_DATABASE", "epilogue"))
        self.collection = self.db.collection("epilogue_accounts")

    def get(self, key):
        return self.collection.document(key).get().to_dict() or {}

    def transact(self, keys, transform):
        from google.cloud import firestore
        refs = [self.collection.document(key) for key in keys]

        @firestore.transactional
        def update(transaction):
            values = [ref.get(transaction=transaction).to_dict() or {} for ref in refs]
            result = transform(values)
            for ref, value in zip(refs, values, strict=True):
                transaction.set(ref, value)
            return result

        return update(self.db.transaction())

    def put(self, key, value):
        self.collection.document(key).set(value, merge=True)

    def records(self, uid, generation):
        return FirestoreRecords(self.collection.document(uid).collection("ledgers").document(generation))


class FirestoreRecords:
    """Each ledger row is its own document; audit history never hits a 1 MiB snapshot limit."""
    def __init__(self, ref):
        self.ref = ref.collection("records")

    def all(self):
        return sorted((doc.to_dict() for doc in self.ref.stream()), key=lambda row: row.get("order", 0))

    def put(self, table, key, row):
        import hashlib
        doc_id = hashlib.sha256(f"{table}:{key}".encode()).hexdigest()
        self.ref.document(doc_id).set({"table": table, "row": row, "order": time.time_ns()})
