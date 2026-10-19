/**
 * Exact money arithmetic for the order form's PREVIEW. JavaScript numbers are binary floats
 * (0.1 + 0.2 = 0.30000000000000004), so amounts are handled as whole cents in BigInt.
 * Same rounding as backend/app/modules/orders/rules.py: per line, half up. The server
 * calculates the real amounts; this only shows the user what to expect while typing.
 */

// BigInt(...) instead of 0n-style literals: the TypeScript target (ES2017) has no literals.
const ZERO = BigInt(0);
const TWO = BigInt(2);
const HUNDRED = BigInt(100);
const THOUSAND = BigInt(1000);
const TEN_THOUSAND = BigInt(10_000);

/** "19.99" -> 1999 with `places` decimals; null if not a plain non-negative decimal. */
export function toScaled(value: string, places: number): bigint | null {
  const match = /^(\d{1,13})(?:\.(\d+))?$/.exec(value.trim());
  if (!match) return null;
  const fraction = match[2] ?? "";
  if (fraction.length > places) return null;
  return BigInt(match[1] + fraction.padEnd(places, "0"));
}

/** a / b rounded half up, for non-negative values. */
function divideHalfUp(a: bigint, b: bigint): bigint {
  return (a * TWO + b) / (b * TWO);
}

export type LinePreview = { subtotal: bigint; tax: bigint; total: bigint };

/** Amounts of one line in cents, or null while the inputs are incomplete or invalid. */
export function previewLine(
  quantity: string,
  unitPrice: string,
  taxRate: string,
): LinePreview | null {
  const q = toScaled(quantity, 3); // thousandths
  const p = toScaled(unitPrice, 2); // cents
  const r = toScaled(taxRate || "0", 2); // hundredths of a percent
  if (q === null || p === null || r === null || q === ZERO || r > TEN_THOUSAND)
    return null;
  const subtotal = divideHalfUp(q * p, THOUSAND);
  const tax = divideHalfUp(subtotal * r, TEN_THOUSAND);
  return { subtotal, tax, total: subtotal + tax };
}

export function sumLines(lines: (LinePreview | null)[]): LinePreview {
  return lines.reduce<LinePreview>(
    (acc, line) =>
      line
        ? {
            subtotal: acc.subtotal + line.subtotal,
            tax: acc.tax + line.tax,
            total: acc.total + line.total,
          }
        : acc,
    { subtotal: ZERO, tax: ZERO, total: ZERO },
  );
}

/** 21416 cents -> "214.16" */
export function centsToDecimal(cents: bigint): string {
  const sign = cents < ZERO ? "-" : "";
  const abs = cents < ZERO ? -cents : cents;
  return `${sign}${abs / HUNDRED}.${String(abs % HUNDRED).padStart(2, "0")}`;
}
