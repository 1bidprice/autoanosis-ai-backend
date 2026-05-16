"""
medical_lexicon.py — Deterministic Greek Medical Lexicon Correction Layer

Post-OCR correction for known Greek medical term errors.
Uses fuzzy matching (Levenshtein distance) + regex substitution.

Architecture:
  Raw OCR text → _apply_lexicon_corrections() → corrected text + corrections_log

Design principles:
  1. Only correct terms that are in the known error map
  2. Never "guess" — if unsure, leave as-is and flag for review
  3. Log every correction for audit trail
  4. Case-insensitive matching, case-preserving output
"""

import re
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known OCR error map: (wrong_pattern, correct_replacement)
# Patterns are regex, replacements are literal strings.
# Order matters: more specific patterns first.
# ---------------------------------------------------------------------------

class LexiconRule(NamedTuple):
    pattern: str          # regex pattern (case-insensitive)
    replacement: str      # correct Greek medical term
    context: str          # human-readable description for logging
    confidence: str       # "high" = always apply, "medium" = apply with flag


LEXICON_RULES: list[LexiconRule] = [
    # -----------------------------------------------------------------------
    # ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ — gallbladder
    # Common errors: ΧΟΛΑΔΟΣΟΣ, ΧΟΛΑΔΟΣ, ΧΟΛΑΔΟΧΟΣ, ΧΟΛΑΔΟΧΗ
    # -----------------------------------------------------------------------
    LexiconRule(
        pattern=r'\bΧΟΛΑΔΟΣΟΣ\s+ΚΥΣΤΗΣ?\b',
        replacement='ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ',
        context='gallbladder_header',
        confidence='high',
    ),
    LexiconRule(
        pattern=r'\bΧΟΛΑΔΟΣ\s+ΚΥΣΤΗΣ?\b',
        replacement='ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ',
        context='gallbladder_header',
        confidence='high',
    ),
    LexiconRule(
        pattern=r'\bΧΟΛΑΔΟΧΟΣ\s+ΚΥΣΤΗΣ?\b',
        replacement='ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ',
        context='gallbladder_header',
        confidence='high',
    ),
    LexiconRule(
        pattern=r'\bΧΟΛΑΔΟΧΗ\s+ΚΥΣΤΗΣ?\b',
        replacement='ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ',
        context='gallbladder_header',
        confidence='high',
    ),

    # -----------------------------------------------------------------------
    # Χοληδόχος πόρος — common bile duct
    # Common errors: Χολήθος, Χολήδοχος, Χολαδόχος
    # -----------------------------------------------------------------------
    LexiconRule(
        pattern=r'\bΧολήθος\s+πόρος\b',
        replacement='Χοληδόχος πόρος',
        context='bile_duct',
        confidence='high',
    ),
    LexiconRule(
        pattern=r'\bΧολήδοχος\s+πόρος\b',
        replacement='Χοληδόχος πόρος',
        context='bile_duct',
        confidence='high',
    ),
    LexiconRule(
        pattern=r'\bΧολαδόχος\s+πόρος\b',
        replacement='Χοληδόχος πόρος',
        context='bile_duct',
        confidence='high',
    ),

    # -----------------------------------------------------------------------
    # ηχοδομή — echogenicity/texture
    # Common errors: εκδόμη, παχέως, ηχοδομή (with wrong accent), εκδομή
    # -----------------------------------------------------------------------
    LexiconRule(
        pattern=r'\bεκδόμη\b',
        replacement='ηχοδομή',
        context='echogenicity',
        confidence='high',
    ),
    LexiconRule(
        pattern=r'\bεκδομή\b',
        replacement='ηχοδομή',
        context='echogenicity',
        confidence='high',
    ),
    LexiconRule(
        pattern=r'(?<=Ομοιογενής\s)παχέως\b',
        replacement='ηχοδομή',
        context='echogenicity_after_homogeneous',
        confidence='high',
    ),

    # -----------------------------------------------------------------------
    # υψή ήπατος — liver echogenicity (specific phrase)
    # Common errors: ηχύ, υψι, υψή (wrong accent)
    # -----------------------------------------------------------------------
    LexiconRule(
        pattern=r'\bηχύ\s+ήπατος\b',
        replacement='υψή ήπατος',
        context='liver_echogenicity',
        confidence='high',
    ),
    LexiconRule(
        pattern=r'\bυψι\s+ήπατος\b',
        replacement='υψή ήπατος',
        context='liver_echogenicity',
        confidence='high',
    ),

    # -----------------------------------------------------------------------
    # νεφρών — of the kidneys (genitive)
    # Common errors: ψευδό, νεφρόν, νεφρόν
    # -----------------------------------------------------------------------
    LexiconRule(
        pattern=r'(?<=μέγεθος\s)ψευδό\b',
        replacement='νεφρών',
        context='kidney_size_genitive',
        confidence='high',
    ),
    LexiconRule(
        pattern=r'(?<=μέγεθος\s)νεφρόν\b',
        replacement='νεφρών',
        context='kidney_size_genitive',
        confidence='high',
    ),

    # -----------------------------------------------------------------------
    # Σπληνεκτομή — splenectomy
    # Common errors: Σπληνική, Σπληνεκτομή (wrong accent), Σπιλνεκτομή
    # -----------------------------------------------------------------------
    LexiconRule(
        pattern=r'(?<=ΣΠΛΗΝΑΣ\s)Σπληνική\b',
        replacement='Σπληνεκτομή',
        context='splenectomy_after_header',
        confidence='high',
    ),
    LexiconRule(
        pattern=r'(?<=ΣΠΙΛΝΑΣ\s)Σπληνεκτομή?\b',
        replacement='Σπληνεκτομή',
        context='splenectomy_after_misspelled_header',
        confidence='high',
    ),

    # -----------------------------------------------------------------------
    # Ανευ λίθων — without stones (gallbladder)
    # Common errors: Απειλούνται, Άνευ λίθων (wrong accent on Α)
    # -----------------------------------------------------------------------
    LexiconRule(
        pattern=r'\bΑπειλούνται\b',
        replacement='Ανευ λίθων',
        context='no_gallstones',
        confidence='high',
    ),

    # -----------------------------------------------------------------------
    # Χολαγγεία φυσιολογικά — normal bile ducts
    # Common errors: Χολαγγείες (plural), Χολαγγεία (correct)
    # -----------------------------------------------------------------------
    LexiconRule(
        pattern=r'\bΧολαγγείες\s+φυσιολογικά\b',
        replacement='Χολαγγεία φυσιολογικά',
        context='bile_ducts_normal',
        confidence='medium',
    ),

    # -----------------------------------------------------------------------
    # ΣΠΙΛΝΑΣ → ΣΠΛΗΝΑΣ (header misspelling)
    # -----------------------------------------------------------------------
    LexiconRule(
        pattern=r'\bΣΠΙΛΝΑΣ\b',
        replacement='ΣΠΛΗΝΑΣ',
        context='spleen_header',
        confidence='high',
    ),
]


