"""Usage tracking for Gemini CLI."""
import json
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

from .config import get_config

# Pricing per 1M tokens (as of Dec 2025)
# https://ai.google.dev/gemini-api/docs/pricing
PRICING = {
    # Gemini 3 models (latest)
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3-pro-image-preview": {"input": 2.00, "output": 12.00},

    # Gemini 2.5 models
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-pro-preview": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-preview-09-2025": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash-lite-preview-09-2025": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash-image": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-preview-tts": {"input": 0.50, "output": 10.00},
    "gemini-2.5-pro-preview-tts": {"input": 1.00, "output": 20.00},
    "gemini-2.5-computer-use-preview-10-2025": {"input": 1.25, "output": 10.00},

    # Gemini 2.0 models
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash-001": {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash-exp": {"input": 0.0, "output": 0.0},  # Free during preview
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash-lite-001": {"input": 0.075, "output": 0.30},

    # Gemini 1.5 models (legacy)
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash-001": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash-002": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-pro-001": {"input": 1.25, "output": 5.00},
    "gemini-1.5-pro-002": {"input": 1.25, "output": 5.00},

    # Gemma models (free tier only)
    "gemma-3-1b-it": {"input": 0.0, "output": 0.0},
    "gemma-3-4b-it": {"input": 0.0, "output": 0.0},
    "gemma-3-12b-it": {"input": 0.0, "output": 0.0},
    "gemma-3-27b-it": {"input": 0.0, "output": 0.0},

    # Embedding model
    "gemini-embedding-001": {"input": 0.15, "output": 0.0},

    # Default for unknown models
    "default": {"input": 0.30, "output": 2.50},
}


def get_usage_file(config=None) -> Path:
    """Get path to usage tracking file."""
    active_config = config or get_config()
    return active_config.get_profile_data_dir() / "usage.json"


def load_usage_data(config=None) -> Dict[str, Any]:
    """Load usage data from file."""
    usage_file = get_usage_file(config)
    if usage_file.exists():
        try:
            return json.loads(usage_file.read_text())
        except (json.JSONDecodeError, IOError):
            return {"requests": [], "daily_totals": {}}
    return {"requests": [], "daily_totals": {}}


def save_usage_data(data: Dict[str, Any], config=None) -> None:
    """Save usage data to file."""
    usage_file = get_usage_file(config)
    usage_file.parent.mkdir(parents=True, exist_ok=True)
    usage_file.write_text(json.dumps(data, indent=2, default=str))


def record_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cached_tokens: int = 0,
    operation: str = "generate",
    config=None,
) -> None:
    """
    Record usage from an API call.

    Args:
        model: Model name used
        prompt_tokens: Number of input tokens
        completion_tokens: Number of output tokens
        total_tokens: Total tokens used
        cached_tokens: Number of cached tokens (reduced cost)
        operation: Type of operation (generate, analyze_video, etc.)
    """
    data = load_usage_data(config)

    today = date.today().isoformat()
    timestamp = datetime.now().isoformat()

    # Get pricing for this model
    model_key = model.replace("models/", "")
    pricing = PRICING.get(model_key, PRICING["default"])

    # Calculate cost (per 1M tokens)
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    total_cost = input_cost + output_cost

    # Record individual request
    request = {
        "timestamp": timestamp,
        "model": model_key,
        "operation": operation,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "estimated_cost": round(total_cost, 6),
    }
    data["requests"].append(request)

    # Update daily totals
    if today not in data["daily_totals"]:
        data["daily_totals"][today] = {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "estimated_cost": 0.0,
        }

    daily = data["daily_totals"][today]
    daily["requests"] += 1
    daily["prompt_tokens"] += prompt_tokens
    daily["completion_tokens"] += completion_tokens
    daily["total_tokens"] += total_tokens
    daily["cached_tokens"] += cached_tokens
    daily["estimated_cost"] = round(daily["estimated_cost"] + total_cost, 6)

    save_usage_data(data, config)


def get_usage_summary(days: int = 30, config=None) -> Dict[str, Any]:
    """
    Get usage summary for the specified number of days.

    Args:
        days: Number of days to include (default: 30)

    Returns:
        Summary dict with totals and daily breakdown
    """
    data = load_usage_data(config)

    # Calculate date range
    today = date.today()

    # Filter daily totals within range
    totals = {
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "estimated_cost": 0.0,
    }

    daily_data = []
    for date_str, daily in sorted(data.get("daily_totals", {}).items(), reverse=True):
        try:
            day_date = date.fromisoformat(date_str)
            day_diff = (today - day_date).days
            if day_diff < days:
                daily_data.append({"date": date_str, **daily})
                totals["requests"] += daily["requests"]
                totals["prompt_tokens"] += daily["prompt_tokens"]
                totals["completion_tokens"] += daily["completion_tokens"]
                totals["total_tokens"] += daily["total_tokens"]
                totals["cached_tokens"] += daily.get("cached_tokens", 0)
                totals["estimated_cost"] += daily["estimated_cost"]
        except ValueError:
            continue

    totals["estimated_cost"] = round(totals["estimated_cost"], 4)

    return {
        "period_days": days,
        "totals": totals,
        "daily": daily_data,
    }


def get_model_breakdown(days: int = 30, config=None) -> Dict[str, Dict[str, Any]]:
    """
    Get usage breakdown by model.

    Args:
        days: Number of days to include

    Returns:
        Dict mapping model names to their usage stats
    """
    data = load_usage_data(config)
    today = date.today()

    models: Dict[str, Dict[str, Any]] = {}

    for request in data.get("requests", []):
        try:
            req_date = date.fromisoformat(request["timestamp"][:10])
            if (today - req_date).days >= days:
                continue
        except (ValueError, KeyError):
            continue

        model = request.get("model", "unknown")
        if model not in models:
            models[model] = {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost": 0.0,
            }

        models[model]["requests"] += 1
        models[model]["prompt_tokens"] += request.get("prompt_tokens", 0)
        models[model]["completion_tokens"] += request.get("completion_tokens", 0)
        models[model]["total_tokens"] += request.get("total_tokens", 0)
        models[model]["estimated_cost"] += request.get("estimated_cost", 0)

    # Round costs
    for model in models:
        models[model]["estimated_cost"] = round(models[model]["estimated_cost"], 4)

    return models


def clear_usage_data(config=None) -> None:
    """Clear all usage data."""
    save_usage_data({"requests": [], "daily_totals": {}}, config)
