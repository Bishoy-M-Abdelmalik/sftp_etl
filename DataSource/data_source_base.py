"""
Data Source Base Module

Provides an abstract base class blueprint for handling source-specific SFTP 
operations. All specific data source processors must inherit from this class.
"""
import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, List, Dict

import paramiko
from sqlalchemy.engine import Engine

# Configure module-level logger
debug_logger = logging.getLogger("etl_debug")

class DataSource(ABC):
    """
    Abstract base class for handling DataSource-specific operations.
    Provides a mandatory blueprint for downloading and processing files.
    """

    def __init__(self,
        sftp_client: Optional[paramiko.SFTPClient],
        config: Dict[str, str],
        date_suffix: str,
        processing_dir: str,
        db_engine: Optional[Engine] = None):
        """
        Initializes the data source configuration.

        Args:
            sftp_client (Optional[paramiko.SFTPClient]): The active SFTP connection.
            config (Dict[str, str]): The YAML configuration dictionary for this specific task.
            date_suffix (str): The current date string for file filtering.
            processing_dir (str): The local directory where files are downloaded and processed.
            db_engine (Optional[Engine]): SQLAlchemy database engine for DB operations.
        """
        self.sftp = sftp_client
        self.date_suffix = date_suffix
        self.db_engine = db_engine
        self.processing_dir = os.path.normpath(processing_dir)

        # Extract common configurations securely
        self.remote_dir =config.get('sftp_path', '')
        self.local_dir = os.path.normpath(config.get('local_path', ''))
        self.prefix = config.get('prefix', '')

    @abstractmethod
    def download_target_files(self) -> List[str]:
        """
        Downloads files from the SFTP server based on source-specific logic.

        Returns:
            List[str]: A list of absolute local paths to the downloaded files.
        """

    @abstractmethod
    def process_pipeline(self, file_paths_list: List[str]):
        """
        Processes the downloaded files through the data transformation pipeline.

        Args:
            file_paths_list (List[str]): List of local file paths to process.
        """
