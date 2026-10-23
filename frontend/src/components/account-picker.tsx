"use client";

import { useEffect, useId, useRef, useState } from "react";

export type AccountOption = { id: string; name: string };

type Status = "idle" | "loading" | "error";

/**
 * A type-to-search account field. A plain <select> can only list the first N accounts; this
 * asks the server for the matches as you type, so it works with any number of accounts.
 *
 * It posts two fields with the form: `account_id` (what the server uses) and `account_label`
 * (only the name, so the field can show the chosen account again after a validation error).
 * The server still checks that the user may use that account, whatever the browser sends.
 */
export function AccountPicker({
  id,
  defaultAccount,
  ...inputProps
}: {
  id: string;
  defaultAccount?: AccountOption | null;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
  className?: string;
}) {
  const listId = useId();
  const [selected, setSelected] = useState<AccountOption | null>(
    defaultAccount ?? null,
  );
  const [query, setQuery] = useState(defaultAccount?.name ?? "");
  const [options, setOptions] = useState<AccountOption[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState<Status>("idle");
  const wrapper = useRef<HTMLDivElement>(null);

  // Ask the server for matches while the list is open (after a short pause in typing).
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setStatus("loading");
      try {
        const response = await fetch(
          `/accounts/search?q=${encodeURIComponent(query)}`,
          {
            signal: controller.signal,
            headers: { accept: "application/json" },
          },
        );
        if (!response.ok) throw new Error(`status ${response.status}`);
        const found = (await response.json()) as AccountOption[];
        setOptions(found);
        setActive(found.length > 0 ? 0 : -1);
        setStatus("idle");
      } catch (error) {
        if ((error as Error).name === "AbortError") return;
        setOptions([]);
        setStatus("error");
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [open, query]);

  function choose(option: AccountOption) {
    setSelected(option);
    setQuery(option.name);
    setOpen(false);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) setOpen(true);
      else setActive((index) => Math.min(index + 1, options.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (
      event.key === "Enter" &&
      open &&
      active >= 0 &&
      options[active]
    ) {
      event.preventDefault(); // choose the account; don't submit the form yet
      choose(options[active]);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
    }
  }

  const message =
    status === "error"
      ? "The accounts could not be loaded. Try typing again."
      : status === "loading"
        ? "Searching…"
        : options.length === 0
          ? "No account matches."
          : "";

  return (
    <div
      ref={wrapper}
      className="relative"
      onBlur={(event) => {
        // Close only when focus leaves the whole picker (not when moving into the list).
        if (!wrapper.current?.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <input type="hidden" name="account_id" value={selected?.id ?? ""} />
      <input type="hidden" name="account_label" value={selected?.name ?? ""} />
      <input
        {...inputProps}
        id={id}
        type="text"
        role="combobox"
        autoComplete="off"
        placeholder="Type to search accounts…"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          open && active >= 0 ? `${listId}-${active}` : undefined
        }
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setSelected(null); // typing again means "not chosen yet"
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {open && (
        <div className="absolute z-20 mt-1 w-full rounded-md border border-slate-200 bg-white shadow-lg">
          <ul
            id={listId}
            role="listbox"
            aria-label="Matching accounts"
            className="max-h-60 overflow-auto py-1"
          >
            {options.map((option, index) => (
              <li
                key={option.id}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={selected?.id === option.id}
                className={`cursor-pointer px-3 py-2 text-sm ${
                  index === active
                    ? "bg-brand-50 text-brand-900"
                    : "text-slate-800"
                }`}
                onMouseDown={(event) => event.preventDefault()} // keep focus in the input
                onClick={() => choose(option)}
                onMouseEnter={() => setActive(index)}
              >
                {option.name}
              </li>
            ))}
          </ul>
          <p
            role="status"
            aria-live="polite"
            className={message ? "px-3 py-2 text-sm text-slate-500" : "sr-only"}
          >
            {message}
          </p>
        </div>
      )}
    </div>
  );
}
