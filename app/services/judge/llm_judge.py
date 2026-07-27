"""
LLM Judge - Layer 4
Evidence-grounded fact verification using an LLM.
Fully Async with strict `gpt-4o-mini` enforcement for <1s latency.
"""

import json
import re
from typing import Optional
from openai import AsyncOpenAI
from app.core.logging import get_logger
from app.core.config import get_settings
from app.models.response import JudgeResponse

logger = get_logger(__name__)

class LLMJudge:
    """
    Uses an LLM to verify answers against evidence via async calls.
    Enforces gpt-4o-mini for maximum speed.
    """

    def __init__(self):
        """Initialize judge with AsyncOpenAI client."""
        settings = get_settings()
        self.api_key = settings.llm_api_key
        self.provider = settings.llm_provider
        
        # Use configured model from settings (accuracy trumps speed)
        self.model = settings.llm_model or "gpt-4o"
        self.client = None
        self.anthropic_client = None

        if not self.api_key or self.api_key in ("your_llm_api_key_here", ""):
            logger.warning("LLM API key not configured")
            return

        try:
            base_url = settings.llm_api_base or None
            if settings.llm_provider == "groq":
                base_url = "https://api.groq.com/openai/v1"
                if not settings.llm_model:
                    self.model = "llama-3.3-70b-versatile"
            elif settings.llm_provider == "grok":
                base_url = "https://api.x.ai/v1"
            elif settings.llm_provider == "gemini":
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
                if not settings.llm_model:
                    self.model = "gemini-2.0-flash"
            elif settings.llm_provider == "anthropic":
                # Claude uses its native SDK, not the OpenAI-compatible endpoint
                try:
                    from anthropic import AsyncAnthropic
                    self.anthropic_client = AsyncAnthropic(api_key=self.api_key)
                    if not settings.llm_model:
                        self.model = "claude-sonnet-4-20250514"
                    logger.info(f"Initialized Anthropic client with model: {self.model} (provider: anthropic)")
                    return  # Skip OpenAI client creation
                except ImportError:
                    logger.error("anthropic package not installed. Run: pip install anthropic")
                    return
                
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=base_url)
            logger.info(f"Initialized Async Judge with model: {self.model} (provider: {settings.llm_provider})")

        except Exception as e:
            logger.error(f"Failed to initialize Async LLM client: {e}", exc_info=True)
            self.client = None

    @staticmethod
    def build_judge_prompt(question: str, answer: str, evidence: str) -> str:
        """
        Build the judge prompt for evidence-grounded evaluation.
        Returns a continuous 0-100 score based purely on factual alignment.
        """
        if not evidence or evidence.strip() == "":
            evidence = "No external evidence was retrieved for this claim."

        prompt = f"""You are a strict factual fact-verification judge.
Evaluate the AI's answer against the retrieved evidence and your own knowledge.
Return exactly this JSON:
{{
    "score": <integer 0-100>,
    "verdict": "<verified, likely_hallucination, or unverifiable>",
    "explanation": "<1-2 sentences explaining what facts support or contradict the answer>"
}}

SCORING PHILOSOPHY:
Score based purely on how well the answer aligns with verified facts and evidence.
Use the full 0-100 range. Do not cluster at fixed values like 0, 50, or 100.

HIGH SCORES (roughly 70-100) = "verified"
  The answer is factually correct and well-supported.
  The closer the answer is to being completely, precisely correct, the higher the score.
  A perfect, explicitly confirmed answer scores near 100.
  A mostly correct answer with minor imprecision or informal phrasing scores in the 70s-80s.
  A broadly correct answer that oversimplifies or is only partially accurate scores in the low 70s.

MIDDLE SCORES (roughly 40-60) = "unverifiable"
  Use this range ONLY when the claim genuinely cannot be confirmed or denied —
  not because evidence is missing, but because the claim is inherently ambiguous,
  subjective, or concerns something that is truly unknown.
  Do NOT use this as a default or safe fallback. It should be rare.

LOW SCORES (roughly 0-39) = "likely_hallucination"
  The answer is factually wrong, contradicted by evidence or established knowledge.
  The severity of wrongness determines how low:
  - Slightly wrong (close but off) → upper end of this range
  - Clearly and significantly wrong → middle of this range
  - Completely fabricated or directly contradicted → near 0

KEY PRINCIPLES:
- A claim that is checkably WRONG must score below 40, regardless of how close it is to the truth.
- A claim that is correct but imprecise or oversimplified should score lower than a precisely correct one.
- Sparse evidence alone is not a reason to score in the middle. Reason about the claim itself.
- If the answer is detailed, internally consistent, and aligns with known facts, score it accordingly.
- Be consistent: the same type and degree of accuracy should always yield a similar score.

QUESTION: {question}
ANSWER: {answer}
EVIDENCE: {evidence}"""

        return prompt


    async def _call_openai(self, prompt: str, max_tokens: int = 400) -> str:
        """Call async LLM API with accuracy-first settings."""
        # NOTE: response_format json_object is NOT used here because
        # Gemini's OpenAI-compat endpoint does not support it and will
        # raise an error that silently falls back to score 50.
        # The prompt already instructs the LLM to return JSON.
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a fact-checking JSON agent. Always return valid JSON with keys: score, verdict, explanation."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    async def _call_anthropic(self, prompt: str, max_tokens: int = 400) -> str:
        """Call Anthropic Claude API."""
        response = await self.anthropic_client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": prompt},
            ],
            system="You are a fact-checking JSON agent. Always return valid JSON with keys: score, verdict, explanation.",
            temperature=0.0,
        )
        return response.content[0].text

    def _parse_judge_response(self, raw_text: str) -> JudgeResponse:
        """Parse LLM response text into JudgeResponse."""
        try:
            # Strip markdown code fences if any
            cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw_text.strip(), flags=re.MULTILINE).strip()
            
            # Try to load the entire cleaned string first
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                # Fallback to finding the first JSON object
                json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                if not json_match:
                    logger.error(f"No JSON object found in LLM response: {raw_text[:200]}")
                    return self._heuristic_judge("unknown", "unknown", "unknown")
                data = json.loads(json_match.group(0))

            score = int(data.get("score", 50))

            # Clamp to valid range
            score = max(0, min(100, score))

            # Validate/infer verdict from score
            verdict = data.get("verdict", "")
            if verdict not in ("verified", "likely_hallucination", "unverifiable"):
                if score >= 70:
                    verdict = "verified"
                elif score >= 40:
                    verdict = "unverifiable"
                else:
                    verdict = "likely_hallucination"

            logger.info(f"Judge parsed: score={score}, verdict={verdict}")
            return JudgeResponse(
                score=score,
                verdict=verdict,
                explanation=data.get("explanation", "No explanation provided."),
                flag=score < 60,
            )
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e} | raw: {raw_text[:300]}")
            return self._heuristic_judge("unknown", "unknown", "unknown")

    @staticmethod
    def _heuristic_judge(question: str, answer: str, evidence: str) -> JudgeResponse:
        """Fallback returning 50 Neutral."""
        return JudgeResponse(
            score=50,
            verdict="unverifiable",
            explanation="Service unavailable. Could not verify.",
            flag=False,
        )

    def _early_exit_check(self, answer: str, evidence: str) -> Optional[JudgeResponse]:
        """
        Only exit early if the LLM client is unavailable.
        Never return 50 just because evidence is empty — the LLM can still
        use its own knowledge to verify/contradict the answer.
        """
        # No early exit based on empty evidence anymore.
        # The LLM judge will handle the no-evidence case in its prompt.
        return None

    async def judge(self, question: str, answer: str, evidence: str) -> JudgeResponse:
        """
        Judge the answer based on evidence asynchronously.
        """
        # 1. Early Exit Contradiction/Empty Check
        early_exit = self._early_exit_check(answer, evidence)
        if early_exit:
            return early_exit

        if not self.client and not self.anthropic_client:
            return self._heuristic_judge(question, answer, evidence)

        prompt = self.build_judge_prompt(question, answer, evidence)
        try:
            if self.anthropic_client:
                raw_response = await self._call_anthropic(prompt)
            else:
                raw_response = await self._call_openai(prompt)
            logger.info(f"LLM raw response: {raw_response[:300]}")
            return self._parse_judge_response(raw_response)
        except Exception as e:
            # Log the full error so we can see what's actually failing
            logger.error(f"Async LLM judge failed: {type(e).__name__}: {e}", exc_info=True)
            return self._heuristic_judge(question, answer, evidence)

    async def extract_triplets(self, answer: str) -> list[dict]:
        """
        Extract Atomic Knowledge Triplets asynchronously using optimized prompt.
        """
        if not self.client and not self.anthropic_client:
            return []

        prompt = f"""Extract verifiable "Atomic Knowledge Triplets" from this text.
Return STRICTLY a JSON list of objects: [{{"subject": "X", "predicate": "Y", "object": "Z"}}]
Ignore opinions. Split complex facts.
Text: "{answer}"
"""
        logger.info(f"Extracting triplets via {self.model}")
        try:
            if self.anthropic_client:
                raw_response = await self._call_anthropic(prompt)
            else:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=250
                )
                raw_response = response.choices[0].message.content
            
            # Simple list parser
            json_match = re.search(r'\[.*\]', raw_response, re.DOTALL)
            if json_match:
                triplets = json.loads(json_match.group(0))
                if isinstance(triplets, list):
                    return triplets
            return []
        except Exception as e:
            logger.error(f"Async Triplet extraction failed: {e}")
            return []

    async def judge_per_claim(
        self,
        question: str,
        answer: str,
        evidence: str,
        claims: list[str],
    ) -> list[dict]:
        """
        Evaluate each claim individually for fine-grained per-claim scoring.

        Sends a single LLM call that evaluates all claims at once and returns
        a per-claim breakdown with scores, verdicts, and text-position mapping.

        Args:
            question: Original question asked to the AI.
            answer:   Full AI-generated answer text.
            evidence: Aggregated evidence string from retrieval layer.
            claims:   List of extracted claim strings to evaluate.

        Returns:
            List of dicts, one per claim, with keys: claim_text, score,
            verdict, explanation, source_text, start_index, end_index.
            Returns empty list on any failure (non-breaking).
        """
        if (not self.client and not self.anthropic_client) or not claims:
            return []

        claims_text = "\n".join([f"{i+1}. {c}" for i, c in enumerate(claims)])

        prompt = f"""You are a strict factual fact-verification judge.
Evaluate EACH claim individually against the evidence.
Return a JSON array with one object per claim:
[
  {{
    "claim_index": <0-based index>,
    "claim_text": "<the claim>",
    "score": <integer 0-100>,
    "verdict": "<verified, likely_hallucination, or unverifiable>",
    "explanation": "<1 sentence explaining your reasoning for THIS specific claim>"
  }}
]

SCORING: Same rules as single-claim scoring.
- 70-100 = "verified" (factually correct)
- 40-69 = "unverifiable" (ambiguous or unknown)
- 0-39 = "likely_hallucination" (factually wrong)

QUESTION: {question}
FULL ANSWER: {answer}
CLAIMS TO EVALUATE:
{claims_text}
EVIDENCE: {evidence if evidence else 'No external evidence was retrieved.'}"""

        try:
            # Per-claim responses are JSON arrays, need more tokens than single-claim
            if self.anthropic_client:
                raw_response = await self._call_anthropic(prompt, max_tokens=800)
            else:
                raw_response = await self._call_openai(prompt, max_tokens=800)

            logger.info(f"Per-claim raw response: {raw_response[:300]}")

            # Parse JSON array from response
            cleaned = re.sub(
                r'^```(?:json)?\s*|\s*```$', '', raw_response.strip(),
                flags=re.MULTILINE,
            ).strip()
            try:
                results = json.loads(cleaned)
            except json.JSONDecodeError:
                json_match = re.search(r'\[.*\]', cleaned, re.DOTALL)
                if not json_match:
                    logger.error("No JSON array found in per-claim response")
                    return []
                results = json.loads(json_match.group(0))

            if not isinstance(results, list):
                return []

            # Map results back to answer text positions
            per_claim_results = []
            for item in results:
                score = max(0, min(100, int(item.get("score", 50))))

                # Map judge verdict to user-facing verdict
                if score >= 70:
                    verdict = "accurate"
                elif score >= 40:
                    verdict = "uncertain"
                else:
                    verdict = "hallucination"

                claim_text = item.get("claim_text", "")

                # Find the claim's position in the original answer
                start_idx = -1
                end_idx = -1
                source_text = ""

                if claim_text:
                    # Try to find the source sentence containing this claim
                    for sentence in re.split(r'(?<=[.!?])\s+', answer):
                        if claim_text.lower()[:30] in sentence.lower():
                            source_text = sentence.strip()
                            sent_start = answer.find(sentence)
                            if sent_start >= 0:
                                start_idx = sent_start
                                end_idx = sent_start + len(sentence)
                            break

                    # Fallback: direct substring match
                    if start_idx < 0:
                        direct = answer.lower().find(claim_text.lower()[:50])
                        if direct >= 0:
                            start_idx = direct
                            end_idx = direct + len(claim_text)

                per_claim_results.append({
                    "claim_text": claim_text,
                    "score": score,
                    "verdict": verdict,
                    "explanation": item.get("explanation", "No explanation provided."),
                    "source_text": source_text,
                    "start_index": start_idx,
                    "end_index": end_idx,
                })

            logger.info(f"Per-claim judging complete: {len(per_claim_results)} claims scored")
            return per_claim_results

        except Exception as e:
            logger.error(f"Per-claim judging failed: {e}", exc_info=True)
            return []
