"""Fixed-entrypoint worker. Module/method selection comes only from trusted config."""
import importlib
import sys
import math
import time

from .engine import AdapterFailure
from .safety import canonical, keys, strict_json, validate_config


def main():
    message = strict_json(sys.stdin.buffer.read(2 * 1048576 + 1), 2 * 1048576)
    keys(message, {"config", "method", "args"}, {"operation_deadline"})
    config = validate_config(message["config"])
    method = message["method"]
    if method not in {"discover", "render", "quality", "publish", "reconcile", "metrics", "metrics_batch", "sync_reward_revenue", "submit_rewards", "reconcile_rewards", "reward_status", "verify_ready", "visual_execution_state"}:
        raise ValueError("unknown_adapter_method")
    try:
        adapter = importlib.import_module(config["adapter_module"]).create_adapter(config)
        if 'operation_deadline' in message:
            deadline = message['operation_deadline']
            if method!='discover' or not config.get('source_discovery') or type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline-time.monotonic() > config['limits']['work_timeout_seconds']:
                raise ValueError('catalog_operation_deadline_invalid')
            if deadline<=time.monotonic():raise TimeoutError('catalog_startup_deadline_exceeded')
            adapter.set_operation_deadline(deadline)
        elif method=='discover' and config.get('source_discovery'):
            raise ValueError('catalog_parent_deadline_required')
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
