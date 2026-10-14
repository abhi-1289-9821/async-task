import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO)

from app.database import SessionLocal, create_all_tables
from app.seed import seed_demo_cases_if_empty

if __name__ == "__main__":
    create_all_tables()
    db = SessionLocal()
    try:
        seed_demo_cases_if_empty(db)
        print("Seed complete.")
    finally:
        db.close()
