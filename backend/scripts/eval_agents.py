"""Play the agent evaluation cases and write a scorecard (BP-10). See agent_evals/cli.py."""

import sys

from agent_evals.cli import main
from app import model_registry as _model_registry  # noqa: F401 - loads every table definition

if __name__ == "__main__":
    sys.exit(main())
