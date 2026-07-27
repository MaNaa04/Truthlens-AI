"""
Query Preprocessor - Layer 2
Extracts key factual claims from answers and determines query type.
"""

import re
import time
from typing import Literal
from dataclasses import dataclass
from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)

QueryType = Literal[
    "encyclopedic", 
    "recent_event", 
    "numeric_statistical", 
    "opinion_subjective",
    "medical_health",
    "finance",
    "programming"
]


@dataclass
class ProcessedQuery:
    """Result of query preprocessing."""
    original_question: str
    original_answer: str
    extracted_claims: list[str]
    query_type: QueryType
    # Analytics metadata
    sentences_found: int = 0
    factual_sentences: int = 0
    preprocessing_time_ms: int = 0


# ── Patterns for query type detection ─────────────────────────────

RECENT_EVENT_KEYWORDS = [
    "today", "yesterday", "tomorrow", "latest", "recent", "recently",
    "breaking", "news", "update", "current", "currently", "now",
    "this week", "this month", "this year", "last week", "last month",
    "2024", "2025", "2026",
]

NUMERIC_PATTERNS = [
    r"\bhow many\b", r"\bhow much\b", r"\bwhat percentage\b",
    r"\bwhat number\b", r"\bhow often\b", r"\bwhat is the rate\b",
    r"\bhow long\b", r"\bhow old\b", r"\bhow far\b", r"\bhow tall\b",
    r"\bwhat is the population\b", r"\bhow fast\b",
]

OPINION_PATTERNS = [
    r"\bshould\b", r"\bdo you think\b", r"\bis it worth\b",
    r"\bwhat do you recommend\b", r"\bwhat's better\b", r"\bwhat is better\b",
    r"\bis it good\b", r"\bis it bad\b", r"\bwould you\b",
    r"\bwhat's your opinion\b", r"\bwhat is your opinion\b",
    r"\bcan you suggest\b", r"\bwhat are the pros\b",
]

MEDICAL_PATTERNS = [
    r"\bcure\b", r"\btreatment\b", r"\bmedicine\b", r"\bmedical\b",
    r"\bsymptom\b", r"\bdisease\b", r"\bdoctor\b", r"\btherapy\b",
    r"\bhealth\b", r"\bcancer\b", r"\bvirus\b", r"\bpill\b", r"\bside effect\b"
]

FINANCE_PATTERNS = [
    r"\bstock\b", r"\bprice of\b", r"\bmarket\b", r"\bshares\b",
    r"\bfinance\b", r"\binvestment\b", r"\binterest rate\b",
    r"\bdividend\b", r"\bwall street\b", r"\beconomy\b"
]

PROGRAMMING_PATTERNS = [
    r"\bcode\b", r"\Bpython\b", r"\bjavascript\b", r"\bc\+\+\b", r"\bjava\b",
    r"\bfunction\b", r"\bapi\b", r"\breact\b", r"\bnode\b", r"\bdatabase\b",
    r"\bbackend\b", r"\bfrontend\b", r"\balgorithm\b", r"\bsql\b"
]

# ── Patterns for filtering non-factual sentences ──────────────────

FILLER_PATTERNS = [
    r"^(in summary|in conclusion|overall|to summarize|in short)\b",
    r"^(i hope|i think|i believe|in my opinion)\b",
    r"^(let me know|feel free|if you have)\b",
    r"^(here is|here are|here's)\b",
    r"^(note that|please note|keep in mind)\b",
]

LEADING_CONNECTORS = re.compile(
    r"^(also|however|moreover|furthermore|additionally|in addition|"
    r"meanwhile|nevertheless|consequently|therefore|thus|hence|"
    r"for example|for instance|specifically|in fact|actually)[,\s]+",
    re.IGNORECASE,
)


