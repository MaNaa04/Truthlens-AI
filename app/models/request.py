"""
Request models for API validation.
Layer 1: API Gateway input validation
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict


class VerifyRequest(BaseModel):
    """
    Request payload for the /verify endpoint.
    
    Attributes:
        question: The original question asked to the AI
        answer: The AI-generated answer to verify
    """
    question: str = Field(
        ..., 
        min_length=5, 
        max_length=2000,
        description="Original question (5-2000 characters)"
    )
    answer: str = Field(
        ..., 
        min_length=5, 
        max_length=5000,
        description="AI-generated answer (5-5000 characters)"
    )
    
    @field_validator('question', 'answer')
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip leading/trailing whitespace."""
        return v.strip()
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "What is the capital of France?",
                "answer": "The capital of France is Paris, located along the Seine River."
            }
        }
    )
