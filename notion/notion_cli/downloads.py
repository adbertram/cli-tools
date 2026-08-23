"""Safe HTTP file downloads shared by Notion attachment commands."""

from pathlib import Path
from typing import List

import requests


def download_files(items: List[dict], output: str, force: bool = False) -> List[dict]:
    """Download named URL records and return metadata without exposing URLs."""
    names = [item["name"] for item in items]
    seen = set()
    duplicates = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    if duplicates:
        raise ValueError(f"Download contains duplicate file names: {', '.join(sorted(duplicates))}")

    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    destinations = []
    for item in items:
        name = item["name"]
        safe_name = Path(name).name
        if safe_name != name or safe_name in {"", ".", ".."}:
            raise ValueError(f"Download has unsafe file name: {name}")
        destination = output_dir / safe_name
        if destination.exists() and not force:
            raise ValueError(f"Output file already exists: {destination}. Use --force to overwrite it.")
        destinations.append(destination)

    results = []
    for item, destination in zip(items, destinations):
        partial = destination.with_name(f".{destination.name}.part")
        try:
            with requests.get(item["url"], stream=True, timeout=30) as response:
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            partial.replace(destination)
        except Exception:
            if partial.exists():
                partial.unlink()
            raise

        result = {key: value for key, value in item.items() if key != "url"}
        result.update({"output": str(destination), "bytes": destination.stat().st_size})
        results.append(result)

    return results
