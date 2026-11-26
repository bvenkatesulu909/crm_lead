/**
 * Rules of the voice receptionist on the public chat page (ADR 0038, step VR4), shared by the
 * call component and its route handler. Nothing here is secret: the server key and the
 * conversation token stay on the Next.js server.
 */
import type { ChatLanguage } from "@/lib/public-chat";

/** One spoken turn is a few seconds; the API refuses more than this (2 MB) unread. */
export const VOICE_MAX_AUDIO_BYTES = 2 * 1024 * 1024;
/** The kinds of audio a browser recorder produces (Chrome/Android: webm, Safari: mp4). */
export const VOICE_AUDIO_TYPES = [
  "audio/webm",
  "audio/mp4",
  "audio/ogg",
  "audio/wav",
  "audio/mpeg",
] as const;

/** Recording a turn: when to stop listening. */
export const VAD = {
  /** Quieter than this (0 to 1, root-mean-square) counts as silence. */
  threshold: 0.02,
  /** After speech, this much silence ends the turn. */
  silenceMs: 1400,
  /** A turn never lasts longer than this. */
  maxMs: 15000,
  /** No speech at all for this long: nothing was said. */
  noSpeechMs: 8000,
  /** Less speech than this is a cough, not a turn. */
  minSpeechMs: 400,
} as const;

export type VadResult = "continue" | "stop" | "nothing";

/**
 * Decides, level by level, when a spoken turn is over. Pure: the recorder feeds it the sound
 * level (0 to 1) and the time; it says keep going, stop and send, or stop because nothing was said.
 */
export function createVad(config: typeof VAD = VAD) {
  let startedAt: number | null = null;
  let speechStart: number | null = null;
  let lastSpeech: number | null = null;
  return {
    push(level: number, nowMs: number): VadResult {
      if (startedAt === null) startedAt = nowMs;
      if (level >= config.threshold) {
        if (speechStart === null) speechStart = nowMs;
        lastSpeech = nowMs;
      }
      if (nowMs - startedAt >= config.maxMs)
        return speechStart === null ? "nothing" : "stop";
      if (speechStart === null)
        return nowMs - startedAt >= config.noSpeechMs ? "nothing" : "continue";
      if (lastSpeech !== null && nowMs - lastSpeech >= config.silenceMs)
        return lastSpeech - speechStart >= config.minSpeechMs
          ? "stop"
          : "nothing";
      return "continue";
    },
  };
}

// --- What the API answers ----------------------------------------------------------------------

export type VoiceAnswer = {
  heard: string;
  reply: string;
  lead_saved: boolean;
  audio_base64: string | null;
  audio_type: string | null;
  seconds_left: number;
  turns_left: number;
  call_ended: boolean;
};
export type VoiceProblem = { code?: string; detail?: string };

/** The audio of a reply as something a browser can play, or null when there is none. */
export function audioBlob(answer: VoiceAnswer): Blob | null {
  if (!answer.audio_base64) return null;
  try {
    const binary = atob(answer.audio_base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: answer.audio_type || "audio/mpeg" });
  } catch {
    return null;
  }
}

// --- Words (ADR 0038): three languages. Written by an assistant: they need a native read-through.

export type VoiceText = {
  talk: string;
  noticeTitle: string;
  notice: string;
  listenNotice: string;
  start: string;
  cancel: string;
  end: string;
  greeting: string;
  listening: string;
  thinking: string;
  speaking: string;
  heardNothing: string;
  micDenied: string;
  noMic: string;
  ended: string;
  consentAgain: string;
  limitCall: string;
  limitDay: string;
  failed: string;
};

