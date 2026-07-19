import type { ProviderType } from "@pymentor/api-client";

/**
 * FE-016 Xunfei/LLM provider presets.
 *
 * A "preset" is a known-good starting point for a vendor's most common
 * provider configuration. When a System Admin types a recognized vendor
 * (e.g. `xfyun`, `openai`, `deepseek`) into the provider form, the dialog
 * offers an "应用预设" button that auto-fills `product`/`model`/`endpoint`
 * (and may set `provider_type`) so they don't have to copy-paste URLs.
 *
 * HONESTY: presets are STARTING POINTS ONLY. They are not locked and are not
 * officially validated. The UI always renders a "预设值可编辑" note and every
 * field remains fully editable after a preset is applied. Vendors may rotate
 * endpoints, deprecate models, or require tenant-specific params — the admin
 * is the human in the loop and is expected to verify before saving.
 *
 * KEY CHOICE: a single flat `Record<string, ProviderPreset[]>` keyed by
 * `vendor`. Each vendor can expose multiple presets (one per
 * `provider_type`). This is the simplest structure that supports the
 * "dropdown if multiple presets for the same vendor" UX in the task spec
 * without nesting vendor → type → preset (which would force the form to
 * pre-pick a type). Keeping it a flat array per vendor also makes the
 * `findPresetsForVendor` lookup O(1).
 */

export type ProviderPreset = {
  /** Discriminator: which capability slot this preset fills. */
  provider_type: ProviderType;
  /** Human-readable label, shown in a dropdown when a vendor has >1 preset. */
  label: string;
  /** Recommended product/family name (mapped to `vendor` on apply). */
  product: string;
  /** Recommended default model id for this vendor/type. */
  model: string;
  /** Recommended endpoint URL (OpenAI-compatible base or vendor-specific). */
  endpoint: string;
};

/**
 * Known-good presets per vendor. Vendors are lowercased ASCII identifiers
 * (matching the vendor field's `[A-Za-z0-9._-]+` pattern in the form).
 *
 * Endpoints reflect the publicly documented Xunfei OpenAI-compatible surface
 * and OpenAI/DeepSeek public APIs as of 2026-07. They are advisory only.
 */
export const PROVIDER_PRESETS: Record<string, ProviderPreset[]> = {
  xfyun: [
    {
      provider_type: "LLM",
      label: "讯飞星火 (Spark) · LLM",
      product: "spark",
      model: "spark-v3.5",
      endpoint: "https://spark-api-open.xf-yun.com/v1",
    },
    {
      provider_type: "TTS",
      label: "讯飞在线语音合成 · TTS",
      product: "xfyun-tts",
      model: "online-tts",
      // Xunfei TTS is WebSocket/signed; this is a placeholder base — admin adjusts.
      endpoint: "https://tts-api.xf-yun.com/v2/tts",
    },
    {
      provider_type: "ASR",
      label: "讯飞语音听写 · ASR",
      product: "xfyun-iat",
      model: "iat-v2",
      endpoint: "https://iat-api.xf-yun.com/v2/iat",
    },
    {
      provider_type: "OCR",
      label: "讯飞文字识别 · OCR",
      product: "xfyun-ocr",
      model: "ocr-v1",
      endpoint: "https://ocr-api.xf-yun.com/v1/ocr",
    },
    {
      provider_type: "MODERATION",
      label: "讯飞内容审核 · MODERATION",
      product: "xfyun-audit",
      model: "audit-v1",
      endpoint: "https://audit-api.xf-yun.com/v1/audit",
    },
    {
      provider_type: "EMBEDDING",
      label: "讯飞向量 · EMBEDDING",
      product: "xfyun-emb",
      model: "emb-v1",
      endpoint: "https://emb-api.xf-yun.com/v1/embeddings",
    },
  ],
  openai: [
    {
      provider_type: "LLM",
      label: "OpenAI · GPT-4o mini",
      product: "openai",
      model: "gpt-4o-mini",
      endpoint: "https://api.openai.com/v1",
    },
    {
      provider_type: "EMBEDDING",
      label: "OpenAI · text-embedding-3-small",
      product: "openai",
      model: "text-embedding-3-small",
      endpoint: "https://api.openai.com/v1",
    },
    {
      provider_type: "MODERATION",
      label: "OpenAI · omni-moderation-latest",
      product: "openai",
      model: "omni-moderation-latest",
      endpoint: "https://api.openai.com/v1",
    },
  ],
  deepseek: [
    {
      provider_type: "LLM",
      label: "DeepSeek · deepseek-chat",
      product: "deepseek",
      model: "deepseek-chat",
      endpoint: "https://api.deepseek.com/v1",
    },
  ],
};

/**
 * Returns all presets matching the given vendor, or `[]` when none.
 *
 * Vendor matching is case-insensitive and trims whitespace so an admin typing
 * `XFYUN` or ` xfyun ` still discovers the preset. The empty-vendor case
 * returns `[]` so the dialog can short-circuit and render no button.
 */
export function findPresetsForVendor(vendor: string): ProviderPreset[] {
  const key = vendor.trim().toLowerCase();
  if (key.length === 0) return [];
  return PROVIDER_PRESETS[key] ?? [];
}

/**
 * Selects the best preset for a vendor given the form's current
 * `provider_type`. Falls back to the first preset when no exact-type match
 * exists (so the single-button UX still works for vendors that only expose
 * one preset). Returns `null` when the vendor has no presets at all.
 */
export function pickPresetForVendor(
  vendor: string,
  providerType: ProviderType,
): ProviderPreset | null {
  const presets = findPresetsForVendor(vendor);
  if (presets.length === 0) return null;
  const match = presets.find((preset) => preset.provider_type === providerType);
  return match ?? presets[0] ?? null;
}
