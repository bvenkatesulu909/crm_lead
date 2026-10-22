# Customer assistant: guardrails and voice

## Surfaces

The customer portal assistant (`/portal/assistant`) answers only from the customer's own data
(tools are permission-checked) and can prepare a support ticket for confirmation.

## Input guardrails

Applied **before any model call** in `assistant/service.py` via `assistant/guardrails.py`:

- empty / over-long questions (> 2,000 characters) are rejected;
- prompt-injection phrases ("ignore previous instructions", "system prompt", "jailbreak",
  "reveal your instructions", ...) are rejected with a safe message;
- payment-card-like numbers, US SSNs and API keys are rejected;
- rejection is HTTP **422** (`input_guardrail`) and is not sent to the LLM.

## Output guardrails

Applied to every model answer **before it is stored or returned**:

- strips length to 8,000 characters;
- if the answer contains system-prompt markers, API keys, database URLs, internal hosts
  (`127.0.0.1`, `localhost:`) or `password=`, it is replaced with:
  *"I can't share that here. Please contact our support team..."*;
- citations continue to come only from customer-visible knowledge articles.

These are deterministic rules, not a substitute for the model's own refusal behaviour.

## Voice

The customer chat has:

- **Speak** — browser speech-to-text (Web Speech API) fills the question box; the transcript is
  sent through the same input guardrails.
- **Listen** — reads an assistant answer aloud with browser speech synthesis.

Both run **in the browser**: audio is processed by the browser vendor's speech service, not
uploaded to or stored by CRM-lead. Support depends on the browser (Chrome/Edge work best);
the controls are hidden when unsupported. HTTPS or localhost is required for microphone access.

## Tests

- `backend/tests/test_assistant_guardrails.py` — injection, PII, long input, output leaks,
  empty output, normal pass-through.
- `backend/tests/db/test_assistant_api.py` — full portal assistant flow still passes.
