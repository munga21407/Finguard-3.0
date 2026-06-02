"""
MongoDB document reader tool.

Agents may fetch raw documents (OCR output, audit trails, external feeds)
from MongoDB. Write operations are not exposed.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from motor.motor_asyncio import AsyncIOMotorDatabase


def make_mongo_reader(db: AsyncIOMotorDatabase):  # type: ignore[type-arg, return]
    @tool
    async def read_mongo(
        collection: str, filter: dict[str, Any], limit: int = 20
    ) -> list[dict[str, Any]]:
        """Fetch documents from a MongoDB collection.

        Args:
            collection: Collection name (e.g. "ocr_results", "audit_logs").
            filter: MongoDB query filter dict (e.g. {"status": "pending"}).
            limit: Maximum number of documents to return (max 100).
        """
        limit = min(limit, 100)
        cursor = db[collection].find(filter, {"_id": 0}).limit(limit)
        return await cursor.to_list(length=limit)

    return read_mongo
