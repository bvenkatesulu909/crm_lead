# Voice receptionist: first measurement (ADR 0038, step VR1)

**What this is.** One spoken turn of the receptionist is *hear* (speech-to-text) -> *think* (the model) ->
*speak* (text-to-speech). `backend/scripts/measure_receptionist_voice.py` times each part on fictional
sentences and scores the hearing. It stores nothing and sets no limit.

**Run it** (Windows CMD, `backend` folder, virtual environment active). Free check of the table:

```
python -m scripts.measure_receptionist_voice C:\Users\<you>\vr1-samples --engine scripted --synthesize
```

Real run (spends a few cents; refuses without the switch). Add your provider's prices from its price page to
get a cost line:

```
set CRM_RUN_LIVE_EVALS=1
python -m scripts.measure_receptionist_voice C:\Users\<you>\vr1-samples --engine real --synthesize
```

Samples are `q1.hi.txt` (the words said) with an optional recording of a real person beside it
(`q1.hi.m4a`). Without a recording `--synthesize` makes one with the text-to-speech voice.

## Result of the first real run (2026-11-21, ElevenLabs speech, DeepSeek model, 9 fictional sentences)

| Language | Word error | Character error | Wait before first sound (average) |
|---|---|---|---|
| English | 0 % | 0 % | 3.1 s |
| Hindi | 30 % | 38 % | 5.4 s (one slow turn of 9.7 s) |
| Telugu | 75 % | 56 % | 4.0 s |

Median wait over 9 turns: **3.2 s**; slowest 9.7 s. Hearing took 1-2.5 s (one 7.3 s outlier), the model's
first sentence 0.7-2 s, speaking the first sentence 0.4-1.1 s. No cost figure: no prices were entered, and the
model's tokens are not included.

## How much to trust this (read before using the numbers)

- **The visitor was a synthetic voice**, not a person on a phone. That should make hearing *easier*, but the
  voice used is a multilingual voice that may itself pronounce Telugu badly, so part of the Telugu error may come
  from the voice and not from the listener. Only a real person reading the sentences settles it.
- **Hindi errors are mostly writing style, not mishearing.** The listener wrote "9876543210" and "number" /
  "call" in English letters where our reference had Hindi words, and the score counts that as wrong. The Hindi
  figure is therefore too pessimistic.
- **Telugu errors are real in places.** A name ("రమేష్") and some words were heard wrongly (for example the
  place word "టవర్స్" became "టీవీస్"), while the spoken digits in Telugu came back correct. The Telugu
  figure is therefore partly real.
- Nine sentences, one run, one provider: this shows the *kind* of problem, not a reliable percentage. The
  Telugu and Hindi sentences were written by an AI assistant and have not been read by native speakers.
- ffmpeg is not installed on this PC, so call length was assumed (6 s a turn) and would matter for a cost figure.

## What it means for the design (ADR 0038)

1. **A wait of about 3 s per turn is workable but not instant** (the ADR expected 2-4 s). The model is the
   smallest part; hearing and speaking dominate. A short spoken "one moment" is worth building.
2. **Never trust a heard name or place.** The receptionist must **read the phone number and the name back and
   ask the visitor to confirm** before `save_lead` (a confirmation step the prompt should require), and a name
   heard in Telugu should be kept as the visitor said it, flagged "from speech - check on the call-back".
3. **Telugu accuracy is the open risk**, exactly as the ADR said. Before the owner decides limits or go-live,
   repeat the measurement with **real recordings** (two people reading `docs/call-trial-samples.md`-style
   sentences on a phone) and compare at least one more speech provider and a Telugu-capable model.
4. Hearing digits as digits ("9876543210") is *good* for phone numbers; the scoring should later treat spoken
   numbers and digits as equal so the Hindi figure stops being misleading.

## Round 2 (real recordings)

The owner chose real recordings first (2026-11-22). The sentences to record, the folder layout, the commands and how to
compare a second speech provider are in `docs/receptionist-trial-samples.md`. The scoring now treats spoken and
written digits as equal (a correctly heard phone number is no longer marked wrong). Nothing has been recorded yet.

## Not done

No real-person recordings, no second provider, no price figures, no native-speaker review of the sentences,
no check on a phone browser. VR2 (the backend) should wait for the owner to look at these numbers.
