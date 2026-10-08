"""
sftp_etl.py

Two-phase SFTP ETL pipeline.
Downloads files from remote SFTP servers, processes them locally,
and optionally bulk-loads data into SQL Server.

Author: Bishoy Abdelmalik
Version: 7.0.1
Date: 2026-06-10
"""
import os
import importlib
import argparse
from datetime import datetime
from typing import Any, Optional, Tuple, List, Dict

from secureConnectors.sftp_vault import load_config
from secureConnectors import sftpify
from secureConnectors.db_engine import create_robust_engine
from LogSuite.db_reporter import log_start, log_end, log_csv
from LogSuite.logging_setup import setup_logging_database, setup_logging_debug

CLASS_MAP = {
    "snapshot": ["SnapshotSource"],
    "bulk": ["AdminSource", "BulkLoadSource"],
    "flow": ["FlowAdminSource", "FlowExtractSource"],
    "all": ["SnapshotSource", "FlowAdminSource", "FlowExtractSource", "AdminSource", "BulkLoadSource"]
}

def import_class(module_name: str, *args, **kwargs) -> Any:
    """Import a class by name and return an instance."""
    try:
        module = importlib.import_module("DataSource." + module_name)
        mod_class = getattr(module, module_name)
        return mod_class(*args, **kwargs)
    except (ImportError, AttributeError) as e:
        raise ValueError(f"Could not import {module_name}") from e

def parse_and_validate_args(args_list: Optional[List[str]] = None) -> Tuple[int, str, List[str], Optional[str]]:
    """
    Parses arguments via argparse.
    Accepts an explicit list or falls back to sys.argv (for CLI).
    """
    parser = argparse.ArgumentParser(description="SFTP ETL Pipeline", exit_on_error=False)

    parser.add_argument("session_id", type=int, help="Global session ID (Integer)")
    parser.add_argument("processing_path", type=str, help="Local directory for processing files")
    parser.add_argument("mode", type=str, choices=list(CLASS_MAP.keys()),
                        help="Target module to execute")
    parser.add_argument("--prefix", type=str, default=None,
                        help="Dynamic file prefix (Required if mode is snapshot)")

    try:
        # Pass the custom args list if provided, otherwise argparse uses sys.argv naturally
        parsed_args = parser.parse_args(args_list)
    except argparse.ArgumentError as e:
        raise ValueError(e)

    os.makedirs(parsed_args.processing_path, exist_ok=True)

    return (parsed_args.session_id, parsed_args.processing_path, CLASS_MAP[parsed_args.mode], parsed_args.prefix)

def sftp_etl(args_list: Optional[List[str]] = None) -> None:
    """Main routine for downloading files via SFTP and processing them."""
    # Validate Args (Can be called via CMD or by another Python script)
    session_id, processing_path, modules_list, dynamic_prefix = parse_and_validate_args(args_list)
    csv_log_file = os.path.join(processing_path, "logs", "etl_log.csv")
    current_date = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]

    # Setup Loggers & Config
    debug_logger = setup_logging_debug(processing_path, "etl_debug.log")
    backup_logger = setup_logging_database(processing_path, "etl_log.csv")
    config = load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"))

    if dynamic_prefix:
        if "SnapshotSource" in modules_list:
            config['SnapshotSource']['prefix'] = dynamic_prefix

    # Setup Database Engine
    try:
        db_config = config['db_connect']
        # The engine is created, tested, and pooled entirely behind the scenes!
        engine = create_robust_engine(
            host=db_config['server'],
            database=db_config['database']
        )
    except Exception as exc:
        debug_logger.error("Fatal error initializing database engine: %s", exc)
        raise

    # Log Start
    current_log_id = None
    try:
        current_log_id = log_start(engine, session_id, "SFTP_ETL")
    except Exception as exc:
        debug_logger.error("Failed to log start to DB. Using CSV Backup: %s", exc)
        backup_logger.info("SFTP_ETL", extra={
            "SessionID": session_id,
            "LinkID": None,
            "SubName": f"Actual time: {current_date}",
            "Status": "START"
        })

    # Data structures to decouple Download and Process phases
    processor_map: Dict[str, Any] = {}
    files_dict: Dict[str, List[str]] = {}

    # 4. Download and process routine
    try:
        # PHASE 1: DOWNLOAD ALL FILES
        debug_logger.info("--- PHASE 1: STARTING DOWNLOADS ---")
        sftp_cfg = config['sftp_connect']

        with sftpify.SFTPService(
            sftp_cfg['host'], sftp_cfg['port'], sftp_cfg['username'], sftp_cfg['password']
        ) as sftp_service:

            for sftp_module in modules_list:
                debug_logger.info("Initializing %s", sftp_module)

                # Instantiate and store the processor object
                sftp_object = import_class(
                    sftp_module,
                    sftp_service,
                    config.get(sftp_module, {}),
                    current_date[:8],
                    processing_path,
                    db_engine=engine
                )

                processor_map[sftp_module] = sftp_object
                # Download and store the file list in the dictionary
                files_dict[sftp_module] = sftp_object.download_target_files()

        debug_logger.info("--- SFTP DISCONNECTED. PHASE 1 COMPLETE ---")

        # PHASE 2: PROCESS ALL FILES LOCALLY
        debug_logger.info("--- PHASE 2: STARTING LOCAL PROCESSING ---")

        for sftp_module in modules_list:
            sftp_object = processor_map[sftp_module]
            target_files = files_dict.get(sftp_module, [])

            if target_files:
                debug_logger.info("Processing files for %s", sftp_module)
                sftp_object.process_pipeline(target_files)
            else:
                debug_logger.info("No files to process for %s", sftp_module)

        debug_logger.info("--- PHASE 2 COMPLETE ---")

        # Log End (Success)
        try:
            log_end(engine, session_id, current_log_id, "SFTP_ETL")
        except Exception:
            backup_logger.info("SFTP_ETL", extra={
                "SessionID": session_id,
                "LinkID": current_log_id,
                "SubName": f"Actual time: {current_date}",
                "Status": "END"
            })

    except Exception as exc:
        # Log End (Failure)
        debug_logger.error("Fatal pipeline error: %s", exc)
        try:
            log_end(engine, session_id, current_log_id, "SFTP_ETL", sp_sub_name="FAIL")
        except Exception:
            backup_logger.info("SFTP_ETL", extra={
                "SessionID": session_id,
                "LinkID": current_log_id,
                "SubName": f"FAIL    {current_date}",
                "Status": "END"
            })
        raise

    finally:
        # Ingest CSV backups if any failed DB hits occurred
        if os.path.exists(csv_log_file) and os.path.getsize(csv_log_file) > 0:
            try:
                if log_csv(engine, csv_log_file):
                    os.remove(csv_log_file)
                    debug_logger.info("Backup CSV records uploaded to DB.")
            except Exception as exc:
                debug_logger.error("Failed to upload backup CSV to DB: %s", exc)

if __name__ == "__main__":
    sftp_etl()