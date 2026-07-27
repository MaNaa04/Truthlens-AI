"""
Grok Mediator - Layer 3b
Acts as a consensus engine, checking multiple sources of evidence for contradictions.
"""

import json
from dataclasses import dataclass
from typing import Optional
from openai import AsyncOpenAI
from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)

@dataclass
class ConsensusResult:
    adjusted_evidence: str
    confidence: float

class GrokMediator:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.llm_api_key  # Or maybe an explicit grok api key
        
        # If grok key exists use it, else default to the multi-provider key
        grok_key = getattr(settings, 'grok_api_key', self.api_key)
        
        if grok_key and grok_key != "your_llm_api_key_here":
            self.client = AsyncOpenAI(api_key=grok_key, base_url="https://api.x.ai/v1")
        else:
            self.client = None

    async def check_consensus(self, claims: list[str], evidence_map: dict[str, str]) -> ConsensusResult:
        if not self.client:
            logger.warning("Grok client not configured. Skipping consensus engine.")
            adjusted_evidence = "\n\n".join([f"--- {source} ---\n{text}" for source, text in evidence_map.items()])
            return ConsensusResult(adjusted_evidence=adjusted_evidence, confidence=1.0)
            
        claims_text = "\n".join([f"- {c}" for c in claims])
        sources_text = "\n\n".join([f"--- {source} ---\n{text}" for source, text in evidence_map.items()])

        prompt = f"""You are an objective Auditor and Consensus Mediator. Your job is to evaluate if multiple sources of evidence represent a consensus or if they contradict each other regarding a set of claims.
CLAIMS:
{claims_text}

EVIDENCE SOURCES:
{sources_text}

TASK:
1. Compare the information provided by different sources. Focus on finding contradictions.
2. Give higher weight to authoritative domains (.gov, .edu, established knowledge) versus generic search results.
3. If they conflict, define the nature of the conflict.
4. Output your analysis and a confidence score between 0.0 and 1.0.
   - 1.0 = All sources agree fully.
   - 0.5 = Partial agreement or some inconsistencies.
   - 0.0 = Complete contradiction among the sources.

Output STRICT JSON matching this schema:
{{
    "analysis": "<short reasoning on consensus/conflict>",
    "confidence": <float_value>
}}"""

        try:
            response = await self.client.chat.completions.create(
                model="grok-beta",
                messages=[
                    {"role": "system", "content": "You are a factual consensus engine. Always output valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                seed=42,
                max_tokens=400,
            )
            raw_text = response.choices[0].message.content
            
            # Clean up markdown
            clean_text = raw_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
                
            data = json.loads(clean_text)
            confidence = float(data.get("confidence", 1.0))
            analysis = data.get("analysis", "No conflict specified")
            
            # Formulate the adjusted evidence for the final LLM Judge
            # We prefix the evidence with the mediator's insight
            adjusted_evidence = f"[Consensus Engine Insight (Confidence: {confidence:.2f})]: {analysis}\n\nRAW EVIDENCE:\n{sources_text}"
            return ConsensusResult(adjusted_evidence=adjusted_evidence, confidence=confidence)
            
        except Exception as e:
            logger.error(f"Grok Mediator failed: {e}")
            # Fallback
            adjusted = "\n\n".join([f"--- {source} ---\n{text}" for source, text in evidence_map.items()])
            return ConsensusResult(adjusted_evidence=adjusted, confidence=1.0)
