"""Cloud usage tracking via Google Cloud Monitoring and BigQuery billing export."""
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

from .config import get_config

PROJECT_ID = "gen-lang-client-0737942335"

# Cloud Monitoring metric types for Generative Language API
_INPUT_TOKEN_METRICS = [
    "generativelanguage.googleapis.com/quota/generate_content_paid_tier_input_token_count/usage",
    "generativelanguage.googleapis.com/quota/generate_content_paid_tier_2_input_token_count/usage",
    "generativelanguage.googleapis.com/quota/generate_content_paid_tier_3_input_token_count/usage",
    "generativelanguage.googleapis.com/quota/generate_content_free_tier_input_token_count/usage",
]

_REQUEST_METRICS = [
    "generativelanguage.googleapis.com/quota/generate_requests_per_model/usage",
    "generativelanguage.googleapis.com/quota/predict_requests_per_model/usage",
    "generativelanguage.googleapis.com/quota/predict_requests_free_tier_per_model/usage",
]


def _get_monitoring_client():
    """Get Cloud Monitoring client using Application Default Credentials."""
    try:
        from google.cloud import monitoring_v3
        return monitoring_v3.MetricServiceClient()
    except ImportError:
        raise RuntimeError(
            "google-cloud-monitoring is not installed. "
            "Run: pip install google-cloud-monitoring"
        )
    except Exception as e:
        if "Could not automatically determine credentials" in str(e):
            raise RuntimeError(
                "Cloud Monitoring credentials not configured. Run:\n"
                "  gcloud auth application-default login"
            )
        raise


def _query_metric(client, metric_type: str, days: int, align_seconds: int) -> List:
    """Query a single metric from Cloud Monitoring.

    Args:
        client: MetricServiceClient instance.
        metric_type: Full metric type string.
        days: Number of days to look back.
        align_seconds: Alignment period in seconds (86400=daily, large=total).

    Returns:
        List of time series results.
    """
    from google.cloud.monitoring_v3 import (
        ListTimeSeriesRequest,
        Aggregation,
        TimeInterval,
    )
    from google.protobuf.timestamp_pb2 import Timestamp

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    start_ts = Timestamp()
    start_ts.FromDatetime(start)
    end_ts = Timestamp()
    end_ts.FromDatetime(now)

    interval = TimeInterval(start_time=start_ts, end_time=end_ts)
    aggregation = Aggregation(
        alignment_period={"seconds": align_seconds},
        per_series_aligner=Aggregation.Aligner.ALIGN_SUM,
    )

    request = ListTimeSeriesRequest(
        name=f"projects/{PROJECT_ID}",
        filter=f'metric.type = "{metric_type}"',
        interval=interval,
        aggregation=aggregation,
        view=ListTimeSeriesRequest.TimeSeriesView.FULL,
    )

    return list(client.list_time_series(request=request))


def query_cloud_usage(days: int = 30) -> Dict[str, Any]:
    """Query Cloud Monitoring for Gemini API usage by model.

    Args:
        days: Number of days to look back.

    Returns:
        Dict with 'models' (per-model breakdown) and 'totals'.
    """
    client = _get_monitoring_client()

    models: Dict[str, Dict[str, Any]] = {}
    totals = {
        "input_tokens": 0,
        "requests": 0,
    }

    # Use a large alignment period to get totals across the whole range
    align_seconds = days * 86400

    # Query input tokens per model
    for metric_type in _INPUT_TOKEN_METRICS:
        for ts in _query_metric(client, metric_type, days, align_seconds):
            model = ts.metric.labels.get("model", "unknown")
            token_count = sum(int(p.value.int64_value) for p in ts.points)

            if model not in models:
                models[model] = {"input_tokens": 0, "requests": 0}
            models[model]["input_tokens"] += token_count
            totals["input_tokens"] += token_count

    # Query requests per model
    for metric_type in _REQUEST_METRICS:
        for ts in _query_metric(client, metric_type, days, align_seconds):
            model = ts.metric.labels.get("model", "unknown")
            request_count = sum(int(p.value.int64_value) for p in ts.points)

            if model not in models:
                models[model] = {"input_tokens": 0, "requests": 0}
            models[model]["requests"] += request_count
            totals["requests"] += request_count

    # Try to add cost data from billing export if configured
    config = get_config()
    if config.bigquery_billing_table:
        try:
            costs = _query_billing_costs(config.bigquery_billing_table, days)
            totals["total_cost"] = costs.get("total_cost", 0.0)
            totals["currency"] = costs.get("currency", "USD")
            for model_name, model_costs in costs.get("models", {}).items():
                # Match billing model names to monitoring model names
                matched = _match_model_name(model_name, models)
                if matched and matched in models:
                    models[matched]["total_cost"] = model_costs.get("total_cost", 0.0)
        except Exception:
            pass  # Billing data is optional enhancement

    return {
        "source": "cloud_monitoring",
        "period_days": days,
        "project": PROJECT_ID,
        "models": models,
        "totals": totals,
    }


