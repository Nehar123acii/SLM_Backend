"""
scripts/purge_expired.py
========================
Standalone maintenance script to check business retention expiration
and execute purge if the retention window has expired.
No background daemon or job runner needed — can be invoked directly or via scheduled task.
Handles Windows file locks by disposing database connections first.
"""

import sys
import logging
from pathlib import Path

# Ensure project root is in sys.path when invoked directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db.engine import SessionLocal
from backend.services.purge import check_and_purge_if_expired

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("purge_expired")


def main() -> int:
    session = SessionLocal()
    try:
        purged, tombstone_path = check_and_purge_if_expired(session)
        if purged:
            logger.info("Business retention period exceeded. Purge completed successfully.")
            logger.info("Tombstone written to: %s", tombstone_path)
            return 0
        else:
            logger.info("Business retention period active. No purge required.")
            return 0
    except Exception as e:
        logger.error("Error running purge check: %s", e)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
