"""Media boundary tests and a real local FFmpeg render; never publish fixtures."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tiktok_clipping_cli.media import MediaRenderer, clip_segments, timed_segments, normalized_crop_segments
from tiktok_clipping_cli.safety import SafetyError, canonical


@pytest.fixture
def config(tmp_path):
    return {"workspace": str(tmp_path), "sources": [{"id": "approved", "allowed_hosts": ["www.youtube.com", "youtu.be"]}],
        "limits": {"work_timeout_seconds": 30, "max_payload_bytes": 1048576, "max_disk_bytes": 100000000,
            "min_clip_seconds": 1, "max_clip_seconds": 10, "caption_chars": 2200},
        "baseline": {"weights": {"centered": 1}}}


@pytest.fixture
def proposal():
    return {"start_seconds": 0, "end_seconds": 3, "caption": "Public post caption", "style": "centered"}


@pytest.fixture
def segments():
    return [{"start": 0, "end": 1.5, "text": "Known synthetic caption."},
            {"start": 1.5, "end": 3, "text": "Second complete sentence."}]


@pytest.mark.parametrize("segments,error", [
    ([], "timed_transcript_required"),
    ([{"start": 1, "end": 0, "text": "Backward."}], "number_out_of_bounds"),
    ([{"start": 0, "end": float("nan"), "text": "Nonfinite."}], "number_out_of_bounds"),
    ([{"start": False, "end": 1, "text": "Boolean."}], "number_out_of_bounds"),
    ([{"start": 0, "end": 0, "text": "Zero duration."}], "empty_caption_interval"),
    ([{"start": 0, "end": 20, "text": "Too long."}], "number_out_of_bounds"),
    ([{"start": 0, "end": 1, "text": "{\\an9}override"}], "caption_markup_forbidden"),
    ([{"start": 0, "end": 1, "text": "<b>markup</b>"}], "caption_markup_forbidden"),
    ([{"start": 0, "end": 1, "text": "Line\n\n00:00:00 --> 00:00:01"}], "caption_markup_forbidden"),
    ([{"start": 0, "end": 2, "text": "Overlap."}, {"start": 1, "end": 3, "text": "Overlap."}], "number_out_of_bounds"),
])
def test_reject_bad_timestamps_and_subtitle_injection(segments, error):
    with pytest.raises(SafetyError, match=error):
        timed_segments({"segments": segments}, 10)


def test_plain_text_is_not_timed_speech():
    with pytest.raises(SafetyError, match="invalid_json"):
        timed_segments("Pretend transcript without timings.", 10)


def test_crop_endpoint_normalization_retains_raw_timing():
    raw = {"segments": [{"start": 0, "end": 6.82, "text": "A complete measured sentence."}]}
    cues, evidence = normalized_crop_segments(raw, 6.683333)
    assert raw["segments"][0]["end"] == 6.82
    assert cues[0]["end"] == 6.683333
    assert evidence["raw_segments"] == raw["segments"]
    assert evidence["end_deltas_seconds"][0] == pytest.approx(0.136667)


@pytest.mark.parametrize("raw,error", [
    ({"segments": [{"start": 0, "end": 1.251, "text": "Too far."}]}, "number_out_of_bounds"),
    ({"segments": [{"start": -0.01, "end": 1, "text": "Negative."}]}, "number_out_of_bounds"),
    ({"segments": [{"start": 0, "end": 1.1, "text": "First."}, {"start": 1.0, "end": 1.2, "text": "Overlap."}]}, "number_out_of_bounds"),
    ({"segments": [{"start": 0, "end": 1.1, "text": "Unfinished"}]}, "clip_ends_mid_sentence"),
    ({"segments": [{"start": 0.3, "end": 1.1, "text": "Missing start."}]}, "clip_splits_spoken_segment"),
])
def test_crop_normalization_refuses_invalid_or_incomplete_speech(raw, error):
    with pytest.raises(SafetyError, match=error):
        normalized_crop_segments(raw, 1)


def test_complete_sentence_boundaries(segments, proposal):
    assert clip_segments(segments, proposal) == segments
    proposal["start_seconds"] = 0.5
    with pytest.raises(SafetyError, match="clip_splits_spoken_segment"):
        clip_segments(segments, proposal)


def test_reject_mid_sentence_boundaries(proposal):
    segments = [{"start": 0, "end": 1, "text": "Sentence continues"}, {"start": 1, "end": 3, "text": "and ends."}]
    proposal["start_seconds"] = 1
    with pytest.raises(SafetyError, match="clip_starts_mid_sentence"):
        clip_segments(segments, proposal)
    proposal["start_seconds"], proposal["end_seconds"] = 0, 1
    with pytest.raises(SafetyError, match="clip_ends_mid_sentence"):
        clip_segments(segments, proposal)


def test_no_speech_inside_selection(proposal):
    with pytest.raises(SafetyError, match="no_caption_in_clip"):
        clip_segments([{"start": 4, "end": 5, "text": "Outside."}], proposal)


def test_paths_are_workspace_files_only(config, tmp_path):
    renderer = MediaRenderer(config)
    outside = tmp_path.parent / (tmp_path.name + "-outside.mp4")
    outside.write_bytes(b"private")
    link = tmp_path / "symlink.mp4"
    link.symlink_to(outside)
    try:
        for bad_path in (outside, link, Path("relative.mp4"), tmp_path / "absent.mp4"):
            with pytest.raises(SafetyError, match="media_path_"):
                renderer._path(bad_path)
        (tmp_path / "parent-link").symlink_to(renderer.root, target_is_directory=True)
        (renderer.root / "nested.mp4").write_bytes(b"data")
        with pytest.raises(SafetyError, match="media_symlink_forbidden"):
            renderer._path(tmp_path / "parent-link" / "nested.mp4")
    finally:
        outside.unlink()


@pytest.mark.parametrize("url,error", [
    ("https://evil.example/watch?v=abcdefghijk", "media_host_not_allowlisted"),
    ("http://www.youtube.com/watch?v=abcdefghijk", "media_host_not_allowlisted"),
    ("https://user:pass@www.youtube.com/watch?v=abcdefghijk", "media_host_not_allowlisted"),
    ("https://www.youtube.com/playlist?list=abcdefghijk", "single_youtube_video_required"),
    ("https://www.youtube.com/watch?v=abcdefghijk&v=lmnopqrstuv", "single_youtube_video_required"),
])
def test_source_url_contract(config, url, error):
    with pytest.raises(SafetyError, match=error):
        MediaRenderer(config)._source({"source_id": "approved", "media_url": url})


def test_playlist_query_is_removed(config):
    assert MediaRenderer(config)._source({"source_id": "approved", "media_url": "https://www.youtube.com/watch?v=abcdefghijk&list=untrusted"}) == "https://www.youtube.com/watch?v=abcdefghijk"


def test_timeout_kills_child_process(config):
    renderer = MediaRenderer(config)
    marker = renderer.root / "should-not-exist"
    child = f"import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).write_text('orphan')"
    parent = f"import subprocess,time,sys; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(60)"
    with pytest.raises(TimeoutError, match="media_work_timeout"):
        renderer._run([sys.executable, "-c", parent], time.monotonic() + 0.3)
    time.sleep(1.1)
    assert not marker.exists()


def test_output_limit(config):
    renderer = MediaRenderer(config)
    with pytest.raises(SafetyError, match="media_process_output_limit"):
        renderer._run([sys.executable, "-c", "print('x'*10000)"], renderer._deadline(), output_limit=10)


def test_disk_limit(config):
    config["limits"]["max_disk_bytes"] = 10
    renderer = MediaRenderer(config)
    (renderer.root / "full").write_bytes(b"x" * 10)
    with pytest.raises(SafetyError, match="disk_budget_exhausted"):
        renderer._run([sys.executable, "-c", "raise Exception('must not start')"], renderer._deadline())


def test_failed_process_cleans_whisper_temporary_files(config):
    renderer = MediaRenderer(config)
    command = "import os; from pathlib import Path; Path(os.environ['TMPDIR'],'orphan.wav').write_bytes(b'data'); raise SystemExit(1)"
    with pytest.raises(SafetyError, match="media_process_failed"):
        renderer._run([sys.executable, "-c", command], renderer._deadline())
    assert not list(renderer.root.glob("process-*"))
    assert not list(renderer.root.rglob("orphan.wav"))


def test_source_cache_prunes_only_owned_files(config):
    config["limits"]["max_disk_bytes"] = 1000
    renderer = MediaRenderer(config)
    state = renderer.workspace / "state.db"
    state.write_bytes(b"coordinator")
    final = renderer.root / "final.mp4"
    final.write_bytes(b"durable output")
    first = renderer.root / ("a" * 64)
    second = renderer.root / ("b" * 64)
    for index, path in enumerate((first, second)):
        path.mkdir()
        (path / "source.mp4").write_bytes(b"x" * 300)
        (path / "source.json").write_bytes(b"{}")
        os.utime(path, (index + 1, index + 1))
    report = renderer.prune_cache()
    assert report == {"cache_bytes": 302, "removed_bytes": 302, "cache_limit_bytes": 500}
    assert not first.exists() and second.exists()
    assert state.read_bytes() == b"coordinator" and final.read_bytes() == b"durable output"
    (second / "state.db").write_bytes(b"unknown owner")
    with pytest.raises(SafetyError, match="unexpected_source_cache_files"):
        renderer.prune_cache()
    assert (second / "state.db").exists()


@pytest.fixture(scope="module")
def ffmpeg():
    # Full Homebrew build is explicit test provisioning; production uses PATH.
    full = Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
    executable = str(full) if full.is_file() else shutil.which("ffmpeg")
    assert executable and shutil.which("ffprobe"), "FFmpeg and FFprobe required for real media tests"
    filters = subprocess.run([executable, "-hide_banner", "-filters"], capture_output=True, check=True, timeout=10)
    assert b" subtitles " in filters.stdout, "FFmpeg build must include libass/subtitles"
    return executable


@pytest.fixture
def source(config, ffmpeg):
    renderer = MediaRenderer(config, ffmpeg=ffmpeg)
    # Punctuation in workspace paths must never become filter syntax.
    folder = renderer.workspace / "media: 'test', [fixture]"
    folder.mkdir()
    source = folder / "source.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=24:d=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)],
        capture_output=True, check=True, timeout=20)
    return renderer, source


def authorized_source(renderer, path):
    from tiktok_clipping_cli.media import sha256
    policy = {"source_url": "https://www.youtube.com/watch?v=abcdefghijk",
              "source_sha256": sha256(path), "source_bytes": path.stat().st_size}
    renderer.config["sources"][0]["publication_policy"] = policy
    return {"source_id": "approved", "media_url": policy["source_url"]}


def measured_whisper(renderer, monkeypatch, *, fail=False):
    original = renderer._run
    def run(command, deadline, **kwargs):
        if command[0] == "whisper":
            if fail:
                raise SafetyError("measured_transcription_failed")
            return canonical({"segments": [{"start": 0, "end": 3, "text": "Measured fixture sentence."}]}).encode()
        return original(command, deadline, **kwargs)
    monkeypatch.setattr(renderer, "_run", run)


def test_authorized_import_atomic_exact_cache_and_idempotence(source, monkeypatch):
    renderer, path = source
    record = authorized_source(renderer, path)
    measured_whisper(renderer, monkeypatch)
    imported = renderer.import_authorized_source(record, path)
    assert imported["duration_seconds"] == pytest.approx(3)
    assert renderer.prepare(record) == imported
    assert renderer.import_authorized_source(record, path) == imported
    cache = next(p for p in renderer.root.iterdir() if p.is_dir() and len(p.name) == 64)
    assert (cache / "source.mp4").read_bytes() == path.read_bytes()
    assert {p.name for p in cache.iterdir()} == {"source.mp4", "source.json"}
    (cache / "source.mp4").write_bytes(b"foreign changed cache")
    with pytest.raises(SafetyError, match="existing_source_cache_rights_mismatch"):
        renderer.import_authorized_source(record, path)
    assert (cache / "source.mp4").read_bytes() == b"foreign changed cache"


@pytest.mark.parametrize("failure", ["symlink", "fifo", "hash", "transcription", "disk"])
def test_authorized_import_failure_never_publishes_cache(source, monkeypatch, failure):
    renderer, path = source
    record = authorized_source(renderer, path)
    measured_whisper(renderer, monkeypatch, fail=failure == "transcription")
    if failure == "symlink":
        link = path.with_name("link.mp4")
        link.symlink_to(path)
        path = link
    if failure == "fifo":
        fifo = path.with_name("pipe.mp4")
        os.mkfifo(fifo)
        path = fifo
    if failure == "hash":
        renderer.config["sources"][0]["publication_policy"]["source_sha256"] = "0" * 64
    if failure == "disk":
        original = renderer._disk
        calls = []
        def pressure(*args, **kwargs):
            calls.append(1)
            return 0 if len(calls) > 1 else original(*args, **kwargs)
        monkeypatch.setattr(renderer, "_disk", pressure)
    with pytest.raises(SafetyError):
        renderer.import_authorized_source(record, path)
    assert not [p for p in renderer.root.iterdir() if p.is_dir()]
    assert path.exists()


def test_cut_refinement_shifts_measured_order_and_preserves_binding(source, monkeypatch):
    renderer, path = source
    original = renderer._run
    deadlines = []
    def run(command, deadline, **kwargs):
        deadlines.append(deadline)
        if command[0] == "whisper":
            return canonical({"segments": [{"start": 0, "end": 1.1, "text": "Measured cut."}]}).encode()
        return original(command, deadline, **kwargs)
    monkeypatch.setattr(renderer, "_run", run)
    cuts = [{"start_seconds": 2, "end_seconds": 3}, {"start_seconds": 0, "end_seconds": 1}]
    captions, evidence = renderer.refine_transcript(path, cuts)
    assert captions == [{"start": 0, "end": 1, "text": "Measured cut."}, {"start": 1, "end": 2, "text": "Measured cut."}]
    assert [entry["cut"] for entry in evidence["cuts"]] == cuts
    assert all(entry["raw_segments"][0]["end"] == 1.1 for entry in evidence["cuts"])
    assert len(set(deadlines)) == 1
    assert not list(renderer.root.glob("refinement-*"))


def test_refined_render_receipt_revalidates_measured_provenance(source, proposal, monkeypatch):
    from tiktok_clipping_cli.safety import strict_json
    renderer, path = source
    measured_whisper(renderer, monkeypatch)
    asset = renderer.render_local(path, [], proposal, "Measured synthetic source", refine_transcript=True)
    assert renderer.quality({}, proposal, asset)["passed"]
    receipt_path = Path(asset["path"]).with_suffix(".json")
    receipt = strict_json(receipt_path.read_bytes())
    receipt["transcript_refinement"]["cuts"][0]["raw_segments"][0]["end"] = 3.1
    receipt_path.write_text(canonical(receipt))
    with pytest.raises(SafetyError, match="transcript_refinement_timing_changed"):
        renderer.quality({}, proposal, asset)


def test_real_caption_render_quality_and_tamper(source, segments, proposal):
    renderer, path = source
    asset = renderer.render_local(path, segments, proposal, "Synthetic local fixture; never publish")
    assert set(asset) == {"path", "sha256", "bytes", "provenance"}
    report = renderer.quality({}, proposal, asset)
    assert set(report) == {"passed", "width", "height", "duration_seconds", "audio_present", "captions_present", "coherent_boundaries", "provenance"}
    assert report["passed"] and report["width"] == 720 and report["height"] == 1280
    assert abs(report["duration_seconds"] - 3) < 0.1
    # Pixel test: burned white glyphs appear in lower caption area of blue frame.
    frame = subprocess.run([renderer.ffmpeg, "-v", "error", "-ss", "0.5", "-i", asset["path"], "-frames:v", "1", "-vf", "crop=720:400:0:880",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True, timeout=20).stdout
    assert sum(1 for i in range(0, len(frame), 3) if min(frame[i:i + 3]) > 200) > 100
    wrong = {**proposal, "caption": "Changed proposal"}
    with pytest.raises(SafetyError, match="render_receipt_mismatch"):
        renderer.quality({}, wrong, asset)
    Path(asset["path"]).write_bytes(b"changed")
    with pytest.raises(SafetyError, match="asset_digest_or_size_mismatch"):
        renderer.quality({}, proposal, asset)


def test_unsupported_style_never_executes_filter(source, proposal, segments):
    renderer, path = source
    config = renderer.config
    config["baseline"]["weights"] = {"movie;exec": 1}
    proposal["style"] = "movie;exec"
    with pytest.raises(SafetyError, match="render_style_not_supported"):
        renderer.render_local(path, segments, proposal, "Synthetic fixture")


def test_missing_subtitles_filter_fails(source, proposal, segments, monkeypatch):
    renderer, path = source
    run = renderer._run
    monkeypatch.setattr(renderer, "_run", lambda command, *a, **kw: b"no subtitles" if "-filters" in command else run(command, *a, **kw))
    with pytest.raises(SafetyError, match="ffmpeg_subtitles_filter_required"):
        renderer.render_local(path, segments, proposal, "Synthetic fixture")


def test_failed_render_cleans_partial_output(source, proposal, segments, monkeypatch):
    renderer, path = source
    run = renderer._run
    def partial_failure(command, *args, **kwargs):
        if "-movflags" in command:
            Path(command[-1]).write_bytes(b"partial invalid media")
            raise SafetyError("media_process_failed: injected encoder failure")
        return run(command, *args, **kwargs)
    monkeypatch.setattr(renderer, "_run", partial_failure)
    with pytest.raises(SafetyError, match="injected encoder failure"):
        renderer.render_local(path, segments, proposal, "Synthetic fixture")
    assert not list(renderer.root.glob("render-*"))
    assert not list(renderer.root.glob("*.mp4"))


def test_source_prepare_cache_uses_cli_timings(source, segments, monkeypatch):
    renderer, path = source
    run = renderer._run
    calls = []
    def fake_command(command, *a, **kw):
        calls.append(command[0])
        if command[0] == "youtube":
            shutil.copy(path, Path(command[command.index("--output-dir") + 1]) / "download.mp4")
            return b""
        if command[0] == "whisper":
            return canonical({"text": "measured", "language": "en", "segments": segments}).encode()
        return run(command, *a, **kw)
    monkeypatch.setattr(renderer, "_run", fake_command)
    record = {"source_id": "approved", "media_url": "https://www.youtube.com/watch?v=abcdefghijk"}
    data = renderer.prepare(record)
    assert data["transcript_segments"][0] == {"start_seconds": 0, "end_seconds": 1.5, "text": segments[0]["text"]}
    assert data["transcript"] == " ".join(s["text"] for s in segments)
    assert renderer.prepare(record) == data
    assert calls.count("youtube") == calls.count("whisper") == 1
    cache = renderer.root / next(p.name for p in renderer.root.iterdir() if p.is_dir() and (p / "source.json").exists())
    (cache / "source.mp4").write_bytes(b"tampered cache")
    with pytest.raises(SafetyError, match="cached_source_digest_mismatch"):
        renderer.prepare(record)


def test_write_allowance_uses_physical_reserve_and_unlinked_workspace_bytes(config, monkeypatch):
    from types import SimpleNamespace
    from tiktok_clipping_cli.safety import PHYSICAL_DISK_RESERVE_BYTES, write_allowance
    monkeypatch.setattr('tiktok_clipping_cli.safety.shutil.disk_usage', lambda _: SimpleNamespace(free=PHYSICAL_DISK_RESERVE_BYTES + 100))
    assert write_allowance(config['workspace'], 1000, unlinked_bytes=50) == 100
    assert write_allowance(config['workspace'], 80, unlinked_bytes=50) == 30
    monkeypatch.setattr('tiktok_clipping_cli.safety.shutil.disk_usage', lambda _: SimpleNamespace(free=PHYSICAL_DISK_RESERVE_BYTES))
    with pytest.raises(SafetyError, match='disk_budget_exhausted'):
        write_allowance(config['workspace'], 1000)


def test_media_kills_writer_when_physical_reserve_reached(config, monkeypatch):
    from types import SimpleNamespace
    from tiktok_clipping_cli.safety import PHYSICAL_DISK_RESERVE_BYTES
    renderer = MediaRenderer(config)
    readings = iter([PHYSICAL_DISK_RESERVE_BYTES + 1000, PHYSICAL_DISK_RESERVE_BYTES])
    monkeypatch.setattr('tiktok_clipping_cli.safety.shutil.disk_usage', lambda _: SimpleNamespace(free=next(readings)))
    with pytest.raises(SafetyError, match='disk_budget_exhausted'):
        renderer._run([sys.executable, '-c', 'import time; time.sleep(10)'], time.monotonic() + 5)


def test_cache_removal_does_not_assume_physical_space_reclaimed(config, monkeypatch):
    from types import SimpleNamespace
    from tiktok_clipping_cli.safety import PHYSICAL_DISK_RESERVE_BYTES
    renderer = MediaRenderer(config)
    cache = renderer.root / ('a' * 64); cache.mkdir()
    (cache / 'source.mp4').write_bytes(b'source')
    (cache / 'source.json').write_text('{}')
    monkeypatch.setattr('tiktok_clipping_cli.safety.shutil.disk_usage', lambda _: SimpleNamespace(free=PHYSICAL_DISK_RESERVE_BYTES))
    with pytest.raises(SafetyError, match='disk_budget_exhausted'):
        renderer.prune_cache()
    assert not cache.exists()


def test_real_reordered_cuts_burn_required_disclosure_across_full_render(source):
    from test_rights import scoped_policy
    renderer,path=source
    from tiktok_clipping_cli.media import sha256
    import json
    configured=renderer.config['sources'][0]
    configured.update(reuse_evidence='https://docs.google.com/document/d/TEST/edit',campaign={'id':'test-campaign'},feed='https://www.youtube.com/watch?v=fixture')
    policy=scoped_policy(configured)
    policy.update(source_sha256=sha256(path),source_bytes=path.stat().st_size,minimum_clip_seconds=1,clip_rules=[])
    configured['publication_policy']=policy
    p={'start_seconds':0,'end_seconds':3,'segments':[{'start_seconds':2,'end_seconds':3},{'start_seconds':0,'end_seconds':1}],'caption':'@hardscope #ad','style':'centered'}
    transcript=[{'start':i,'end':i+1,'text':f'Sentence {i}.'} for i in range(3)]
    asset=renderer.render_local(path,transcript,p,'Synthetic local fixture; never publish',publication_policy=policy)
    report=renderer.quality({'input':{'source_id':configured['id']}},p,asset)
    assert report['passed'] and abs(report['duration_seconds']-2)<0.1
    receipt=json.loads(Path(asset['path']).with_suffix('.json').read_text())
    assert receipt['edit']=={'segments':p['segments'],'rendered_duration':2,'reservation':'whole_source_bounding_span'}
    assert receipt['captions'][0]['text']=='Sentence 2.' and receipt['captions'][1]['text']=='Sentence 0.'
    assert receipt['audio_provenance']=={'source_sha256':policy['source_sha256'],'segments':p['segments'],'external_audio':False}
    # Disclosure pixels at both ends, measured independently from filter strings.
    for second in (0.1,1.8):
        frame=subprocess.run([renderer.ffmpeg,'-v','error','-ss',str(second),'-i',asset['path'],'-frames:v','1','-vf','crop=720:240:0:0','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True,timeout=20).stdout
        assert sum(1 for i in range(0,len(frame),3) if min(frame[i:i+3])>200)>100
    receipt['audio_provenance']['external_audio']=True
    Path(asset['path']).with_suffix('.json').write_text(json.dumps(receipt))
    with pytest.raises(SafetyError,match='render_rights_overlay_audio_receipt_changed'):renderer.quality({'input':{'source_id':configured['id']}},p,asset)
