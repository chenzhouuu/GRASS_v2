/**
 * Validation utilities for settings.
 * Patterns ported from NextChat (app/store/config.ts, app/utils/clone.ts).
 */

/**
 * Clamp a number to [min, max], returning defaultValue if NaN.
 */
export function limitNumber(
  x: number,
  min: number,
  max: number,
  defaultValue: number,
): number {
  if (isNaN(x)) return defaultValue;
  return Math.min(max, Math.max(min, x));
}

/** Map config validators — clamp lat/lon/zoom to valid ranges. */
export const MapConfigValidator = {
  latitude: (x: number) => limitNumber(x, -90, 90, 39.8283),
  longitude: (x: number) => limitNumber(x, -180, 180, -98.5795),
  zoom: (x: number) => limitNumber(x, 1, 18, 5),
};

/**
 * Lightweight format check for provider API keys.
 * Non-blocking — returns false for obviously wrong prefixes.
 */
export function isValidProviderKey(
  provider: string,
  key: string,
): boolean {
  if (!key || key.trim() === "") return false;
  switch (provider) {
    case "openai":
      return key.startsWith("sk-");
    case "anthropic":
      return key.startsWith("sk-ant-");
    case "google":
      return key.startsWith("AIza");
    default:
      return true;
  }
}
