/**
 * utils/money.js
 * ==============
 * Pure formatting helpers for monetary values.
 * All amounts are integer cents. The LLM never computes amounts;
 * this module only formats deterministic engine output.
 */

/**
 * Formats an integer cent value as a dollar string.
 * @param {number|null|undefined} cents - Integer cents
 * @returns {string} e.g. "$12.34", "-$12.34", or "-" if invalid
 */
export function formatCents(cents) {
  if (cents === null || cents === undefined || isNaN(cents)) return '-';
  const abs = Math.abs(cents);
  const formatted = (abs / 100).toFixed(2);
  return cents < 0 ? `-$${formatted}` : `$${formatted}`;
}

/**
 * Returns a sign-aware difference string.
 * Negative diff = overcharge (customer was billed too much).
 * @param {number} diffCents
 * @returns {string} e.g. "-$5.00 overcharge" or "+$2.00 undercharge"
 */
export function formatDifference(diffCents) {
  if (diffCents === null || diffCents === undefined || isNaN(diffCents)) return '-';
  if (diffCents === 0) return '$0.00 (exact)';
  if (diffCents < 0) {
    return `${formatCents(diffCents)} overcharge`;
  }
  return `+${formatCents(diffCents)} undercharge`;
}
