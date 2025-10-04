"""Allow ``python -m copilot_proxy`` to run the CLI entrypoint."""
from __future__ import annotations

from .cli import main


if __name__ == "__main__":
    main()
