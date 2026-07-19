/**
 * FE-021 — Red tests for the OCR typed wrapper (BE-024 `POST /api/v1/ocr`).
 *
 * These mirror the FE-020 practice wrapper tests: stub `fetch`, assert the
 * wire shape (multipart, MIME/size guardrails, Bearer auth) and the typed
 * `{ data, error, response }` result shape.
 */
import { saveServerUrl } from "@pymentor/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { commandHeaders, configureStudentApi } from "../../student-api";
import { MAX_OCR_FILE_BYTES, OCR_ACCEPTED_MIME, submitOcr } from "./ocr-api";

function ocrJson(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  window.localStorage.clear();
  saveServerUrl("https://api.example.test");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  configureStudentApi();
});

afterEach(() => vi.unstubAllGlobals());

function pngFile(bytes = 0x100): File {
  // 256-byte PNG-ish blob; the wrapper only inspects type/size, not the bytes.
  return new File([new Uint8Array(bytes)], "error.png", { type: "image/png" });
}

describe("FE-021 ocr-api submitOcr", () => {
  it("POSTs multipart/form-data to /api/v1/ocr with Bearer + idempotency key and returns extracted_text", async () => {
    fetchMock.mockResolvedValueOnce(
      ocrJson({
        extracted_text: "IndexError: list index out of range",
        confidence: 0.92,
        mime: "image/png",
        size_bytes: 0x100,
      }),
    );
    const file = pngFile();
    const result = await submitOcr({
      body: { file },
      headers: commandHeaders("student-access", "ocr-screenshot"),
    });

    expect(result.response.status).toBe(200);
    expect(result.data?.extracted_text).toBe(
      "IndexError: list index out of range",
    );
    expect(result.data?.confidence).toBeCloseTo(0.92);
    expect(result.data?.mime).toBe("image/png");
    expect(result.data?.size_bytes).toBe(0x100);

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toBe("https://api.example.test/api/v1/ocr");
    expect(request.method).toBe("POST");
    expect(request.headers.get("Authorization")).toBe("Bearer student-access");
    expect(request.headers.get("Idempotency-Key")).toMatch(/^ocr-screenshot-/);
    // The wrapper must NOT force `application/json` on a multipart body — it
    // drops the runtime default so the browser can stamp the boundary. We
    // don't assert an exact Content-Type because jsdom labels FormData
    // differently than real browsers; the load-bearing checks are (a) we did
    // not send JSON and (b) the request carries a body (the file part).
    expect(request.headers.get("Content-Type") ?? "").not.toMatch(
      /^application\/json/,
    );
    // The request was built from a FormData body, so a body stream is
    // attached. `request.body` is null only when no body was provided.
    expect(request.body).not.toBeNull();
  });

  it("rejects unsupported MIME before any network call", async () => {
    const file = new File([new Uint8Array(8)], "err.bmp", { type: "image/bmp" });
    const result = await submitOcr({
      body: { file },
      headers: commandHeaders("student-access", "ocr-screenshot"),
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.data).toBeNull();
    expect(result.error).toBeInstanceOf(Error);
    expect(
      String((result.error as Error)?.message),
    ).toContain("不支持的图片格式");
  });

  it("rejects files over the 5 MiB cap before any network call", async () => {
    // Avoid materialising a 5 MiB+1 byte buffer in the test runner: the
    // validator only reads `.type`/`.size`, so a lightweight stub is enough
    // to exercise the cap. We cast because `submitOcr`'s signature requires
    // a real `File`; the wrapper never touches the bytes for a rejected file.
    const oversized = {
      type: "image/png",
      size: MAX_OCR_FILE_BYTES + 1,
    } as unknown as File;
    const result = await submitOcr({
      body: { file: oversized },
      headers: commandHeaders("student-access", "ocr-screenshot"),
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.data).toBeNull();
    expect(
      String((result.error as Error)?.message),
    ).toContain("5 MiB");
  });

  it("accepts all three BE-024 MIME allowlist entries", () => {
    expect([...OCR_ACCEPTED_MIME]).toEqual([
      "image/png",
      "image/jpeg",
      "image/webp",
    ]);
  });

  it("surfaces a 503 as an error result (UI degrades) without throwing", async () => {
    fetchMock.mockResolvedValueOnce(
      ocrJson({ detail: "OCR service unavailable" }, 503),
    );
    const result = await submitOcr({
      body: { file: pngFile() },
      headers: commandHeaders("student-access", "ocr-screenshot"),
    });
    expect(result.response.status).toBe(503);
    expect(result.data).toBeNull();
    expect(result.error).toEqual({ detail: "OCR service unavailable" });
  });

  it("tolerates a missing confidence field in the response", async () => {
    fetchMock.mockResolvedValueOnce(
      ocrJson({
        extracted_text: "Traceback (most recent call last)",
        mime: "image/jpeg",
        size_bytes: 0x80,
      }),
    );
    const result = await submitOcr({
      body: {
        file: new File([new Uint8Array(0x80)], "e.jpg", {
          type: "image/jpeg",
        }),
      },
      headers: commandHeaders("student-access", "ocr-screenshot"),
    });
    expect(result.data?.extracted_text).toBe("Traceback (most recent call last)");
    expect(result.data?.confidence).toBeUndefined();
  });
});
