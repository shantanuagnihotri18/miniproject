"""Create database/property.db (safe to run repeatedly):  python database/init_db.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402
load_dotenv()
from database.db import db_path, init_db  # noqa: E402

if __name__ == "__main__":
    init_db()
    print("Database ready:", db_path())
