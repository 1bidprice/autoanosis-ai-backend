"""
Migration: Recalculate abnormal_flag for all ExamResult records.
Sets H/L/N based on value_numeric vs reference_low/reference_high.
Records without numeric value or reference range are left as-is.

Run: python migrate_abnormal_flags.py
"""

import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate_flags")

# Load env
from dotenv import load_dotenv
load_dotenv()

from exams_module.models.exam_models import ExamResult
from exams_module.db.database import SessionLocal

def migrate():
    db = SessionLocal()
    try:
        results = db.query(ExamResult).all()
        logger.info(f"Total ExamResult records: {len(results)}")

        updated = 0
        skipped_no_value = 0
        skipped_no_range = 0

        for r in results:
            val = float(r.value_numeric) if r.value_numeric is not None else None
            low = float(r.reference_low) if r.reference_low is not None else None
            high = float(r.reference_high) if r.reference_high is not None else None

            if val is None:
                skipped_no_value += 1
                continue

            if low is None and high is None:
                skipped_no_range += 1
                continue

            # Compute flag
            if low is not None and high is not None:
                if val < low:
                    new_flag = "L"
                elif val > high:
                    new_flag = "H"
                else:
                    new_flag = "N"
            elif low is not None:
                new_flag = "L" if val < low else "N"
            else:  # only high
                new_flag = "H" if val > high else "N"

            if r.abnormal_flag != new_flag:
                logger.debug(f"  {r.display_name}: {r.abnormal_flag} → {new_flag} (val={val}, low={low}, high={high})")
                r.abnormal_flag = new_flag
                updated += 1

        db.commit()
        logger.info(f"Migration complete: {updated} updated, {skipped_no_value} skipped (no value), {skipped_no_range} skipped (no range)")

    except Exception as e:
        db.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate()
