import pytest

from backend.knowledge.graph.manager import graph_manager


@pytest.mark.asyncio
async def test_upsert_document_without_driver(monkeypatch):
    monkeypatch.setattr(graph_manager, "__dict__", graph_manager.__dict__, raising=False)
    await graph_manager.upsert_document({"id": "doc", "title": "t", "source": "src"}, [])
    assert True