export const VOICE_TEXT: Record<ChatLanguage, VoiceText> = {
  en: {
    talk: "Talk to us",
    noticeTitle: "Before we talk",
    notice:
      "You are about to talk to an automated assistant, not a person. What you say is turned into " +
      "text by our speech service and the conversation may be saved together with the details you " +
      "give. We do not keep your voice recording. Please do not say card numbers, bank details, " +
      "ID numbers or one-time passwords.",
    listenNotice: "Listen to this notice",
    start: "I understand - start the call",
    cancel: "Not now",
    end: "End the call",
    greeting:
      "Hello, I am an automated assistant. How can I help you find a home?",
    listening: "Listening… speak now",
    thinking: "One moment…",
    speaking: "Speaking…",
    heardNothing:
      "I could not hear anything. Please try again, or type your message below.",
    micDenied:
      "The microphone is blocked. Please allow it in your browser, or type your message below.",
    noMic: "No microphone was found. Please type your message below instead.",
    ended: "The call has ended. You can keep typing below.",
    consentAgain: "Please read the notice and start the call again.",
    limitCall:
      "This call reached its time limit. Please leave your number below, or call us.",
    limitDay:
      "You have made several calls today. Please try again tomorrow, or type below.",
    failed:
      "Something went wrong with the call. Please type your message below.",
  },
  hi: {
    talk: "हमसे बात करें",
    noticeTitle: "बात शुरू करने से पहले",
    notice:
      "आप एक स्वचालित सहायक से बात करने वाले हैं, किसी व्यक्ति से नहीं। आप जो कहेंगे उसे हमारी स्पीच सेवा " +
      "लिखित शब्दों में बदलेगी और बातचीत आपके दिए विवरण के साथ सहेजी जा सकती है। हम आपकी आवाज़ की " +
      "रिकॉर्डिंग नहीं रखते। कृपया कार्ड नंबर, बैंक विवरण, पहचान पत्र नंबर या वन-टाइम पासवर्ड न बोलें।",
    listenNotice: "यह सूचना सुनें",
    start: "मैं समझ गया/गई - कॉल शुरू करें",
    cancel: "अभी नहीं",
    end: "कॉल समाप्त करें",
    greeting:
      "नमस्ते, मैं एक स्वचालित सहायक हूँ। मैं आपको घर ढूँढने में कैसे मदद कर सकता हूँ?",
    listening: "सुन रहे हैं… अब बोलिए",
    thinking: "एक क्षण…",
    speaking: "बोल रहे हैं…",
    heardNothing:
      "कुछ सुनाई नहीं दिया। कृपया दोबारा कोशिश करें, या नीचे अपना संदेश लिखें।",
    micDenied:
      "माइक्रोफ़ोन बंद है। कृपया अपने ब्राउज़र में अनुमति दें, या नीचे संदेश लिखें।",
    noMic: "माइक्रोफ़ोन नहीं मिला। कृपया नीचे अपना संदेश लिखें।",
    ended: "कॉल समाप्त हो गई। आप नीचे लिखना जारी रख सकते हैं।",
    consentAgain: "कृपया सूचना पढ़ें और कॉल फिर से शुरू करें।",
    limitCall:
      "इस कॉल का समय पूरा हो गया। कृपया नीचे अपना नंबर छोड़ें, या हमें कॉल करें।",
    limitDay:
      "आपने आज कई कॉल कर ली हैं। कृपया कल फिर कोशिश करें, या नीचे लिखें।",
    failed: "कॉल में कुछ गड़बड़ हुई। कृपया नीचे अपना संदेश लिखें।",
  },
  te: {
    talk: "మాతో మాట్లాడండి",
    noticeTitle: "మాట్లాడే ముందు",
    notice:
      "మీరు ఒక ఆటోమేటెడ్ అసిస్టెంట్‌తో మాట్లాడబోతున్నారు, మనిషితో కాదు. మీరు చెప్పేది మా స్పీచ్ సేవ " +
      "అక్షరాలుగా మారుస్తుంది, మరియు సంభాషణ మీరు ఇచ్చే వివరాలతో పాటు నిల్వ చేయబడవచ్చు. మేము మీ గొంతు " +
      "రికార్డింగ్‌ను ఉంచుకోము. దయచేసి కార్డ్ నంబర్లు, బ్యాంక్ వివరాలు, ID నంబర్లు లేదా వన్-టైమ్ పాస్‌వర్డ్‌లు చెప్పవద్దు.",
    listenNotice: "ఈ నోటీసు వినండి",
    start: "అర్థమైంది - కాల్ మొదలుపెట్టండి",
    cancel: "ఇప్పుడు కాదు",
    end: "కాల్ ముగించండి",
    greeting:
      "నమస్కారం, నేను ఒక ఆటోమేటెడ్ అసిస్టెంట్‌ని. ఇల్లు వెతకడంలో నేను మీకు ఎలా సహాయం చేయగలను?",
    listening: "వింటున్నాము… ఇప్పుడు మాట్లాడండి",
    thinking: "ఒక్క క్షణం…",
    speaking: "చెబుతున్నాము…",
    heardNothing:
      "ఏమీ వినిపించలేదు. దయచేసి మళ్లీ ప్రయత్నించండి, లేదా కింద మీ సందేశం రాయండి.",
    micDenied:
      "మైక్రోఫోన్ నిలిపివేయబడింది. దయచేసి మీ బ్రౌజర్‌లో అనుమతించండి, లేదా కింద సందేశం రాయండి.",
    noMic: "మైక్రోఫోన్ కనిపించలేదు. దయచేసి కింద మీ సందేశం రాయండి.",
    ended: "కాల్ ముగిసింది. మీరు కింద రాయడం కొనసాగించవచ్చు.",
    consentAgain: "దయచేసి నోటీసు చదివి కాల్‌ను మళ్లీ మొదలుపెట్టండి.",
    limitCall:
      "ఈ కాల్ సమయం పూర్తయింది. దయచేసి కింద మీ నంబర్ ఇవ్వండి, లేదా మాకు కాల్ చేయండి.",
    limitDay:
      "మీరు ఈ రోజు చాలా కాల్స్ చేశారు. దయచేసి రేపు ప్రయత్నించండి, లేదా కింద రాయండి.",
    failed: "కాల్‌లో ఏదో తప్పు జరిగింది. దయచేసి కింద మీ సందేశం రాయండి.",
  },
};

/** What the visitor reads when a turn could not be answered, and whether the call is over. */
export function voiceErrorText(
  language: ChatLanguage,
  status: number,
  code?: string,
  detail?: string,
): { text: string; endsCall: boolean } {
  const words = VOICE_TEXT[language];
  if (code === "voice_consent_required")
    return { text: words.consentAgain, endsCall: true };
  if (code === "voice_heard_nothing")
    return { text: words.heardNothing, endsCall: false };
  if (code === "voice_limit_reached")
    // The API's own sentence says which limit it was (the call's time or the day's calls).
    return {
      text: /today|tomorrow/i.test(detail ?? "")
        ? words.limitDay
        : words.limitCall,
      endsCall: true,
    };
  // A refused sentence (a card number said aloud) explains itself and the call goes on.
  if (status === 422 && code === "message_refused" && detail)
    return { text: detail, endsCall: false };
  return { text: words.failed, endsCall: true };
}
