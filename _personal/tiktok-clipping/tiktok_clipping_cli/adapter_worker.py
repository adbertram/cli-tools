"""Fixed-entrypoint worker. Module/method selection comes only from trusted config."""
import importlib
import sys

from .engine import AdapterFailure
from .safety import canonical, keys, strict_json, validate_config


def main():
    message = strict_json(sys.stdin.buffer.read(2 * 1048576 + 1), 2 * 1048576)
    keys(message, {"config", "method", "args"})
    config = validate_config(message["config"])
    method = message["method"]
    if method not in {"discover", "render", "quality", "publish", "reconcile", "metrics", "metrics_batch", "sync_reward_revenue", "submit_rewards", "reconcile_rewards", "reward_status", "verify_ready", "visual_execution_state"}:
        raise ValueError("unknown_adapter_method")
    try:
        adapter = importlib.import_module(config["adapter_module"]).create_adapter(config)
        result = getattr(adapter, method)(*message["args"])
        output = {"result": result}
    except AdapterFailure as exc:
        output = {"error": str(exc), "category": exc.category, "retry_after": exc.retry_after, "provider": exc.provider, "code": exc.code, "status": exc.status, "diagnostics": exc.diagnostics}
    except (TimeoutError, ConnectionError) as exc:
        output = {"error": type(exc).__name__, "category": "ambiguous" if method in {"publish", "submit_rewards"} else "transient", "retry_after": None}
    except Exception as exc:
        output = {"error": type(exc).__name__ + ": " + str(exc)[:500], "category": "ambiguous" if method in {"publish", "submit_rewards"} else "permanent", "retry_after": None}
    sys.stdout.write(canonical(output) + "\n")


if __name__ == "__main__":
    main()
