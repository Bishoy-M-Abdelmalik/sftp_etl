"""
BulkLoadSource Module

Concrete implementation of the DataSource abstract base class.
Handles download, unzip, and bulk loading via SQL Server BCP.
"""
import os
import shutil
import logging
import subprocess
from datetime import datetime
from typing import Optional, List, Dict, Any

import paramiko
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from DataSource.data_source_base import DataSource
from DataSource.Utilities import file_utils, zipfile_utils

debug_logger = logging.getLogger("etl_debug")


class BulkLoadSource(DataSource):
    """Handles extracting and bulk-loading files."""

    def __init__(
        self,
        sftp_client: Optional[paramiko.SFTPClient],
        config: Dict[str, Any],
        current_date: str,
        processing_dir: str,
        db_engine: Optional[Engine] = None
    ):
        super().__init__(sftp_client, config, current_date, processing_dir, db_engine=db_engine)

        self.db_server = config.get("db_server", "")
        self.db_name = config.get("db_name", "")
        self.db_schema = config.get("db_schema", "bulkload")
        self.xml_path = config.get("xml_path", "")

        os.makedirs(self.processing_dir, exist_ok=True)

    def download_target_files(self) -> List[str]:
        if not self.sftp:
            raise RuntimeError("SFTP client is not connected.")

        target_path = os.path.normpath(os.path.join(self.processing_dir, "BulkLoadSource"))
        os.makedirs(target_path, exist_ok=True)

        downloaded_files: List[str] = []
        try:
            debug_logger.info("Scanning remote directory: %s", self.remote_dir)
            remote_files = self.sftp.listdir(self.remote_dir)

            target_files = [
                f for f in remote_files
                if f.startswith(self.prefix) and self.date_suffix in f
            ]

            if not target_files:
                debug_logger.warning("No matching files found for date %s", self.date_suffix)
                return []

            files_to_download = file_utils.get_latest_file(target_files, self.date_suffix)

            for file_name in files_to_download:
                remote_path = f"{self.remote_dir.rstrip('/')}/{file_name}"
                local_path = os.path.normpath(os.path.join(target_path, file_name))

                debug_logger.info("Downloading: %s", file_name)
                self.sftp.get(remote_path, local_path)
                downloaded_files.append(local_path)
                debug_logger.info("Successfully downloaded %s", file_name)

            return downloaded_files

        except paramiko.SSHException as ssh_err:
            debug_logger.error("SSH error during file download: %s", ssh_err)
            raise
        except paramiko.SFTPError as sftp_err:
            debug_logger.error("SFTP error: %s", sftp_err)
            raise
        except FileNotFoundError as fnf_err:
            debug_logger.error("Remote path not found: %s", fnf_err)
            raise
        except IOError as io_err:
            debug_logger.error("Error downloading the file(s): %s", io_err)
            raise
        except Exception as exc:
            debug_logger.error("Error during download: %s", exc)
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(OperationalError),
        reraise=True
    )
    def process_pipeline(self, file_paths_list: List[str]) -> None:
        if not file_paths_list:
            return

        try:
            files_list = zipfile_utils.multi_part_zipfile_processing(file_paths_list)
            files_list = zipfile_utils.extract_all_zip_files(files_list)

            # The extracted content is typically a folder of .dat files
            self.processing_dir, _ = os.path.split(files_list[0])

            self._run_bcp_load()
            self._run_data_integrity_check()

            if os.path.exists(self.processing_dir):
                shutil.rmtree(self.processing_dir)
                debug_logger.info("Successfully cleaned up processing directory: %s", self.processing_dir)

            debug_logger.info("Pipeline completed successfully.")
        except Exception as exc:
            debug_logger.error("Error in processing pipeline: %s", exc)
            raise

    def _run_bcp_load(self) -> None:
        debug_logger.info("--- Starting BCP load process ---")

        try:
            with self.db_engine.begin() as conn:
                result = conn.execute(
                    text("SELECT TableName, FileDAT, FileXML FROM [etl].[FileMapping]")
                )
                table_data = result.fetchall()

            for row in table_data:
                table_name = row.TableName
                file_dat = row.FileDAT
                file_xml = row.FileXML

                truncate_sql = f"TRUNCATE TABLE {self.db_schema}.{table_name}"

                try:
                    with self.db_engine.begin() as conn:
                        conn.execute(text(truncate_sql))
                    self._log_db_command(truncate_sql, "SUCCESS", 0, None)

                    dat_path = os.path.normpath(os.path.join(self.processing_dir, file_dat))
                    xml_path = os.path.normpath(os.path.join(self.xml_path, file_xml))

                    # -Yo = Encryption Optional (compatible with ODBC Driver 18+)
                    bcp_cmd = (
                        rf'bcp [{self.db_name}].[{self.db_schema}].{table_name} '
                        rf'in "{dat_path}" -n -T -S {self.db_server} -f "{xml_path}" -Yo'
                    )

                    result = subprocess.run(bcp_cmd, capture_output=True, text=True, check=True)

                    if result.returncode == 0:
                        rows_affected = 0
                        for line in result.stdout.splitlines():
                            if "rows copied" in line.lower():
                                words = line.split()
                                if words and words[0].isdigit():
                                    rows_affected = int(words[0])
                                    break
                        self._log_db_command(bcp_cmd, "SUCCESS", rows_affected, None)

                except subprocess.CalledProcessError as e:
                    self._log_db_command(bcp_cmd, "FAILED", 0, e.stdout.strip())
                    debug_logger.error(
                        "BCP failed for '%s'. Exit code: %s, stdout: %s, stderr: %s",
                        table_name, e.returncode, e.stdout, e.stderr
                    )
                    raise
                except Exception as inner_exc:
                    error_msg = str(inner_exc)
                    self._log_db_command(truncate_sql, "FAILED", 0, error_msg)
                    debug_logger.error("Error processing %s: %s", table_name, error_msg)
                    raise

            with self.db_engine.begin() as conn:
                conn.execute(
                    text(f"DELETE FROM {self.db_schema}.MainInstances WHERE root_number IS NULL")
                )
            debug_logger.info("BCP load process completed.")

        except Exception as exc:
            debug_logger.error("Fatal error during BCP Load: %s", exc)
            raise

    def _log_db_command(
        self, command_text: str, status: str, rows: int, error_message: Optional[str]
    ) -> None:
        timestamp = datetime.now()
        insert_stmt = text("""
            INSERT INTO [etl].[LoadLog]
            (CommandText, Status, RowsAffected, ErrorMessage, ExecutionTime)
            VALUES (:cmd, :status, :rows, :err, :time)
        """)
        try:
            with self.db_engine.begin() as conn:
                conn.execute(insert_stmt, {
                    "cmd": command_text,
                    "status": status,
                    "rows": rows,
                    "err": error_message,
                    "time": timestamp
                })
        except Exception as exc:
            debug_logger.error("Failed to log command to DB: %s", exc)

    def _run_data_integrity_check(self) -> None:
        debug_logger.info("Running data integrity checks...")

        try:
            with self.db_engine.begin() as conn:
                # Example cleanup – adjust IDs / tables to your environment
                delete_stmt = text(
                    f"DELETE FROM [{self.db_schema}].[MainInstances] "
                    "WHERE instance_id IN (271847, 272298)"
                )
                result = conn.execute(delete_stmt)
                debug_logger.info("Cleaned up instances. Rows deleted: %d", result.rowcount)

                # Generic uniqueness / null checks (replace with your own rules)
                integrity_query = text(f"""
                    SELECT 0 FROM [{self.db_schema}].[MainInstances] WHERE root_number IS NULL
                    UNION ALL
                    SELECT COUNT(*) FROM [{self.db_schema}].[MainInstances]
                    GROUP BY instance_id HAVING COUNT(*) <> 1
                """)
                result = conn.execute(integrity_query)
                first_error = result.fetchone()

                if first_error:
                    raise ValueError(f"Data integrity check failed: {first_error[0]}")

            debug_logger.info("Data integrity check passed successfully.")

        except Exception as exc:
            debug_logger.error("Database execution error during integrity check: %s", exc)
            raise RuntimeError("Failed to execute DB checks.") from exc