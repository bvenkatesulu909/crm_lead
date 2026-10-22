import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatForm } from "@/app/portal/assistant/chat-form";
import { type FormState, initialFormState } from "@/lib/form-state";
import { modulesFor } from "@/lib/modules";

type Action = (state: FormState, formData: FormData) => Promise<FormState>;

describe("assistant chat box", () => {
  it("sends with Enter and keeps Shift+Enter for new lines", async () => {
    const action = vi.fn<Action>(async (state) => state);
    const user = userEvent.setup();
    render(<ChatForm action={action} initialState={initialFormState} />);

    const box = screen.getByLabelText("Your question");
    await user.type(box, "Where is{Shift>}{Enter}{/Shift}my order?");
    expect(action).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");

    expect(action).toHaveBeenCalledTimes(1);
    expect(action.mock.calls[0][1].get("text")).toBe("Where is\nmy order?");
  });

  it("shows the server's error and keeps the typed text", async () => {
    const action = vi.fn<Action>(async (state) => ({
      attempt: state.attempt + 1,
      values: { text: "hello" },
      fieldErrors: {},
      error: { status: 429, message: "You have sent many messages.", code: "too_many_messages", requestId: null, fieldErrors: {} },
    }));
    const user = userEvent.setup();
    render(<ChatForm action={action} initialState={initialFormState} />);

    await user.type(screen.getByLabelText("Your question"), "hello{Enter}");

    expect(await screen.findByText("You have sent many messages.")).toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveValue("hello");
  });
}); // prettier-ignore

describe("module overview", () => {
  it("links the staff assistant to its own page", () => {
    const assistant = modulesFor({ permissions: ["ticket:read:all"] }).find(
      (m) => m.key === "assistant",
    );
    expect(assistant?.note).toBe("Open");
    expect(assistant?.link).toBe("/assistant");
  });
}); // prettier-ignore




