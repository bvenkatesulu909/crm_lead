"""Public interface of the contracts module. Other modules (and the worker) import only from here.

Grows with the steps in docs/contracts.md: C3 adds what the worker needs (expiry and renewal
reminders), C4 nothing (the screens use the HTTP API).
"""

from app.modules.contracts.rules import label

__all__ = ["label"]
