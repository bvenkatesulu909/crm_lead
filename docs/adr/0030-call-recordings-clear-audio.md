# ADR 0030 — Call recordings: clear audio and transcripts in Hinglish and Telugu

- **Status:** Accepted (2026-11-13, owner: "Approve, build CA1"). CA1 built 2026-11-13; the provider's `language` and timestamps move to CA2.
- **Date:** 2026-11-12
- **Deciders:** Project owner
- **Depends on:** ADR 0025 (large files straight to the store through signed links), ADR 0012 (the
  speech provider abstraction), ADR 0027 (Hindi and Telugu), ADR 0016 (agent registry: switch and
  budget), ADR 0017/0018 (cleaning of untrusted text), ADR 0028 (buyer memory)
- **Used by:** "clips of key moments from sales calls" (a later item) and, later, call summaries that
  propose buyer memory entries

## 1. The problem

Most of a home sale happens on the phone, in Hindi mixed with English ("Hinglish") or in Telugu, on a noisy
line. Today a call leaves, at best, one line typed by the rep. What was really said - the budget, the worry
about the loan, the date they mentioned - is lost, and nobody can listen again or search for it.

"Clear call audio" means three things: the recording is **kept with the lead**, it is **cleaned** so a person
can actually hear it, and it has a **transcript** in the language it was spoken.

## 2. What exists

- A speech provider abstraction with an OpenAI-compatible Whisper-style client and a local engine; today only
  for short staff voice questions (10 MB upload limit, English only for the local engine).
- Large uploads go straight to the file store with signed links (ADR 0025); the CRM then reads the file back
  once to check it. A worker with retries, outbox jobs and retention sweeps.
- Buyer memory (ADR 0028) to hold what a call teaches; the lead timeline for notes and calls.
- No telephony, no call records, no audio processing (no ffmpeg anywhere in the repository).

## 3. Decisions (proposed)

