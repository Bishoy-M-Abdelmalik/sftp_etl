"""
logging_setup Module

Provides debug file logging and structured CSV telemetry logging.
"""
import os
import logging
import csv

def setup_logging_debug(log_path: str, file_name: str) -> logging.Logger:
    """
    Sets up a debug logger that writes to a log file.

    Args:
        log_path (str): Directory where log file will be stored.
        file_name (str): The name of the log file.
    Returns:
        Logging.Logger: Logger for detailed debug messages.
    """
    debug_logger = logging.getLogger("etl_debug")

    if debug_logger.hasHandlers():
        return debug_logger

    debug_logger.setLevel(logging.DEBUG)

    # Create a log directory if it doesn't exist
    folder_path = os.path.join(log_path, "logs")
    os.makedirs(folder_path, exist_ok=True)

    # Define file path for the log file
    log_file_path = os.path.join(folder_path, file_name)

    # Detailed log format for the debug logger
    detailed_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - [%(module)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    debug_log_handler = logging.FileHandler(log_file_path, mode = 'a', encoding="utf-8")
    debug_log_handler.setLevel(logging.DEBUG)
    debug_log_handler.setFormatter(detailed_formatter)
    debug_logger.addHandler(debug_log_handler)

    return debug_logger

class CSVHandler(logging.Handler):
    """
    Custom logging handler for writing log records to a CSV file.

    This handler manages the creation of the CSV file and writing of log entries
    in a structured format.

    Opens and closes the file on each emit. While this carries a small I/O 
    overhead, it is extremely safe for low-frequency logging and ensures 
    data is flushed to disk immediately without locking the file permanently.
    """

    def __init__(self, filename: str):
        super().__init__()
        self.filename = filename
        self.fieldnames = [
            "SessionID", "LinkID", "SPName", "SubName", "Status"
        ]

    def emit(self, record):
        """
        Writes a log entry to the CSV file by extracting custom attributes 
        passed via the `extra` dictionary in the logging call.

        Args:
            record (logging.LogRecord): The log record to write.
        """
        try:
            # Check if we need to write the header right BEFORE we write the log
            file_exists = os.path.exists(self.filename)
            write_header = not file_exists or os.path.getsize(self.filename) == 0

            log_entry = {
                "SessionID": getattr(record, "SessionID", ""),
                "LinkID": getattr(record, "LinkID", ""),
                "SPName": record.msg,
                "SubName": getattr(record, "SubName", ""),
                "Status": getattr(record, "Status", ""),
            }

            with open(self.filename, "a", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self.fieldnames)
                if write_header:
                    writer.writeheader()
                writer.writerow(log_entry)

        except Exception:
            # Fallback to standard error so the system captures the failure,
            # but the main application keeps running.
            self.handleError(record)

def setup_logging_database(log_path: str, csvfile_name: str) -> logging.Logger:
    """
    Sets up a CSV logger that writes telemetry to a structured log file.

    Args:
        log_path (str): Directory where the log file will be stored.
        csvfile_name (str): The name of the CSV log file.

    Returns:
        logging.Logger: Logger for database-related logs in CSV format.
    """
    folder_path = os.path.join(log_path, "logs")
    os.makedirs(folder_path, exist_ok=True)
    csv_file_path = os.path.join(folder_path ,csvfile_name)

    # Note: No formatter is set here because the CSVHandler manually
    # maps the log record attributes to columns in its emit() method.

    database_logger = logging.getLogger("etl_database_log")
    database_logger.setLevel(logging.INFO)

    if not database_logger.hasHandlers():
        csv_log_handler = CSVHandler(csv_file_path)
        csv_log_handler.setLevel(logging.INFO)
        database_logger.addHandler(csv_log_handler)

    return database_logger
