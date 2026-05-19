"""Snagit file operations client for managing .snagx capture files."""
import os
import json
import zipfile
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


class ClientError(Exception):
    """Custom exception for Snagit file operation errors."""
    pass


class SnagitClient:
    """Client for interacting with Snagit .snagx capture files."""

    def __init__(self, captures_path: Optional[str] = None):
        """
        Initialize Snagit client.

        Args:
            captures_path: Path to Snagit captures folder. If None, uses default.
        """
        if captures_path:
            self.captures_path = Path(captures_path)
        else:
            # Default Snagit captures location
            self.captures_path = Path.home() / "Pictures" / "Snagit" / "Autosaved Captures.localized"

        if not self.captures_path.exists():
            raise ClientError(
                f"Snagit captures folder not found: {self.captures_path}\n"
                f"Use --path to specify a different location."
            )

    def list_captures(self) -> List[Dict]:
        """
        List all .snagx files in the captures folder.

        Returns:
            List of capture file information dictionaries
        """
        captures = []

        try:
            for file_path in self.captures_path.glob("*.snagx"):
                stat = file_path.stat()
                captures.append({
                    "filename": file_path.name,
                    "path": str(file_path),
                    "size": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "modified_human": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })

            # Sort by modification time, newest first
            captures.sort(key=lambda x: x["modified"], reverse=True)

        except Exception as e:
            raise ClientError(f"Failed to list captures: {e}")

        return captures

    def _extract_snagx(self, snagx_path: Path, extract_dir: Path) -> Dict:
        """
        Extract a .snagx file to a directory.

        Args:
            snagx_path: Path to the .snagx file
            extract_dir: Directory to extract to

        Returns:
            Dictionary with extracted file information
        """
        try:
            with zipfile.ZipFile(snagx_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            # Read index.json to find the page metadata file
            index_path = extract_dir / "index.json"
            if not index_path.exists():
                raise ClientError("Invalid .snagx file: missing index.json")

            with open(index_path, 'r') as f:
                index_data = json.load(f)

            # Find the pages (note: capital 'P' in Snagit format)
            pages = index_data.get("Pages", index_data.get("pages", []))
            if not pages:
                raise ClientError("Invalid .snagx file: no pages found in index.json")

            # Get the first page's metadata file (it's a JSON reference)
            page_json_file = pages[0]
            page_json_path = extract_dir / page_json_file

            if not page_json_path.exists():
                raise ClientError(f"Page metadata not found: {page_json_file}")

            # Read the page JSON to find the actual image file
            with open(page_json_path, 'r') as f:
                page_data = json.load(f)

            # Get the capture background image filename
            main_image_filename = page_data.get("CaptureBackgroundImage")
            if not main_image_filename:
                raise ClientError("Invalid .snagx file: no CaptureBackgroundImage found")

            main_image_path = extract_dir / main_image_filename

            if not main_image_path.exists():
                raise ClientError(f"Main image not found: {main_image_filename}")

            main_guid = main_image_filename.replace(".png", "")

            return {
                "extract_dir": extract_dir,
                "main_image": main_image_path,
                "guid": main_guid,
                "index_data": index_data,
            }

        except zipfile.BadZipFile:
            raise ClientError(f"Invalid .snagx file: {snagx_path}")
        except json.JSONDecodeError:
            raise ClientError("Invalid .snagx file: corrupted index.json")
        except Exception as e:
            raise ClientError(f"Failed to extract .snagx file: {e}")

    def view_capture(self, filename: str) -> Dict:
        """
        Extract a .snagx capture file and return path to the main image.

        Args:
            filename: Filename or path to the .snagx file

        Returns:
            Dictionary with extracted image path info
        """
        # Resolve file path
        file_path = Path(filename)
        if not file_path.exists():
            # Try in captures folder
            file_path = self.captures_path / filename
            if not file_path.exists():
                raise ClientError(f"File not found: {filename}")

        if not file_path.suffix == ".snagx":
            raise ClientError(f"Not a .snagx file: {filename}")

        # Create temp directory
        temp_dir = Path(tempfile.mkdtemp(prefix="snagit_"))

        try:
            # Extract the .snagx file
            extracted = self._extract_snagx(file_path, temp_dir)

            return {
                "filename": file_path.name,
                "image_path": str(extracted["main_image"]),
                "guid": extracted["guid"],
                "temp_dir": str(temp_dir),
            }

        except Exception as e:
            # Clean up on error
            if temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def export_capture(self, filename: str, output_path: Optional[str] = None) -> Dict:
        """
        Export the main PNG image from a .snagx capture file.

        Args:
            filename: Filename or path to the .snagx file
            output_path: Path for the exported PNG file. If None, uses current directory
                        with the capture filename. Can be a directory or full file path.

        Returns:
            Dictionary with export information
        """
        # Resolve file path
        file_path = Path(filename)
        if not file_path.exists():
            # Try in captures folder
            file_path = self.captures_path / filename
            if not file_path.exists():
                raise ClientError(f"File not found: {filename}")

        if not file_path.suffix == ".snagx":
            raise ClientError(f"Not a .snagx file: {filename}")

        # Create temp directory for extraction
        temp_dir = Path(tempfile.mkdtemp(prefix="snagit_"))

        try:
            # Extract the .snagx file to temp
            extracted = self._extract_snagx(file_path, temp_dir)

            # Determine output path
            if output_path:
                output = Path(output_path)
                # If it's a directory, use the capture name
                if output.is_dir() or not output.suffix:
                    output = output / f"{file_path.stem}.png"
            else:
                # Use current directory with capture name
                output = Path.cwd() / f"{file_path.stem}.png"

            # Create parent directory if needed
            output.parent.mkdir(parents=True, exist_ok=True)

            # Copy the main image to output location
            import shutil
            shutil.copy2(extracted["main_image"], output)

            return {
                "filename": file_path.name,
                "output_path": str(output),
                "size_bytes": output.stat().st_size,
                "size_mb": round(output.stat().st_size / (1024 * 1024), 2),
            }

        except Exception as e:
            raise ClientError(f"Failed to export capture: {e}")
        finally:
            # Clean up temp directory
            if temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)


# Module-level client instance - singleton pattern
_client: Optional[SnagitClient] = None
_client_path: Optional[str] = None


def get_client(captures_path: Optional[str] = None) -> SnagitClient:
    """
    Get or create the global Snagit client instance.

    Args:
        captures_path: Path to Snagit captures folder. If provided and different
                      from existing client, creates a new client instance.

    Returns:
        SnagitClient instance
    """
    global _client, _client_path

    # Create new client if none exists or path changed
    if _client is None or (captures_path and captures_path != _client_path):
        _client = SnagitClient(captures_path)
        _client_path = captures_path

    return _client