**CA1 - v1 handles uploaded recordings, not live calling.** A rep adds a call recording to a lead (the file
their phone's call recorder or their calling provider produced). The CRM does not place or receive calls in
v1. "Calling in Hinglish and Telugu" through a telephony provider (Exotel, Twilio, a SIM-based service) needs
the owner's account, numbers and a legal review, and is a separate decision with its own ADR.

**CA2 - One module, `calls`, one table, files in the file store.** `call_recordings`: the lead, who added it
and when, the language the rep says was spoken (`hi`, `te` or `en`), the **consent record** (see CA5), a
status (`uploading`, `queued`, `processing`, `ready`, `failed` with a reason code), the duration, the keys of
the original file and of the cleaned copy, the transcript text, its segments with start and end times (so
later clips can point at a moment) and which engine wrote it. The file goes straight to the store through a
signed link (recordings are often bigger than the web host's 6 MB request limit), then a `finish` call
checks it (type by content, size, duration) exactly as for documents. The tenant comes only from the
verified token; the lead is loaded through the leads module, so a person only reaches the recordings of a
lead they may read (else 404).

**CA3 - Cleaning with ffmpeg, in the worker; the original is always kept.** The worker makes two copies: a
mono 16 kHz file for the speech engine, and a **listening copy** with a high-pass filter, noise reduction and
loudness normalisation. Both are labelled ("cleaned copy"); the original stays untouched. ffmpeg becomes a
new dependency of the worker image (size and licence noted in the docs); without it on a developer's PC the
cleaning step is skipped and the recording says so.

**CA4 - Transcripts from a hosted Whisper-class model, with a language hint.** The existing provider
abstraction gains a `language` hint (`hi`, `te`, `en`) and timestamps. A transcript is the engine's own
output in the script it produces (Hindi comes out in Devanagari with English words kept; Telugu in Telugu
script) and is always shown with "Automatic transcript - may contain mistakes". Accuracy for Telugu and for
Hinglish on noisy phone audio is the real risk; it is measured on a small fictional sample before the feature
is called done, and the result is written in the docs. A local engine is the alternative for organisations that
cannot send audio out.

**CA5 - Consent, access and retention.** The form has a required checkbox - "the buyer agreed to this call
being recorded" - and the CRM stores who ticked it and when; without it nothing is accepted. Recordings and
copies are deleted after a retention period (default 90 days, set by the organisation); transcripts follow the
lead's own retention. Only people who may read the lead **and** hold `call:read` can listen or read; adding one
needs `call:write`. Listening uses a 60-second signed link (ADR 0025). Every add, listen and delete is audited
with ids only. A recording of a buyer is personal data: nothing is shared outside the CRM, and the speech
vendor is named in the privacy notice.

**CA6 - Limits and a switch.** At most 60 minutes and 100 MB per recording; mp3, m4a, wav, ogg, webm and amr
(checked by content, not by name); a per-person and per-organisation limit per hour; a monthly **minutes**
budget and an on/off switch in the agent registry (entry `call_audio`, no language model, **off by default**,
like voice). The platform kill switch for AI does not apply (no model), a separate switch for speech does.

**CA7 - A transcript is untrusted text, and no model reads it in v1.** The transcript is screened (links,
markup and hidden text removed; instruction-like text kept but reported), shown as plain text and never given
to an assistant. A later step may let an AI **propose** buyer memory entries from a transcript - as
assumptions only, through the approval queue (ADR 0014, ADR 0028).

## 4. What this does not do

No live calling or telephony, no call recording inside the CRM, no speaker identification, no AI summary or
buyer-memory suggestions, no clips (the next item builds on the timestamped transcript), no sharing outside
the CRM, no translation.

## 5. Steps (Phase CA), each stops for review

| Step | Content |
|---|---|
| CA0 | This ADR (documents only) |
| CA1 | Backend: migration `call_recordings` (forced RLS), pure rules, signed upload start / finish, status flow, permissions, audit, settings, the registry entry `call_audio` (**done 2026-11-13**; `language` and timestamps in the speech provider moved to CA2) |
| CA2 | The worker: ffmpeg cleaning, transcription with the language hint, retries, retention sweep; tests with a fake engine and a fake cleaner, one real ffmpeg test (**built 2026-11-13**; see docs/call-recordings.md) |
| CA3 | The lead page card (add a recording, status, player for the cleaned copy, transcript), a Playwright journey, docs, and a measured trial on a small fictional Hindi, Hinglish and Telugu sample |

## 6. Questions for the owner (recommended answer first)

1. **Scope of v1.** *Recommended:* uploaded recordings only; live calling is a separate later decision.
   Alternative: build telephony now (needs your provider account and a legal review first).
2. **Speech engine.** *Recommended:* a hosted Whisper-class model behind the existing provider abstraction,
   with a local engine as the option for data that must stay in-house. Alternative: local only (slower, needs
   a bigger server).
3. **Cleaning.** *Recommended:* yes, with ffmpeg in the worker; original always kept. Alternative: send the raw
   file to the engine and play the raw file.
4. **Consent and retention.** *Recommended:* a required consent checkbox that is stored, 90 days for the audio
   (the organisation can change it), transcripts with the lead. Alternative: no retention limit (not
   recommended) or no audio kept, transcript only.
5. **Languages.** *Recommended:* Hindi (including Hinglish), Telugu and English, chosen by the rep.
   Alternative: automatic language detection (less reliable on mixed speech).
6. **Limits.** *Recommended:* 60 minutes, 100 MB, a minutes budget, switched off until an administrator turns
   it on. Alternative: your numbers.
7. **AI on transcripts.** *Recommended:* none in v1; later, only suggestions through approval. Alternative:
   summaries from the start.

## 7. Consequences

- A call becomes something a rep and a manager can listen to again (cleaned) and read, in the language it was
  spoken, attached to the lead.
- One more module and table, ffmpeg in the worker image, and a speech vendor that hears buyers' voices - hence
  the consent record, the retention and the privacy note.
- Quality on noisy Telugu and Hinglish audio is uncertain until measured; the transcript is always labelled as
  automatic.
- The timestamped transcript is the foundation for the key-moment clips and the buyer memory suggestions that
  come next.
