"""Numbers said aloud (ADR 0038, VR9): a speech recogniser may write digits as words, in English,
Hindi or Telugu, and the digit-based card check would not see them. Pure rules, no database."""

import pytest

from app.modules.public_chat.rules import SPOKEN_CARD_MIN_DIGITS, spoken_number_refusal

EN_DIGITS = "four one one one one one one one one one one one one one one one".split()
HI_DIGITS = "चार एक एक एक एक एक एक एक एक एक एक एक एक एक एक एक".split()
TE_DIGITS = "నాలుగు ఒకటి ఒకటి ఒకటి ఒకటి ఒకటి ఒకటి ఒకటి ఒకటి ఒకటి ఒకటి ఒకటి ఒకటి ఒకటి".split()


@pytest.mark.parametrize("words", [EN_DIGITS, HI_DIGITS, TE_DIGITS])
def test_a_long_run_of_spoken_digits_is_refused(words: list[str]) -> None:
    assert spoken_number_refusal(" ".join(words))


def test_a_run_may_mix_words_and_digits() -> None:
    assert spoken_number_refusal("four one one one 1111 1111 1111")  # 4 + 12 digits


def test_the_limit_is_exactly_thirteen_digits() -> None:
    twelve = " ".join(["one"] * (SPOKEN_CARD_MIN_DIGITS - 1))
    thirteen = " ".join(["one"] * SPOKEN_CARD_MIN_DIGITS)
    assert not spoken_number_refusal(twelve)  # a phone number with +91 is 12 digits
    assert spoken_number_refusal(thirteen)


def test_a_normal_phone_number_said_aloud_passes() -> None:
    assert not spoken_number_refusal(
        "my number is nine eight four eight zero one two three four five"
    )
    assert not spoken_number_refusal("मेरा नंबर नौ आठ सात छह पाँच चार तीन दो एक शून्य है")
    assert not spoken_number_refusal("నా నంబర్ తొమ్మిది ఎనిమిది ఏడు ఆరు ఐదు నాలుగు మూడు రెండు ఒకటి సున్నా")


def test_a_word_between_the_digits_starts_a_new_run() -> None:
    spaced = " ".join(["one"] * 7 + ["and"] + ["one"] * 7)
    assert not spoken_number_refusal(spaced)  # two runs of 7, not one of 14


@pytest.mark.parametrize(
    "said", ["my OTP is coming", "the cvv is on the back", "मेरा ओटीपी आया है", "నా ఓటీపీ వచ్చింది"]
)
def test_naming_a_one_time_password_or_a_card_code_is_refused(said: str) -> None:
    assert spoken_number_refusal(said)


@pytest.mark.parametrize(
    "said",
    [
        "I want a two bedroom flat",
        "my budget is eighty lakh",
        "",
        "   ",
        "फ्लैट दो बेडरूम का चाहिए",
    ],
)
def test_ordinary_sentences_pass(said: str) -> None:
    assert not spoken_number_refusal(said)
