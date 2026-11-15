# ADR 0033 — Highlight clips from recorded sales calls

- **Status:** Proposed (2026-11-15; waits for the owner's answers in section 6)
- **Date:** 2026-11-15
- **Deciders:** Project owner
- **Depends on:** ADR 0030 (call recordings, the cleaned copy and the timestamped transcript), ADR 0025
  (signed links), ADR 0009 (RLS), ADR 0017/0018 (cleaning of untrusted text), ADR 0016 (agent registry)
- **Master plan:** BP-25 (sales-call highlight clips)

## 1. The problem

A 20-minute call holds two moments that matter: the buyer says their real budget, or they say what is
stopping them. Today anyone who wants to hear those moments - a manager coaching a rep, a colleague taking
over the lead - has to play the whole call. A **clip** is a short piece of the call, with its few lines of
transcript and a title, kept with the lead.

## 2. What exists (ADR 0030)

Call recordings on a lead with the buyer's recorded consent, a cleaned listening copy next to the original,
a timestamped transcript (segments with start and end times), 60-second signed listening links, retention
(90 days for the audio) and a switch (`call_audio`, off by default). ffmpeg runs in the worker. No clips.

## 3. Decisions (proposed)

**CL1 - A person picks the moment; no AI picks it in v1.** On a ready recording the rep or manager selects a
start and an end (by clicking transcript lines or typing the times), gives the clip a title and an optional
note. A later step may let an AI **propose** moments through the approval queue (ADR 0014); nothing here
reads a transcript with a model.

**CL2 - One table, `call_clips`, one file per clip.** The recording and lead it belongs to, who made it, start
and end in milliseconds (at least 3 and at most 120 seconds, inside the recording), a title (up to 100
characters), a note (up to 500), the transcript lines inside the range (copied and cleaned), a status
(`queued`, `ready`, `failed` with a reason code), the clip's duration and the key of its audio file. Forced
RLS. A clip never changes after it is `ready` (title and note may be edited by its maker; a database
trigger refuses any other change).

**CL3 - Cut in the worker from the cleaned copy, never from the original.** A job `call.clip` runs ffmpeg with
`-ss`/`-to` on the cleaned listening copy and writes a small mp3 (64 kbit/s). Safe to run twice; a recording
whose audio was already deleted gives `audio_deleted`; limits of 20 clips per recording and 100 per
organisation per day. A clip uses no speech minutes (no transcription happens).

**CL4 - Same access as the recording, and it stays inside the CRM.** Making a clip needs `call:write`;
listening and reading need `call:read` and the right to read the lead (else 404). Listening is a 60-second
signed link, audited like recordings. There is **no public or shareable link** in v1: a colleague opens the
lead page. Deleting a clip is allowed to its maker and to managers and tenant admins, audited with ids only.

**CL5 - Consent and retention are inherited.** A clip exists only for a recording with stored consent; when
the recording's audio is deleted (retention or by hand) its clips' audio is deleted with it and each clip
becomes "audio deleted" (the title, note and transcript lines stay with the lead, like the transcript does).
Deleting the recording's transcript rules of ADR 0030 apply to the clip's lines too.

**CL6 - The same switch.** Clips are part of call audio: the `call_audio` switch, permissions and privacy
notice cover them. No new agent entry (no model).

**CL7 - Untrusted text.** The title, the note and the transcript lines are cleaned with the shared screening
(links, markup and hidden text out; an instruction-like text is kept but reported) and shown as plain text.

## 4. What this does not do

No AI-picked highlights, no video, no speaker labels, no editing or merging of clips, no sharing outside the
CRM, no translation, no clips of recordings without consent, no clips longer than 120 seconds.

## 5. Steps (Phase CL), each stops for review

| Step | Content |
|---|---|
| CL0 | This ADR and the owner's answers |
| CL1 | Backend: migration `call_clips` (forced RLS, locks), pure rules (range, lengths, cleaning), API create / list / edit / delete / listen link, permissions, audit, limits; tests |
| CL2 | The worker job `call.clip` with ffmpeg (fake cutter in tests, one real ffmpeg test), `audio_deleted` handling, retention hook; tests and deliberate breaks |
| CL3 | Screens on the lead page (pick a range on the transcript, title, player, list, delete), a Playwright journey with the scripted engine, docs |

## 6. Questions for the owner (recommended answer first)

1. **Who picks the moment.** *Recommended:* a person, in v1; AI suggestions later through the approval queue.
   Alternative: AI picks highlights from the start (needs an AI agent, budget and approval flow).
2. **Size.** *Recommended:* 3-120 seconds, 20 clips per recording, 100 per organisation per day.
   Alternative: your numbers.
3. **Source and retention.** *Recommended:* cut from the cleaned copy, deleted together with the recording's
   audio (the lines stay). Alternative: clips kept longer than the recording (needs a separate consent).
4. **Sharing.** *Recommended:* inside the CRM only (signed 60-second links, lead page). Alternative: a shareable
   link for people without a login (needs a legal review and an expiry design).
5. **Switch.** *Recommended:* reuse `call_audio`, no new switch. Alternative: a separate switch for clips.
6. **Where it shows.** *Recommended:* on the lead page under the recording. Alternative: also a "Clips" page
   for managers to browse all clips (adds a list endpoint and a permission rule).

## 7. Consequences

- Managers can coach and colleagues can take over a lead by listening to two minutes instead of twenty.
- One more table and one more worker job; no new dependency (ffmpeg is already in the image).
- A clip is a copy of a buyer's voice: hence inherited consent, deletion with the recording, no public link.
