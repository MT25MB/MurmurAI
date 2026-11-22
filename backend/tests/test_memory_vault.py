"""Remembered facts are filtered for private data and user-editable."""

from __future__ import annotations

import json

from memory import PRIVATE_RE, MemoryVault


def test_private_patterns_detected():
    samples = [
        "my password is hunter2",
        "card number 4111 1111 1111 1111",
        "email me at alice@example.com",
        "api key sk-abcdefghijklmnop",
        "my phone number is 555-123-4567",
    ]
    for sample in samples:
        assert PRIVATE_RE.search(sample), sample


def test_benign_fact_is_not_private():
    assert not PRIVATE_RE.search("I prefer short spoken replies")


def test_vault_refuses_private_fact(tmp_path):
    vault = MemoryVault(path=tmp_path / "memories.json")
    assert vault.store("my password is hunter2") is None
    assert vault.list() == []
    assert not (tmp_path / "memories.json").exists()


def test_vault_stores_and_persists_benign_fact(tmp_path):
    path = tmp_path / "memories.json"
    vault = MemoryVault(path=path)
    entry = vault.store("I prefer short spoken replies")
    assert entry is not None and entry["text"] == "I prefer short spoken replies"
    assert json.loads(path.read_text(encoding="utf-8"))["facts"]


def test_forget_and_undo_restore(tmp_path):
    vault = MemoryVault(path=tmp_path / "memories.json")
    entry = vault.store("I like tea")
    assert vault.forget(entry["id"]) is True
    assert vault.list() == []
    assert vault.undo() is True
    assert [f["text"] for f in vault.list()] == ["I like tea"]


def test_memory_tools_dispatch_through_os_tools(tmp_path, monkeypatch):
    import tools.memory_tools as memory_tools_module
    from tools.os_tools import dispatch_tool

    vault = MemoryVault(path=tmp_path / "memories.json")
    monkeypatch.setattr(memory_tools_module, "MemoryVault", lambda: vault)

    assert dispatch_tool("remember_fact", {"text": "my password is secret"}, None).startswith("I can't")
    assert dispatch_tool("remember_fact", {"text": "I like tea"}, None) == "Remembered."
    assert "I like tea" in dispatch_tool("list_memories", {}, None)


def test_clear_all_removes_everything(tmp_path):
    vault = MemoryVault(path=tmp_path / "memories.json")
    vault.store("I like tea")
    vault.store("I use Linux")
    assert vault.clear() == 2
    assert vault.list() == []
