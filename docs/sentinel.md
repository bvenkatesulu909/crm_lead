# Sentinel and input screening (BP-21, ADR 0017)

A deterministic second check on every AI proposal, plus one function that cleans untrusted text.
**Status:** step SN1 - the rules and the screening function exist and are tested as pure
functions. Nothing calls them yet: `propose()` is hooked up in SN2, the guardrails and the staff
prompt in SN3. On screen it will be called "Safety check".

## Screening (`app/core/screening.py`)

`screen(text)` returns the text cleaned and what it found. It takes out of the clean text: hidden
and control characters (including ASCII hidden as "tag" characters), HTML comments, scripts and
tags, images, links and e-mail addresses (each replaced by a visible marker such as
`[link removed]`), and text that repeats itself (a line more than 5 times, a word more than 20 in
a row, one character more than 200 times). It only *reports* phrases that read like instructions
to an AI (`instruction_phrase`) - deleting words would change their meaning. Findings carry a
stable code and a sentence and never repeat the text they found.

Zero-width joiners inside Indic scripts (Telugu, Hindi) are ordinary and kept; a joiner next to
Latin letters or several in a row is hidden text.

## The rules (`app/modules/approvals/sentinel.py`)

`verify(candidate, facts, limits)` runs five groups and returns a verdict (findings + the groups
checked). A **block** refuses the proposal, a **warning** is stored and shown to the approver.

| Group | Block | Warn |
|---|---|---|
| words (reason, task subject) | every screening finding: link, e-mail address, markup, external image, hidden / control characters, instruction phrase, repeated text | phone-number-like digits |
| pattern | identical proposal already waiting; 10 proposals / hour; 3 assignments / hour | 3 or more proposals for one record in a day |
| state | any change to a converted lead; a status "change" to the same status | qualified -> unqualified; assigning a lead someone else owns; a task for someone other than the asker |
| tenant | record or assignee of another organisation | |
| the record's own text | the reason repeats an instruction found in the record | the record contains an instruction, hidden text or a link |

A rule that raises makes the verdict a block (`sentinel_error`): it fails closed. At approval
(`recheck=True`) only the state and tenant groups run again. `Verdict.to_json()` is what will be
stored with an accepted proposal: groups and warnings, never record text.

## The attack library (`backend/evals/attacks/library.json`)

55 texts in six families: instructions (13), hidden characters (9), links / images / markup /
addresses (13), floods (3), a phone number (1) and 16 ordinary texts (English, Telugu, Hindi,
rupee amounts, "ignore the noise", "act on it") that must pass untouched. Each case says exactly
which findings are expected and what must be gone from the clean text. Both test files read it, so
a new attack is one line of JSON.

Tests: `tests/test_screening.py` (199), `tests/test_sentinel.py` (89). With the link rule and one
instruction pattern switched off, 19 of them fail.
