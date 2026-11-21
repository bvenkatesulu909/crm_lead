# Video briefs (ADR 0041)

The CRM writes the **brief** for a personalised video to a buyer; a person or a tool the organisation trusts
makes the video. Nothing in the CRM creates a video, an avatar or audio.

## What VB1 does (built 2026-11-21)

`GET /api/v1/leads/{lead_id}/video-brief?goal=&language=&tone=&length=` builds a brief on demand. Nothing is
stored and nothing is written (a test counts the rows).

| Choice | Values | Default |
|---|---|---|
| `goal` | introduce, follow_up, after_visit, explain_quote, revive | follow_up |
| `language` | en, hi, te | the lead's preferred language, else en |
| `tone` | warm, professional, brisk | warm |
| `length` | 30, 60, 90 (seconds; about 75 / 150 / 225 words) | 60 |

The answer holds: the buyer's **first name only**, the facts it knows (each marked **fact**, **assumption** or
**lead form**, with its source and quote), a **script** (greeting, intro for the goal, up to five fact lines,
one question per assumption, a closing for the goal), the fixed **must say** and **must not say** lists, the
**consent notes**, and **cautions**.

## The rules that keep it honest

- A buyer-memory **fact** may be spoken as a statement. An **assumption** is only ever a question ("Is ... still
  right for ...?"). What the lead form says is shown but never spoken.
- A value with a phone number, e-mail address, card number or instruction is left out and reported.
- Links, markup and hidden characters in stored values are cleaned before they reach the script.
- The phone number, e-mail address and last name never appear in the answer.
- A script longer than the chosen length gets the caution `script_too_long`.
- Banned kinds of statement (guaranteed returns, false urgency, religion, health, a named competitor) are
  detected by `rules.banned_phrases_in`; the built script is checked with it.

## Who may ask

Permission `video_brief:read` (sales agents, managers, administrators) **and** the lead's own read rules: a lead
the person may not read is a 404, exactly like a lead that does not exist. Support staff and customers get 403.

## Tests

`tests/test_video_brief_rules.py` (30 pure tests) and `tests/db/test_video_brief_api.py` (15 tests: roles,
colleague, other organisation, made-up ids, no data leaked, nothing written).

## Not yet built

Quote and brochure price facts (VB1b), the screen and print page (VB2), hand-written scripts and stored approved
scripts (VB3), the governed model draft (VB4), the approval kind (VB5), evaluation cases (VB6). The Hindi and
Telugu words need a native-speaker read-through.
