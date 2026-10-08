"""
Database Reporter Module

Logs start and end of pipeline executions to SQL Server,
with CSV fallback support.
"""
import csv
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

debug_logger = logging.getLogger("etl_debug")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(OperationalError),
    reraise=True  # Ensures the final exception is passed back to the main module
)
def log_start(
    db_engine: Engine,
    session_id: int,
    sp_name: str,
    sp_sub_name: Optional[str] = None
) -> int:
    """
    Logs the start of a stored procedure execution.

    Args:
      db_engine (Engine): An _engine.Engine instance of SQLAlchemy.
      session_id (int): ID for the global extract session.
      sp_name (str): Name of the stored procedure.
      sp_sub_name: (Optional[str], optional) Name of the sub-stored procedure.

    Returns:
      int: The ID of the log entry created.

    Raises:
        Exception: If the database execution fails.
    """
    try:
        with db_engine.begin() as conn:

            exec_stmt = text("""
                EXEC etl.LogStart 
                    @SessionID = :session_id,
                    @SPName = :sp_name,
                    @SubName = :sub_name
            """)

            # Execute and Fetch the first column of the first row (the Log ID)
            current_log_id = conn.execute(exec_stmt, {
                "session_id": session_id,
                "sp_name": sp_name,
                "sub_name": sp_sub_name
            }).scalar()

            return current_log_id
    except Exception as e:
        debug_logger.error("Error logging start: %s", e)
        raise

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(OperationalError),
    reraise=True  # Ensures the final exception is passed back to the main module
)
def log_end(
    db_engine: Engine,
    session_id: int,
    link_id: int,
    sp_name: str,
    sp_sub_name: Optional[str] = None,
) -> bool:
    try:
        with db_engine.begin() as conn:

            exec_stmt = text("""
                EXEC etl.LogEnd 
                    @SessionID = :session_id,
                    @LinkID = :link_id,
                    @SPName = :sp_name,
                    @SubName = :sub_name
            """)
            conn.execute(exec_stmt, {
                "session_id": session_id,
                "link_id": link_id,
                "sp_name": sp_name,
                "sub_name": sp_sub_name
            })
        return True
    except Exception as e:
        debug_logger.error("Error logging end: %s", e)
        raise

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(OperationalError),
    reraise=True  # Ensures the final exception is passed back to the main module
)
def log_csv(db_engine: Engine, file_path: str) -> bool:
    rows_to_process: List[Dict[str, Any]] = []
    all_valid = True  # Flag to track the validity of all rows

    try:
        with open(file_path, mode="r", newline="", encoding="utf-8") as csvfile:
            csv_reader = csv.DictReader(csvfile)

            for row in csv_reader:
                status = row.get("Status", "").upper().strip()
                if status not in ["START", "END"]:
                    debug_logger.warning("Invalid Status: %s", row)
                    all_valid = False
                    continue
                rows_to_process.append(row)

        if not all_valid:
            debug_logger.error("CSV validation failed. No database entries created.")
            return False

        for row in rows_to_process:
            session_id = int(row["SessionID"])
            sp_name = row["SPName"]
            sub_name = row["SubName"] if row.get("SubName", "").strip() else None
            status = row.get("Status", "").upper().strip()

            if status == "START":
                log_start(db_engine, session_id, sp_name, sp_sub_name=sub_name)
            elif status == "END":
                link_id = int(row["LinkID"]) if row.get("LinkID") else None
                log_end(db_engine, session_id, link_id, sp_name, sp_sub_name=sub_name)

        return True  # Return True only if all rows are processed successfully

    except FileNotFoundError:
        debug_logger.error("File not found: %s", file_path)
    except PermissionError:
        debug_logger.error("Permission denied for file: %s", file_path)
    except ValueError as val_err:
        debug_logger.error("Data conversion error (e.g., non-integer ID in CSV): %s", val_err)
    except IOError as io_err:
        debug_logger.error("I/O error occurred: %s", io_err)
    except Exception as exc:
        debug_logger.error("Unexpected error processing CSV: %s", exc)

    return False
