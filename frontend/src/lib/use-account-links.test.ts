import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAccountLinks } from "@/lib/use-account-links";

const ID_A = "11111111-1111-4111-8111-111111111111";
const ID_B = "22222222-2222-4222-8222-222222222222";

const links = {
  contacts: [{ id: "c1", name: "Dana Customer", accountId: ID_A }],
  opportunities: [{ id: "o1", name: "Big deal", accountId: ID_A }],
};

function mockFetch(ok = true) {
  const fetchMock = vi.fn<(url: string) => Promise<Response>>(
    async () =>
      new Response(JSON.stringify(ok ? links : { error: "no" }), {
        status: ok ? 200 : 500,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("useAccountLinks", () => {
  it("fetches the chosen account's contacts and deals", async () => {
    const fetchMock = mockFetch();
    const { result } = renderHook(() => useAccountLinks(ID_A, true));
    await waitFor(() => expect(result.current.contacts).toHaveLength(1));
    expect(result.current.opportunities[0].name).toBe("Big deal");
    expect(String(fetchMock.mock.calls[0][0])).toBe(`/accounts/${ID_A}/links`);
  });

  it("does nothing when disabled or when no account is chosen", () => {
    const fetchMock = mockFetch();
    const off = renderHook(() => useAccountLinks(ID_A, false));
    const none = renderHook(() => useAccountLinks("", true));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(off.result.current.contacts).toEqual([]);
    expect(none.result.current.opportunities).toEqual([]);
  });

  it("never shows one account's choices under another account", async () => {
    mockFetch();
    const { result, rerender } = renderHook(
      ({ id }) => useAccountLinks(id, true),
      { initialProps: { id: ID_A } },
    );
    await waitFor(() => expect(result.current.contacts).toHaveLength(1));
    rerender({ id: ID_B }); // the new account's lists have not arrived yet
    expect(result.current.contacts).toEqual([]);
  });

  it("stays empty (and the form usable) when the request fails", async () => {
    const fetchMock = mockFetch(false);
    const { result } = renderHook(() => useAccountLinks(ID_A, true));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(result.current.contacts).toEqual([]);
    expect(result.current.opportunities).toEqual([]);
  });
});
