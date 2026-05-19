"""Bulk processing module for CLI tools.

Supports processing multiple items from JSON file, stdin, or inline data
with configurable concurrency and error handling.
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class BulkProcessor:
    """Process items in bulk with configurable concurrency and error handling."""

    def __init__(
        self,
        concurrency: int = 5,
        delay: float = 0,
        continue_on_error: bool = True,
        show_progress: bool = True,
    ):
        self.concurrency = concurrency
        self.delay = delay / 1000.0 if delay > 0 else 0  # Convert ms to seconds
        self.continue_on_error = continue_on_error
        self.show_progress = show_progress

    def parse_input(
        self,
        file: Optional[str] = None,
        stdin: bool = False,
        data: Optional[Any] = None,
    ) -> List[Dict]:
        """Parse input from file, stdin, or inline data."""
        if data is not None:
            if isinstance(data, list):
                return data
            if isinstance(data, str):
                return json.loads(data)
            raise ValueError("Invalid data format: expected list or JSON string")

        if file:
            content = Path(file).read_text()
            if file.endswith(".csv"):
                return self._parse_csv(content)
            return json.loads(content)

        if stdin:
            content = sys.stdin.read().strip()
            parsed = json.loads(content)
            return parsed if isinstance(parsed, list) else [parsed]

        raise ValueError("No input source. Use --input <file>, --stdin, or provide data.")

    def _parse_csv(self, content: str) -> List[Dict]:
        """Parse CSV content into list of dicts."""
        lines = content.strip().split("\n")
        if len(lines) < 2:
            raise ValueError("CSV must have header row and at least one data row")

        headers = [h.strip() for h in lines[0].split(",")]
        items = []
        for line in lines[1:]:
            values = [v.strip() for v in line.split(",")]
            item = {}
            for i, header in enumerate(headers):
                val = values[i] if i < len(values) else ""
                try:
                    item[header] = int(val)
                except ValueError:
                    try:
                        item[header] = float(val)
                    except ValueError:
                        item[header] = val
            items.append(item)
        return items

    def process(
        self, items: List[Dict], operation: Callable[[Dict, int], Any]
    ) -> Dict:
        """Process items with the provided operation function.

        Args:
            items: List of items to process
            operation: Function(item, index) -> result

        Returns:
            Dict with summary, results, and errors
        """
        total = len(items)
        completed = 0
        succeeded = 0
        failed = 0
        results = []
        errors = []
        lock = threading.Lock()
        start_time = time.time()

        def _process_item(item_index):
            nonlocal completed, succeeded, failed
            item, index = item_index

            if self.delay > 0 and index > 0:
                time.sleep(self.delay)

            try:
                result = operation(item, index)
                with lock:
                    succeeded += 1
                    completed += 1
                    if self.show_progress:
                        print(
                            f"\rProcessing: {completed}/{total} ({succeeded} ok, {failed} failed)",
                            end="",
                            file=sys.stderr,
                        )
                return {"success": True, "input": item, "result": result}
            except Exception as e:
                with lock:
                    failed += 1
                    completed += 1
                    if self.show_progress:
                        print(
                            f"\rProcessing: {completed}/{total} ({succeeded} ok, {failed} failed)",
                            end="",
                            file=sys.stderr,
                        )
                if not self.continue_on_error:
                    raise
                return {"success": False, "input": item, "error": str(e)}

        if self.concurrency <= 1:
            # Sequential processing
            for i, item in enumerate(items):
                result = _process_item((item, i))
                if result["success"]:
                    results.append(result)
                else:
                    errors.append(result)
        else:
            # Parallel processing
            with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                futures = {
                    executor.submit(_process_item, (item, i)): i
                    for i, item in enumerate(items)
                }
                for future in as_completed(futures):
                    result = future.result()
                    if result["success"]:
                        results.append(result)
                    else:
                        errors.append(result)

        duration_ms = int((time.time() - start_time) * 1000)

        if self.show_progress:
            print("", file=sys.stderr)  # Newline after progress

        return {
            "summary": {
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
                "duration_ms": duration_ms,
                "concurrency": self.concurrency,
            },
            "results": results,
            "errors": errors,
        }
