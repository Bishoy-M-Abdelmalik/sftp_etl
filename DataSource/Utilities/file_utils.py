"""
File Utilities Module

Processes JSON files, converts them into well-structured CSV and/or JSON outputs.
Handles finding the latest files, renaming, moving to specific directories, and copying files.
"""
import os
import json
import csv
import re
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, overload

# Configure module-level logger
debug_logger = logging.getLogger("sftp_download_debug")

def _load_json(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Load a JSON file from disk using various encodings.

    Args:
        file_path (str): Path to the JSON file to load.

    Returns:
        Optional[Dict[str, Any]]: The loaded JSON data, or None if the file cannot be loaded.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file cannot be decoded as JSON.
        IOError: For I/O errors during file reading.
    """
    encodings_to_try = ["utf_16", "utf_8_sig", "utf_16_be", "utf_16_le", "latin-1", "cp1252"]
    for encoding in encodings_to_try:
        try:
            with open(file_path, "r", encoding=encoding, errors='replace') as file:
                return json.load(file)
        except FileNotFoundError:
            debug_logger.error("[file_utils] The file '%s' does not exist.", file_path)
        except json.JSONDecodeError:
            continue # Try the next encoding
        except IOError as e:
            debug_logger.error("[file_utils] IO error while loading '%s': %s", file_path, e)
        except ValueError as e:
            debug_logger.error("[file_utils] ValueError while loading '%s': %s", file_path, e)
        except Exception as e:
            debug_logger.error("[file_utils] Unexpected error loading '%s': %s", file_path, e)

    debug_logger.error(
        "[file_utils] Exhausted all encodings. Could not decode The file '%s", file_path)
    return None

def _write_to_csv(filename: str, headers: List[str], csv_rows: List[Dict[str, Any]]) -> None:
    """
    Writes data to a CSV file with the specified headers and rows.

    Args:
        filename (str): The name of the output CSV file.
        headers (List[str]): The list of headers for the CSV file.
        csv_rows (List[Dict[str, Any]]): A list of dictionaries to write as rows in the CSV file.

    Raises:
        IOError: If there is an I/O error during file writing.
    """
    try:

        # Write the CSV file with specified headers and rows
        with open(filename, mode="w", newline="", errors='replace') as file:
            writer = csv.DictWriter(file, fieldnames=headers, delimiter=',')
            writer.writeheader()
            writer.writerows(csv_rows)
            debug_logger.info("[file_utils] Generated CSV file for '%s'.", filename)
    except IOError as e:
        debug_logger.error("[file_utils] IO error while writing to CSV '%s': %s", filename, e)
        raise
    except Exception as e:
        debug_logger.error("[file_utils] Unexpected error writing to CSV '%s': %s", filename, e)
        raise

def _write_to_json(filename: str, key: str, data: List[Dict[str, Any]]) -> None:
    """
    Writes a list of dictionaries to a JSON file under a specific key.

    Args:
        filename (str): The path to the output JSON file.
        key (str): The key to wrap the data under in the JSON file.
        data (list): The list of dictionaries to write to the JSON file.

    Raises:
        IOError: If there is an I/O error during file writing.
    """
    try:
        json_structure = {key: data}
        with open(filename, "w", encoding="utf-16", errors='replace') as jsonfile:
            json.dump(json_structure, jsonfile, indent=4, ensure_ascii=False)
            debug_logger.info("[file_utils] Generated JSON file for '%s' as '%s'.", key, filename)
    except IOError as e:
        debug_logger.error("[file_utils] IO error writing JSON '%s': %s", filename, e)
        raise
    except Exception as e:
        debug_logger.error("[file_utils] Unexpected error writing JSON '%s': %s", filename, e)
        raise

def _process_data(
        json_data: Dict[str, Any], file_basename: str, output_format: str = "both") -> List[str]:
    """
    Helper function to process JSON data and generate CSV and/or JSON files.
    Iterates through the JSON data and generates corresponding CSV and JSON files
    for keys that have list values.    
    
    Args:
        json_data (Dict[str, Any]): The loaded JSON data.
        file_basename (str): The base name of the file for naming output files.
        output_format (str): The desired format of output files

    Returns:
        List[str]: A list of generated CSV and JSON files path.

    Raises:
        ValueError: If unexpected headers are found in the JSON data.
    """
    try:
        if json_data is None:
            debug_logger.error("[file_utils] No data to process for file '%s'.", file_basename)
            return []  # return empty list if loading failed

        new_files_list: List[str] = []
        for key, value in json_data.items():

            if isinstance(value, dict):
                continue  # Skip nested dictionaries (no CSV/JSON generation).

            if isinstance(value, list) and value and isinstance(value[0], dict):
                headers = set()
                for item in value:
                    if isinstance(item, dict):
                        headers.update(item.keys())

                # Convert headers set to list and sort
                headers = sorted(headers)

                # Generate a CSV file for lists of dictionaries.
                if output_format in ["csv", "both"]:
                    csv_filename = f"{file_basename}{key}.csv"
                    _write_to_csv(csv_filename, headers, value)
                    new_files_list.append(csv_filename)
                    debug_logger.info(
                        "[file_utils] Generated CSV file for '%s' as '%s'.", key, csv_filename)

                # Generate a JSON file for the list of dictionaries.
                if output_format in ["json", "both"]:
                    json_filename = f"{file_basename}{key}.json"
                    _write_to_json(json_filename, key, value)
                    new_files_list.append(json_filename)
    except ValueError as e:
        debug_logger.error("[file_utils] %s", e)
        raise
    except Exception as e:
        debug_logger.error("[file_utils] %s", e)
        raise

    return new_files_list

def convert_json_to_formats(file_paths_list: List[str], output_format: str = "both") -> List[str]:
    """
    A main function to convert a list of JSON files into CSV and JSON files
    for each key in the JSON that contains a list of dictionaries.

    Args:
    file_paths_list (List[str]): A list of paths to JSON files to process.

    Returns:
      List[str]: A list of paths to the generated CSV and JSON files.

    Raises:
        FileNotFoundError: If any of the provided file paths do not exist.
        json.JSONDecodeError: If any of the JSON files are invalid or cannot be decoded.
        IOError: If there are I/O errors while reading or writing files.
        ValueError: If the JSON data contains unexpected data (e.g., unexpected headers).
        Exception: Any other unexpected errors during the conversion process.
    """
    updated_file_paths: List[str] = []

    for file_path in file_paths_list:
        debug_logger.info("[file_utils] Processing file: %s", file_path)
        if not os.path.exists(file_path):
            debug_logger.error("[file_utils] File '%s' does not exist. Skipping.", file_path)
            continue
        # If the file is not a JSON file, keep the original path.
        if not file_path.lower().endswith(".json"):
            updated_file_paths.append(file_path)
            continue

        # Process only JSON files.
        try:
            json_data = _load_json(file_path)

            # Extract the directory and basename (without extension) from the file path.
            directory, file_basename = os.path.split(file_path)
            file_basename = file_basename.replace(".json", "")

            # Process the JSON data and generate CSV/JSON files.
            new_files_list = _process_data(
                json_data, os.path.join(directory, file_basename), output_format)

            # Prepend the directory path to each generated file.
            new_files_list = [os.path.join(directory, files) for files in new_files_list]
            updated_file_paths.extend(new_files_list)

            os.remove(file_path)    # Delete original json

        except FileNotFoundError:
            debug_logger.error("[file_utils] File '%s' not found.", file_path)
            raise
        except json.JSONDecodeError:
            debug_logger.error("[file_utils] File '%s' is not a valid JSON file.", file_path)
            raise
        except ValueError as e:
            raise ValueError(f"[file_utils] Error processing file '{file_path}': {str(e)}") from e
        except Exception as e:
            debug_logger.error("[file_utils] Error processing '%s': %s", file_path, e)
            raise

    return updated_file_paths

def get_latest_file(file_names: List[str], date_str: str) -> List[str]:
    """
    Given a list of file names, this function returns the latest file(s)
    for each unique filename prefix based on the date-time encoded in the filename.

    The function expects filenames with format: <prefix><YYYYMMDD><HHMMSS...>
    It identifies files with the same prefix but different timestamps,
    and returns only the most recent version of each file.

    Args:
        file_names (list[str]): A list of file names to evaluate.
        date_str (str): The date string (in format YYYYMMDD) to locate in the filenames.

    Returns:
        list[str]: A list of the latest file name(s) for each prefix.
    """
    latest_files = {}

    for file_name in file_names:
        # Check if the filename contains the date string
        if date_str not in file_name:
            continue

        # Extract the prefix and the time part
        prefix = file_name.split(date_str)[0]  # Everything before the date
        time_part = file_name.split(date_str)[1]  # Everything after the date

        # Safeguard against insufficient string length for timestamp extraction
        if len(time_part) < 9:  # Needs at least 9 characters for time
            debug_logger.warning(
                "[file_utils] Filename needs at least 9 characters for timestamp: %s", file_name)
            continue

        # Extract the timestamp (first 9 characters)
        time_str = time_part[:9]

        try:
            file_time = datetime.strptime(time_str, "%H%M%S%f")
        except ValueError:
            debug_logger.warning(
                "[file_utils] Filename does not contain a valid time: %s", file_name
            )
            continue

        # a unique key that includes the suffix to handle multi-part zipped files
        file_suffix = time_part[9:]
        unique_key = (prefix, file_suffix)

        # Compare and store the latest file for each prefix
        if unique_key not in latest_files:
            latest_files[unique_key] = (file_time, file_name)
        else:
            if file_time > latest_files[unique_key][0]:
                latest_files[unique_key] = (file_time, file_name)

    # Extract the latest file names from the dictionary
    return [file_info[1] for file_info in latest_files.values()]

@overload
def rename_files(file_paths: List[str], index: int, suffix_to_add: str = "") -> List[str]:
    ...

@overload
def rename_files(file_paths: List[str], string_to_remove: str, suffix_to_add: str="") -> List[str]:
    ...

def rename_files(file_paths: List[str],
                 index_or_string: Union[int, str],suffix_to_add: str = "") -> List[str]:
    """
    Renames files based on either an index (removes prefix before index) 
    or a specific string (removes string and everything before it).

    Args:
        file_paths (List[str]): List of file paths to rename.
        index_or_string (Union[int, str]): An integer index OR a substring to remove.
        suffix_to_add (str): The suffix to add to the base filename.

    Returns:
        List[str]: A list of renamed file paths.

    Raises:
        PermissionError: If there are permission issues.
        OSError: If there is an OS-specific error.
    """
    updated_file_paths: List[str] = []

    for path_str in file_paths:
        try:
            file_path = Path(path_str)

            # Skip if it's not a valid file
            if not file_path.is_file():
                updated_file_paths.append(path_str)
                continue

            old_name = file_path.name
            temp_path = Path(old_name)

            # BRANCH 1: User passed an Integer (Index)
            if isinstance(index_or_string, int):
                index = index_or_string
                new_filename = f"{temp_path.stem[index:]}{suffix_to_add}{temp_path.suffix}"

            # BRANCH 2: User passed a String (Target text to remove)
            elif isinstance(index_or_string, str):
                string_to_remove = index_or_string

                # Apply your specific string-removal business logic
                if string_to_remove in old_name:
                    # Extract the suffix after the target string
                    suffix = old_name.split(string_to_remove)[1]

                    # Strip 9-digit numerical prefix if it exists
                    if bool(re.match(r"^\d{9}.*", suffix)):
                        suffix = suffix.replace(suffix[:9], "")

                    # Separate the remaining stem and extension to safely add suffix_to_add
                    temp_suffix = Path(suffix)
                    new_filename = f"{temp_suffix.stem}{suffix_to_add}{temp_suffix.suffix}"
                else:
                    # If it doesn't meet the conditions, skip renaming
                    updated_file_paths.append(path_str)
                    continue

            else:
                raise TypeError("The second argument must be either an int or a str.")

            # Apply the rename. The existing file (with the same name) will be silently overwritten
            new_file_path = file_path.with_name(new_filename)
            file_path.replace(new_file_path)

            debug_logger.info("[file_utils] Renamed '%s' -> '%s'", old_name, new_filename)
            updated_file_paths.append(str(new_file_path))

        except (PermissionError, OSError) as e:
            debug_logger.error("[file_utils] OS error renaming '%s': %s", path_str, e)
            raise
        except Exception as e:
            debug_logger.error("[file_utils] Unexpected error with '%s': %s", path_str, e)
            raise

    return updated_file_paths

def copy_files(updated_file_paths: List[str], target_directory: str) -> None:
    """
    Deletes all existing files and subdirectories in the target directory.
    Then copies the new files to that clean destination.

    Args:
        updated_file_paths (List[str]): List of file paths to copy.
        target_directory (str): The target directory destination.

    Raises:
        FileNotFoundError: If the file does not exist.
        PermissionError: If there are permission issues.
        shutil.Error: If there is an error during coping files.
    """
    # 1. Clean the target directory
    try:
        if not os.path.exists(target_directory):
            os.makedirs(target_directory, exist_ok=True)

        for filename in os.listdir(target_directory):
            file_path = os.path.join(target_directory, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                debug_logger.error("[file_utils] Failed to delete %s: %s", file_path, e)
                continue
    except OSError as e:
        debug_logger.error("[file_utils] Could not access or clear target directory: %s", e)
        raise

    # 2. COPY: Populate with new files
    for file_path in updated_file_paths:
        file_name = os.path.basename(file_path)
        target_path = os.path.join(target_directory, file_name)

        try:
            if os.path.exists(target_path):
                debug_logger.warning(
                    "[file_utils] File '%s' will be overwritten", target_path)

            shutil.copy(file_path, target_path)
            debug_logger.info("[file_utils] File '%s' copied to '%s'", file_name, target_directory)

        except FileNotFoundError:
            debug_logger.error("[file_utils] File '%s' not found.", file_path)
            raise
        except PermissionError:
            debug_logger.error("[file_utils] Permission denied while coping '%s'.", file_path)
            raise
        except shutil.Error as e:
            debug_logger.error("[file_utils] Error coping '%s': %s", file_path, e)
            raise
        except Exception as e:
            debug_logger.error("[file_utils] Unexpected error coping '%s': %s", file_path, e)
            raise

def move_files(updated_file_paths: List[str], target_directory: str) -> None:
    """
    Deletes all existing files and subdirectories in the target directory.
    Then moves the new files to that clean destination.

    Args:
        updated_file_paths (List[str]): List of file paths to move.
        target_directory (str): The target directory destination.

    Raises:
        FileNotFoundError: If the source file does not exist.
        PermissionError: If there are permission issues.
        shutil.Error: If there is an error during moving files.
    """
    # 1. Clean the target directory
    try:
        if not os.path.exists(target_directory):
            os.makedirs(target_directory, exist_ok=True)

        for filename in os.listdir(target_directory):
            file_path = os.path.join(target_directory, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                debug_logger.error("[file_utils] Failed to delete %s: %s", file_path, e)
                continue
    except OSError as e:
        debug_logger.error("[file_utils] Could not access or clear target directory: %s", e)
        raise

    # 2. MOVE: Populate with new files
    for file_path in updated_file_paths:
        file_name = os.path.basename(file_path)
        target_path = os.path.join(target_directory, file_name)

        try:
            if os.path.exists(target_path):
                debug_logger.warning(
                    "[file_utils] File '%s' will be overwritten", target_path)

            shutil.move(file_path, target_path)
            debug_logger.info("[file_utils] File '%s' moved to '%s'", file_name, target_directory)

        except FileNotFoundError:
            debug_logger.error("[file_utils] File '%s' not found.", file_path)
            raise
        except PermissionError:
            debug_logger.error("[file_utils] Permission denied while moving '%s'.", file_path)
            raise
        except shutil.Error as e:
            debug_logger.error("[file_utils] Error moving '%s': %s", file_path, e)
            raise
        except Exception as e:
            debug_logger.error("[file_utils] Unexpected error moving '%s': %s", file_path, e)
            raise
