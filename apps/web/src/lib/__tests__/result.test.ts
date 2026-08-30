import { describe, expect, it } from "vitest";

import { isOk, parseErrorBody, type ApiResult } from "@/lib/api/result";

describe("parseErrorBody", () => {
  it("extracts a reason code from PACTRA's structured refusal body", () => {
    const parsed = parseErrorBody({
      detail: {
        reason_code: "AUTHORIZATION_REPLAY_DETECTED",
        detail: "the authorization was already consumed",
      },
    });
    expect(parsed.reasonCode).toBe("AUTHORIZATION_REPLAY_DETECTED");
    expect(parsed.detail).toBe("the authorization was already consumed");
  });

  it("handles FastAPI's plain-string 404 detail without inventing a code", () => {
    const parsed = parseErrorBody({ detail: "mission not found" });
    expect(parsed.reasonCode).toBeNull();
    expect(parsed.detail).toBe("mission not found");
  });

  it("reads the state field a conflict body carries instead of a detail", () => {
    const parsed = parseErrorBody({
      detail: { reason_code: "MISSION_NOT_AWAITING_APPROVAL", state: "AUTHORIZED" },
    });
    expect(parsed.reasonCode).toBe("MISSION_NOT_AWAITING_APPROVAL");
    expect(parsed.detail).toBe("state: AUTHORIZED");
  });

  it("returns a null reason code rather than guessing one from an unknown shape", () => {
    const parsed = parseErrorBody({ unexpected: true });
    expect(parsed.reasonCode).toBeNull();
  });

  it("accepts a bare string body", () => {
    expect(parseErrorBody("upstream exploded").detail).toBe("upstream exploded");
  });
});

describe("ApiResult", () => {
  it("keeps 'unavailable' distinct from 'failed' so empty never reads as down", () => {
    const unreachable: ApiResult<number> = { kind: "unavailable", detail: "connection refused" };
    const refused: ApiResult<number> = {
      kind: "failed",
      status: 409,
      reasonCode: "NO_AUTHORIZATION",
      detail: "no authorization to spend",
    };
    expect(isOk(unreachable)).toBe(false);
    expect(isOk(refused)).toBe(false);
    expect(unreachable.kind).not.toBe(refused.kind);
  });

  it("narrows to the payload on success", () => {
    const result: ApiResult<{ id: string }> = {
      kind: "ok",
      status: 200,
      data: { id: "m-1" },
    };
    expect(isOk(result) && result.data.id).toBe("m-1");
  });
});
