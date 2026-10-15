/**
 * utils/money.js
 * ==============
 * Pure formatting helpers for monetary values.
 * All amounts are integer cents. The LLM never computes amounts;
 * this module formats deterministic engine and ledger outputs.
 */

/**
 * Returns the currency symbol for supported currencies (USD, EUR, GBP).
 * @param {string} currency - ISO 4217 code (default: 'USD')
 * @returns {string} Currency symbol ('$', '€', '£')
 */
export function getCurrencySymbol(currency = 'USD') {
  const curr = (currency || 'USD').toUpperCase();
  switch (curr) {
    case 'EUR':
      return '€';
    case 'GBP':
      return '£';
    case 'USD':
    default:
      return '$';
  }
}

/**
 * Formats an integer cent value as a localized currency string using Intl.NumberFormat.
 * @param {number|null|undefined} cents - Integer cents
 * @param {string} currency - ISO 4217 code ('USD', 'EUR', 'GBP')
 * @returns {string} e.g. "$12.34", "€12.34", "-€12.34", or "-" if invalid
 */
export function formatMoney(cents, currency = 'USD') {
  if (cents === null || cents === undefined || isNaN(cents)) return '-';
  const curr = (currency || 'USD').toUpperCase();
  const dollars = cents / 100;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: curr,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(dollars);
}

/**
 * Backward-compatible alias for formatMoney.
 * @param {number|null|undefined} cents
 * @param {string} currency
 * @returns {string}
 */
export function formatCents(cents, currency = 'USD') {
  return formatMoney(cents, currency);
}

/**
 * Returns a sign-aware difference string.
 * Negative diff = overcharge (customer was billed too much).
 * @param {number} diffCents
 * @param {string} currency
 * @returns {string} e.g. "-€490.00 overcharge" or "+$2.00 undercharge"
 */
export function formatDifference(diffCents, currency = 'USD') {
  if (diffCents === null || diffCents === undefined || isNaN(diffCents)) return '-';
  if (diffCents === 0) return `${formatMoney(0, currency)} (exact)`;
  if (diffCents < 0) {
    return `${formatMoney(diffCents, currency)} overcharge`;
  }
  return `+${formatMoney(diffCents, currency)} undercharge`;
}

/**
 * Converts integer cents to a standard decimal string (e.g. 125000 -> "1250.00")
 * for HTML input elements, keeping all toFixed(2) calls inside money.js.
 * @param {number|null|undefined} cents
 * @returns {string}
 */
export function centsToDollarString(cents) {
  if (cents === null || cents === undefined || isNaN(cents)) return '';
  return (Math.abs(cents) / 100).toFixed(2);
}