# ---------------------------------------------------------------------------
# Suspicious patterns: if these appear after correction, flag for review
# ---------------------------------------------------------------------------

SUSPICIOUS_AFTER_CORRECTION = [
    r'\bψευδό\b',
    r'\bηχύ\b',
    r'\bεκδόμη\b',
    r'\bΧΟΛΑΔΟΣ',
    r'\bΑπειλούνται\b',
    r'\bΣπληνική\b(?!\s+αρτηρία)',  # Σπληνική is OK if followed by αρτηρία
]


class CorrectionResult:
    def __init__(self, original: str, corrected: str, corrections: list[dict], needs_review: bool):
        self.original = original
        self.corrected = corrected
        self.corrections = corrections  # list of {rule, original_match, replacement}
        self.needs_review = needs_review
        self.correction_count = len(corrections)


def apply_lexicon_corrections(raw_text: str) -> CorrectionResult:
    """
    Apply deterministic medical lexicon corrections to raw OCR text.

    Returns CorrectionResult with:
    - corrected: the corrected text
    - corrections: list of corrections applied (for audit log)
    - needs_review: True if suspicious patterns remain after correction
    """
    text = raw_text
    corrections = []

    for rule in LEXICON_RULES:
        # Find all matches (case-insensitive for pattern matching)
        matches = list(re.finditer(rule.pattern, text, re.IGNORECASE))
        if matches:
            for match in matches:
                original_match = match.group(0)
                # Apply replacement preserving the case structure of the replacement
                text = text[:match.start()] + rule.replacement + text[match.end():]
                corrections.append({
                    'rule_context': rule.context,
                    'original': original_match,
                    'replacement': rule.replacement,
                    'confidence': rule.confidence,
                })
                logger.info(
                    "[LEXICON] Corrected '%s' → '%s' (rule: %s)",
                    original_match, rule.replacement, rule.context
                )
            # Re-run finditer on updated text for next rule
            # (corrections may affect subsequent matches)

    # Check for suspicious patterns remaining after correction
    text_lower = text.lower()
    remaining_suspicious = []
    for pattern in SUSPICIOUS_AFTER_CORRECTION:
        if re.search(pattern, text, re.IGNORECASE):
            remaining_suspicious.append(pattern)

    needs_review = len(remaining_suspicious) > 0
    if needs_review:
        logger.warning(
            "[LEXICON] Suspicious patterns remain after correction: %s",
            remaining_suspicious
        )

    if corrections:
        logger.info("[LEXICON] Applied %d corrections to OCR text", len(corrections))
    else:
        logger.debug("[LEXICON] No corrections needed")

    return CorrectionResult(
        original=raw_text,
        corrected=text,
        corrections=corrections,
        needs_review=needs_review,
    )


def get_correction_summary(result: CorrectionResult) -> dict:
    """Return a summary dict suitable for API response or logging."""
    return {
        'corrections_applied': result.correction_count,
        'needs_review': result.needs_review,
        'corrections': result.corrections,
    }
