"""Pure rules of the video brief (ADR 0041): no database, no model, no network.

A video brief is the written preparation for a personalised video to a buyer: what to say, in which
language and tone, for how long, using which cited facts, and what must NOT be said. In this first
step it is built by code from what the CRM already holds. Nothing is invented:

- a buyer-memory FACT may be spoken as a statement,
- an ASSUMPTION may only be asked as a question,
- what the lead form says is shown as "lead form" (the buyer did not confirm it) and is not spoken.

This module only arranges the inputs the service gathered.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.screening import screen
from app.modules.assistant import api as assistant_api

LANGUAGES = ("en", "hi", "te")
TONES = ("warm", "professional", "brisk")
GOALS = ("introduce", "follow_up", "after_visit", "explain_quote", "revive")
LENGTHS = (30, 60, 90)

# About 150 spoken words a minute, so a length fixes how many words the script may hold.
WORDS_PER_SECOND = 2.5
MAX_FACTS_IN_SCRIPT = 5
MAX_PRICE_LINES_IN_SCRIPT = 3
VALUE_MAX = 200

MUST_SAY: tuple[str, ...] = (
    "Say the project's RERA registration number, if the brochure or quote has one.",
    "Say that prices are subject to change.",
    "Say that images and plans are indicative.",
)

MUST_NOT_SAY: tuple[str, ...] = (
    "Never promise guaranteed or assured returns.",
    "Never say 'last units' or invent urgency that the project does not have.",
    "Never invent a discount, an offer or a price - use only the cited facts.",
    "Never compare with, or name, a competitor.",
    "Never speak about the buyer's family, health, religion or caste.",
    "Never put the buyer's phone number, address or financial details in the video.",
)

CONSENT_NOTES: tuple[str, ...] = (
    "Check the buyer's consent to be contacted before you send the video.",
    "Do not put the buyer's phone number, e-mail address or home address in the video.",
    "Tell the buyer if the presenter is a synthetic (AI) avatar rather than a real person.",
)

# --- words in the three languages (the Hindi and Telugu still need a native read-through) --------

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "budget": "Budget", "property_type": "Property type", "location": "Area",
        "timeline": "Timeline", "purpose": "Purpose", "financing": "Payment plan",
        "household": "Household", "decision_makers": "Decision makers",
        "must_haves": "Must-haves", "deal_breakers": "Deal-breakers",
        "current_home": "Current home", "other_options": "Other options",
    },
    "hi": {
        "budget": "बजट", "property_type": "प्रॉपर्टी का प्रकार", "location": "इलाका",
        "timeline": "समय-सीमा", "purpose": "उद्देश्य", "financing": "भुगतान का तरीका",
        "household": "परिवार", "decision_makers": "फ़ैसला लेने वाले",
        "must_haves": "ज़रूरी बातें", "deal_breakers": "न चलने वाली बातें",
        "current_home": "अभी का घर", "other_options": "दूसरे विकल्प",
    },
    "te": {
        "budget": "బడ్జెట్", "property_type": "ఆస్తి రకం", "location": "ప్రాంతం",
        "timeline": "కాలపరిమితి", "purpose": "ఉద్దేశ్యం", "financing": "చెల్లింపు విధానం",
        "household": "కుటుంబం", "decision_makers": "నిర్ణయం తీసుకునేవారు",
        "must_haves": "తప్పనిసరి అంశాలు", "deal_breakers": "అంగీకరించలేని అంశాలు",
        "current_home": "ప్రస్తుత ఇల్లు", "other_options": "ఇతర ఎంపికలు",
    },
}  # fmt: skip

GREETING = {
    "en": "Hello {name},",
    "hi": "नमस्ते {name} जी,",
    "te": "నమస్కారం {name} గారు,",
}
FACT_LINE = {
    "en": "On {label}, you told us: {value}.",
    "hi": "{label} के बारे में आपने बताया: {value}।",
    "te": "{label} గురించి మీరు చెప్పింది: {value}.",
}
QUESTION_LINE = {
    "en": "Is {value} still right for {label}?",
    "hi": "{label} के लिए क्या {value} अब भी सही है?",
    "te": "{label} కోసం {value} ఇప్పటికీ సరైనదేనా?",
}
PRICE_LINE = {
    "en": "{description} - {amount}.",
    "hi": "{description} - {amount}।",
    "te": "{description} - {amount}.",
}
PRICE_TOTAL = {
    "en": "The total is {amount}, valid until {valid_until}.",
    "hi": "कुल राशि {amount} है, {valid_until} तक मान्य।",
    "te": "మొత్తం {amount}, {valid_until} వరకు చెల్లుతుంది.",
}
INTRO = {
    "introduce": {
        "en": "Thank you for your interest - here is a short introduction to what we can offer.",
        "hi": "आपकी रुचि के लिए धन्यवाद - हम क्या दे सकते हैं, इसका एक छोटा परिचय यह है।",
        "te": "మీ ఆసక్తికి ధన్యవాదాలు - మేము ఏమి అందించగలమో చిన్న పరిచయం ఇది.",
    },
    "follow_up": {
        "en": "Thank you for speaking with us - here is a short follow-up.",
        "hi": "हमसे बात करने के लिए धन्यवाद - यह एक छोटा फ़ॉलो-अप है।",
        "te": "మాతో మాట్లాడినందుకు ధన్యవాదాలు - ఇది చిన్న ఫాలో-అప్.",
    },
    "after_visit": {
        "en": "Thank you for visiting the site - here is a short recap.",
        "hi": "साइट पर आने के लिए धन्यवाद - यह एक छोटा सार है।",
        "te": "సైట్‌ను సందర్శించినందుకు ధన్యవాదాలు - ఇది చిన్న సారాంశం.",
    },
    "explain_quote": {
        "en": "Here is a short walk-through of the quote we sent you.",
        "hi": "हमने जो कोटेशन भेजा है, उसकी एक छोटी जानकारी यह है।",
        "te": "మేము పంపిన కోట్ గురించి చిన్న వివరణ ఇది.",
    },
    "revive": {
        "en": "It has been a while - here is a short update that may interest you.",
        "hi": "काफ़ी समय हो गया - यह एक छोटी जानकारी है जो आपके काम की हो सकती है।",
        "te": "చాలా రోజులైంది - మీకు ఉపయోగపడే చిన్న అప్‌డేట్ ఇది.",
    },
}
CLOSING = {
    "introduce": {
        "en": "If you would like to know more, we would be happy to talk.",
        "hi": "यदि आप और जानना चाहें, तो हमें बात करके खुशी होगी।",
        "te": "మీరు మరింత తెలుసుకోవాలనుకుంటే, మాట్లాడటానికి మాకు సంతోషం.",
    },
    "follow_up": {
        "en": "Thank you for your time - we are happy to answer questions or arrange a visit.",
        "hi": "आपके समय के लिए धन्यवाद - किसी भी सवाल का जवाब देने या विज़िट तय करने में हमें खुशी होगी।",
        "te": "మీ సమయానికి ధన్యవాదాలు - మీ ప్రశ్నలకు సమాధానం ఇవ్వడానికి లేదా సందర్శన ఏర్పాటు చేయడానికి మాకు సంతోషం.",
    },
    "after_visit": {
        "en": "Tell us what you thought of the visit, and we will take the next step together.",
        "hi": "विज़िट कैसी लगी, हमें बताइए - अगला कदम हम साथ मिलकर तय करेंगे।",
        "te": "సందర్శన ఎలా అనిపించిందో చెప్పండి - తదుపరి అడుగు కలిసి వేద్దాం.",
    },
    "explain_quote": {
        "en": "Please reply with any question about the quote, and we will go through it with you.",
        "hi": "कोटेशन के बारे में कोई भी सवाल हो तो बताइए, हम आपके साथ उसे देखेंगे।",
        "te": "కోట్ గురించి ఏ ప్రశ్న ఉన్నా చెప్పండి, మేము మీతో కలిసి చూస్తాము.",
    },
    "revive": {
        "en": "If your plans have changed or stayed the same, we would love to hear from you.",
        "hi": "आपकी योजना बदली हो या वही हो, हमें आपसे सुनकर अच्छा लगेगा।",
        "te": "మీ ప్రణాళికలు మారినా, అలాగే ఉన్నా, మీ నుండి వినడానికి సంతోషిస్తాము.",
    },
}
TONE_NOTES = {
    "warm": "Speak warmly and slowly, like a friendly neighbour who knows the area.",
    "professional": "Speak clearly and formally; keep every sentence short.",
    "brisk": "Speak briskly and to the point; no small talk.",
}

# --- the checks on what is said --------------------------------------------------------------

_BANNED: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("guaranteed_returns", re.compile(r"\b(guarantee[ds]?|assured)\b", re.I)),
    (
        "false_urgency",
        re.compile(r"\b(last\s+(few\s+)?units?|only\s+a?\s*few\s+units|hurry)\b", re.I),
    ),
    (
        "personal_matter",
        re.compile(r"\b(religion|caste|hindu|muslim|christian|illness|disease|health)\b", re.I),
    ),
)
_PHONE_RUN = re.compile(r"\d{10,}")
_EMAIL = re.compile(r"\S+@\S+\.\S+")


class BriefError(ValueError):
    """A choice outside the fixed lists."""


def words(text: str) -> int:
    return len(text.split())


def spoken_seconds(text: str) -> int:
    return round(words(text) / WORDS_PER_SECOND)


def banned_phrases_in(text: str, competitors: Sequence[str] = ()) -> list[str]:
    """Codes of the banned kinds of statement found in ``text`` (a competitor's name counts)."""
    found = [code for code, pattern in _BANNED if pattern.search(text)]
    lowered = text.lower()
    if any(c.strip() and c.strip().lower() in lowered for c in competitors):
        found.append("competitor_named")
    return found


# --- the inputs the service gathers ----------------------------------------------------------


@dataclass(frozen=True)
class KnownFact:
    key: str
    label: str
    value: str
    source: str | None
    quote: str | None


@dataclass(frozen=True)
class KnownGuess:
    key: str
    label: str
    value: str
    reason: str | None


# --- the brief ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceLine:
    description: str
    quantity: Decimal
    unit: str
    net_unit_price: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class PriceFacts:
    """The figures of one quote the person may read (never its notes)."""

    label: str  # "QT-0007"
    currency: str
    valid_until: date
    total: Decimal
    lines: Sequence[PriceLine]


def _lakh_grouping(whole: str) -> str:
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    pairs: list[str] = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join([*pairs, tail])


def format_money(amount: Decimal, currency: str) -> str:
    """The amount as stored: rupees with the rupee sign and lakh grouping (no decimals when they
    are .00), any other currency with its code and thousands grouping. Never rounded."""
    sign = "-" if amount < 0 else ""
    whole, _, fraction = f"{abs(amount):.2f}".partition(".")
    if currency == "INR":
        tail = "" if fraction == "00" else f".{fraction}"
        return f"{sign}\u20b9{_lakh_grouping(whole)}{tail}"
    return f"{sign}{currency} {int(whole):,}.{fraction}"


@dataclass(frozen=True)
class KnownLine:
    kind: str  # fact | assumption | form
    key: str
    label: str
    value: str
    source: str | None  # for a fact: where it came from; for the form: "lead_form"
    quote: str | None
    reason: str | None


@dataclass(frozen=True)
class ScriptLine:
    kind: str  # greeting | intro | fact | question | closing
    text: str
    cites: list[str] = field(default_factory=list)
    seconds: int = 0


@dataclass(frozen=True)
class Caution:
    code: str
    text: str


@dataclass(frozen=True)
class VideoBrief:
    first_name: str
    language: str
    tone: str
    tone_note: str
    goal: str
    length_seconds: int
    word_target: int
    known: list[KnownLine]
    script: list[ScriptLine]
    words: int
    must_say: list[str]
    must_not_say: list[str]
    consent_notes: list[str]
    cautions: list[Caution] = field(default_factory=list)


def _label(language: str, key: str, fallback: str) -> str:
    return LABELS[language].get(key, fallback)


def _safe_value(raw: str) -> str | None:
    """The value as it may be spoken, or None when it must be left out (a card number, an
    instruction, a phone number or an e-mail address). Links and markup are cleaned away."""
    if not assistant_api.inspect_input(raw).allowed:
        return None
    squeezed = re.sub(r"[\s-]", "", raw)
    if _PHONE_RUN.search(squeezed) or _EMAIL.search(raw):
        return None
    cleaned = " ".join(screen(raw, strip_links=True, strip_addresses=True).clean.split())
    if not cleaned or len(cleaned) > VALUE_MAX:
        return None
    return cleaned


def build_video_brief(
    *,
    first_name: str,
    language: str,
    goal: str,
    tone: str,
    length_seconds: int,
    facts: Sequence[KnownFact],
    guesses: Sequence[KnownGuess],
    form_wishes: Sequence[tuple[str, str]],
    price: PriceFacts | None = None,
    competitors: Sequence[str] = (),
) -> VideoBrief:
    if language not in LANGUAGES:
        raise BriefError("language must be en, hi or te")
    if tone not in TONES:
        raise BriefError(f"tone must be one of {', '.join(TONES)}")
    if goal not in GOALS:
        raise BriefError(f"goal must be one of {', '.join(GOALS)}")
    if length_seconds not in LENGTHS:
        raise BriefError("length must be 30, 60 or 90 seconds")

    name = " ".join(first_name.split())
    cautions: list[Caution] = []
    known: list[KnownLine] = []
    script = [ScriptLine("greeting", GREETING[language].format(name=name))]
    script.append(ScriptLine("intro", INTRO[goal][language]))

    spoken_facts = 0
    for f in facts:
        safe = _safe_value(f.value)
        known.append(
            KnownLine("fact", f.key, f.label, safe or "[left out]", f.source, f.quote, None)
        )
        if safe is None:
            cautions.append(
                Caution(
                    "value_left_out",
                    f"The {f.label} detail was left out of the script because it holds contact "
                    "details or text that is not safe to say.",
                )
            )
            continue
        if spoken_facts < MAX_FACTS_IN_SCRIPT:
            label = _label(language, f.key, f.label)
            script.append(
                ScriptLine("fact", FACT_LINE[language].format(label=label, value=safe), [f.key])
            )
            spoken_facts += 1
    if price is not None:
        spoken_lines = 0
        for pl in price.lines:
            amount = format_money(pl.line_total, price.currency)
            safe = _safe_value(pl.description)
            known.append(
                KnownLine("price", "price", "Price", f"{safe or '[left out]'} - {amount}",
                          price.label, None, None)
            )  # fmt: skip
            if safe is None:
                cautions.append(
                    Caution(
                        "value_left_out",
                        "A product description on the quote was left out of the script because "
                        "it holds contact details or text that is not safe to say.",
                    )
                )
                continue
            if spoken_lines < MAX_PRICE_LINES_IN_SCRIPT:
                text = PRICE_LINE[language].format(description=safe, amount=amount)
                script.append(ScriptLine("price", text, [price.label]))
                spoken_lines += 1
        total_amount = format_money(price.total, price.currency)
        known.append(KnownLine("price", "total", "Total", total_amount, price.label, None, None))
        script.append(
            ScriptLine(
                "price",
                PRICE_TOTAL[language].format(
                    amount=total_amount, valid_until=price.valid_until.isoformat()
                ),
                [price.label],
            )
        )
    for g in guesses:
        safe = _safe_value(g.value)
        known.append(
            KnownLine("assumption", g.key, g.label, safe or "[left out]", None, None, g.reason)
        )
        if safe is None:
            cautions.append(
                Caution(
                    "value_left_out",
                    f"The {g.label} assumption was left out of the script because it holds "
                    "contact details or text that is not safe to say.",
                )
            )
            continue
        label = _label(language, g.key, g.label)
        script.append(
            ScriptLine("question", QUESTION_LINE[language].format(label=label, value=safe), [g.key])
        )
    for key, value in form_wishes:
        label = _label("en", key, key.replace("_", " ").title())
        known.append(KnownLine("form", key, label, value, "lead_form", None, None))
    script.append(ScriptLine("closing", CLOSING[goal][language]))

    script = [ScriptLine(s.kind, s.text, s.cites, spoken_seconds(s.text)) for s in script]
    total = sum(words(s.text) for s in script)
    target = int(length_seconds * WORDS_PER_SECOND)
    if total > target:
        cautions.append(
            Caution(
                "script_too_long",
                f"The script has {total} words but {length_seconds} seconds holds about {target}. "
                "Choose a longer video or drop some lines.",
            )
        )
    if spoken_facts == 0:
        cautions.append(
            Caution(
                "no_facts",
                "No confirmed buyer facts yet - the script is generic. Confirm a detail first.",
            )
        )
    for code in banned_phrases_in(" ".join(s.text for s in script), competitors):
        cautions.append(
            Caution("banned_phrase", f"The script contains a banned kind of statement: {code}.")
        )

    return VideoBrief(
        first_name=name,
        language=language,
        tone=tone,
        tone_note=TONE_NOTES[tone],
        goal=goal,
        length_seconds=length_seconds,
        word_target=target,
        known=known,
        script=script,
        words=total,
        must_say=list(MUST_SAY),
        must_not_say=list(MUST_NOT_SAY),
        consent_notes=list(CONSENT_NOTES),
        cautions=cautions,
    )
