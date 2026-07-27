"""
Per-user audit history schema — app/models/history.py

``UserHistoryRecord`` is the canonical Pydantic v2 model that maps a single
verification pipeline result to a MongoDB document owned by one user.

Design rationale
----------------
* ``user_id`` comes from the JWT ``sub`` claim — the only identifier we trust.
* ``request_id`` is a UUID so audit records can be correlated with pipeline
  logs without exposing internal DB ids to the Chrome Extension.
* ``score`` is strictly bounded [0, 100] with Pydantic's ``ge``/``le``
  constraints — invalid scores are rejected before any DB write.
* ``cache_hit`` tells the Chrome Extension whether the LLM was actually invoked;
  useful for filtering cached results in usage analytics.
* ``timestamp`` defaults to UTC now so insert callers don't have to supply it.

Redis cache key contract (DO NOT CHANGE):
  The Redis verify cache key is ``verify_{SHA-256(question + answer)}``.
  It is intentionally GLOBAL (not scoped to user_id) to maximise cache-hit
  rates across all users querying the same content.  ``cache_hit`` in this
  model simply *records* whether that global key was hit for a given request;
  it does not alter the key format.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class UserHistoryRecord(BaseModel):
    """
    Immutable audit record for one verification request made by a user.

    Fields
    ------
    user_id     : Extracted from the JWT ``sub`` claim by the auth dependency.
    request_id  : UUID sourced directly from the pipeline's ``VerifyResponse.request_id``.
    question    : The original question text submitted by the user.
    score       : Hallucination risk score, strictly in [0, 100].
    verdict     : Human-readable verdict string from the pipeline response.
    cache_hit   : True when the global Redis cache served the result (no LLM call).
    timestamp   : UTC timestamp of when the record was created; defaults to now.
    """

    model_config = {"frozen": True}  # records are append-only; never mutated

    user_id: str = Field(
        ...,
        min_length=1,
        description="Provider user ID extracted from the JWT 'sub' claim",
    )
    request_id: UUID = Field(
        default_factory=uuid4,
        description="Pipeline request UUID for cross-referencing pipeline logs",
    )
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Original question text submitted by the user",
    )
    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Hallucination risk score strictly in [0, 100]",
    )
    verdict: str = Field(
        ...,
        min_length=1,
        description="Verdict label from the pipeline (e.g. 'accurate', 'hallucination')",
    )
    cache_hit: bool = Field(
        default=False,
        description=(
            "True when this result was served from the global Redis cache "
            "(no LLM inference was performed for this request)."
        ),
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of record creation",
    )

    # ── Validators ─────────────────────────────────────────────────────────────

    @field_validator("user_id")
    @classmethod
    def user_id_must_not_be_whitespace(cls, v: str) -> str:
        """Reject blank / whitespace-only user_id strings."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("user_id must not be blank or whitespace-only")
        return stripped

    @field_validator("question")
    @classmethod
    def question_strip(cls, v: str) -> str:
        """Normalise question whitespace consistent with VerifyRequest."""
        return v.strip()

    # ── Serialisation helpers ──────────────────────────────────────────────────

    def to_mongo_doc(self) -> dict:
        """
        Serialise the record to a plain dict suitable for Motor ``insert_one``.

        UUID and datetime fields are converted to types MongoDB handles natively.
        """
        data = self.model_dump()
        data["request_id"] = str(data["request_id"])   # store as string in Mongo
        return data
