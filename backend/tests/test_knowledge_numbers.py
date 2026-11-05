"""Pure rules of the RERA / price refusal gate (CRM-115 / BP-08, step BR2, docs/brochures-rera.md).

No database, no model: which strings are RERA numbers, how amounts in rupees are read, and when an
answer quotes a number or a price that its cited sources do not contain.
"""

import pytest

from app.modules.knowledge import numbers

# --- RERA-shaped numbers --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("RERA: DEMO-P02400000001.", ["DEMO-P02400000001"]),
        ("Telangana P02400001234 is registered", ["P02400001234"]),
        ("Maharashtra P51800012345", ["P51800012345"]),
        ("ka PRM/KA/RERA/1251/309/PR/171014/000526 ok", ["PRM/KA/RERA/1251/309/PR/171014/000526"]),
        ("lower case demo-p02400000001 too", ["demo-p02400000001"]),
        (
            "two: DEMO-P02400000001 and DEMO-P02400000002",
            ["DEMO-P02400000001", "DEMO-P02400000002"],
        ),
    ],
)
def test_rera_numbers_are_found(text: str, found: list[str]) -> None:
    assert numbers.rera_numbers(text) == found


@pytest.mark.parametrize(
    "text",
    [
        "Call +91 98765 43210 today",  # a phone number: no letter
        "Price ₹1,20,00,000 or 1.2 Cr",  # money
        "Possession 2027-12-01",  # a date
        "Lead 3c5acf4c-8478-4f9f-9e82-e3f4a9d5ac64 please",  # an id pasted into a question
        "A 2 BHK of 1,250 sq ft",
        "Room B12345",  # too few digits
        "",
    ],
)
def test_other_things_are_not_rera_numbers(text: str) -> None:
    assert numbers.rera_numbers(text) == []


def test_numbers_are_compared_ignoring_case_spaces_and_dashes() -> None:
    assert numbers.normalise("demo-p024 000 00001") == numbers.normalise("DEMO-P02400000001")
    assert numbers.normalise("DEMOP02400000001") == "DEMOP02400000001"
    assert numbers.normalise("PRM/KA/RERA/1") == "PRM/KA/RERA/1"  # slashes are kept


def test_contains_number_looks_for_the_whole_number() -> None:
    text = "RERA registration number: DEMO-P02400000001."
    assert numbers.contains_number(text, "demo p02400000001")
    assert not numbers.contains_number(text, "DEMO-P0240000000")  # a shorter number is not it
    assert not numbers.contains_number(text, "DEMO-P024000000012")


# --- amounts in rupees ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rupees"),
    [
        ("from ₹85 lakh", {8_500_000}),
        ("up to ₹1.4 crore", {14_000_000}),
        ("₹1,20,00,000", {12_000_000}),
        ("Rs. 1.2 Cr", {12_000_000}),
        ("INR 80 L", {8_000_000}),
        ("120 lakhs", {12_000_000}),
        ("85 lac", {8_500_000}),
        ("2.10 crores", {21_000_000}),
        ("₹ 60,000", {60_000}),
        ("between ₹72 lakh and ₹1.1 crore", {7_200_000, 11_000_000}),
    ],
)
def test_amounts_are_read_as_whole_rupees(text: str, rupees: set[int]) -> None:
    assert numbers.rupee_amounts(text) == rupees


@pytest.mark.parametrize(
    "text",
    [
        "a 2 BHK of 1,250 sq ft",  # no currency, no unit
        "possession in 2027",
        "call 98765 43210",
        "DEMO-P02400000001",
        "3 BHK villa",
    ],
)
def test_other_numbers_are_not_amounts(text: str) -> None:
    assert numbers.rupee_amounts(text) == set()


# --- the check of one answer ----------------------------------------------------------------------

SOURCE = (
    "Skyline Towers. RERA registration number: DEMO-P02400000003. "
    "2 BHK: from ₹78 lakh. 3 BHK: up to ₹1.2 crore."
)


def test_an_answer_quoting_its_cited_source_passes() -> None:
    answer = "Skyline Towers (DEMO-P02400000003) starts at ₹78 lakh and goes up to 1.2 Cr [1]."
    assert numbers.unsupported(answer, [SOURCE], question="") is None


def test_a_rera_number_not_in_the_cited_sources_is_refused() -> None:
    answer = "It is registered as DEMO-P02400000009 [1]."
    assert numbers.unsupported(answer, [SOURCE], question="") == "rera_not_cited"


def test_a_price_not_in_the_cited_sources_is_refused() -> None:
    answer = "A 2 BHK starts at ₹72 lakh [1]."  # the OLD edition's price
    assert numbers.unsupported(answer, [SOURCE], question="") == "price_not_cited"


def test_an_amount_the_person_gave_in_the_question_may_be_repeated() -> None:
    answer = "With a budget of ₹90 lakh, the 2 BHK from ₹78 lakh fits [1]."
    assert numbers.unsupported(answer, [SOURCE], question="My budget is 90 lakh") is None


def test_a_rera_number_from_the_question_must_still_be_in_a_cited_source() -> None:
    answer = "DEMO-P02400000009 is registered [1]."
    question = "Is DEMO-P02400000009 registered?"
    assert numbers.unsupported(answer, [SOURCE], question=question) == "rera_not_cited"


def test_an_answer_without_numbers_or_prices_is_not_this_gates_business() -> None:
    assert numbers.unsupported("The project is in Gachibowli [1].", [SOURCE], question="") is None


def test_the_rera_check_comes_before_the_price_check() -> None:
    answer = "DEMO-P02400000009 costs ₹10 lakh [1]."
    assert numbers.unsupported(answer, [SOURCE], question="") == "rera_not_cited"


def test_mentions_rera_says_when_the_fixed_line_is_due() -> None:
    assert numbers.mentions_rera("Its number is DEMO-P02400000003 [1].")
    assert not numbers.mentions_rera("A 2 BHK starts at ₹78 lakh [1].")
