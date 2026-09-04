"""
MongoDB document reader tool.

Agents may fetch raw documents (OCR output, audit trails, external feeds)
from MongoDB. Write operations are not exposed. Readable collections are
scoped per agent via ``agent_registry.allowed_mongo_collections`` — the same
fail-closed, declarative-grant posture already proven for the SQL, HTTP, and
event-publishing tools.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domains.intelligence.agent_registry import allowed_mongo_collections


def make_mongo_reader(db: AsyncIOMotorDatabase[Any], agent_id: str) -> Any:
    @tool
    async def read_mongo(
        collection: str, filter: dict[str, Any], limit: int = 20
    ) -> list[dict[str, Any]] | str:
        """Fetch documents from a MongoDB collection.

        Args:
            collection: Collection name (e.g. "ocr_results", "audit_logs").
            filter: MongoDB query filter dict (e.g. {"status": "pending"}).
            limit: Maximum number of documents to return (max 100).
        """
        granted = allowed_mongo_collections(agent_id)
        if collection not in granted:
            return (
                f"Collection '{collection}' is not permitted for agent "
                f"'{agent_id}'. Allowed: {sorted(granted)}"
            )
        limit = min(limit, 100)
        cursor = db[collection].find(filter, {"_id": 0}).limit(limit)
        return await cursor.to_list(length=limit)

    return read_mongo
