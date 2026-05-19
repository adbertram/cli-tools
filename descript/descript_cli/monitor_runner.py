"""Background runner for the CDP network monitor."""
from .monitor import LOG_FILE, run_monitor

if __name__ == "__main__":
    run_monitor(LOG_FILE)
