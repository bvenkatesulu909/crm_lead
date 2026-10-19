import type { ProblemDetails } from "@/lib/api-types";

/** A failed backend call, carrying the backend's own explanation (Problem Details). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: ProblemDetails,
  ) {
    super(problem.detail);
    this.name = "ApiError";
  }
}

/** Plain, serializable error info that can be passed to client components and forms. */
export type ApiErrorInfo = {
  status: number;
  message: string;
  code: string | null;
  requestId: string | null;
  fieldErrors: Record<string, string>;
};

const FRIENDLY: Record<number, string> = {
  401: "Your session has expired. Please sign in again.",
  403: "You don't have permission to do this.",
  404: "This item doesn't exist or you don't have access to it.",
  503: "The CRM service is temporarily unavailable. Please try again shortly.",
};

/** Turns a backend error into something a person can act on. */
export function toErrorInfo(error: unknown): ApiErrorInfo {
  if (error instanceof ApiError) {
    const fieldErrors: Record<string, string> = {};
    for (const item of error.problem.errors ?? []) {
      // ["body", "email"] -> "email"; the first message per field wins.
      const field = String(item.location[item.location.length - 1]);
      fieldErrors[field] ??= item.message.replace(/^Value error, /, "");
    }
    const useBackendText =
      error.status === 409 || error.status === 422 || error.status === 400;
    return {
      status: error.status,
      message: useBackendText
        ? error.problem.detail
        : (FRIENDLY[error.status] ?? error.problem.detail),
      code: error.problem.code ?? null,
      requestId: error.problem.request_id ?? null,
      fieldErrors,
    };
  }
  return {
    status: 0,
    message: "The CRM service could not be reached. Please try again.",
    code: null,
    requestId: null,
    fieldErrors: {},
  };
}
