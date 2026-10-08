"""
db_engine Module

Provides a robust SQLAlchemy Engine configured for connection pooling and resilience.
Designed for long-running applications that execute multiple queries over time.
"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import OperationalError, InterfaceError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

debug_logger = logging.getLogger("etl_debug")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((OperationalError, InterfaceError)),
    reraise=True
)
def create_robust_engine(
    host: str,
    database: str,
    driver: str = "ODBC Driver 17 for SQL Server"
) -> Engine:
    """
    Creates and validates a SQLAlchemy engine with robust connection pooling.

    Args:
        host (str): Database server hostname or IP.
        database (str): Target database name.
        driver (str): ODBC driver name.

    Returns:
        Engine: A fully configured and tested SQLAlchemy Engine.
    """
    try:
        connection_url = URL.create(
            drivername="mssql+pyodbc",
            host=host,
            database=database,
            query={"driver": driver, "trusted_connection": "yes"}
        )

        engine = create_engine(
            connection_url,
            fast_executemany=True,
            pool_pre_ping=True,     # Checks connection health before every use
            pool_recycle=1800       # Re-creates connections every half hour to avoid stale sockets
        )

        # Validate the engine immediately. create_engine does not connect until
        # the first query. We force a connection here so the tenacity retry triggers
        # if the server is offline during initialization.
        with engine.connect():
            debug_logger.info("Database connection verified successfully.")

        return engine
    except OperationalError as e:
        # Handles: Server down, network issues, firewall, invalid credentials
        debug_logger.error("server down or network error: %s", e)
        raise
    except InterfaceError as e:
        # Handles: Driver not found, ODBC issues
        debug_logger.error("driver or ODBC config error: %s", e)
        raise
    except Exception as exc:
        debug_logger.error("Failed to establish database engine: %s", exc)
        raise
