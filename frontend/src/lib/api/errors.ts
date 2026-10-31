// SPDX-FileCopyrightText: 2026 Siddharth Majhi
// SPDX-License-Identifier: MIT
/**
 * One error type for every failed API call, parsed from the backend contract
 * `{"error": {"code", "message", "request_id", ...}}` (see `backend/app/api/errors.py`).
 */

export interface ValidationDetail {
  loc: string[];
  msg: string;
}

/** Codes produced by the client itself, when the server gave no contract error body. */
export type ClientErrorCode = "NETWORK_ERROR" | "UNEXPECTED_RESPONSE";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: ValidationDetail[];

  constructor(options: {
    status: number;
    code: string;
    message: string;
    requestId?: string | null;
    details?: ValidationDetail[];
  }) {
    super(options.message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId ?? null;
    this.details = options.details ?? [];
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseDetails(value: unknown): ValidationDetail[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): ValidationDetail[] => {
    if (!isRecord(item) || typeof item.msg !== "string") return [];
    const loc = Array.isArray(item.loc) ? item.loc.map((part) => String(part)) : [];
    return [{ loc, msg: item.msg }];
  });
}

/**
 * Builds an `ApiError` from a non-2xx response body. Bodies that do not follow the contract (a
 * proxy's HTML page, an empty body) become `UNEXPECTED_RESPONSE` with the HTTP status kept, so the
 * UI never invents a code the server did not send.
 */
export function parseApiError(status: number, body: unknown, requestIdHeader?: string | null) {
  const error = isRecord(body) ? body.error : undefined;
  if (isRecord(error) && typeof error.code === "string" && typeof error.message === "string") {
    const requestId = typeof error.request_id === "string" ? error.request_id : requestIdHeader;
    return new ApiError({
      status,
      code: error.code,
      message: error.message,
      requestId: requestId ?? null,
      details: parseDetails(error.details),
    });
  }
  return new ApiError({
    status,
    code: "UNEXPECTED_RESPONSE" satisfies ClientErrorCode,
    message: `The server responded with HTTP ${status} and no error details.`,
    requestId: requestIdHeader ?? null,
  });
}

export function networkError(cause: unknown): ApiError {
  const error = new ApiError({
    status: 0,
    code: "NETWORK_ERROR" satisfies ClientErrorCode,
    message: "The DentalVoice API could not be reached. Check that the backend is running.",
  });
  error.cause = cause;
  return error;
}

/** Normalises anything thrown by an API call into an `ApiError`. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError({
    status: 0,
    code: "UNEXPECTED_RESPONSE" satisfies ClientErrorCode,
    message: error instanceof Error ? error.message : "Something went wrong.",
  });
}
