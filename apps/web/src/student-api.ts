import { client } from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";

export function configureStudentApi(): void {
  client.setConfig({
    baseUrl: readServerUrl(),
    credentials: "include",
    fetch,
  });
}

export function studentAuthorization(accessToken: string): {
  Authorization: string;
} {
  return { Authorization: `Bearer ${accessToken}` };
}

export function commandHeaders(
  accessToken: string,
  prefix: string,
): { Authorization: string; "Idempotency-Key": string } {
  return {
    ...studentAuthorization(accessToken),
    "Idempotency-Key": `${prefix}-${crypto.randomUUID()}`.slice(0, 128),
  };
}

export function safeApiMessage(error: unknown): string {
  if (!error || typeof error !== "object") return "请求失败，请稍后重试";
  const message = Reflect.get(error, "message");
  return typeof message === "string" ? message : "请求失败，请稍后重试";
}
