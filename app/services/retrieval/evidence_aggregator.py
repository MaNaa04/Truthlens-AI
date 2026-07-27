"""
Evidence Aggregator - Layer 3D
Deduplicates, ranks, and trims evidence to fit context windows.
"""

import re
from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)


class EvidenceAggregator:
    """
    Aggregates evidence from multiple sources.

    Operations:
    1. Deduplication - remove duplicate snippets
    2. Ranking - prioritize most relevant evidence
    3. Trimming - fit within token budget (~800 tokens)
    4. Formatting - clean markup, proper citations
    """

    def __init__(self):
        """Initialize aggregator."""
        settings = get_settings()
        self.max_tokens = settings.max_evidence_tokens

    def deduplicate(self, evidence_list: list[str]) -> list[str]:
        """
        Remove duplicate evidence snippets.

        Handles:
        - Exact duplicates
        - Substring containment (if A fully contains B, drop B)

        Args:
            evidence_list: Raw evidence from all sources

        Returns:
            Deduplicated evidence list
        """
        if not evidence_list:
            return []

        logger.info(f"Deduplicating {len(evidence_list)} evidence items")

        # Normalize: lowercase, collapse whitespace, strip punctuation
        normalized = [
            (e, re.sub(r'[^\w\s]', '', re.sub(r'\s+', ' ', e.strip().lower())))
            for e in evidence_list
        ]

        # Remove exact duplicates (preserve order, keep first occurrence)
        seen: set[str] = set()
        unique: list[tuple[str, str]] = []
        for original, norm in normalized:
            if norm not in seen:
                seen.add(norm)
                unique.append((original, norm))

        # Remove items fully contained in another
        result = []
        for i, (orig_i, norm_i) in enumerate(unique):
            is_contained = False
            for j, (orig_j, norm_j) in enumerate(unique):
                if i != j and norm_i in norm_j and len(norm_i) < len(norm_j):
                    is_contained = True
                    break
            if not is_contained:
                result.append(orig_i)

        logger.info(f"Deduplicated: {len(evidence_list)} → {len(result)} items")
        return result

    def rank_evidence(self, evidence_list: list[str]) -> list[str]:
        """
        Rank evidence by quality and usefulness.

        Scoring:
        - Prefer medium-length snippets (50-500 chars) — they're usually
          the most focused and relevant
        - Penalize very short (<50 chars) or very long (>1000 chars) snippets
        - Penalize generic boilerplate phrases

        Args:
            evidence_list: Deduplicated evidence

        Returns:
            Ranked evidence list (best first)
        """
        if not evidence_list:
            return []

        logger.info(f"Ranking {len(evidence_list)} evidence items")

        boilerplate_phrases = [
            "click here", "read more", "subscribe", "cookie",
            "privacy policy", "terms of service", "sign up",
            "advertisement", "sponsored",
        ]

        def score(text: str) -> float:
            s = 0.0
            length = len(text)

            # Length scoring: prefer medium-length
            if 50 <= length <= 500:
                s += 3.0
            elif 500 < length <= 1000:
                s += 2.0
            elif length > 1000:
                s += 1.0
            else:
                s += 0.5  # Very short

            # Penalize boilerplate
            lower = text.lower()
            for phrase in boilerplate_phrases:
                if phrase in lower:
                    s -= 1.0

            # Reward sentences with numbers (often factual)
            if re.search(r'\d', text):
                s += 0.5

            return s

        ranked = sorted(evidence_list, key=score, reverse=True)
        return ranked

    def trim_to_budget(self, evidence_text: str) -> str:
        """
        Trim evidence to fit within token budget.

        Uses sentence-boundary aware trimming: cuts at the last complete
        sentence that fits within the token budget.

        Rough estimate: 1 token ≈ 4 characters

        Args:
            evidence_text: Combined evidence text

        Returns:
            Trimmed evidence within token budget
        """
        estimated_tokens = len(evidence_text) // 4

        if estimated_tokens <= self.max_tokens:
            logger.info(f"Evidence within budget: {estimated_tokens}/{self.max_tokens} tokens")
            return evidence_text

        logger.warning(f"Trimming evidence: {estimated_tokens} → {self.max_tokens} tokens")

        char_limit = self.max_tokens * 4

        # Try to cut at a sentence boundary
        trimmed = evidence_text[:char_limit]
        last_period = trimmed.rfind(".")
        last_newline = trimmed.rfind("\n")
        cut_point = max(last_period, last_newline)

        if cut_point > char_limit * 0.5:
            # Only cut at boundary if it doesn't lose too much content
            trimmed = trimmed[:cut_point + 1]

        return trimmed.strip()

    def aggregate(self, evidence_list: list[str]) -> str:
        """
        Full aggregation pipeline.

        Args:
            evidence_list: Raw evidence from all sources

        Returns:
            Final aggregated, cleaned evidence text
        """
        if not evidence_list:
            logger.info("No evidence to aggregate")
            return ""

        # Flatten any nested evidence (source router returns combined strings)
        flat = []
        for item in evidence_list:
            if isinstance(item, str):
                # Split combined evidence back into individual pieces
                parts = [p.strip() for p in item.split("\n\n") if p.strip()]
                flat.extend(parts)

        deduped = self.deduplicate(flat)
        ranked = self.rank_evidence(deduped)
        combined = "\n\n".join(ranked)
        trimmed = self.trim_to_budget(combined)

        logger.info(f"Aggregated evidence: {len(trimmed)} chars")
        return trimmed
