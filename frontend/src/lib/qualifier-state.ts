import type { QualifierTrial } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";

/**
 * What the Qualifier forms keep between attempts. They live here, not in the Server Actions
 * file: a "use server" file may export only async functions.
 */
export type SaveState = DialogState & { values: Record<string, string> };
export const initialSaveState: SaveState = {
  attempt: 0,
  fieldErrors: {},
  error: null,
  values: {},
};

export type TrialState = DialogState & {
  trial: QualifierTrial | null;
  values: Record<string, string>;
};
export const initialTrialState: TrialState = {
  attempt: 0,
  fieldErrors: {},
  error: null,
  trial: null,
  values: {},
};
