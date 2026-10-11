"""
Zipfile Utilities Module

This module provides utilities for handling zip files, including:
    - Identifying and safely combining multi-part zip files.
    - Extracting contents from zip files into their respective directories.
"""
import os
import re
import zipfile
import shutil
import logging
from typing import List, Tuple, Optional

debug_logger = logging.getLogger("etl_debug")

def multi_part_zipfile_processing(files_path_list: List[str]) -> List[str]:
    """
    Process a list of file paths to combine multi-part zip files.

    This function identifies zip files that are split into multiple parts,
    combines them into a single zip file, and updates the list of files
    accordingly until no more multi-part zip files are found.

    Args:
        files_path_list (List[str]): A list of file paths to process.

    Returns:
        List[str]: An updated list of file paths after processing.
    """
    try:
        base_name, zipfiles_parts_list = _get_next_multipart(files_path_list)

        while zipfiles_parts_list and base_name:
            if _combine_zipfile_parts(base_name, zipfiles_parts_list):
                files_path_list = _update_zipfiles_list(
                    files_path_list, base_name, zipfiles_parts_list)
            else:
                # If combination fails, break to avoid an infinite loop
                debug_logger.error("[zipfile_utils] Failed to combine parts for %s", base_name)
                break
            base_name, zipfiles_parts_list = _get_next_multipart(files_path_list)

        return files_path_list
    except Exception as e:
        debug_logger.error(
            "[zipfile_utils] Unexpected error processing multi-part zip file: %s", e)
        raise

def _get_next_multipart(files_path_list: List[str]) -> Tuple[Optional[str], List[str]]:
    """
    Identify the next set of multi-part zip files from the provided paths.

    Args:
        files_path_list (List[str]): A list of file paths to check.

    Returns:
        Tuple ([Optional[str], List[str]]): The base filename and a sorted list of its parts.
    """
    for file_path in files_path_list:
        # Match e.g., "data.zip.001" or "data.zip.part1"
        match = re.search(r"(.+\.zip)(\.\d+|\.part\d+)$", file_path, re.IGNORECASE)
        if match:
            base_name = match.group(1)
            # Find all parts for this specific base name AND sort them alphabetically
            #  to ensure binary combination order is correct!
            parts = sorted([f for f in files_path_list if f.startswith(base_name)])
            return base_name, parts

    return None, []

def _combine_zipfile_parts(base_name: str, zipfiles_parts_list: List[str]) -> bool:
    """
    Combine multiple parts of a zip file securely using memory-safe chunking.

    This function takes a list of zip file parts and combines them
    into a single zip file by writing their contents to a new file.

    Args:
        base_name (str): The target output filename (e.g., "data.zip").
        zipfiles_parts_list (List[str]): A sorted list of the file parts.

    Returns:
        bool: True if successful, False otherwise.
                
    Raises:
        (shutil.Error, IOError, OSError): Disk, and System errors
    """
    try:
        # Validate all parts exist before starting
        for part in zipfiles_parts_list:
            if not os.path.exists(part):
                debug_logger.warning("[zipfile_utils] Part %s does not exist.", part)
                return False

        with open(base_name, "wb") as combined_zipfile:
            for file_part in zipfiles_parts_list:
                with open(file_part, "rb") as part:
                    shutil.copyfileobj(part, combined_zipfile)
        debug_logger.info("[zipfile_utils] Combined zip file created: %s", base_name)

        # Delete the parts after successful combination to save disk space
        for part in zipfiles_parts_list:
            os.remove(part)

        return True
    except (shutil.Error, IOError, OSError) as e:
        debug_logger.error("[zipfile_utils] error combining zip file '%s': %s", base_name, e)
        raise
    except Exception as e:
        debug_logger.error(
            "[zipfile_utils] Unexpected error combining zip file '%s': %s", base_name, e)
        raise

def _update_zipfiles_list(
        files_path_list: List[str], base_name: str, zipfiles_parts_list: List[str]) -> List[str]:
    """
    Update the list of file paths after combining zip file parts.

    This function removes the original parts from the list and adds
    the newly created combined zip file.

    Args:
        files_path_list (List[str]): The original list of file paths.
        base_name (str): The newly created combined zip file.
        zipfiles_parts_list (List[str]): The parts to remove from the list.

    Returns:
        List[str]: An updated list of file paths.
    """
    updated_list = [file for file in files_path_list if file not in zipfiles_parts_list]
    updated_list.append(base_name)
    return updated_list

def extract_all_zip_files(files_path_list: List[str]) -> List[str]:
    """
    Extract all zip files from the list, returning a unified list of 
    extracted files and any non-zip files that were untouched.

    Args:
        files_path_list (List[str]): A list of file paths to check for zip files.

    Returns:
        List[str]: Updated list containing extracted files and untouched non-zips.

    Raises:
        zipfile.BadZipFile: Corrupted zip file
        (PermissionError, FileNotFoundError): Access errors
        (OSError, zipfile.LargeZipFile): System or Size errors
    """
    updated_file_list: List[str] = []

    for file_path in files_path_list:
        if not file_path.lower().endswith(".zip"):
            # Keep non-zip files in the pipeline
            updated_file_list.append(file_path)
            continue

        try:
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                extract_to = os.path.dirname(file_path) # Extract to the same directory
                zip_ref.extractall(extract_to)

                # Construct the absolute paths for the extracted files
                updated_file_list.extend(
                    [os.path.join(extract_to, file) for file in zip_ref.namelist()])
            debug_logger.info("Extracted: %s to %s", file_path, extract_to)

        except zipfile.BadZipFile:
            debug_logger.error("[zipfile_utils] Corrupted zip file: %s", file_path)
            raise
        except (PermissionError, FileNotFoundError) as e:
            debug_logger.error("[zipfile_utils] Access error for %s: %s", file_path, e)
            raise
        except (OSError, zipfile.LargeZipFile) as e:
            debug_logger.error("[zipfile_utils] System or Size error for %s: %s", file_path, e)
            raise
        except Exception as e:
            debug_logger.error(
                "An unexpected error occurred while extracting %s: %s", file_path, e)
            raise

    return updated_file_list