def query_cloud_usage_daily(days: int = 30) -> List[Dict[str, Any]]:
    """Query Cloud Monitoring for daily Gemini API usage.

    Args:
        days: Number of days to look back.

    Returns:
        List of daily usage dicts sorted by date descending.
    """
    client = _get_monitoring_client()

    daily: Dict[str, Dict[str, Any]] = {}

    # Query input tokens per day (86400s = 1 day alignment)
    for metric_type in _INPUT_TOKEN_METRICS:
        for ts in _query_metric(client, metric_type, days, 86400):
            model = ts.metric.labels.get("model", "unknown")
            for point in ts.points:
                date_str = point.interval.end_time.strftime("%Y-%m-%d")
                token_count = int(point.value.int64_value)

                if date_str not in daily:
                    daily[date_str] = {"date": date_str, "input_tokens": 0, "requests": 0, "models": {}}
                daily[date_str]["input_tokens"] += token_count

                if model not in daily[date_str]["models"]:
                    daily[date_str]["models"][model] = {"input_tokens": 0, "requests": 0}
                daily[date_str]["models"][model]["input_tokens"] += token_count

    # Query requests per day
    for metric_type in _REQUEST_METRICS:
        for ts in _query_metric(client, metric_type, days, 86400):
            model = ts.metric.labels.get("model", "unknown")
            for point in ts.points:
                date_str = point.interval.end_time.strftime("%Y-%m-%d")
                request_count = int(point.value.int64_value)

                if date_str not in daily:
                    daily[date_str] = {"date": date_str, "input_tokens": 0, "requests": 0, "models": {}}
                daily[date_str]["requests"] += request_count

                if model not in daily[date_str]["models"]:
                    daily[date_str]["models"][model] = {"input_tokens": 0, "requests": 0}
                daily[date_str]["models"][model]["requests"] += request_count

    return sorted(daily.values(), key=lambda x: x["date"], reverse=True)


def _match_model_name(billing_name: str, monitoring_models: Dict) -> str:
    """Best-effort match a billing SKU model name to a monitoring model name."""
    billing_lower = billing_name.lower().replace(" ", "-")
    for model_key in monitoring_models:
        if model_key in billing_lower or billing_lower in model_key:
            return model_key
    return ""


def _query_billing_costs(table_id: str, days: int) -> Dict[str, Any]:
    """Query BigQuery billing export for cost data only."""
    from google.cloud import bigquery

    client = bigquery.Client()
    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    query = f"""
        SELECT
            sku.description AS sku_description,
            SUM(cost) AS total_cost,
            currency
        FROM `{table_id}`
        WHERE service.description = 'Generative Language API'
            AND usage_start_time >= TIMESTAMP('{start_date}')
            AND cost_type = 'regular'
        GROUP BY sku.description, currency
        ORDER BY total_cost DESC
    """

    rows = list(client.query(query).result())

    models: Dict[str, Dict[str, float]] = {}
    total_cost = 0.0
    currency = "USD"

    for row in rows:
        sku = row.sku_description or "Unknown"
        cost = float(row.total_cost or 0)
        currency = row.currency or "USD"

        # Extract model name from SKU
        model_name = _parse_model_from_sku(sku)
        if model_name not in models:
            models[model_name] = {"total_cost": 0.0}
        models[model_name]["total_cost"] += cost
        total_cost += cost

    return {
        "total_cost": round(total_cost, 4),
        "currency": currency,
        "models": {k: {"total_cost": round(v["total_cost"], 4)} for k, v in models.items()},
    }


def _parse_model_from_sku(sku_description: str) -> str:
    """Extract model name from SKU description."""
    desc = sku_description.lower()
    for suffix in [
        " generate content input", " generate content output",
        " online prediction input", " online prediction output",
        " input", " output",
        " cached", " grounding", " context caching",
    ]:
        if desc.endswith(suffix):
            desc = desc[: -len(suffix)]
            break
    return desc.strip().title()


def verify_bigquery_connection(table_id: str) -> Dict[str, Any]:
    """Verify BigQuery table exists and is accessible."""
    from google.cloud import bigquery

    client = bigquery.Client()

    try:
        query = f"""
            SELECT COUNT(*) as row_count
            FROM `{table_id}`
            WHERE service.description = 'Generative Language API'
            LIMIT 1
        """
        rows = list(client.query(query).result())
        row_count = rows[0].row_count if rows else 0

        return {
            "connected": True,
            "table": table_id,
            "gemini_rows": row_count,
            "message": f"Connected. Found {row_count} Generative Language API billing records.",
        }
    except Exception as e:
        return {
            "connected": False,
            "table": table_id,
            "error": str(e),
        }
