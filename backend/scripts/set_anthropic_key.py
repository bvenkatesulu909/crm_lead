"""Store the Anthropic API key in backend/.env without showing it on screen.

Run in CMD from the backend folder with the virtual environment active:
    python -m scripts.set_anthropic_key

The key is read with getpass (nothing is echoed while you paste), checked for the workspace-key
format, and written as CRM_ANTHROPIC_API_KEY=... into backend/.env (replacing an existing line).
It is never printed, logged or sent anywhere.
"""

import getpass
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
NAME = "CRM_ANTHROPIC_API_KEY"


def main() -> int:
    key = getpass.getpass("Paste your Anthropic API key and press Enter: ").strip()
    if not key.startswith(("sk-ant-api", "sk-ant-usr")):
        print("That doesn't look like an Anthropic API key. Nothing was changed.")
        return 1
    if key.startswith("sk-ant-usr") and "CRM_ANTHROPIC_WORKSPACE_ID=wrkspc_" not in (
        ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    ):
        print("Note: user-level keys (sk-ant-usr) also need CRM_ANTHROPIC_WORKSPACE_ID in .env.")
    if any(c.isspace() for c in key) or len(key) < 40:
        print("The key looks incomplete or contains spaces. Nothing was changed.")
        return 1

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    lines = [line for line in lines if not line.startswith(f"{NAME}=")]
    lines.append(f"{NAME}={key}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved in {ENV_FILE} (key ending ...{key[-4:]}). Restart the API to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
