/**
 * Which speech engine a voice conversation uses here (ADR 0023). Pure: tested without a browser.
 *
 * Order: the scripted engine in browser tests; otherwise the CRM's own speech service when it is
 * configured (one vendor the organisation chose); otherwise the browser's own speech, if the
 * organisation allows it (CRM_VOICE_BROWSER_ENGINE) and this browser can listen and speak.
 */

export type VoiceStatus = {
  enabled: boolean;
  browser_engine: boolean;
  server_engine: boolean;
  minutes_used: number;
  minutes_budget: number;
};

export type Capabilities = {
  canListen: boolean;
  canSpeak: boolean;
  canRecord: boolean;
  script: boolean;
};

export type Choice =
  | { kind: "browser" | "server" | "script" }
  | {
      kind: "none";
      reason:
        "off" | "browser_cannot_listen" | "needs_server" | "no_microphone";
    };

export function chooseEngine(
  status: VoiceStatus | null,
  caps: Capabilities,
): Choice {
  if (caps.script) return { kind: "script" };
  if (!status?.enabled) return { kind: "none", reason: "off" };
  if (status.server_engine) {
    if (caps.canRecord) return { kind: "server" };
    if (!status.browser_engine)
      return { kind: "none", reason: "no_microphone" };
  }
  if (!status.browser_engine) return { kind: "none", reason: "needs_server" };
  if (caps.canListen && caps.canSpeak) return { kind: "browser" };
  return { kind: "none", reason: "browser_cannot_listen" };
}

/** Plain words for why voice is not offered (none when it is simply switched off). */
export function unavailableText(reason: string): string | null {
  switch (reason) {
    case "browser_cannot_listen":
      return "This browser cannot listen (Firefox, for example). Use Chrome, Edge or Safari, or type your question.";
    case "needs_server":
      return "Voice needs the CRM's speech service, which is not set up yet. You can type your question.";
    case "no_microphone":
      return "This browser cannot record from the microphone. You can type your question.";
    default:
      return null;
  }
}

/** Who hears the audio, in plain words, shown before the microphone is first used. */
export function privacyText(kind: "browser" | "server" | "script"): string {
  if (kind === "server")
    return "Your voice is sent to the CRM's speech service to be turned into text, and the answers are turned into speech the same way. The CRM does not store the audio.";
  return "Your browser's own speech service turns your voice into text (Google in Chrome, Apple in Safari, Microsoft in Edge). The CRM never receives or stores the audio - only the text of your question.";
}

/** The status words shown (and read out by screen readers) while a conversation runs. */
export const STATE_TEXT = {
  idle: "",
  listening: "Listening… speak now",
  thinking: "Thinking…",
  speaking: "Speaking…",
} as const;