class QueryPreprocessor:
    """
    Extracts key factual claims from AI responses and identifies query type.

    This layer helps route queries to appropriate retrievers:
    - encyclopedic → Wikipedia (historical, biographical, scientific)
    - recent_event → SerpAPI (news, current events)
    - numeric_statistical → Either (statistics, data)
    - opinion_subjective → Low priority (harder to verify)
    """

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """
        Split text into sentences using regex.
        Handles common abbreviations (Dr., Mr., U.S., etc.).

        Args:
            text: Input text

        Returns:
            List of sentence strings
        """
        # Protect common abbreviations from being split
        protected = text
        abbreviations = ["Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "Jr.", "Sr.",
                         "U.S.", "U.K.", "U.N.", "e.g.", "i.e.", "etc.",
                         "vs.", "St.", "Mt.", "ft.", "Vol.", "No."]
        for abbr in abbreviations:
            protected = protected.replace(abbr, abbr.replace(".", "###DOT###"))

        # Split on sentence-ending punctuation followed by space or end
        sentences = re.split(r'(?<=[.!?])\s+', protected)

        # Restore abbreviation dots and clean up
        sentences = [s.replace("###DOT###", ".").strip() for s in sentences]
        return [s for s in sentences if s]

    @staticmethod
    def _is_factual_sentence(sentence: str) -> bool:
        """
        Determine if a sentence likely contains a verifiable factual claim.

        Filters out questions, very short text, opinions, and filler phrases.

        Args:
            sentence: A single sentence

        Returns:
            True if the sentence appears to be a factual claim
        """
        clean = sentence.strip()

        # Too short to be a meaningful claim
        if len(clean) < 15:
            return False

        # Questions are not claims
        if clean.endswith("?"):
            return False

        # Filter filler/opinion phrases
        lower = clean.lower()
        for pattern in FILLER_PATTERNS:
            if re.match(pattern, lower):
                return False

        return True

    @staticmethod
    def _clean_claim(sentence: str) -> str:
        """
        Clean a sentence into a concise search query.

        Strips leading connectors, trailing punctuation, and extra whitespace.

        Args:
            sentence: A factual sentence

        Returns:
            Cleaned search query string
        """
        claim = sentence.strip()

        # Remove leading connectors (e.g., "However, ...", "Also, ...")
        claim = LEADING_CONNECTORS.sub("", claim)

        # Remove trailing punctuation
        claim = claim.rstrip(".!;:")

        # Normalize whitespace
        claim = re.sub(r'\s+', ' ', claim).strip()

        return claim

    @staticmethod
    async def extract_claims_async(answer: str, max_claims: int = 3) -> list[str]:
        """
        Extract key factual claims from the answer asynchronously.

        Uses LLM-based Atomic Knowledge Triplet extraction first.
        If it fails, falls back to heuristic approach.

        Args:
            answer: The AI-generated answer
            max_claims: Maximum number of claims to extract

        Returns:
            List of extracted claims as search queries
        """
        settings = get_settings()
        max_claims = min(max_claims, settings.max_claims_per_request)

        logger.info(f"Extracting claims from answer (max: {max_claims})")

        if not answer or len(answer.strip()) < 10:
            logger.warning("Answer too short for claim extraction")
            return []

        # Step 0: Try LLM-based Triplets Extraction
        try:
            from app.services.judge.llm_judge import LLMJudge
            judge = LLMJudge()
            triplets = await judge.extract_triplets(answer)
            if triplets:
                claims = []
                for t in triplets:
                    subject = t.get("subject", "")
                    predicate = t.get("predicate", "")
                    obj = t.get("object", "")
                    if subject and predicate and obj:
                        claims.append(f"{subject} {predicate} {obj}")
                
                if claims:
                    # Return top claims
                    result = claims[:max_claims]
                    logger.info(f"Extracted {len(result)} claims via LLM Triplets")
                    return result
        except Exception as e:
            logger.error(f"LLM Triplet extraction failed: {e}, falling back to heuristic")

        # Fallback Heuristic Approach
        # Step 1: Split into sentences
        sentences = QueryPreprocessor._split_sentences(answer)
        logger.info(f"Fallback: Split answer into {len(sentences)} sentences")

        # Step 2: Filter for factual sentences
        factual = [s for s in sentences if QueryPreprocessor._is_factual_sentence(s)]
        logger.info(f"Fallback: Found {len(factual)} factual sentences")

        # Step 3: Clean into search queries
        claims = [QueryPreprocessor._clean_claim(s) for s in factual]

        # Remove empty claims after cleaning
        claims = [c for c in claims if len(c) >= 10]

        # Step 4: Return top claims (prioritize longer, more specific sentences)
        claims.sort(key=len, reverse=True)
        result = claims[:max_claims]

        logger.info(f"Extracted {len(result)} claims via heuristic fallback")
        return result

    @staticmethod
    def determine_query_type(question: str) -> QueryType:
        """
        Determine the type of query for routing to appropriate retrievers.

        Uses keyword pattern matching:
        - recent_event: time-related keywords, year references
        - numeric_statistical: "how many", "how much", "percentage"
        - opinion_subjective: "should", "recommend", "better"
        - encyclopedic: default fallback for factual questions

        Args:
            question: The original question

        Returns:
            Query type classification
        """
        logger.info("Determining query type")

        lower = question.lower().strip()

        # Check for opinion/subjective first (most specific)
        for pattern in OPINION_PATTERNS:
            if re.match(pattern, lower):
                logger.info("Query type: opinion_subjective")
                return "opinion_subjective"
                
        # Check for medical
        for pattern in MEDICAL_PATTERNS:
            if re.search(pattern, lower):
                logger.info("Query type: medical_health")
                return "medical_health"
                
        # Check for programming
        for pattern in PROGRAMMING_PATTERNS:
            if re.search(pattern, lower):
                logger.info("Query type: programming")
                return "programming"
                
        # Check for finance
        for pattern in FINANCE_PATTERNS:
            if re.search(pattern, lower):
                logger.info("Query type: finance")
                return "finance"

        # Check for numeric/statistical
        for pattern in NUMERIC_PATTERNS:
            if re.match(pattern, lower):
                logger.info("Query type: numeric_statistical")
                return "numeric_statistical"

        # Check for recent events
        for keyword in RECENT_EVENT_KEYWORDS:
            if keyword in lower:
                logger.info("Query type: recent_event")
                return "recent_event"

        # Default: encyclopedic
        logger.info("Query type: encyclopedic")
        return "encyclopedic"

    @staticmethod
    async def preprocess_async(question: str, answer: str) -> ProcessedQuery:
        """
        Full async preprocessing pipeline.

        Args:
            question: Original question
            answer: AI-generated answer

        Returns:
            Processed query with extracted claims, type, and analytics metadata
        """
        start = time.time()

        # Split sentences and count for analytics
        sentences = QueryPreprocessor._split_sentences(answer) if answer and len(answer.strip()) >= 10 else []
        factual = [s for s in sentences if QueryPreprocessor._is_factual_sentence(s)]

        claims = await QueryPreprocessor.extract_claims_async(answer)
        query_type = QueryPreprocessor.determine_query_type(question)

        preprocessing_time_ms = int((time.time() - start) * 1000)

        return ProcessedQuery(
            original_question=question,
            original_answer=answer,
            extracted_claims=claims,
            query_type=query_type,
            sentences_found=len(sentences),
            factual_sentences=len(factual),
            preprocessing_time_ms=preprocessing_time_ms,
        )

    @staticmethod
    def extract_claims(answer: str, max_claims: int = 3) -> list[str]:
        """Synchronous compatibility wrapper for tests."""
        import asyncio
        try:
            return asyncio.run(QueryPreprocessor.extract_claims_async(answer, max_claims))
        except RuntimeError:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    lambda: asyncio.run(QueryPreprocessor.extract_claims_async(answer, max_claims))
                )
                return future.result()

    @staticmethod
    def preprocess(question: str, answer: str) -> ProcessedQuery:
        """Synchronous compatibility wrapper for tests."""
        import asyncio
        try:
            return asyncio.run(QueryPreprocessor.preprocess_async(question, answer))
        except RuntimeError:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    lambda: asyncio.run(QueryPreprocessor.preprocess_async(question, answer))
                )
                return future.result()

