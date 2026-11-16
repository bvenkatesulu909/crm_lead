# Call transcription trial: sample scripts (ADR 0030, CA3)

The accuracy trial of call transcription needs a few short **fictional** recordings with the exact words that
were said. This page is the script to read aloud, so no real buyer's call is ever used. Nothing here is
measured yet: **no accuracy figure exists until the trial has been run** on these recordings.

## How to record

1. Use a phone voice recorder. Hold the phone as on a normal call, in a normal room (not a studio).
2. Read each script below once, at a natural speed, two people if possible (one reads "Rep", one "Buyer").
3. Record **one extra** version of the first script with some noise (a fan or a street window).
4. Save the files as `visit1.hi.m4a`, `visit2.hi.m4a`, `visit3.te.m4a`, `visit4.en.m4a`, `visit5.hi.m4a`
   (the middle part is the language the rep would choose: `hi`, `te` or `en`). Hinglish uses `hi`.
5. Next to each recording put a text file with the same name and `.txt` ending, holding **exactly** the words
   from the script (copy the script text; no speaker names).
6. Put them all in one folder, for example `C:\Users\<you>\call-samples`. Do not commit them.

## Scripts (all made up)

**visit1.hi - Hindi (Devanagari)**

> नमस्ते, मैं सनराइज प्रॉपर्टीज़ से बोल रहा हूँ। आपने दो बेडरूम वाले फ्लैट के बारे में पूछा था। आपका बजट कितना है? जी, मेरा बजट अस्सी लाख के आसपास है, और मुझे हैदराबाद में गाचीबोवली के पास चाहिए। ठीक है, मैं शनिवार को साइट विज़िट रख देता हूँ।

**visit2.hi - Hinglish (Hindi mixed with English)**

> Hello sir, main Sunrise Properties se bol raha hoon. Aapne two bedroom flat ke baare mein enquiry ki thi. Budget kitna rakha hai? Mera budget around eighty lakh hai, aur mujhe Gachibowli ke paas chahiye. Loan ka process bhi dekhna hai. Theek hai, main Saturday ko site visit fix kar deta hoon.

**visit3.te - Telugu**

> నమస్కారం, నేను సన్‌రైజ్ ప్రాపర్టీస్ నుంచి మాట్లాడుతున్నాను. మీరు రెండు పడకగదుల ఫ్లాట్ గురించి అడిగారు. మీ బడ్జెట్ ఎంత? నా బడ్జెట్ సుమారు ఎనభై లక్షలు, గచ్చిబౌలి దగ్గర కావాలి. సరే, శనివారం సైట్ విజిట్ పెడతాను.

**visit4.en - English (Indian accent, as spoken)**

> Hello, this is Sunrise Properties. You asked about a two bedroom flat. What budget do you have in mind? My budget is around eighty lakh rupees and I want something near Gachibowli. Fine, I will fix the site visit for Saturday and send you the brochure.

**visit5.hi - Hindi with numbers and a name**

> जी, मेरा नाम रमेश है और मेरा फ़ोन नंबर नौ आठ सात छह पाँच चार तीन दो एक शून्य है। मुझे एक करोड़ बीस लाख तक का तीन बेडरूम फ्लैट चाहिए, मार्च तक कब्ज़ा मिलना चाहिए।

The Hindi and Telugu wording was written by an AI assistant and **has not been read by a native speaker**.
Before the trial a Hindi speaker and a Telugu speaker should read it aloud once and fix anything that sounds
unnatural; the file `.txt` must then match what they actually say.

## Run it (Windows CMD, from the `backend` folder, virtual environment active)

Free check that the table works (the "hearing" is scripted, nothing is sent anywhere):

```
python -m scripts.measure_call_transcription C:\Users\<you>\call-samples --engine scripted
```

The real run needs ffmpeg installed on this PC and the speech service key in `backend\.env`, and spends a
little money per minute of audio (these five samples are about three minutes in all, a few rupees). It
refuses to start without the explicit switch:

```
set CRM_RUN_LIVE_EVALS=1
python -m scripts.measure_call_transcription C:\Users\<you>\call-samples --engine real --also-original
```

`--also-original` also sends the uncleaned audio, so the table shows whether the cleaning helps. The script
prints only sample names, error rates and seconds - never a key or a transcript.

## What to do with the result

Write the word and character error rates per language into `docs/call-recordings.md` with the date and the
engine name, say plainly that it is five short samples, and decide with the owner whether the rates are good
enough to tell a client that Hinglish and Telugu calls are supported. Until then the CRM says "automatic
transcript" next to every transcript, as it already does.
