"""
sftpify Module

Provides a context-managed, classes and functions for securely establishing, 
managing, and terminating SFTP connections using the paramiko library.
"""
import time
import logging
from socket import error as SocketError
from types import TracebackType
from typing import Optional, Type
import socket
import paramiko

debug_logger = logging.getLogger("etl_debug")

class SFTPService:
    """Context manager for SFTP operations."""

    def __init__(self, host: str, port: int, username: str, password: str, retries: int = 3):
        """
        Initializes the SFTPService object with connection credentials.

        Args:
            host (str): The hostname or IP address of the SFTP server.
            port (int): The port number for the SFTP server.
            username (str): The username for authenticating with the server.
            password (str): The password for authenticating with the server.
            retries (int, optional): Number of connection attempts. Defaults to 3.
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.retries = retries
        self.transport: Optional[paramiko.Transport] = None
        self.client: Optional[paramiko.SFTPClient] = None

    def __enter__(self) -> paramiko.SFTPClient:
        """
        Establishes an SFTP connection using the provided credentials.

        Returns:
            paramiko.SFTPClient: An active SFTP client session.

        Raises:
            paramiko.AuthenticationException: If the username or password is rejected.
            paramiko.SSHException, socket.error: If max retry limit is reached during connection.
        """
        attempt = 0
        while attempt < self.retries:
            try:
                debug_logger.info("Connecting to %s:%d (Attempt %d/%d)",
                                   self.host, self.port, attempt + 1, self.retries)

                sock = socket.create_connection((self.host, self.port), timeout=90)

                self.transport = paramiko.Transport(sock)

                self.transport.default_window_size = 4 * 1024 * 1024  # 4MB buffer
                self.transport.set_keepalive(30) # Send a heartbeat every 30 seconds
                self.transport.banner_timeout = 60 # Timeout for initial connection

                self.transport.connect(username=self.username, password=self.password)
                self.client = paramiko.SFTPClient.from_transport(self.transport)

                debug_logger.info("SFTP connection established successfully.")
                return self.client

            except paramiko.AuthenticationException as auth_err:
                attempt += 1
                debug_logger.error("Authentication failed: %s", auth_err)
                self._cleanup_failed_connection()
                if attempt < self.retries:
                    time.sleep(5)  # Wait before retrying
                raise
            except (SocketError, paramiko.SSHException) as ssh_err:
                attempt += 1
                debug_logger.error("Connection error: %s", ssh_err)
                self._cleanup_failed_connection()
                if attempt < self.retries:
                    time.sleep(5)  # Wait before retrying
                else:
                    debug_logger.error("Connection error: Max retries reached.")
                    raise

    def __exit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[TracebackType]
        ) -> None:
        """
        Closes the SFTP connection if it is established.

        This method gracefully handles errors during disconnection without 
        raising exceptions, ensuring the context manager can exit cleanly.

        Args:
            exc_type: The exception type, if an exception was raised in the with block.
            exc_val: The exception instance, if an exception was raised.
            exc_tb: The traceback, if an exception was raised.
        """
        try:
            if self.client:
                self.client.close()
                debug_logger.info("SFTP connection closed.")
            else:
                debug_logger.info("No active SFTP connection to close.")

            if self.transport:
                self.transport.close()
                debug_logger.info("SFTP transport closed.")
        except Exception as err:
            debug_logger.error("Error closing the SFTP connection: %s", err)

    def _cleanup_failed_connection(self) -> None:
        """Helper method to prevent resource leaks if __enter__ fails."""
        if self.transport:
            self.transport.close()
            self.transport = None
