"""Pure rules of the video brief (ADR 0041, step VB1): no database, no model, no network."""

import pytest

from app.modules.video_brief import rules

KEYS = [
    ("budget", "Budget"), ("property_type", "Property type"), ("location", "Area or location"),
    ("timeline", "Timeline"), ("purpose", "Purpose"), ("financing", "Financing"),
    ("household", "Household"), ("decision_makers", "Decision makers"),
    ("must_haves", "Must-haves"), ("deal_breakers", "Deal-breakers"),
    ("current_home", "Current home"), ("other_options", "Other options"),
]  # fmt: skip


def fact(key: str = "budget", value: str = "Up to 1.5 Cr") -> rules.KnownFact:
    return rules.KnownFact(
        key, dict(KEYS)[key], value, "buyer_confirmed", "Our budget is 1.5 crore."
    )


def guess(key: str = "timeline", value: str = "Within six months") -> rules.KnownGuess:
    return rules.KnownGuess(key, dict(KEYS)[key], value, "Sounded in a hurry")


def make(**kw: object) -> rules.VideoBrief:
    base: dict[str, object] = dict(
        first_name="Suresh", language="en", goal="follow_up", tone="warm", length_seconds=60,
        facts=[fact()], guesses=[guess()], form_wishes=[("property_type", "Apartment")],
    )  # fmt: skip
    base.update(kw)
    return rules.build_video_brief(**base)  # type: ignore[arg-type]


def test_the_brief_uses_only_the_first_name_and_the_chosen_settings() -> None:
    brief = make(first_name="  Suresh  ")
    assert brief.first_name == "Suresh"
    assert (brief.language, brief.tone, brief.goal, brief.length_seconds) == (
        "en", "warm", "follow_up", 60,
    )  # fmt: skip
    assert brief.word_target == 150


@pytest.mark.parametrize(("seconds", "words"), [(30, 75), (60, 150), (90, 225)])
def test_the_word_target_follows_the_length(seconds: int, words: int) -> None:
    assert make(length_seconds=seconds).word_target == words


@pytest.mark.parametrize(
    "kw",
    [{"language": "fr"}, {"tone": "angry"}, {"goal": "spam"}, {"length_seconds": 45}],
)
def test_values_outside_the_fixed_lists_are_refused(kw: dict[str, object]) -> None:
    with pytest.raises(rules.BriefError):
        make(**kw)


def test_a_fact_keeps_its_source_and_the_script_says_it_as_a_statement() -> None:
    brief = make()
    line = brief.known[0]
    assert (line.kind, line.key, line.source) == ("fact", "budget", "buyer_confirmed")
    assert any("Up to 1.5 Cr" in s.text and s.cites == ["budget"] for s in brief.script)


def test_an_assumption_is_never_a_statement_only_a_question() -> None:
    brief = make()
    q = [s for s in brief.script if s.cites == ["timeline"]]
    assert len(q) == 1 and q[0].text.endswith("?")
    assert q[0].kind == "question"
    assert brief.known[1].kind == "assumption"


def test_at_most_five_facts_reach_the_script() -> None:
    facts = [fact(k, f"v{i}") for i, (k, _) in enumerate(KEYS[:8])]
    brief = make(facts=facts, guesses=[], form_wishes=[])
    assert sum(1 for s in brief.script if s.kind == "fact") == 5
    assert len(brief.known) == 8


def test_the_script_has_a_greeting_and_a_goal_specific_closing() -> None:
    a, b = make(goal="follow_up"), make(goal="after_visit")
    assert a.script[0].kind == "greeting" and "Suresh" in a.script[0].text
    assert a.script[-1].kind == "closing" and a.script[-1].text != b.script[-1].text


@pytest.mark.parametrize("language", ["en", "hi", "te"])
def test_every_language_has_every_goal(language: str) -> None:
    for goal in rules.GOALS:
        brief = make(language=language, goal=goal)
        assert brief.script[0].text and brief.script[-1].text


def test_hindi_and_telugu_scripts_are_written_in_their_scripts() -> None:
    assert any("ऀ" <= c <= "ॿ" for c in make(language="hi").script[0].text)
    assert any("ఀ" <= c <= "౿" for c in make(language="te").script[0].text)


def test_the_must_say_and_must_not_say_lists_are_fixed_and_always_present() -> None:
    brief = make()
    assert brief.must_not_say == list(rules.MUST_NOT_SAY)
    assert any("RERA" in m for m in brief.must_say)
    assert any("guaranteed" in m.lower() for m in brief.must_not_say)


def test_consent_notes_warn_about_contact_details_in_the_video() -> None:
    notes = " ".join(make().consent_notes).lower()
    assert "phone" in notes and "consent" in notes


def test_links_and_markup_in_a_stored_value_never_reach_the_script() -> None:
    brief = make(facts=[fact("budget", "1.5 Cr <b>x</b> see https://evil.example/a")], guesses=[])
    spoken = " ".join(s.text for s in brief.script)
    assert "http" not in spoken and "<b>" not in spoken and "evil.example" not in spoken


def test_a_phone_number_in_a_value_is_left_out_of_the_script() -> None:
    brief = make(facts=[fact("budget", "call me on 98480 12345")], guesses=[])
    assert "98480" not in " ".join(s.text for s in brief.script)
    assert any(c.code == "value_left_out" for c in brief.cautions)


def test_a_line_that_would_not_fit_the_length_is_reported() -> None:
    long = " ".join(f"w{i}" for i in range(45))
    brief = make(length_seconds=30, facts=[fact("budget", long.strip())], guesses=[])
    assert any(c.code == "script_too_long" for c in brief.cautions)


def test_a_normal_script_fits_its_length() -> None:
    brief = make()
    assert brief.words <= brief.word_target
    assert not any(c.code == "script_too_long" for c in brief.cautions)


def test_form_wishes_are_shown_as_lead_form_lines_not_buyer_facts() -> None:
    brief = make(facts=[], guesses=[])
    assert [(k.kind, k.source) for k in brief.known] == [("form", "lead_form")]
    assert not any(s.kind == "fact" for s in brief.script)


@pytest.mark.parametrize(
    "text",
    [
        "This is a guaranteed return of 20%",
        "Only last units left, hurry",
        "We are better than Brigade",
        "Your religion does not matter",
        "Assured returns for you",
    ],
)
def test_banned_phrases_are_found(text: str) -> None:
    assert rules.banned_phrases_in(text, competitors=["Brigade"])


def test_ordinary_sales_language_is_not_flagged() -> None:
    assert rules.banned_phrases_in("Two bedrooms near the metro, ready in 2027.") == []


def test_the_spoken_time_estimate_matches_the_word_count() -> None:
    assert rules.spoken_seconds("one two three four five") == 2
    assert rules.words("  a  b\nc ") == 3
