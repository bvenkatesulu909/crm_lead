import type { ScriptRead } from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { GOAL_LABELS, TONE_LABELS, languageName } from "@/lib/video-brief";

/** The saved versions of a lead's buyer-video script, newest first (ADR 0041, VB3). Plain text. */
export function SavedScripts({ scripts }: { scripts: ScriptRead[] }) {
  return (
    <section aria-labelledby="saved-scripts" className="mt-8 print:hidden">
      <h2 id="saved-scripts" className="mb-2 text-lg font-semibold">
        Saved scripts
      </h2>
      {scripts.length === 0 ? (
        <p className="text-sm text-slate-600">No script saved yet.</p>
      ) : (
        <ul className="space-y-4">
          {scripts.map((s) => (
            <li
              key={s.id}
              aria-label={`Version ${s.version}`}
              className="rounded-md border border-slate-200 p-3 text-sm"
            >
              <p className="font-medium">
                Version {s.version}{" "}
                <span className="font-normal text-slate-500">
                  · {formatDateTime(s.created_at)} · {languageName(s.language)}{" "}
                  · {GOAL_LABELS[s.goal]} · {TONE_LABELS[s.tone]} ·{" "}
                  {s.length_seconds} seconds · {s.words} words
                </span>
              </p>
              <ol lang={s.language} className="mt-2 space-y-1">
                {s.lines.map((line, index) => (
                  <li key={index}>{line}</li>
                ))}
              </ol>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
