# Voice receptionist trial: sentences to record (ADR 0038, round 2 of VR1)

The first measurement used a *synthetic* voice, so its Hindi and Telugu numbers are not trustworthy
(`docs/receptionist-voice-measurement.md`). This round needs **real people speaking on a phone**. The
sentences are made up; nothing here is a real buyer's call.

## What you need

* **One Hindi speaker and one Telugu speaker**, ideally native, plus (for English) either of you.
  Each reads their own language's three sentences, **twice**: once in a quiet room, once with a
  fan or street noise (that is how a visitor will sound).
* A phone voice recorder. Hold the phone as a visitor would, about a hand's length away.
* Each sentence is one short recording of 4-10 seconds.

## The sentences (read each one aloud once per recording)

Put each sentence in a text file named exactly like its recording, with **only the words said**.
If a speaker says it differently from the script (a more natural wording is welcome), **change the
text file to match what they really said**, because the score compares recording and text.

| File name (recording + text) | Language | Say this |
|---|---|---|
| `q1.hi` | Hindi | नमस्ते, मुझे हैदराबाद में दो बेडरूम का फ्लैट चाहिए। क्या स्काईलाइन टावर्स में अभी कोई फ्लैट उपलब्ध है? |
| `q2.hi` | Hindi | इसकी कीमत कितनी है और क्या यह रेरा में रजिस्टर्ड है? |
| `q3.hi` | Hindi | मेरा नाम रमेश है, मेरा नंबर नौ आठ सात छह पाँच चार तीन दो एक शून्य है, कृपया मुझे कल सुबह कॉल करें। |
| `q1.te` | Telugu | నమస్కారం, నాకు హైదరాబాద్‌లో రెండు పడకగదుల ఫ్లాట్ కావాలి. స్కైలైన్ టవర్స్‌లో ఇప్పుడు ఏదైనా ఫ్లాట్ అందుబాటులో ఉందా? |
| `q2.te` | Telugu | దాని ధర ఎంత, మరియు అది రెరాలో నమోదై ఉందా? |
| `q3.te` | Telugu | నా పేరు రమేష్, నా నంబర్ తొమ్మిది ఎనిమిది ఏడు ఆరు ఐదు నాలుగు మూడు రెండు ఒకటి సున్నా, దయచేసి రేపు ఉదయం కాల్ చేయండి. |
| `q1.en` | English | Hello, I want a two bedroom flat in Hyderabad. Is anything available at Skyline Towers right now? |
| `q2.en` | English | What is the price, and is it registered with RERA? |
| `q3.en` | English | My name is Ramesh, my number is nine eight seven six five four three two one zero, please call me tomorrow morning. |

The Hindi and Telugu wording was written by an AI assistant: **let the speaker fix anything that
sounds unnatural** (and fix the text file to match). A visitor will often mix English words into
Hindi ("call", "number", "flat"): leaving those in is realistic.

## Folder and names

One folder, for example `C:\Users\<you>\receptionist-samples`. For the quiet recordings use
`q1.hi.m4a` with `q1.hi.txt`; for the noisy ones add `n`: `q1n.hi.m4a` with `q1n.hi.txt` (same words).
Allowed audio: mp3, m4a, wav, ogg, webm, amr. Do not commit these files.

## Run it (Windows CMD, `backend` folder, virtual environment active)

Free check that the table works:

```
python -m scripts.measure_receptionist_voice C:\Users\<you>\receptionist-samples --engine scripted
```

Real run with the speech service in `backend\.env` (spends a few cents; refuses without the switch):

```
set CRM_RUN_LIVE_EVALS=1
python -m scripts.measure_receptionist_voice C:\Users\<you>\receptionist-samples --engine real
```

To compare a **second speech provider**, run the same folder again with another provider (a key
from that provider in `CRM_VOICE_API_KEY`; the models are the ones the service already knows):

```
set CRM_VOICE_PROVIDER=openai
set CRM_VOICE_BASE_URL=https://api.openai.com/v1
set CRM_VOICE_STT_MODEL=gpt-4o-mini-transcribe
set CRM_VOICE_TTS_MODEL=gpt-4o-mini-tts
set CRM_VOICE_TTS_VOICE=alloy
python -m scripts.measure_receptionist_voice C:\Users\<you>\receptionist-samples --engine real
```

Add your provider's prices to get a cost line: `--stt-price-per-minute <number>
--tts-price-per-1k-chars <number>` (copy them from the provider's price page; the script invents none).

## What to send back

Paste the printed table for each provider (it holds only names, rates and timings, never your
voice or a transcript). Then the numbers can replace the first, synthetic ones.

The scoring now counts spoken digits and written digits as the same (so a correctly heard phone number
is not marked wrong), but English words written in Latin letters inside a Hindi sentence still count as
errors, so the Hindi word error stays a little pessimistic; the character error is the fairer figure.
