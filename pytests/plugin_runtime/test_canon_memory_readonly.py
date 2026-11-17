from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, FrozenSet, List
from unittest.mock import AsyncMock, patch

import ast
import asyncio
import json
import math
import re
import sqlite3
import sys
import threading
import time
import unittest


ROOT = next(path for path in Path(__file__).resolve().parents if (path / "src/services/memory_service.py").exists())
SELECTION = {"package_id": "canon.test", "version": "1", "work": "Example", "character": "Alice", "route": "main", "known_at": 1}


def load_class(path, class_name, methods):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    cls.body = [node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in methods]
    cls.bases = []
    namespace = dict(globals())
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[class_name]


def retrieval_module():
    path = ROOT / "src/A_memorix/core/retrieval/dual_path.py"
    classes = [node for node in ast.parse(path.read_text(encoding="utf-8")).body
               if isinstance(node, ast.ClassDef) and node.name in {"RetrievalScope", "RetrievalStrategy"}]
    namespace = dict(globals())
    exec(compile(ast.Module(body=classes, type_ignores=[]), str(path), "exec"), namespace)
    module = ModuleType("src.A_memorix.core.retrieval")
    module.RetrievalScope = namespace["RetrievalScope"]
    module.RetrievalStrategy = namespace["RetrievalStrategy"]
    return module


