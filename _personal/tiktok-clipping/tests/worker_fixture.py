import os
import time
from pathlib import Path


def create_adapter(config):
    class Adapter:
        def render(self, job, proposal):
            from contextlib import nullcontext
            from tiktok_clipping_cli.live import LiveAdapter
            from tiktok_clipping_cli.media import normalized_crop_segments, RefinementTimingError
            class MeasuredMedia:
                def render(self, job, proposal):
                    from tiktok_clipping_cli.safety import canonical
                    context=nullcontext()
                    start,end=583.04,596.4
                    if 'id' in job:
                        from tiktok_clipping_cli.asset_retention import RenderOwnership
                        Path(config['workspace'],'media').mkdir(exist_ok=True)
                        owner=RenderOwnership(config,job,proposal,clock=lambda:job['lease_until']-1)
                        context=owner.temporary('refinement')
                        start,end=proposal['start_seconds'],proposal['end_seconds']
                    with context:
                        try:
                            normalized_crop_segments(canonical({'segments':[{'start':8.76,'end':round(end-start+1.96,2),'text':'Measured test speech.'}]}),round(end-start,2))
                        except RefinementTimingError as exc:
                            exc.diagnostics.update(cut_index=0,cut_start_seconds=start,cut_end_seconds=end)
                            raise
            return LiveAdapter(config,media=MeasuredMedia()).render(job,proposal)
        def publish(self, job, asset, key, policy):
            from types import SimpleNamespace
            from tiktok_clipping_cli.studio_adapter import StudioPublicationAdapter
            from tiktok_clipping_cli.safety import digest
            bridge=StudioPublicationAdapter(config,publisher_factory=lambda:None)
            binding=bridge._binding(asset,key,policy)
            operation={**binding,'policy':policy,'binding':digest({'asset_sha256':asset['sha256'],'policy':policy}),
                       'state':'outcome_unknown','public_action_dispatched':True,'post_failure':job['post_failure']}
            sdk=SimpleNamespace(status=lambda request:operation)
            exc=TimeoutError('SECRET session payload must never be emitted')
            exc.retry_after=172800.25
            exc.provider,exc.code,exc.status='tiktok','publication_transport_failed',503
            raise bridge._failure(sdk,binding,policy,exc)
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
