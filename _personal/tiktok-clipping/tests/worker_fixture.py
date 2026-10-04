import os
import time
from pathlib import Path


def create_adapter(config):
    class Adapter:
        def discover(self, source):
            Path(config['workspace'], 'worker-started').write_text(str(os.getpid()))
            time.sleep(60)
            return []
    return Adapter()
