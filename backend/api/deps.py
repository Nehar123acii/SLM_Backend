from typing import Generator
from sqlalchemy.orm import Session
from backend.db.engine import get_db

# Re-export get_db for clean route dependencies
__all__ = ["get_db"]
