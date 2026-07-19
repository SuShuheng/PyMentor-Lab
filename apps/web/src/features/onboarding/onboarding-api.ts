/**
 * FE-014 — typed wrapper for BE-018 `POST /api/v1/profiles/onboarding`.
 *
 * The generated SDK (@pymentor/api-client) does not yet expose this endpoint,
 * so we post through the shared `client` from the generated runtime and keep
 * the request/response types here. When the generator picks the route up,
 * this wrapper can be retired in favour of the generated function without
 * changing call sites.
 */
import { client } from "@pymentor/api-client";

/**
 * Answers collected during conversational onboarding. Field names mirror the
 * BE-018 `OnboardingAnswers` contract one-to-one (snake_case on the wire).
 */
export type OnboardingAnswers = {
  prior_experience: string;
  primary_goal: string;
  error_strategy: string;
  preferred_exercise: string;
  weekly_band: string;
};

/** Request body for `POST /api/v1/profiles/onboarding`. */
export type OnboardingRequest = {
  answers: OnboardingAnswers;
  /**
   * Optimistic-concurrency handshake. The first onboarding submission sends
   * `0` because no profile version exists yet.
   */
  expected_profile_version: number;
};

/** Successful response body returned by BE-018. */
export type OnboardingResponse = {
  evidence_event_id: string;
  profile_version_id: string;
  profile_version: number;
  replan_requested: boolean;
};

export type SubmitOnboardingOptions = {
  baseUrl?: string;
  body: OnboardingRequest;
  headers: { Authorization: string; "Idempotency-Key": string };
};

/**
 * Submits onboarding answers to the backend profile projection. Mirrors the
 * generated SDK's `{ data, error, response }` result shape so callers can use
 * the same error-handling idiom as the generated endpoints.
 */
export async function submitOnboarding({
  body,
  headers,
}: SubmitOnboardingOptions) {
  return client.post<OnboardingResponse, unknown, false>({
    url: "/api/v1/profiles/onboarding",
    body,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
  });
}
