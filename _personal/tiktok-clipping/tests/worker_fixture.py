import os
import time
from pathlib import Path


def create_adapter(config):
    class Adapter:
        def quality(self, *args):
            from tiktok_clipping_cli.engine import AdapterFailure
            raise AdapterFailure('transient', 'whop:submission_form_unavailable', provider='whop',
                code='submission_form_unavailable', diagnostics={'kind':'submission_form_predicate', 'available':False, 'context_origin':'whop_wrapper', 'route_match':False})
        def verify_ready(self, job):
            from tiktok_clipping_cli.engine import AdapterFailure
            raise AdapterFailure('rate_limit', 'TEST provider throttled', 172800.25,
                provider='whop', code='read_throttled', status=429)

        def discover(self, source):
            Path(config['workspace'], 'worker-started').write_text(str(os.getpid()))
            time.sleep(60)
            return []
    return Adapter()
