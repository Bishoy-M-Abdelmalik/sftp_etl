"""
sftp_vault Module

Loads configuration YAML files and securely retrieves secrets
from the OS credential store via the keyring library.
"""
import logging
import yaml
import keyring

debug_logger = logging.getLogger("etl_debug")

def load_config(file_path: str) -> dict[str, str | int]:
    """
    Loads configuration from a YAML file and injects the SFTP password.

    Args:
        file_path (str): The path to the configuration YAML file.

    Returns:
        (dict[str, str | int]): The complete configuration dictionary with the password included.
    
    Raises:
        RuntimeError: If the password cannot be found in the locker
        (FileNotFoundError, yaml.YAMLError, KeyError): If config parsing fails.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)

            if not config or 'sftp_connect' not in config:
                raise KeyError("The config.yaml file is missing the 'sftp_connect' section.")

            service_name = config['sftp_connect']['service_name']
            username = config['sftp_connect']['username']

        config['sftp_connect']['password'] = keyring.get_password(service_name, username)

        if config['sftp_connect']['password'] is None:
            raise RuntimeError(f"Could not find password for '{service_name}' user '{username}'")

        return config
    except FileNotFoundError:
        debug_logger.error("'%s' not found.", file_path)
        raise
    except yaml.YAMLError as exc:
        debug_logger.error("'%s' has invalid syntax. Details: %s", file_path, exc)
        raise
    except KeyError as exc:
        debug_logger.error("A required key was not found in the config file: %s", exc)
        raise
    except Exception as e:
        debug_logger.error("An unexpected error occurred while loading config: %s", e)
        raise
