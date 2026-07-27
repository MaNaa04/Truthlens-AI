"""
Response models for API output formatting.
Layer 5: Response Builder
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Literal


class ClaimResult(BaseModel):
    """Per-claim verification result for fine-grained scoring.
    
    Each extracted claim gets its own score, verdict, and text-position
    mapping so the Chrome Extension can highlight exactly which sentence
    in the AI answer is a hallucination.
    """
    claim_text: str = Field(
        ...,
        description="The extracted claim text that was verified"
    )
    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Per-claim hallucination risk score (0-100)"
    )
    verdict: Literal["accurate", "uncertain", "hallucination"] = Field(
        ...,
        description="Per-claim verdict"
    )
    explanation: str = Field(
        ...,
        description="Why this specific claim received this score"
    )
    source_text: str = Field(
        default="",
        description="Original sentence from the answer this claim maps to"
    )
    start_index: int = Field(
        default=-1,
        description="Character start offset in the original answer (-1 if unmapped)"
    )
    end_index: int = Field(
        default=-1,
        description="Character end offset in the original answer (-1 if unmapped)"
    )


class JudgeResponse(BaseModel):
    """
    Judgment output from the LLM Judge.
    
    Attributes:
        score: Hallucination risk score (0-100)
        verdict: Classification of the answer
        explanation: Evidence-grounded reasoning
        flag: Whether the response needs attention
    """
    score: int = Field(
        ..., 
        ge=0, 
        le=100,
        description="Hallucination risk score"
    )
    verdict: Literal["verified", "likely_hallucination", "unverifiable"] = Field(
        ...,
        description="Classification verdict"
    )
    explanation: str = Field(
        ...,
        description="1-2 sentence explanation grounded in evidence"
    )
    flag: bool = Field(
        ...,
        description="True if score < 60 (needs attention)"
    )


class VerifyResponse(BaseModel):
    """
    Complete response from the /verify endpoint.
    
    Maps score ranges to user-friendly verdicts:
    - 75-100: ✅ Likely accurate
    - 40-74: ⚠️ Uncertain, verify
    - 0-39: 🚩 High hallucination risk
    """
    score: int = Field(
        ..., 
        ge=0, 
        le=100,
        description="Hallucination risk score (0-100)"
    )
    verdict: Literal["accurate", "uncertain", "hallucination"] = Field(
        ...,
        description="User-friendly verdict"
    )
    explanation: str = Field(
        ...,
        description="Explanation of the verdict"
    )
    flag: bool = Field(
        ...,
        description="Red flag if high hallucination risk"
    )
    sources_used: Optional[list[str]] = Field(
        default=None,
        description="Which sources provided evidence (Wikipedia, SerpAPI, etc.)"
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Unique request ID for tracing and debugging"
    )
    processing_time_ms: Optional[int] = Field(
        default=None,
        description="Total pipeline processing time in milliseconds"
    )
    cache_hit: bool = Field(
        default=False,
        description=(
            "True if this result was served from the Redis cache (no LLM call was made). "
            "False if the full pipeline ran and a fresh LLM judgment was produced. "
            "Use this field to filter out cached results when benchmarking LLM quality."
        )
    )
    debug: Optional[dict] = Field(
        default=None,
        description="Debug info detailing exactly what evidence snippets were retrieved"
    )
    claim_results: Optional[list[ClaimResult]] = Field(
        default=None,
        description=(
            "Per-claim fine-grained scoring results. Each claim gets its own "
            "score, verdict, and character-offset mapping to the original answer "
            "so the Chrome Extension can highlight hallucinated sentences."
        )
    )
    provider: Optional[str] = Field(
        default=None,
        description=(
            "LLM provider used for judging (gemini, openai, groq, grok, anthropic). "
            "Use this alongside cache_hit=false to benchmark specific providers."
        )
    )
    model: Optional[str] = Field(
        default=None,
        description="Specific LLM model used (e.g. gemini-2.0-flash, claude-sonnet-4-20250514)"
    )
    
    @staticmethod
    def from_judge_response(
        judge_resp: JudgeResponse,
        sources: Optional[list[str]] = None,
        request_id: Optional[str] = None,
        processing_time_ms: Optional[int] = None,
        debug: Optional[dict] = None,
        cache_hit: bool = False,
        claim_results: Optional[list["ClaimResult"]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> "VerifyResponse":
        """
        Convert LLM Judge response to user-facing response.
        
        Args:
            judge_resp: Raw judge response
            sources: Sources used for evidence retrieval
            request_id: Unique request ID for tracing
            processing_time_ms: Pipeline processing time
            debug: Detailed evidence snippets retrieved
            claim_results: Per-claim fine-grained scoring results
            
        Returns:
            Formatted response with user-friendly verdict
        """
        # Map judge score to user-friendly verdict
        # 70+  = accurate (verified), 40-69 = uncertain (unverifiable), <40 = hallucination
        if judge_resp.score >= 70:
            verdict = "accurate"
        elif judge_resp.score >= 40:
            verdict = "uncertain"
        else:
            verdict = "hallucination"
        
        return VerifyResponse(
            score=judge_resp.score,
            verdict=verdict,
            explanation=judge_resp.explanation,
            flag=judge_resp.flag,
            sources_used=sources,
            request_id=request_id,
            processing_time_ms=processing_time_ms,
            cache_hit=cache_hit,
            debug=debug,
            claim_results=claim_results,
            provider=provider,
            model=model,
        )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "score": 85,
                "verdict": "accurate",
                "explanation": "Verified against Wikipedia. Paris is indeed the capital of France.",
                "flag": False,
                "sources_used": ["Wikipedia"],
                "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "processing_time_ms": 1250,
                "cache_hit": False,
                "provider": "gemini",
                "model": "gemini-2.0-flash",
                "claim_results": [
                    {
                        "claim_text": "Paris is the capital of France",
                        "score": 95,
                        "verdict": "accurate",
                        "explanation": "Confirmed by multiple sources.",
                        "source_text": "Paris is indeed the capital of France.",
                        "start_index": 0,
                        "end_index": 39,
                    }
                ],
            }
        }
    )
