import { describe, expect, it } from "vitest";

import { defaultValidUntil, previewTotals, quoteNumber } from "@/lib/quotes";
import {
  fieldErrors,
  priceBookSchema,
  priceSchema,
  productSchema,
} from "@/lib/validation/catalog";
import { quoteErrors, quoteSchema } from "@/lib/validation/quotes";

const ID = "6f9619ff-8b86-4d01-b42d-00cf4fc964ff";

describe("quote preview totals", () => {
  it("matches the server rules to the cent (values from quotes/rules.py)", () => {
    // Reference computed with backend line_money/quote_money for the same three lines.
    const preview = previewTotals([
      { quantity: 3, listPrice: 19.99, discountPercent: 12.5, taxRate: 19 },
      { quantity: 2.5, listPrice: 100, discountPercent: 0, taxRate: 7 },
      { quantity: 7, listPrice: 0.15, discountPercent: 33.33, taxRate: 19 },
    ]);

    expect(preview).toEqual({
      gross: 311.02,
      discount: 7.85,
      subtotal: 303.17,
      tax: 27.6,
      total: 330.77,
      needsApproval: true,
    });
  });

  it("needs approval only above the organisation's limit (10 % by default)", () => {
    const line = { quantity: 1, listPrice: 10, taxRate: 0 };
    expect(
      previewTotals([{ ...line, discountPercent: 10 }]).needsApproval,
    ).toBe(false);
    expect(
      previewTotals([{ ...line, discountPercent: 10.01 }]).needsApproval,
    ).toBe(true);
    expect(
      previewTotals([{ ...line, discountPercent: 15 }], 20).needsApproval,
    ).toBe(false);
    expect(
      previewTotals([{ ...line, discountPercent: 0.5 }], 0).needsApproval,
    ).toBe(true);
    expect(
      previewTotals([{ ...line, discountPercent: 0 }], 0).needsApproval,
    ).toBe(false);
    expect(previewTotals([]).total).toBe(0);
  });
});

describe("quote helpers", () => {
  it("formats numbers with the revision only from revision 2", () => {
    expect(quoteNumber(7)).toBe("QT-0007");
    expect(quoteNumber(7, 1)).toBe("QT-0007");
    expect(quoteNumber(7, 2)).toBe("QT-0007 rev 2");
  });

  it("defaults validity to 30 days ahead", () => {
    expect(defaultValidUntil(new Date("2026-10-19T12:00:00Z"))).toBe(
      "2026-11-18",
    );
  });
});

describe("quote form validation", () => {
  const valid = {
    account_id: ID,
    title: " 50 widgets ",
    price_book_id: ID,
    opportunity_id: "",
    contact_id: "",
    valid_until: "2026-11-18",
    customer_note: "",
    internal_note: "  ",
    lines: [{ product_id: ID, quantity: "2.5", discount_percent: "" }],
  };

  it("accepts a valid quote and normalises empty values", () => {
    const parsed = quoteSchema.parse(valid);
    expect(parsed.title).toBe("50 widgets");
    expect(parsed.opportunity_id).toBeNull();
    expect(parsed.internal_note).toBeNull();
    expect(parsed.lines[0].discount_percent).toBe("0");
    // Prices are never part of the input - the API takes them from the price book.
    expect(parsed.lines[0]).not.toHaveProperty("unit_price");
  });

  it("reports line errors with the line number", () => {
    const result = quoteSchema.safeParse({
      ...valid,
      account_id: "not-an-id",
      lines: [
        { product_id: ID, quantity: "1", discount_percent: "5" },
        { product_id: ID, quantity: "0", discount_percent: "101" },
      ],
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    const errors = quoteErrors(result.error);
    expect(errors.account_id).toBe("Choose the customer account.");
    expect(errors.lines).toBe(
      "Line 2: Quantity must be more than 0 (up to 3 decimals).",
    );
  });
});

describe("catalogue validation", () => {
  it("checks product codes, tax rates and names", () => {
    const ok = productSchema.parse({
      sku: "WID-100",
      name: "Widget",
      description: "",
      product_type: "product",
      unit: "each",
      tax_rate: "19,5",
    });
    expect(ok.tax_rate).toBe("19.5");
    expect(ok.description).toBeNull();

    const bad = productSchema.safeParse({
      sku: "WID 100",
      name: "",
      description: "",
      product_type: "gadget",
      unit: "each",
      tax_rate: "120",
    });
    expect(bad.success).toBe(false);
    if (bad.success) return;
    expect(Object.keys(fieldErrors(bad.error)).sort()).toEqual([
      "name",
      "product_type",
      "sku",
      "tax_rate",
    ]);
  });

  it("uppercases currencies and rejects bad prices", () => {
    expect(
      priceBookSchema.parse({
        name: "Std",
        currency: "eur",
        description: "",
        is_default: true,
      }).currency,
    ).toBe("EUR");
    expect(priceSchema.parse({ unit_price: "12,50" }).unit_price).toBe("12.50");
    expect(priceSchema.safeParse({ unit_price: "-1" }).success).toBe(false);
    expect(priceSchema.safeParse({ unit_price: "1.999" }).success).toBe(false);
  });
});
