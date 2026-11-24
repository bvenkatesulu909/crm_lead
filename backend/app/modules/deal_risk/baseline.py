"""What is "usual" in an organisation, worked out from its won deals (ADR 0037, DR2).

Pure helpers. With fewer than MIN_SAMPLES won deals there is no usual value: the answer is None
and the forecast lists the comparison as unknown instead of guessing.
"""

from decimal import Decimal
from statistics import median

MIN_SAMPLES = 5


def typical_days(samples: list[int] | None) -> int | None:
    """The median number of days won deals spent in a stage, or None when there are too few."""
    if not samples or len(samples) < MIN_SAMPLES:
        return None
    return int(median(samples))


def typical_amount(samples: list[Decimal] | None) -> Decimal | None:
    """The median amount of won deals in one currency, or None when there are too few."""
    if not samples or len(samples) < MIN_SAMPLES:
        return None
    return Decimal(median(samples))
