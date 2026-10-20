"""Personal-data scan for knowledge documents (RAG R1, design rule 8).

Only patterns and category codes leave this module - never the matched values. A finding stops
indexing and marks the document "needs review" until a person redacts the file.
"""

import re

from app.modules.knowledge.extraction import Section

# 13-19 digits, optionally grouped by single spaces or hyphens. Validated with the Luhn check.
_CARD = re.compile(r"(?<![0-9])(?:[0-9][ -]?){13,19}(?![0-9])")
# Indian PAN: five letters, four digits, one letter.
_PAN = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
# Aadhaar is 12 digits, usually grouped 4-4-4. It must not start in the middle of a longer
# grouped number (for example a 16-digit card): the two characters before must not be "digit ".
_AADHAAR = re.compile(r"(?<![0-9])(?<![0-9] )[0-9]{4} [0-9]{4} [0-9]{4}(?![0-9])(?! [0-9])")


def _luhn(number: str) -> bool:
    digits = [int(character) for character in number]
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def scan_sections(sections: list[Section]) -> list[str]:
    """Sorted category codes found in the text (for example ["card_number"])."""
    found: set[str] = set()
    for section in sections:
        for block in section.blocks:
            for match in _CARD.finditer(block):
                digits = re.sub(r"[ -]", "", match.group())
                if _luhn(digits):
                    found.add("card_number")
            if _PAN.search(block):
                found.add("pan")
            if _AADHAAR.search(block):
                found.add("aadhaar")
    return sorted(found)
