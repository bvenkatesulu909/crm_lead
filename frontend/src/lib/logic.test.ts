import { describe, expect, it } from "vitest";

import {
  accountApiQuery,
  accountPageHref,
  parseAccountParams,
} from "@/app/(app)/accounts/list-params";
import {
  apiQuery,
  pageHref,
  parseListParams,
} from "@/app/(app)/leads/list-params";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { Me } from "@/lib/api-types";
import { modulesFor, sidebarModulesFor } from "@/lib/modules";
import { PERMISSION_LABELS, navigationFor } from "@/lib/permissions";
import { validateLead } from "@/lib/validation/lead";

const PERMISSIONS: Record<string, string[]> = {
  sales_agent: [
    "lead:read:own",
    "lead:write:own",
    "account:read:own",
    "order:read:own_accounts",
    "order:write:own_accounts",
    "invoice:read:own_accounts",
    "catalog:read",
    "quote:read:own",
    "quote:write:own",
    "knowledge:read",
  ],
  sales_manager: [
    "lead:read:all",
    "lead:write:all",
    "lead:assign",
    "account:read:all",
  ],
  support_agent: ["account:read:all", "contact:read:all", "catalog:read"],
  customer: ["portal:account:read"],
  super_admin: ["platform:tenant:read"],
};

function me(role: string, user_type: Me["user_type"] = "staff"): Me {
  return {
    user_id: "u",
    display_name: "Test",
    email: null,
    tenant_id: "t",
    tenant_name: "Test Org",
    user_type,
    roles: [role],
    permissions: PERMISSIONS[role],
  };
}

describe("role-based navigation", () => {
  it.each([
    [
      "sales_agent",
      "staff",
      [
        "Dashboard",
        "Leads",
        "Accounts",
        "Quotes",
        "Orders",
        "Invoices",
        "Products",
        "Knowledge",
        "Reports",
      ],
    ],
    ["sales_manager", "staff", ["Dashboard", "Leads", "Accounts", "Reports"]],
    [
      "support_agent",
      "staff",
      ["Dashboard", "Accounts", "Contacts", "Products", "Reports"],
    ],
    ["customer", "customer", []],
    ["super_admin", "platform", ["Dashboard", "Organisations"]],
  ] as const)("%s sees %j", (role, type, expected) => {
    expect(navigationFor(me(role, type)).map((i) => i.label)).toEqual(expected);
  });
});

describe("lead form validation (mirrors the backend rules)", () => {
  it("accepts a minimal lead and drops empty optional fields", () => {
    const result = validateLead({
      last_name: "  Example ",
      email: "",
      source: "",
    });

    expect(result).toEqual({ ok: true, data: { last_name: "Example" } });
  });

  it.each([
    [{ last_name: "" }, "last_name", "Last name is required."],
    [{ last_name: "   " }, "last_name", "Last name is required."],
    [{ last_name: "x".repeat(101) }, "last_name", "at most 100"],
    [{ last_name: "A", email: "nope" }, "email", "valid e-mail"],
    [{ last_name: "A", email: "a@@b.example" }, "email", "valid e-mail"],
    [{ last_name: "A", phone: "call me" }, "phone", "digits"],
    [{ last_name: "A", source: "pigeon" }, "source", ""],
  ])("rejects %j", (values, field, message) => {
    const result = validateLead(values);

    expect(result.ok).toBe(false);
    if (!result.ok)
      expect(result.errors[field as keyof typeof result.errors]).toContain(
        message,
      );
  });
});

describe("lead list URL parameters", () => {
  it("falls back to safe defaults for invalid values", () => {
    const params = parseListParams({
      status: "hacked",
      sort: "password",
      page: "-3",
      source: "x",
    });

    expect(params).toEqual({
      q: "",
      status: "",
      source: "",
      priority: "",
      sort: "-created_at",
      page: 1,
    });
  });

  it("builds the backend query with offset paging", () => {
    const params = parseListParams({ q: " acme ", status: "new", page: "3" });

    expect(apiQuery(params)).toBe(
      "limit=20&offset=40&sort=-created_at&q=acme&status=new",
    );
  });

  it("builds short list links that keep the filters", () => {
    const params = parseListParams({
      q: "a&b",
      status: "qualified",
      sort: "last_name",
    });

    expect(pageHref(params, 1)).toBe(
      "/leads?q=a%26b&status=qualified&sort=last_name",
    );
    expect(pageHref(params, 2)).toBe(
      "/leads?q=a%26b&status=qualified&sort=last_name&page=2",
    );
    expect(pageHref(parseListParams({}), 1)).toBe("/leads");
  });
});

describe("API error messages", () => {
  const problem = (status: number, extra: object = {}) =>
    new ApiError(status, {
      title: "x",
      status,
      detail: "Backend detail.",
      request_id: "req-1",
      ...extra,
    });

  it("maps validation errors to form fields", () => {
    const info = toErrorInfo(
      problem(422, {
        errors: [
          {
            location: ["body", "email"],
            message: "Value error, must be a valid e-mail address",
            type: "value_error",
          },
        ],
      }),
    );

    expect(info.fieldErrors).toEqual({
      email: "must be a valid e-mail address",
    });
    expect(info.requestId).toBe("req-1");
  });

  it("shows the backend's explanation for business-rule conflicts", () => {
    expect(
      toErrorInfo(problem(409, { code: "version_conflict" })),
    ).toMatchObject({
      message: "Backend detail.",
      code: "version_conflict",
    });
  });

  it.each([
    [403, "permission"],
    [404, "doesn't exist"],
    [503, "temporarily unavailable"],
  ])("uses a friendly sentence for %i", (status, text) => {
    expect(toErrorInfo(problem(status)).message).toContain(text);
  });

  it("handles network failures", () => {
    expect(toErrorInfo(new TypeError("fetch failed")).message).toContain(
      "could not be reached",
    );
  });
});

