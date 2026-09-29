"""CLI entry point: ``python -m srdp.setup`` runs the database-bootstrap phase and exits."""

import logging

from srdp.setup.bootstrap import bootstrap_databases

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the database-bootstrap phase."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    bootstrap_databases()
    logger.info("Database bootstrap complete.")


if __name__ == "__main__":
    main()
