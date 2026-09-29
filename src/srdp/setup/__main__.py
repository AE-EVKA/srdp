"""CLI entry point: ``python -m srdp.setup`` runs the database-bootstrap phase and exits."""

import logging
import sys

from pydantic import ValidationError

from srdp.setup.bootstrap import bootstrap_databases

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the database-bootstrap phase."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        bootstrap_databases()
    except ValidationError as exc:
        # Pydantic's default message echoes the raw input, which holds the
        # role passwords, so report only the location and message of each error.
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in error["loc"]) or "settings"
            logger.error("Invalid setup config (%s): %s", location, error["msg"])  # noqa: TRY400 -- a traceback would print the passwords
        sys.exit(1)
    logger.info("Database bootstrap complete.")


if __name__ == "__main__":
    main()