describe("dashboard module catalog", () => {
  it("lists every CRM module, honestly labelled", () => {
    const modules = modulesFor(me("sales_agent"));

    expect(modules.map((m) => m.name)).toEqual([
      "Lead Management",
      "Customer Management",
      "Contacts",
      "Sales Opportunities",
      "Activities",
      "Product Catalog",
      "Quotations",
      "Contracts & Renewals",
      "Orders",
      "Invoices",
      "Customer Support",
      "Customer Portal",
      "Documents",
      "Communication Center",
      "Marketing",
      "Workflow & Notifications",
      "Reports",
      "Integrations",
      "AI Assistant",
      "Knowledge Base",
      "Administration",
    ]);
    expect(modules.find((m) => m.key === "portal")?.note).toBe(
      "Used by your customers",
    );
    // Only modules that really work can be opened; nothing links to an empty screen.
    expect(modules.filter((m) => m.link).map((m) => m.name)).toEqual([
      "Lead Management",
      "Customer Management",
      "Product Catalog",
      "Quotations",
      "Orders",
      "Invoices",
      "Reports",
      "Knowledge Base",
    ]);
    expect(modules.find((m) => m.key === "orders")?.link).toBe("/orders");
    expect(modules.find((m) => m.key === "quotes")?.link).toBe("/quotes");
    expect(modules.find((m) => m.key === "marketing")?.note).toBe(
      "Planned · phase 16",
    );
    expect(modules.find((m) => m.key === "customers")?.link).toBe("/accounts");
  });

  it("does not offer a module the role can't use", () => {
    const leads = modulesFor(me("support_agent")).find(
      (m) => m.key === "leads",
    );

    expect(leads?.link).toBeUndefined();
    expect(leads?.note).toBe("Not included in your role");
  });
});

describe("account list URL parameters", () => {
  it("keeps valid values and drops invalid ones", () => {
    expect(
      parseAccountParams({ q: " acme ", status: "inactive", page: "2" }),
    ).toEqual({
      q: "acme",
      status: "inactive",
      segment: "",
      country: "",
      lifecycle: "",
      archived: false,
      page: 2,
    });
    expect(
      parseAccountParams({
        status: "deleted",
        page: "abc",
        segment: "huge",
        archived: "yes",
      }),
    ).toEqual({
      q: "",
      status: "",
      segment: "",
      country: "",
      lifecycle: "",
      archived: false,
      page: 1,
    });
  });

  it("passes segment and the archived view on", () => {
    const params = parseAccountParams({ segment: "enterprise", archived: "1" });
    expect(accountApiQuery(params)).toBe(
      "limit=20&offset=0&segment=enterprise&archived=true",
    );
    expect(accountPageHref(params, 2)).toBe(
      "/accounts?segment=enterprise&archived=1&page=2",
    );
  });

  it("builds the backend query and short links", () => {
    const params = parseAccountParams({ q: "a&b", page: "3" });

    expect(accountApiQuery(params)).toBe("limit=20&offset=40&q=a%26b");
    expect(accountPageHref(params, 1)).toBe("/accounts?q=a%26b");
    expect(accountPageHref(parseAccountParams({}), 1)).toBe("/accounts");
  });
});

describe("profile permission labels", () => {
  it("explains every permission the backend defines", () => {
    const backendPermissions = [
      "platform:tenant:read", "platform:tenant:manage", "tenant:user:read", "tenant:user:manage",
      "account:read:all", "account:read:own", "account:write:all", "account:write:own",
      "contact:read:all", "contact:read:own", "contact:write:all", "contact:write:own",
      "lead:read:all", "lead:read:own", "lead:write:all", "lead:write:own", "lead:assign",
      "lead:convert", "portal:account:read",
    ]; // prettier-ignore

    for (const permission of backendPermissions)
      expect(PERMISSION_LABELS[permission]).toBeTruthy();
  });
});

describe("sidebar module list", () => {
  it("shows every module that isn't already in the menu", () => {
    const agent = me("sales_agent");
    const menu = navigationFor(agent).map((i) => i.href);
    const extra = sidebarModulesFor(agent, menu);

    // Together, menu + "All CRM modules" cover every module.
    const shown = new Set([...extra.map((m) => m.key)]);
    for (const m of modulesFor(agent))
      expect(shown.has(m.key) || (m.link && menu.includes(m.link))).toBe(true);
    // Nothing appears twice, and modules this role can't open are not links.
    expect(extra.some((m) => m.link && menu.includes(m.link))).toBe(false);
    expect(extra.find((m) => m.key === "administration")?.link).toBeUndefined();
    expect(extra.find((m) => m.key === "marketing")?.note).toBe(
      "Planned · phase 16",
    );
  });

  it("is empty for platform operators and customers", () => {
    expect(sidebarModulesFor(me("super_admin", "platform"), [])).toEqual([]);
    expect(sidebarModulesFor(me("customer", "customer"), [])).toEqual([]);
  });
});
