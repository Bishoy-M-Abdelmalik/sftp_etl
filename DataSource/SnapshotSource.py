"""
SnapshotSource Module

Concrete implementation of the DataSource abstract base class.
Handles download and processing for snapshot-style data sources.
"""
import os
import logging
from typing import Optional, List, Dict, Any
import paramiko
from sqlalchemy.engine import Engine
from DataSource.data_source_base import DataSource
from DataSource.Utilities import file_utils, zipfile_utils

debug_logger = logging.getLogger("etl_debug")


class SnapshotSource(DataSource):
    """Handles extracting and processing files for snapshot sources."""

    def __init__(
        self,
        sftp_client: Optional[paramiko.SFTPClient],
        config: Dict[str, Any],
        current_date: str,
        processing_dir: str = "/tmp/etl/processing",
        db_engine: Optional[Engine] = None
    ):
        super().__init__(sftp_client, config, current_date, processing_dir, db_engine=db_engine)
        try:
            self.index = int(config.get("index", 0))
        except ValueError:
            debug_logger.warning("'index' in config is not a valid int. Defaulting to 0.")
            self.index = 0

        os.makedirs(self.local_dir, exist_ok=True)
        os.makedirs(self.processing_dir, exist_ok=True)

    def download_target_files(self) -> List[str]:
        if not self.sftp:
            raise RuntimeError("SFTP client is not connected.")

        target_path = os.path.normpath(os.path.join(self.processing_dir, "SnapshotSource"))
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

            for file_name in target_files:
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

    def process_pipeline(self, file_paths_list: List[str]) -> None:
        if not file_paths_list:
            return

        try:
            files_list = zipfile_utils.multi_part_zipfile_processing(file_paths_list)
            files_list = zipfile_utils.extract_all_zip_files(files_list)
            files_list = file_utils.rename_files(files_list, self.index, "_snapshot")
            file_utils.move_files(files_list, self.local_dir)
            debug_logger.info("Pipeline completed successfully.")
        except Exception as exc:
            debug_logger.error("Error in processing pipeline: %s", exc)
            raise