"""Seed the UI-preview case (see epilogue.preview). Prefer: `epilogue preview`.

Usage:
    EPILOGUE_DATA_DIR=data-preview python scripts/preview_state.py
    EPILOGUE_DATA_DIR=data-preview epilogue serve
"""

from epilogue.config import db_path
from epilogue.ledger import Ledger
from epilogue.preview import seed_preview

case = seed_preview(Ledger(db_path()))
print(f"Preview case ready: {case.id} (db: {db_path()})")