class ReadOnlyStore:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE knowledge_packages (package_id TEXT, installation_id TEXT, version TEXT, status TEXT, scope_type TEXT);
            CREATE TABLE knowledge_package_paragraphs (installation_id TEXT, paragraph_hash TEXT);
            CREATE TABLE paragraphs (hash TEXT, content TEXT, source TEXT, metadata TEXT, is_deleted INT, deleted_at REAL, expires_at REAL);
            CREATE TABLE relations (hash TEXT, is_inactive INT);
            CREATE TABLE paragraph_relations (paragraph_hash TEXT, relation_hash TEXT);
            INSERT INTO knowledge_packages VALUES ('canon.test','install-1','1','installed','global');
        """)

    def add(self, identifier, **changes):
        canon = {"approved": True, "version": "1", "work": "Example", "character": "Alice", "route": "main", "known_at": 1, **changes}
        metadata = {"canon": canon, "knowledge_package_id": "canon.test", "knowledge_package_installation_id": "install-1"}
        self.connection.execute("INSERT INTO paragraphs VALUES (?, ?, ?, ?, 0, NULL, NULL)",
                                (identifier, "Current verified " + identifier, "knowledge_pack:canon.test", json.dumps(metadata)))
        self.connection.execute("INSERT INTO knowledge_package_paragraphs VALUES ('install-1', ?)", (identifier,))
        self.connection.commit()

    def query(self, sql, parameters=()):
        if not sql.lstrip().upper().startswith("SELECT"):
            raise AssertionError("mutation attempted")
        return [dict(row) for row in self.connection.execute(sql, parameters)]


class ReadonlyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service_class = load_class(ROOT / "src/services/memory_service.py", "MemoryService",
                                       {"_read_canon_candidates", "search_canon_readonly"})
        self.store = ReadOnlyStore()
        self.addCleanup(self.store.connection.close)
        for identifier, changes in (("allowed", {}), ("future", {"known_at": 5}), ("other-route", {"route": "other"}),
                                    ("draft", {"approved": False}), ("deleted", {}), ("frozen", {}), ("expired", {})):
            self.store.add(identifier, **changes)
        self.store.connection.execute("UPDATE paragraphs SET is_deleted=1 WHERE hash='deleted'")
        self.store.connection.execute("UPDATE paragraphs SET expires_at=1 WHERE hash='expired'")
        self.store.connection.execute("INSERT INTO relations VALUES ('frozen-relation', 1)")
        self.store.connection.execute("INSERT INTO paragraph_relations VALUES ('frozen', 'frozen-relation')")
        self.store.connection.commit()
        registry = ModuleType("src.A_memorix.runtime_registry")
        self.kernel = SimpleNamespace(metadata_store=self.store, retriever=SimpleNamespace(retrieve=AsyncMock(return_value=[])))
        registry.get_runtime_kernel = lambda: self.kernel
        self.modules_patch = patch.dict(sys.modules, {"src.A_memorix.core.retrieval": retrieval_module(),
                                                      "src.A_memorix.runtime_registry": registry})
        self.modules_patch.start()
        self.addCleanup(self.modules_patch.stop)

    async def test_prefilter_scope_only_paragraph_no_mutations(self):
        self.kernel.retriever.retrieve.return_value = [SimpleNamespace(hash_value="allowed", result_type="paragraph", score=0.8)]
        before = self.store.connection.total_changes
        payload = await self.service_class().search_canon_readonly("Bob", **SELECTION)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["hits"][0]["source"], "knowledge_pack:canon.test")
        self.assertEqual(payload["hits"][0]["content"], "Current verified allowed")
        call = self.kernel.retriever.retrieve.call_args.kwargs
        self.assertEqual(call["strategy"].value, "paragraph_only")
        self.assertFalse(call["enable_ppr"])
        self.assertEqual(call["scope"].paragraph_ids, frozenset({"allowed"}))
        self.assertFalse(call["scope"].relation_ids)
        self.assertEqual(before, self.store.connection.total_changes)

    async def test_native_edit_during_embedding_not_returned(self):
        async def retrieve(**kwargs):
            self.store.connection.execute("UPDATE paragraphs SET content='Edited' WHERE hash='allowed'")
            self.store.connection.commit()
            return [SimpleNamespace(hash_value="allowed", result_type="paragraph", score=0.8)]
        self.kernel.retriever.retrieve = retrieve
        self.assertEqual((await self.service_class().search_canon_readonly("Bob", **SELECTION))["hits"], [])

    async def test_multiple_versions_refused(self):
        self.store.connection.execute("INSERT INTO knowledge_packages VALUES ('canon.test','install-2','2','installed','global')")
        self.store.connection.commit()
        with self.assertRaisesRegex(ValueError, "not_uniquely"):
            self.service_class._read_canon_candidates(self.store, SELECTION)

    async def test_uninstalled_history_ignored(self):
        self.store.connection.execute("INSERT INTO knowledge_packages VALUES ('canon.test','old','0','uninstalled','global')")
        self.store.connection.commit()
        self.assertEqual(self.service_class._read_canon_candidates(self.store, SELECTION)["installation_id"], "install-1")

    async def test_query_constraints(self):
        for changes in ({"known_at": True}, {"package_id": "person_fact:user"}, {"limit": 21}):
            with self.assertRaises(ValueError):
                await self.service_class().search_canon_readonly("Bob", **{**SELECTION, **changes})

    async def test_capability_session_lookup_runs_off_event_loop(self):
        capability_class = load_class(ROOT / "src/plugin_runtime/capabilities/data.py", "RuntimeDataCapabilityMixin",
                                      {"_cap_knowledge_search_canon"})
        loop_thread = threading.get_ident()
        lookup_threads = []

        def lookup_session(session_id):
            lookup_threads.append(threading.get_ident())
            self.assertEqual(session_id, "existing-session")
            return SimpleNamespace(session_id=session_id)

        chat_module = ModuleType("src.chat.message_receive.chat_manager")
        chat_module.chat_manager = SimpleNamespace(get_existing_session_by_session_id=lookup_session)
        memory_module = ModuleType("src.services.memory_service")
        search = AsyncMock(return_value={"success": True, "hits": []})
        memory_module.memory_service = SimpleNamespace(search_canon_readonly=search)
        with patch.dict(sys.modules, {chat_module.__name__: chat_module, memory_module.__name__: memory_module}):
            result = await capability_class()._cap_knowledge_search_canon(
                "local.canon-memory", "knowledge.search_canon", {**SELECTION, "query": "Bob", "session_id": "existing-session"},
            )
        self.assertTrue(result["success"])
        self.assertEqual(len(lookup_threads), 1)
        self.assertNotEqual(lookup_threads[0], loop_thread)
        search.assert_awaited_once_with(query="Bob", **SELECTION, limit=20)

    async def test_authenticated_webui_schema(self):
        from pydantic import BaseModel, Field, ValidationError
        path = ROOT / "src/webui/routers/memory.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        model = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CanonSearchRequest")
        namespace = {"BaseModel": BaseModel, "Field": Field}
        exec(compile(ast.Module(body=[model], type_ignores=[]), str(path), "exec"), namespace)
        cls = namespace["CanonSearchRequest"]
        self.assertEqual(cls(query="Bob", **SELECTION).limit, 20)
        for changes in ({"known_at": True}, {"limit": 21}, {"extra": "unexpected"}):
            with self.assertRaises(ValidationError):
                cls(query="Bob", **{**SELECTION, **changes})
        self.assertIn('@router.post("/query/canon")', path.read_text(encoding="utf-8"))
        from fastapi import HTTPException
        from src.host.proxy import BotProxy
        sessions = SimpleNamespace(cookie_name="host", valid=lambda token: token == "valid")
        proxy = BotProxy(SimpleNamespace(), sessions)
        with self.assertRaises(HTTPException) as denied:
            proxy._require_session(SimpleNamespace(cookies={}))
        self.assertEqual(denied.exception.status_code, 401)
        proxy._require_session(SimpleNamespace(cookies={"host": "valid"}))


if __name__ == "__main__":
    unittest.main()
