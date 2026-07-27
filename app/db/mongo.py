"""
MongoDB async database module — app/db/mongo.py

Responsibilities:
  1. Expose ``init_mongo`` / ``close_mongo`` lifecycle helpers that are called
     from main.py's lifespan context manager.
  2. Create the ``user_history`` collection's B-Tree index on ``user_id`` at
     startup so paginated per-user lookups are always O(log n).
  3. Provide a thin ``UserHistoryRepository`` for inserting and querying records
     without scattering Motor calls across the codebase.

Architecture note:
  - The Motor AsyncIOMotorClient is created once and stored on ``app.state.db``
    by the lifespan wiring in main.py.
  - This module does NOT hold a module-level client reference; callers always
    obtain the ``db`` handle from ``request.app.state.db``.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, IndexModel

from app.core.logging import get_logger

logger = get_logger(__name__)

# Collection name — shared constant so nothing is hard-coded elsewhere.
HISTORY_COLLECTION = "user_history"
EVENTS_COLLECTION = "verification_events"

# ── Index definitions ─────────────────────────────────────────────────────────
_HISTORY_INDEXES: list[IndexModel] = [
    IndexModel(
        [("user_id", ASCENDING)],
        name="idx_user_id",
        background=True,   # non-blocking build
    ),
    IndexModel(
        [("user_id", ASCENDING), ("timestamp", -1)],
        name="idx_user_id_timestamp",
        background=True,
    ),
]

_EVENTS_INDEXES: list[IndexModel] = [
    IndexModel(
        [("user_id", ASCENDING)],
        name="idx_events_user_id",
        background=True,
    ),
    IndexModel(
        [("timestamp", -1)],
        name="idx_events_timestamp",
        background=True,
    ),
]


# ── Lifecycle helpers ─────────────────────────────────────────────────────────

async def init_mongo(mongodb_url: str, database_name: str) -> AsyncIOMotorDatabase:
    """
    Connect to MongoDB, build required indexes, and return the database handle.

    Called once from main.py's lifespan startup block.  The returned handle is
    bound to ``app.state.db`` so every request handler can reach it via
    ``request.app.state.db``.

    Args:
        mongodb_url:   Motor-compatible connection URI, e.g.
                       ``mongodb://localhost:27017`` or
                       ``mongodb+srv://…@cluster.mongodb.net``.
        database_name: Target database name (e.g. ``"aimatrix_db"``).

    Returns:
        An ``AsyncIOMotorDatabase`` instance backed by a connection pool.
    """
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        mongodb_url,
        serverSelectionTimeoutMS=5_000,  # fail fast if Mongo is unreachable
    )

    db: AsyncIOMotorDatabase = client[database_name]

    # Verify the connection is live before yielding control back to the lifespan.
    await client.admin.command("ping")
    logger.info(f"MongoDB connected: {mongodb_url!r}  db={database_name!r}")

    # Ensure indexes exist.  ``create_indexes`` is idempotent — safe to call on
    # every startup even if the indexes already exist.
    history_collection = db[HISTORY_COLLECTION]
    await history_collection.create_indexes(_HISTORY_INDEXES)
    logger.info(
        f"MongoDB indexes ensured on '{HISTORY_COLLECTION}': "
        f"{[idx.document['name'] for idx in _HISTORY_INDEXES]}"
    )

    events_collection = db[EVENTS_COLLECTION]
    await events_collection.create_indexes(_EVENTS_INDEXES)
    logger.info(
        f"MongoDB indexes ensured on '{EVENTS_COLLECTION}': "
        f"{[idx.document['name'] for idx in _EVENTS_INDEXES]}"
    )

    return db


async def close_mongo(db: AsyncIOMotorDatabase) -> None:
    """
    Gracefully close the underlying Motor connection pool.

    Args:
        db: The ``AsyncIOMotorDatabase`` handle stored on ``app.state.db``.
    """
    try:
        db.client.close()
        logger.info("MongoDB connection pool closed")
    except Exception as exc:
        logger.warning(f"Error closing MongoDB connection: {exc}")


# ── Repository ────────────────────────────────────────────────────────────────

class UserHistoryRepository:
    """
    Thin async repository for the ``user_history`` collection.

    Instantiate with the database handle from ``app.state.db``::

        repo = UserHistoryRepository(request.app.state.db)
        await repo.insert(record)
        records = await repo.list_for_user(user_id, skip=0, limit=20)
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[HISTORY_COLLECTION]

    async def insert(self, record_dict: dict[str, Any]) -> str:
        """
        Persist a single ``UserHistoryRecord`` document.

        Args:
            record_dict: A plain dictionary produced by
                         ``UserHistoryRecord.to_mongo_doc()``.
                         Must already have UUIDs and datetimes converted
                         to BSON-safe types (str / datetime).

        Returns:
            The inserted document's ``_id`` as a hex string.

        Raises:
            No exceptions propagate — errors are logged and the method
            returns an empty string so background threads exit gracefully.
        """
        try:
            result = await self._col.insert_one(record_dict)
            logger.debug(f"Inserted history record _id={result.inserted_id}")
            return str(result.inserted_id)
        except Exception as exc:
            logger.error(
                f"MongoDB insert failed (non-fatal): {exc}",
                exc_info=True,
            )
            return ""

    async def list_for_user(
        self,
        user_id: str,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Return the most recent history records for a given user.

        Uses the ``idx_user_id_timestamp`` compound index so the query is
        covered entirely within the index, avoiding a collection scan.

        Args:
            user_id: The user's ID (from JWT ``sub`` claim).
            skip:    Number of records to skip (for pagination).
            limit:   Maximum records to return per page.

        Returns:
            List of raw MongoDB documents (dicts), newest first.
        """
        cursor = (
            self._col.find({"user_id": user_id})
            .sort("timestamp", -1)
            .skip(skip)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        for doc in docs:
            if doc and "_id" in doc:
                doc["_id"] = str(doc["_id"])
        return docs
