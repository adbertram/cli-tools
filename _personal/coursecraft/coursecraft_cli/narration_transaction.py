"""Fail-closed transaction boundary for authoritative CourseCraft demo narration."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

from .coursecraft_project import COURSES_ROOT, load_coursecraft_module
from .narration_identity import narration_metadata_path
from .voice_recording_fields import (
    DICTATION_RECORDED_FIELD,
    ELEVENLABS_HISTORY_ITEM_ID_FIELD,
    ELEVENLABS_MODEL_ID_FIELD,
    ELEVENLABS_OUTPUT_FORMAT_FIELD,
    ELEVENLABS_REQUEST_ID_FIELD,
    ELEVENLABS_VOICE_ID_FIELD,
    VOICE_CHARACTER_COUNT_FIELD,
    VOICE_GENERATED_AT_FIELD,
    VOICE_RECORDING_ID_FIELD,
    VOICE_SOURCE_HASH_FIELD,
)

TRANSACTION_SCHEMA_VERSION = "coursecraft-authoritative-narration/1.0"
STANDALONE_NARRATION_PROVENANCE_SCHEMA = "coursecraft-standalone-narration-provenance/1.0"
SUPPORTED_DEMO_OUTPUT_FORMATS = {"mp3_44100_128": ".mp3"}
PRODUCTION_CONFIG_SCHEMA = "coursecraft-production-narration/1.0"
PRODUCTION_CONFIG_PATH = Path(".agents/skills/demo/artifacts/dictation_audio/production-narration.json")
PEAK_LIMIT_DBFS = -1.0
MIN_WORD_RECALL = 0.90
MIN_SEQUENCE_RECALL = 0.85
GENERATION_TIMEOUT_SECONDS = 300
TRANSCRIPTION_TIMEOUT_SECONDS = 600
PROVENANCE_RELATIVE_PATH = Path(".agents/skills/demo/artifacts/automated_walkthrough/tools/provenance.py")
_PROVENANCE_MODULE: Any = None
RECORDED_FIELD = "Recorded"
OWNED_UPDATE_FIELDS = (
    VOICE_RECORDING_ID_FIELD,
    VOICE_SOURCE_HASH_FIELD,
    ELEVENLABS_VOICE_ID_FIELD,
    ELEVENLABS_MODEL_ID_FIELD,
    ELEVENLABS_OUTPUT_FORMAT_FIELD,
    ELEVENLABS_REQUEST_ID_FIELD,
    ELEVENLABS_HISTORY_ITEM_ID_FIELD,
    VOICE_CHARACTER_COUNT_FIELD,
    VOICE_GENERATED_AT_FIELD,
    DICTATION_RECORDED_FIELD,
)
_JSON_CONTAINER_NAMES = {dict: "object", list: "array"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required_string(payload: dict, key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} is missing required string {key}.")
    return value.strip()


def _run_json(
    args: list[str],
    *,
    timeout: Optional[int] = 60,
    expected_type: Optional[type] = None,
    context: str = "Command",
) -> Any:
    result = subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"Command returned invalid JSON: {' '.join(args[:3])}") from error
    if expected_type is not None and not isinstance(payload, expected_type):
        expected_name = _JSON_CONTAINER_NAMES[expected_type]
        raise ValueError(
            f"{context} returned non-{expected_name} JSON: {' '.join(args[:3])}"
        )
    return payload


def load_production_config(coursecraft_root: Path) -> dict:
    """Load and strictly validate the sole CourseCraft-owned production contract."""
    path = coursecraft_root.expanduser().resolve() / PRODUCTION_CONFIG_PATH
    if not path.is_file():
        raise ValueError(f"CourseCraft production narration configuration is absent: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"CourseCraft production narration configuration is unreadable: {path}: {error}") from error
    if not isinstance(config, dict) or config.get("$schema") != PRODUCTION_CONFIG_SCHEMA:
        raise ValueError(f"CourseCraft production narration configuration has the wrong schema: {path}")
    if set(config) != {"$schema", "elevenLabs", "authoritativeOutput", "derivedWav"}:
        raise ValueError(f"CourseCraft production narration configuration has unknown or missing top-level keys: {path}")
    eleven = config.get("elevenLabs")
    output = config.get("authoritativeOutput")
    derived = config.get("derivedWav")
    if not isinstance(eleven, dict) or set(eleven) != {"voiceId", "modelId", "outputFormat", "tuning"}:
        raise ValueError(f"CourseCraft production narration elevenLabs contract is incomplete: {path}")
    for key in ("voiceId", "modelId", "outputFormat"):
        _required_string(eleven, key, "CourseCraft production narration elevenLabs contract")
    tuning = eleven.get("tuning")
    tuning_keys = {"stability", "similarityBoost", "style", "speakerBoost", "speed"}
    if not isinstance(tuning, dict) or set(tuning) != tuning_keys:
        raise ValueError(f"CourseCraft production narration tuning contract is incomplete: {path}")
    if not all(isinstance(tuning[key], (int, float)) and not isinstance(tuning[key], bool) for key in ("stability", "similarityBoost", "style", "speed")) or not isinstance(tuning["speakerBoost"], bool):
        raise ValueError(f"CourseCraft production narration tuning values have invalid types: {path}")
    if not all(0 <= float(tuning[key]) <= 1 for key in ("stability", "similarityBoost", "style")) or not 0.7 <= float(tuning["speed"]) <= 1.2:
        raise ValueError(f"CourseCraft production narration tuning values are out of range: {path}")
    if not isinstance(output, dict) or set(output) != {"relativeDirectory", "filenameStem"}:
        raise ValueError(f"CourseCraft production narration output contract is incomplete: {path}")
    for key in ("relativeDirectory", "filenameStem"):
        value = _required_string(output, key, "CourseCraft production narration output contract")
        component = Path(value)
        if component.is_absolute() or ".." in component.parts or len(component.parts) != 1:
            raise ValueError(f"CourseCraft production narration output {key} must be one safe relative component: {path}")
    expected_derived = {"relativePath": "voiceover.wav", "codec": "pcm_s16le", "sampleRate": 48000, "channels": 1}
    if derived != expected_derived:
        raise ValueError(f"CourseCraft production narration derived-WAV contract must equal {expected_derived}: {path}")
    suffix_for_output_format(eleven["outputFormat"])
    config["contractPath"] = str(path)
    config["contractSha256"] = _sha256_file(path)
    return config


def resolve_production_voice(voice_id: str) -> dict:
    """Live-verify the exact voice selected by the CourseCraft production contract."""
    metadata = _run_json(["elevenlabs", "voices", "get", voice_id])
    if not isinstance(metadata, dict):
        raise ValueError("ElevenLabs voices get returned a non-object payload.")
    verified_id = _required_string(metadata, "voice_id", "ElevenLabs voice metadata")
    if verified_id != voice_id:
        raise ValueError(f"ElevenLabs voice identity mismatch: requested {voice_id}, returned {verified_id}.")
    return {
        "voiceId": voice_id,
        "resolutionSource": "CourseCraft production narration contract",
        "name": metadata.get("name"),
        "category": metadata.get("category"),
        "labels": _voice_labels(metadata),
    }


def _voice_labels(metadata: dict) -> dict:
    """The voice's ``labels`` map. Absent is legal; present-but-wrong is not.

    ElevenLabs omits ``labels`` for a voice that carries none, so a missing key
    is an ordinary empty map. A present ``labels`` of any other type is a
    contract change in the voice metadata this narration pins itself to, and is
    reported rather than silently emptied.
    """
    if "labels" not in metadata:
        return {}
    labels = metadata["labels"]
    if not isinstance(labels, dict):
        raise ValueError(
            "ElevenLabs voice metadata 'labels' must be an object; got "
            f"{type(labels).__name__}."
        )
    return labels


def verify_model(model_id: str) -> dict:
    metadata = _run_json(["elevenlabs", "models", "get", model_id])
    if not isinstance(metadata, dict):
        raise ValueError("ElevenLabs models get returned a non-object payload.")
    returned_id = metadata.get("model_id") or metadata.get("modelId")
    if returned_id != model_id:
        raise ValueError(f"ElevenLabs model identity mismatch: requested {model_id}, returned {returned_id!r}.")
    return {"modelId": model_id, "name": metadata.get("name")}


def suffix_for_output_format(output_format: str) -> str:
    try:
        return SUPPORTED_DEMO_OUTPUT_FORMATS[output_format]
    except KeyError as error:
        supported = ", ".join(sorted(SUPPORTED_DEMO_OUTPUT_FORMATS))
        raise ValueError(
            f"Unsupported authoritative demo narration output format {output_format!r}; supported: {supported}."
        ) from error


def _resolve_demo_folder(fields: dict) -> Path:
    raw = fields.get("Folder Root")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Demo is missing Folder Root; cannot resolve narration authority.")
    folder = Path(raw.strip()).expanduser()
    return folder if folder.is_absolute() else COURSES_ROOT / folder


def _t04_provenance_path(folder: Path) -> Path:
    return folder / ".coursecraft" / "automated-walkthrough" / "provenance.json"


def _has_t04_provenance(folder: Path) -> bool:
    return _t04_provenance_path(folder).is_file()


def _load_provenance() -> Any:
    """The CourseCraft T04 provenance boundary, loaded once per process.

    One loader for every CourseCraft contract module (coursecraft_project), so the
    checkout is resolved the same single way here as everywhere else in this CLI.
    """
    global _PROVENANCE_MODULE
    if _PROVENANCE_MODULE is None:
        _PROVENANCE_MODULE = load_coursecraft_module(
            PROVENANCE_RELATIVE_PATH, "coursecraft_cli_t04_provenance"
        )
    return _PROVENANCE_MODULE


def _standalone_narration_binding(authoritative_path: Path, output_hash: str) -> dict:
    return {
        "schemaVersion": STANDALONE_NARRATION_PROVENANCE_SCHEMA,
        "mode": "narration-only",
        "authoritativePath": str(authoritative_path),
        "outputSha256": output_hash,
    }


def _publish_narration_standalone(source: Path, authoritative_path: Path, output_hash: str) -> dict:
    if not source.is_file() or _sha256_file(source) != output_hash:
        raise ValueError("Standalone narration source is missing or does not match the validated output hash.")
    authoritative_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = authoritative_path.with_name(f".{authoritative_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        if _sha256_file(temporary) != output_hash:
            raise ValueError("Standalone narration temporary copy hash mismatch.")
        os.replace(temporary, authoritative_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    if authoritative_path.is_symlink():
        raise ValueError("Standalone narration authority must be a regular file, not a symlink.")
    if not authoritative_path.is_file() or _sha256_file(authoritative_path) != output_hash:
        raise ValueError("Standalone narration authority postcheck failed.")
    return _standalone_narration_binding(authoritative_path, output_hash)


def _ensure_canonical_script_normalization(
    folder: Path, normalized_text: str, script_text: str
) -> dict | None:
    """Publish Script parser output byte-exactly before narration reuse/rebind.

    The canonical parser deliberately emits no terminal newline. Provenance can
    prove a manually supplied text file is current without proving that byte-level
    parser contract, so the voice producer repairs that boundary before it
    republishes dependent narration.
    """
    if not _has_t04_provenance(folder):
        return None
    if not isinstance(normalized_text, str) or not normalized_text:
        raise ValueError("Canonical normalized Script text is required for T04 publication.")
    if not isinstance(script_text, str) or not script_text:
        raise ValueError("Fresh CourseCraft Script text is required for T04 publication.")

    provenance = _load_provenance()
    record = provenance.load_record(folder)
    stage = record["stages"]["script_normalization"]
    source_inputs = stage.get("sourceInputs", [])
    script_sources = [item for item in source_inputs if item.get("identity") == "scriptSource"]
    if len(script_sources) != 1:
        raise ValueError("T04 script_normalization must declare exactly one scriptSource input.")
    script_source = Path(script_sources[0].get("path", ""))
    if not script_source.is_file() or script_source.read_text(encoding="utf-8") != script_text:
        raise ValueError("T04 scriptSource does not exactly match the fresh CourseCraft Script.")

    errors = provenance.validate_stage(folder, record, "script_normalization", visited=set())
    outputs = stage.get("outputs", [])
    if not errors and stage.get("status") == "published" and len(outputs) == 1:
        current = Path(outputs[0].get("path", ""))
        if current.is_file() and current.read_bytes() == normalized_text.encode("utf-8"):
            return outputs[0]

    action_summary = record["stages"]["action_summary"]
    action_errors = provenance.validate_stage(folder, record, "action_summary", visited=set())
    action_outputs = action_summary.get("outputs", [])
    if action_errors or len(action_outputs) != 1 or action_outputs[0].get("identity") != "actionSummary":
        raise ValueError(
            "T04 action_summary prerequisite is not valid: " + "; ".join(action_errors)
        )
    action_summary_path = Path(action_outputs[0].get("path", ""))

    with redirect_stdout(io.StringIO()):
        provenance.begin_command(
            SimpleNamespace(folder_root=str(folder), stage="script_normalization", state=[])
        )
    record = provenance.load_record(folder)
    replacement = record["stages"]["script_normalization"]
    generation = replacement["generationId"]
    staging = Path(replacement["stagingPath"])
    staged = staging / "normalized-spoken-text.txt"
    try:
        staged.write_bytes(normalized_text.encode("utf-8"))
        with redirect_stdout(io.StringIO()):
            provenance.publish_command(
                SimpleNamespace(
                    folder_root=str(folder),
                    stage="script_normalization",
                    generation_id=generation,
                    input=[
                        f"actionSummary={action_summary_path}",
                        f"scriptSource={script_source}",
                    ],
                    output=[f"normalizedText={staged}"],
                    simulate_crash=None,
                    alignment_authority=None,
                )
            )
        published_stage = provenance.load_record(folder)["stages"]["script_normalization"]
        published_outputs = published_stage.get("outputs", [])
        if len(published_outputs) != 1:
            raise ValueError("T04 canonical normalization publication produced invalid outputs.")
        published = Path(published_outputs[0].get("path", ""))
        if published.read_bytes() != normalized_text.encode("utf-8"):
            raise ValueError("T04 canonical normalization publication changed parser output bytes.")
        return published_outputs[0]
    except Exception as error:
        with redirect_stdout(io.StringIO()):
            provenance.fail_command(
                SimpleNamespace(
                    folder_root=str(folder),
                    stage="script_normalization",
                    diagnostic=str(error),
                )
            )
        raise


def _publish_narration(folder: Path, source: Path, authoritative_path: Path, source_hash: str) -> dict:
    """Publish/rebind validated bytes through T04, then atomically project authority.

    T04's prepared publication intent is the durable byte-publication boundary.  A
    prior stable symlink is deliberately left usable while ``begin`` quarantines
    the old generation; it is replaced only after the new current is recoverable.
    """
    if not _has_t04_provenance(folder):
        return _publish_narration_standalone(source, authoritative_path, source_hash)
    provenance = _load_provenance()
    record = provenance.load_record(folder)
    normalized = record["stages"]["script_normalization"]
    errors = provenance.validate_stage(folder, record, "script_normalization", visited=set())
    if errors or len(normalized.get("outputs", [])) != 1:
        raise ValueError("T04 script_normalization prerequisite is not valid: " + "; ".join(errors))
    normalized_path = Path(normalized["outputs"][0]["path"])

    narration = record["stages"]["narration"]
    if narration.get("status") == "published" and len(narration.get("outputs", [])) == 1:
        output = narration["outputs"][0]
        published = Path(output.get("path", ""))
        if output.get("sha256") == source_hash and published.is_file() and provenance.sha256_file(published) == source_hash:
            authoritative_path.parent.mkdir(parents=True, exist_ok=True)
            if authoritative_path.is_symlink() and authoritative_path.resolve() == published.resolve():
                return output
            temporary_link = authoritative_path.with_name(f".{authoritative_path.name}.{uuid.uuid4().hex}.tmp")
            temporary_link.symlink_to(published)
            os.replace(temporary_link, authoritative_path)
            return output

    # Preserve the previously registered bytes behind the same lexical authority
    # before T04 moves its old current.  This rollback generation keeps the old
    # CourseCraft registration usable throughout replacement and is intentionally
    # retained after success for reconciliation.
    if authoritative_path.is_symlink() and authoritative_path.is_file():
        previous_root = authoritative_path.parent / ".previous" / uuid.uuid4().hex
        previous_root.mkdir(parents=True, exist_ok=False)
        previous_bytes = previous_root / authoritative_path.name
        shutil.copyfile(authoritative_path, previous_bytes)
        temporary_previous = authoritative_path.with_name(
            f".{authoritative_path.name}.{uuid.uuid4().hex}.tmp"
        )
        temporary_previous.symlink_to(previous_bytes)
        os.replace(temporary_previous, authoritative_path)

    with redirect_stdout(io.StringIO()):
        provenance.begin_command(SimpleNamespace(folder_root=str(folder), stage="narration", state=[]))
    record = provenance.load_record(folder)
    generation = record["stages"]["narration"]["generationId"]
    staging = Path(record["stages"]["narration"]["stagingPath"])
    staged = staging / authoritative_path.name
    try:
        shutil.copyfile(source, staged)
        with redirect_stdout(io.StringIO()):
            provenance.publish_command(SimpleNamespace(
                folder_root=str(folder), stage="narration", generation_id=generation,
                input=[f"normalizedText={normalized_path}"],
                output=[f"authoritativeNarration={staged}"], simulate_crash=None,
                alignment_authority=None,
            ))
        published = provenance.current_path(folder, "narration") / authoritative_path.name
        if provenance.sha256_file(published) != source_hash:
            raise ValueError("T04 narration publication hash does not match validated narration.")
        authoritative_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_link = authoritative_path.with_name(f".{authoritative_path.name}.{uuid.uuid4().hex}.tmp")
        temporary_link.symlink_to(published)
        os.replace(temporary_link, authoritative_path)
        return provenance.load_record(folder)["stages"]["narration"]["outputs"][0]
    except Exception as error:
        # Loading first resolves T04's prepared intent.  If publication crossed
        # its rename boundary, finish the stable projection instead of calling
        # fail (which would destroy a recoverable committed generation).
        try:
            recovered = provenance.load_record(folder)["stages"]["narration"]
            outputs = recovered.get("outputs", [])
            if recovered.get("status") == "published" and len(outputs) == 1:
                published = Path(outputs[0].get("path", ""))
                if published.is_file() and provenance.sha256_file(published) == source_hash:
                    authoritative_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary_link = authoritative_path.with_name(
                        f".{authoritative_path.name}.{uuid.uuid4().hex}.tmp"
                    )
                    temporary_link.symlink_to(published)
                    os.replace(temporary_link, authoritative_path)
                    return outputs[0]
        except Exception:
            pass
        with redirect_stdout(io.StringIO()):
            provenance.fail_command(SimpleNamespace(folder_root=str(folder), stage="narration", diagnostic=str(error)))
        raise


def _tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text)]


def _recall_report(expected_text: str, transcript_text: str) -> dict:
    expected = _tokens(expected_text)
    actual = _tokens(transcript_text)
    if not expected or not actual:
        raise ValueError("Whole-script recall requires non-empty expected and transcribed words.")
    matcher = SequenceMatcher(a=expected, b=actual, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    word_recall = matched / len(expected)
    sequence_recall = matcher.ratio()
    report = {
        "expectedWordCount": len(expected),
        "transcriptWordCount": len(actual),
        "matchedWordCount": matched,
        "wordRecall": round(word_recall, 6),
        "sequenceRecall": round(sequence_recall, 6),
        "minimumWordRecall": MIN_WORD_RECALL,
        "minimumSequenceRecall": MIN_SEQUENCE_RECALL,
    }
    if word_recall < MIN_WORD_RECALL or sequence_recall < MIN_SEQUENCE_RECALL:
        raise ValueError(f"Whole-script content recall failed: {_canonical_json(report)}")
    return report


def _assert_no_cue_leakage(cues: list[dict], transcript_text: str) -> dict:
    transcript = " ".join(_tokens(transcript_text))
    leaked = []
    checked = []
    for cue in cues:
        text = cue.get("text") if isinstance(cue, dict) else None
        if not isinstance(text, str):
            raise ValueError("Canonical cue metadata contains an invalid cue text.")
        phrase = " ".join(_tokens(text.strip("<>")))
        if phrase:
            checked.append(text)
            if phrase in transcript:
                leaked.append(text)
    if leaked:
        raise ValueError(f"Action-cue leakage detected in narration transcript: {leaked}")
    return {"valid": True, "checkedCueCount": len(checked), "leakedCues": []}


def _probe_audio(path: Path) -> dict:
    probe = _run_json([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ])
    if not isinstance(probe, dict) or not isinstance(probe.get("streams"), list):
        raise ValueError("ffprobe returned an invalid media payload.")
    audio_streams = [stream for stream in probe["streams"] if isinstance(stream, dict) and stream.get("codec_type") == "audio"]
    non_audio = [stream for stream in probe["streams"] if isinstance(stream, dict) and stream.get("codec_type") != "audio"]
    if len(audio_streams) != 1 or non_audio:
        raise ValueError(f"Narration candidate must contain exactly one audio stream and no other streams; audio={len(audio_streams)}, other={len(non_audio)}.")
    raw_duration = audio_streams[0].get("duration") or (probe.get("format") or {}).get("duration")
    try:
        duration = float(str(raw_duration))
    except (TypeError, ValueError) as error:
        raise ValueError("Narration candidate has no numeric duration.") from error
    if duration <= 0:
        raise ValueError(f"Narration candidate duration must be positive, got {duration}.")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-map", "0:a:0", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
        timeout=GENERATION_TIMEOUT_SECONDS,
    )
    levels = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "astats=metadata=0:reset=0", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
        timeout=GENERATION_TIMEOUT_SECONDS,
    )
    peak_matches = re.findall(r"Peak level dB:\s*(-?inf|[-+0-9.]+)", levels.stderr)
    if not peak_matches:
        raise ValueError("ffmpeg astats did not report peak level.")
    finite_peaks = [float(value) for value in peak_matches if value != "-inf"]
    peak_dbfs = max(finite_peaks) if finite_peaks else float("-inf")
    if peak_dbfs > PEAK_LIMIT_DBFS:
        raise ValueError(
            f"Narration peak/clipping policy failed: peakDbfs={peak_dbfs}, limitDbfs={PEAK_LIMIT_DBFS}."
        )
    stream = audio_streams[0]
    return {
        "durationSeconds": duration,
        "codecName": stream.get("codec_name"),
        "sampleRate": int(stream["sample_rate"]) if str(stream.get("sample_rate", "")).isdigit() else None,
        "channels": stream.get("channels"),
        "peakDbfs": peak_dbfs,
        "peakLimitDbfs": PEAK_LIMIT_DBFS,
        "clippedSampleCount": 0,
        "fullDecode": True,
    }


def _transcription_command(path: Path, vocabulary: str) -> tuple[str, list[str]]:
    openai_whisper = shutil.which("openai-whisper")
    if openai_whisper:
        return "openai-whisper", [
            openai_whisper, "transcripts", "create", str(path),
            "--model", "turbo", "--language", "en", "--timeout", str(TRANSCRIPTION_TIMEOUT_SECONDS),
            "--temperature", "0", "--initial-prompt", vocabulary,
        ]
    whisper = shutil.which("whisper")
    if whisper:
        return "whisper", [
            whisper, "transcripts", "create", str(path),
            "--language", "en", "--timeout", str(TRANSCRIPTION_TIMEOUT_SECONDS),
            "--prompt", vocabulary,
        ]
    raise ValueError("No supported Whisper transcript command found; expected openai-whisper or whisper.")


def _transcribe(path: Path, expected_text: str) -> tuple[str, dict]:
    vocabulary = ", ".join(dict.fromkeys(_tokens(expected_text)))[:4000]
    command_name, command = _transcription_command(path, vocabulary)
    payload = _run_json(command, timeout=TRANSCRIPTION_TIMEOUT_SECONDS + 30)
    if not isinstance(payload, dict):
        raise ValueError(f"{command_name} returned a non-object transcript payload.")
    return _required_string(payload, "text", "Whisper transcript"), payload


def _validate_candidate(
    path: Path,
    normalized_text: str,
    normalized_source_hash: str,
    cues: list[dict],
    identity: dict,
    generation_metadata: dict,
) -> dict:
    actual_source_hash = _sha256_bytes(normalized_text.encode("utf-8"))
    if actual_source_hash != normalized_source_hash:
        raise ValueError(
            f"Canonical normalized Script hash mismatch: expected {normalized_source_hash}, got {actual_source_hash}."
        )
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"Narration staging candidate is missing or empty: {path}")
    for key in ("history_item_id", "character_count"):
        if generation_metadata.get(key) in (None, ""):
            raise ValueError(f"ElevenLabs generation metadata is missing {key}.")
    request_id = generation_metadata.get("request_id")
    if request_id in (None, "") and not (
        request_id == ""
        and generation_metadata.get("request_id_status") == "unavailable-official-history-recovery"
        and isinstance(generation_metadata.get("request_id_provenance"), str)
        and generation_metadata["request_id_provenance"]
    ):
        raise ValueError("ElevenLabs generation metadata is missing request_id or explicit recovery provenance.")
    if generation_metadata.get("output_path") not in (None, str(path)):
        raise ValueError("ElevenLabs generation output path does not match the unique staging candidate.")
    expected_download_hash = generation_metadata.get("download_sha256")
    if expected_download_hash is not None and expected_download_hash != _sha256_file(path):
        raise ValueError("ElevenLabs history download SHA-256 does not match the transaction candidate.")
    audio = _probe_audio(path)
    if identity["outputFormat"] == "mp3_44100_128":
        if audio.get("codecName") != "mp3" or audio.get("sampleRate") != 44100:
            raise ValueError(
                "Authoritative audio does not match mp3_44100_128: "
                f"codec={audio.get('codecName')!r}, sampleRate={audio.get('sampleRate')!r}."
            )
    transcript, transcript_payload = _transcribe(path, normalized_text)
    cue_validation = _assert_no_cue_leakage(cues, transcript)
    recall = _recall_report(normalized_text, transcript)
    output_hash = _sha256_file(path)
    return {
        "valid": True,
        "sourceSha256": normalized_source_hash,
        "outputSha256": output_hash,
        "audio": audio,
        "cueLeakage": cue_validation,
        "recall": recall,
        "transcript": transcript,
        "transcriptSha256": _sha256_bytes(transcript.encode("utf-8")),
        "transcription": {"model": "turbo", "language": transcript_payload.get("language")},
        "identity": identity,
    }


def validate_manual_narration_take(
    path: Path,
    normalized_text: str,
    cues: list[dict],
) -> dict:
    """Prove that a registered manual take speaks the current narration."""
    if not isinstance(normalized_text, str) or not normalized_text.strip():
        raise ValueError("Canonical narration text is required to verify a manual take.")
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"Registered manual narration file is missing or empty: {path}")

    transcript, transcript_payload = _transcribe(path, normalized_text)
    cue_validation = _assert_no_cue_leakage(cues, transcript)
    recall = _recall_report(normalized_text, transcript)
    return {
        "valid": True,
        "sourceSha256": _sha256_bytes(normalized_text.encode("utf-8")),
        "outputSha256": _sha256_file(path),
        "cueLeakage": cue_validation,
        "recall": recall,
        "transcript": transcript,
        "transcriptSha256": _sha256_bytes(transcript.encode("utf-8")),
        "transcription": {"model": "turbo", "language": transcript_payload.get("language")},
    }


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(_canonical_json(payload) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_manifest(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Narration metadata is not an object: {path}")
    return payload


def _require_symlink_authority(folder: Path, authoritative_path: Path) -> None:
    """Require the T04-published authority to be the expected symlink, never a regular file."""
    if not _has_t04_provenance(folder):
        return
    if authoritative_path.is_symlink() or not authoritative_path.exists():
        return
    raise ValueError(
        "Authoritative narration path must be a symlink to its T04-published output, "
        f"but it is a regular file: {authoritative_path}"
    )


def _canonical_utc_second(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _readback_fields(readback: object, record_id: str) -> dict:
    """The ``fields`` of a post-write readback, or a loud failure.

    A readback that is not a record object means the read itself did not
    produce one -- the record vanished, or the source returned something
    unexpected. Coercing that to ``{}`` used to make it arrive at the caller's
    field-comparison as an ordinary "did not match every owned field" mismatch,
    which named the wrong cause for a narration registration whose state is
    genuinely unknown.
    """
    if not isinstance(readback, dict):
        raise ValueError(
            f"Narration registration readback for Demos/{record_id} is a "
            f"{type(readback).__name__}, not a record object; the registration "
            "state could not be confirmed."
        )
    fields = readback.get("fields", {})
    if not isinstance(fields, dict):
        raise ValueError(
            f"Narration registration readback for Demos/{record_id} has a "
            f"{type(fields).__name__} 'fields' payload, not an object."
        )
    return fields


def _record_matches(fields: dict, expected_fields: dict) -> bool:
    """Require exact equality for the complete narration update field mapping."""
    def matches(key: str, actual: Any, expected: Any) -> bool:
        if key == VOICE_GENERATED_AT_FIELD:
            return _canonical_utc_second(actual) == _canonical_utc_second(expected)
        return actual == expected

    return (
        isinstance(fields, dict)
        and isinstance(expected_fields, dict)
        and set(expected_fields) == set(OWNED_UPDATE_FIELDS)
        and all(matches(key, fields.get(key), value) for key, value in expected_fields.items())
    )


def _verified_narration_provenance(
    folder: Path,
    authoritative_path: Path,
    output_hash: str,
    expected_binding: Optional[dict] = None,
) -> dict:
    """Bind the stable symlink to the exact current validated T04 narration output."""
    if not _has_t04_provenance(folder):
        if authoritative_path.is_symlink():
            raise ValueError(f"Standalone narration authority must not be a symlink: {authoritative_path}")
        if not authoritative_path.is_file() or _sha256_file(authoritative_path) != output_hash:
            raise ValueError("Standalone narration authority does not match the validated output hash.")
        binding = _standalone_narration_binding(authoritative_path, output_hash)
        if expected_binding is not None and expected_binding != binding:
            raise ValueError("Standalone narration manifest provenance does not match current authority.")
        return binding
    if not authoritative_path.is_symlink():
        raise ValueError(f"Authoritative narration path must remain a symlink: {authoritative_path}")
    provenance = _load_provenance()
    record = provenance.load_record(folder)
    errors = provenance.validate_stage(folder, record, "narration", visited=set())
    stage = record["stages"]["narration"]
    outputs = stage.get("outputs", [])
    generation = stage.get("generationId")
    if errors:
        raise ValueError("T04 current narration provenance is invalid: " + "; ".join(errors))
    if stage.get("status") != "published" or not isinstance(generation, str) or not generation or len(outputs) != 1:
        raise ValueError("T04 current narration status/generation/output identity is incomplete.")
    output = outputs[0]
    published = Path(output.get("path", ""))
    try:
        registered_target = authoritative_path.resolve(strict=True)
        published_target = published.resolve(strict=True)
    except OSError as error:
        raise ValueError("T04 current narration target is missing.") from error
    if (
        output.get("identity") != "authoritativeNarration"
        or output.get("sha256") != output_hash
        or registered_target != published_target
        or provenance.sha256_file(published_target) != output_hash
    ):
        raise ValueError("Stable narration authority does not bind the current T04 output identity/hash.")
    binding = {"generationId": generation, "output": output}
    if expected_binding is not None and expected_binding != binding:
        raise ValueError("Narration manifest provenance does not match the current T04 generation/output.")
    return binding


def _manifest_is_reusable(
    manifest: dict,
    transaction_id: str,
    folder: Path,
    path: Path,
    identity: dict,
    source_hash: str,
) -> bool:
    if manifest.get("schemaVersion") != TRANSACTION_SCHEMA_VERSION or manifest.get("transactionId") != transaction_id:
        return False
    if manifest.get("authoritativePath") != str(path) or manifest.get("sourceSha256") != source_hash:
        return False
    if manifest.get("identity") != identity or manifest.get("validation", {}).get("valid") is not True:
        return False
    if not path.is_file() or manifest.get("outputSha256") != _sha256_file(path):
        return False
    provenance_binding = manifest.get("narrationProvenance")
    if not isinstance(provenance_binding, dict):
        return False
    try:
        _verified_narration_provenance(
            folder, path, manifest["outputSha256"], provenance_binding
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


def _build_update_fields(
    transaction_id: str,
    source_hash: str,
    identity: dict,
    generation_metadata: dict,
) -> dict:
    return {
        VOICE_RECORDING_ID_FIELD: transaction_id,
        VOICE_SOURCE_HASH_FIELD: source_hash,
        ELEVENLABS_VOICE_ID_FIELD: identity["voiceId"],
        ELEVENLABS_MODEL_ID_FIELD: identity["modelId"],
        ELEVENLABS_OUTPUT_FORMAT_FIELD: identity["outputFormat"],
        ELEVENLABS_REQUEST_ID_FIELD: generation_metadata["request_id"],
        ELEVENLABS_HISTORY_ITEM_ID_FIELD: generation_metadata["history_item_id"],
        VOICE_CHARACTER_COUNT_FIELD: generation_metadata["character_count"],
        VOICE_GENERATED_AT_FIELD: datetime.now(timezone.utc).isoformat(timespec="seconds"),
        DICTATION_RECORDED_FIELD: True,
    }


def _registered_identity_matches(fields: dict, transaction_id: str,
                                 source_hash: str, identity: dict) -> bool:
    """Prove the CourseCraft half of reusable bytes without trusting a sidecar."""
    required = {
        VOICE_RECORDING_ID_FIELD: transaction_id,
        VOICE_SOURCE_HASH_FIELD: source_hash,
        ELEVENLABS_VOICE_ID_FIELD: identity["voiceId"],
        ELEVENLABS_MODEL_ID_FIELD: identity["modelId"],
        ELEVENLABS_OUTPUT_FORMAT_FIELD: identity["outputFormat"],
        DICTATION_RECORDED_FIELD: True,
    }
    return (
        all(fields.get(key) == value for key, value in required.items())
        and fields.get(ELEVENLABS_REQUEST_ID_FIELD) is not None
        and all(fields.get(key) not in (None, "") for key in (
            ELEVENLABS_HISTORY_ITEM_ID_FIELD,
            VOICE_CHARACTER_COUNT_FIELD, VOICE_GENERATED_AT_FIELD,
        ))
    )


def _generation_metadata_from_fields(fields: dict, output_path: Optional[Path] = None) -> dict:
    metadata = {
        "request_id": fields[ELEVENLABS_REQUEST_ID_FIELD],
        "history_item_id": fields[ELEVENLABS_HISTORY_ITEM_ID_FIELD],
        "character_count": fields[VOICE_CHARACTER_COUNT_FIELD],
        "output_path": str(output_path) if output_path is not None else None,
    }
    if metadata["request_id"] == "":
        metadata.update({
            "request_id_status": "unavailable-official-history-recovery",
            "request_id_provenance": "CourseCraft empty readback; official history item does not guarantee original request ID",
        })
    return metadata


def _publication_manifest(*, transaction_id: str, record_id: str, authoritative_path: Path,
                          folder: Path, source_hash: str, output_hash: str, identity: dict,
                          generation_metadata: dict, validation: dict,
                          narration_binding: dict) -> dict:
    return {
        "schemaVersion": TRANSACTION_SCHEMA_VERSION,
        "state": "promoted-unregistered",
        "transactionId": transaction_id,
        "recordId": record_id,
        "recordType": "demo",
        "authoritativePath": str(authoritative_path),
        "sourceSha256": source_hash,
        "outputSha256": output_hash,
        "identity": identity,
        "generationMetadata": generation_metadata,
        "validation": validation,
        "narrationProvenance": narration_binding,
        "derivedWavInput": {
            "authoritativeSourcePath": str(authoritative_path.resolve()),
            "authoritativeSourceSha256": output_hash,
            "sourceFormat": identity["outputFormat"],
            "targetPath": str(folder / "voiceover.wav"),
            "policy": {"codec": "pcm_s16le", "sampleRate": 48000, "channels": 1},
        },
    }


def _candidate_facts(path: Path) -> dict:
    exists = path.is_file()
    return {
        "path": str(path), "exists": exists,
        "size": path.stat().st_size if exists else None,
        "sha256": _sha256_file(path) if exists else None,
    }


def _timeout_facts(error: BaseException, candidate_path: Path) -> dict:
    """Preserve every identifier/output fact exposed by a timed-out subprocess."""
    stdout = getattr(error, "stdout", None)
    stderr = getattr(error, "stderr", None)
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    facts: dict[str, Any] = {
        "exceptionType": type(error).__name__,
        "command": list(error.cmd) if isinstance(error, subprocess.TimeoutExpired) and isinstance(error.cmd, (list, tuple)) else None,
        "timeoutSeconds": getattr(error, "timeout", None),
        "stdout": stdout, "stderr": stderr,
        "candidate": _candidate_facts(candidate_path),
    }
    exposed: dict[str, Any] = {}
    for value in (stdout, stderr):
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            for key in ("request_id", "history_item_id", "character_count", "output_path"):
                if payload.get(key) not in (None, ""):
                    exposed[key] = payload[key]
    facts["generationMetadata"] = exposed
    return facts


def _coursecraft_pre_state_matches(fields: dict, pending: dict) -> bool:
    prior = pending.get("courseCraftPreState")
    expected_keys = set(OWNED_UPDATE_FIELDS) | {RECORDED_FIELD}
    return (
        isinstance(fields, dict)
        and isinstance(prior, dict)
        and set(prior) == expected_keys
        and all(fields.get(key) == prior[key] for key in expected_keys)
    )


def _history_character_count(item: dict) -> tuple[int, str]:
    """Derive billed characters only from verified official history fields."""
    direct = item.get("character_count")
    if isinstance(direct, int) and not isinstance(direct, bool) and direct > 0:
        return direct, "history_item.character_count"
    before = item.get("character_count_change_from")
    after = item.get("character_count_change_to")
    if (
        isinstance(before, int) and not isinstance(before, bool)
        and isinstance(after, int) and not isinstance(after, bool)
    ):
        delta = after - before
        if delta > 0:
            return delta, "history_item.character_count_change_to-minus-from"
    text = item.get("text")
    if isinstance(text, str) and text:
        return len(text), "history_item.text-length"
    raise ValueError(
        "HISTORY_RECOVERY_CHARACTER_COUNT_UNAVAILABLE: official history item lacks a positive character_count, "
        "valid character_count_change_from/to delta, or non-empty text."
    )


def _generation_identity_matches(pending: dict, metadata: dict) -> bool:
    known = pending.get("timeoutFacts", {}).get("generationMetadata", {})
    return all(
        known.get(key) in (None, "") or metadata.get(key) == known.get(key)
        for key in ("request_id", "history_item_id")
    )


def _reconcile_elevenlabs_history(pending: dict, candidate_path: Path) -> dict:
    """Recover one exact generation through the repo-owned ElevenLabs history CLI."""
    timeout_metadata = pending.get("timeoutFacts", {}).get("generationMetadata", {})
    if not isinstance(timeout_metadata, dict):
        timeout_metadata = {}
    history_item_id = timeout_metadata.get("history_item_id")
    request_id = timeout_metadata.get("request_id")
    if not isinstance(history_item_id, str) or not history_item_id.strip():
        return {
            "state": "unavailable",
            "evidence": {
                "adapter": "repo-owned-elevenlabs-cli",
                "supportedLookup": False,
                "reason": (
                    "Official ElevenLabs History API requires history_item_id; request-ID-only "
                    "or identifier-free reconciliation is ambiguous and cannot authorize paid retry."
                ),
                "requestId": request_id,
                "historyItemId": history_item_id,
            },
        }
    history_item_id = history_item_id.strip()
    try:
        item = _run_json(["elevenlabs", "history", "get", history_item_id])
        if not isinstance(item, dict):
            raise ValueError("elevenlabs history get returned a non-object payload.")
        returned_id = _required_string(item, "history_item_id", "ElevenLabs history item")
        if returned_id != history_item_id:
            raise ValueError(
                f"ElevenLabs history identity mismatch: requested {history_item_id}, returned {returned_id}."
            )
        if "state" not in item:
            raise ValueError("ElevenLabs history item is missing state.")
        character_count, character_count_source = _history_character_count(item)
        download = _run_json([
            "elevenlabs", "history", "download", history_item_id,
            "--output", str(candidate_path),
        ])
        if not isinstance(download, dict):
            raise ValueError("elevenlabs history download returned a non-object payload.")
        if download.get("history_item_id") != history_item_id:
            raise ValueError("ElevenLabs history download identity does not match the requested item.")
        if download.get("output_path") != str(candidate_path):
            raise ValueError("ElevenLabs history download did not target the transaction candidate.")
        size_bytes = download.get("size_bytes")
        if not isinstance(size_bytes, int) or size_bytes <= 0:
            raise ValueError("ElevenLabs history download reported no audio bytes.")
        if not candidate_path.is_file() or candidate_path.stat().st_size != size_bytes:
            raise ValueError("ElevenLabs history download candidate size does not match structured output.")
        download_sha256 = download.get("sha256")
        if not isinstance(download_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", download_sha256):
            raise ValueError("ElevenLabs history download reported no valid SHA-256 evidence.")
        if _sha256_file(candidate_path) != download_sha256:
            raise ValueError("ElevenLabs history download SHA-256 does not match the transaction candidate.")
        media = download.get("media")
        if not isinstance(media, dict) or media.get("full_decode") is not True or media.get("ffprobe") is not True:
            raise ValueError("ElevenLabs history download reported no complete media validation evidence.")
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        return {
            "state": "ambiguous",
            "evidence": {
                "adapter": "repo-owned-elevenlabs-cli",
                "supportedLookup": True,
                "historyItemId": history_item_id,
                "requestId": request_id,
                "reason": str(error),
                "noChargeEstablished": False,
            },
        }

    generation_metadata = dict(timeout_metadata)
    generation_metadata["history_item_id"] = history_item_id
    generation_metadata["output_path"] = str(candidate_path)
    generation_metadata["character_count"] = character_count
    generation_metadata["character_count_provenance"] = character_count_source
    generation_metadata["download_sha256"] = download_sha256
    if not isinstance(request_id, str) or not request_id.strip():
        generation_metadata["request_id"] = ""
        generation_metadata["request_id_status"] = "unavailable-official-history-recovery"
        generation_metadata["request_id_provenance"] = (
            "Official ElevenLabs history item does not guarantee the original TTS request ID; "
            "CourseCraft/Airtable empty value recorded."
        )
    return {
        "state": "completed",
        "generationMetadata": generation_metadata,
        "evidence": {
            "adapter": "repo-owned-elevenlabs-cli",
            "supportedLookup": True,
            "historyItemId": history_item_id,
            "historyState": item["state"],
            "historyItem": item,
            "download": download,
            "noChargeEstablished": False,
        },
    }


def generate_authoritative_demo_narration(
    *,
    client: Any,
    record: dict,
    record_id: str,
    normalized_text: str,
    canonical_preview: dict,
    spoken_text: str,
    production_config: dict,
    dictionary_locator: str,
    run_generation: Callable[..., dict],
    reconcile_generation: Callable[[dict, Path], dict] = _reconcile_elevenlabs_history,
) -> dict:
    """Generate, validate, promote, and register one authoritative demo take."""
    fresh_record = client.get_record("Demos", record_id)
    # The coercion this replaces made the guard below unreachable: a non-dict
    # record became {}, which is a dict, so the "payload is invalid" check could
    # never fire for the case it was written for.
    if not isinstance(fresh_record, dict):
        raise ValueError(
            f"Fresh CourseCraft Demo record for {record_id} is a "
            f"{type(fresh_record).__name__}, not a record object."
        )
    fields = fresh_record.get("fields", {})
    if not isinstance(fields, dict):
        raise ValueError("Fresh CourseCraft Demo fields payload is invalid.")
    recorded_pre_state = fields.get(RECORDED_FIELD)
    eleven = production_config["elevenLabs"]
    model_id = eleven["modelId"]
    output_format = eleven["outputFormat"]
    tuning = eleven["tuning"]
    suffix = suffix_for_output_format(output_format)
    voice = resolve_production_voice(eleven["voiceId"])
    model = verify_model(model_id)
    dictionary_parts = dictionary_locator.split(":")
    if len(dictionary_parts) != 2 or not all(dictionary_parts):
        raise ValueError("Pronunciation dictionary identity must be dictionary_id:version_id.")
    source_hash = _sha256_bytes(normalized_text.encode("utf-8"))
    preview_hash = canonical_preview.get("normalizedNarrationSha256")
    if preview_hash != source_hash:
        raise ValueError(f"Canonical Script preview hash mismatch: preview={preview_hash!r}, computed={source_hash}.")
    identity = {
        "voiceId": voice["voiceId"],
        "modelId": model["modelId"],
        "outputFormat": output_format,
        "suffix": suffix,
        "dictionaryId": dictionary_parts[0],
        "dictionaryVersionId": dictionary_parts[1],
        "tuning": tuning,
        "productionContractPath": production_config["contractPath"],
        "productionContractSha256": production_config["contractSha256"],
    }
    transaction_hash = _sha256_bytes(_canonical_json({"sourceSha256": source_hash, "identity": identity}).encode("utf-8"))
    transaction_id = f"coursecraft:demo:{record_id}:{transaction_hash}"
    folder = _resolve_demo_folder(fields)
    fresh_script = fields.get("Script")
    initial_script = record.get("fields", {}).get("Script") if isinstance(record, dict) else None
    if not isinstance(fresh_script, str) or fresh_script != initial_script:
        raise ValueError("Fresh CourseCraft Script changed after canonical narration preview.")
    normalization_binding = _ensure_canonical_script_normalization(
        folder, normalized_text, fresh_script
    )
    output_contract = production_config["authoritativeOutput"]
    authoritative_dir = folder / output_contract["relativeDirectory"]
    authoritative_path = authoritative_dir / f"{output_contract['filenameStem']}{suffix}"
    manifest_path = narration_metadata_path(authoritative_path)

    manifest = _read_manifest(manifest_path)
    _require_symlink_authority(folder, authoritative_path)
    staging_dir = authoritative_dir / ".staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    pending_path = staging_dir / f"{record_id}-{transaction_hash}.pending.json"

    # Upstream normalization replacement can move the prior T04 current before
    # this transaction starts. Rebind the unchanged lexical registration to the
    # preserved generation so the old CourseCraft fields remain usable while a
    # spoken replacement is generated and validated.
    if _has_t04_provenance(folder) and authoritative_path.is_symlink() and not authoritative_path.is_file() and isinstance(manifest, dict):
        old_hash = manifest.get("outputSha256")
        if isinstance(old_hash, str):
            provenance = _load_provenance()
            for preserved in provenance.stage_root(folder, "narration").rglob(authoritative_path.name):
                if preserved.is_file() and _sha256_file(preserved) == old_hash:
                    temporary_old = authoritative_path.with_name(
                        f".{authoritative_path.name}.{uuid.uuid4().hex}.tmp"
                    )
                    temporary_old.symlink_to(preserved)
                    os.replace(temporary_old, authoritative_path)
                    break

    registered_identity = _registered_identity_matches(
        fields, transaction_id, source_hash, identity
    )

    # Reconcile all authoritative identities before any paid call.  The local
    # sidecar is a reconstructible checkpoint, never the byte authority.
    if registered_identity:
        reusable_source: Optional[Path] = authoritative_path if (
            authoritative_path.is_file()
        ) else None
        if reusable_source is None and _has_t04_provenance(folder) and isinstance(manifest, dict):
            expected_output_hash = manifest.get("outputSha256")
            if isinstance(expected_output_hash, str):
                provenance = _load_provenance()
                search_root = provenance.stage_root(folder, "narration")
                for candidate in search_root.rglob(authoritative_path.name):
                    if candidate.is_file() and _sha256_file(candidate) == expected_output_hash:
                        reusable_source = candidate
                        break
        output_hash = _sha256_file(reusable_source) if reusable_source is not None else ""
        try:
            if reusable_source != authoritative_path:
                raise ValueError("Current T04 projection requires provenance rebind.")
            narration_binding = _verified_narration_provenance(
                folder, authoritative_path, output_hash
            )
        except (OSError, ValueError, KeyError, TypeError) as provenance_error:
            # A cue-only normalization replacement invalidates narration while its
            # spoken bytes and CourseCraft generation identity remain unchanged.
            old_manifest_proves_bytes = bool(
                reusable_source is not None
                and manifest
                and manifest.get("transactionId") == transaction_id
                and manifest.get("sourceSha256") == source_hash
                and manifest.get("identity") == identity
                and manifest.get("outputSha256") == output_hash
                and manifest.get("validation", {}).get("valid") is True
            )
            if not old_manifest_proves_bytes:
                raise ValueError(
                    "Registered narration provenance is not fully reconcilable; refusing paid generation."
                ) from provenance_error
            reusable_copy = staging_dir / f"{record_id}-{transaction_hash}-rebind{suffix}"
            assert reusable_source is not None
            shutil.copyfile(reusable_source, reusable_copy)
            publication = _publish_narration(
                folder, reusable_copy, authoritative_path, output_hash
            )
            narration_binding = _verified_narration_provenance(
                folder, authoritative_path, output_hash
            )
            reusable_copy.unlink(missing_ok=True)
            if _has_t04_provenance(folder) and narration_binding["output"] != publication:
                raise ValueError("Rebound narration output changed before manifest binding.")
            if not _has_t04_provenance(folder) and narration_binding != publication:
                raise ValueError("Rebound standalone narration binding changed before manifest binding.")
            reuse_status = "rebound-current-normalization"
        else:
            reuse_status = "reused" if manifest else "reconstructed-sidecar"

        generation_metadata = _generation_metadata_from_fields(fields)
        prior_validation = manifest.get("validation") if isinstance(manifest, dict) else None
        validation = prior_validation if isinstance(prior_validation, dict) and prior_validation.get("valid") is True else {
            "valid": True,
            "reconciled": True,
            "sourceSha256": source_hash,
            "outputSha256": output_hash,
            "identity": identity,
        }
        manifest = _publication_manifest(
            transaction_id=transaction_id, record_id=record_id,
            authoritative_path=authoritative_path, folder=folder,
            source_hash=source_hash, output_hash=output_hash, identity=identity,
            generation_metadata=generation_metadata, validation=validation,
            narration_binding=narration_binding,
        )
        manifest["state"] = "registered"
        manifest["courseCraftReadback"] = {key: fields.get(key) for key in OWNED_UPDATE_FIELDS}
        _atomic_write_json(manifest_path, manifest)
        return {
            "status": reuse_status, "creditsSpent": False, "recordId": record_id,
            "recordType": "demo", "transactionId": transaction_id,
            "authoritativePath": str(authoritative_path), "metadataPath": str(manifest_path),
            "scriptNormalization": normalization_binding,
            "sourceSha256": source_hash, "outputSha256": output_hash, "identity": identity,
            "validation": validation, "derivedWavInput": manifest["derivedWavInput"],
        }
    local_reusable = bool(manifest and _manifest_is_reusable(
        manifest, transaction_id, folder, authoritative_path, identity, source_hash
    ))
    generated_this_call = False
    if local_reusable:
        assert manifest is not None
        generation_metadata = manifest.get("generationMetadata")
        validation = manifest.get("validation")
        if not isinstance(generation_metadata, dict) or not isinstance(validation, dict):
            raise ValueError("Validated local narration metadata is incomplete; refusing regeneration.")
    else:
        pending = _read_manifest(pending_path) if pending_path.exists() else None
        if pending is not None and pending.get("state") in {"validated", "published"}:
            generation_metadata = pending.get("generationMetadata")
            validation = pending.get("validation")
            candidate_path = Path(str(pending.get("candidatePath", "")))
            if not isinstance(generation_metadata, dict) or not isinstance(validation, dict):
                raise ValueError("Recoverable narration intent is incomplete; refusing regeneration.")
        elif pending is not None:
            if (
                pending.get("transactionId") != transaction_id
                or pending.get("sourceSha256") != source_hash
                or pending.get("identity") != identity
            ):
                raise ValueError("Pending narration identity does not match this transaction; refusing regeneration.")
            candidate_path = Path(str(pending.get("candidatePath", "")))
            if not _coursecraft_pre_state_matches(fields, pending):
                pending["reconciliation"] = {
                    "decision": "blocked-coursecraft-mismatch",
                    "freshCourseCraft": {key: fields.get(key) for key in pending.get("courseCraftPreState", {})},
                    "candidate": _candidate_facts(candidate_path),
                }
                _atomic_write_json(pending_path, pending)
                raise ValueError("Fresh CourseCraft state changed since generation started; paid retry blocked.")
            external = reconcile_generation(pending, candidate_path)
            if not isinstance(external, dict):
                raise ValueError("ElevenLabs reconciliation adapter returned a non-object result.")
            pending["reconciliation"] = {
                "external": external,
                "freshCourseCraft": {key: fields.get(key) for key in pending.get("courseCraftPreState", {})},
                "candidate": _candidate_facts(candidate_path),
            }
            external_state = external.get("state")
            generation_metadata = external.get("generationMetadata")
            timeout_metadata = pending.get("timeoutFacts", {}).get("generationMetadata")
            if (
                candidate_path.is_file()
                and isinstance(timeout_metadata, dict)
                and all(timeout_metadata.get(key) not in (None, "") for key in ("request_id", "history_item_id", "character_count"))
            ):
                generation_metadata = timeout_metadata
                external_state = "completed"
                pending["reconciliation"]["decision"] = "adopt-complete-local-candidate"
            if (
                external_state == "completed"
                and isinstance(generation_metadata, dict)
                and _generation_identity_matches(pending, generation_metadata)
                and candidate_path.is_file()
            ):
                validation = _validate_candidate(
                    candidate_path, normalized_text, source_hash,
                    canonical_preview.get("cues") or [], identity, generation_metadata,
                )
                pending.update({"state": "validated", "generationMetadata": generation_metadata,
                                "validation": validation})
                _atomic_write_json(pending_path, pending)
            elif external_state == "not-completed-no-charge" and not candidate_path.is_file():
                if pending.get("state") in {"regeneration-started", "regeneration-timeout-unknown"}:
                    raise ValueError("Safe regeneration was already started once; another paid retry is blocked.")
                if pending.get("state") != "safe-to-regenerate":
                    pending["state"] = "safe-to-regenerate"
                    pending["reconciliation"]["decision"] = "one-retry-authorized"
                    _atomic_write_json(pending_path, pending)
                pending["state"] = "regeneration-started"
                _atomic_write_json(pending_path, pending)
                try:
                    generation_metadata = run_generation(
                        identity["voiceId"], spoken_text, candidate_path, model_id, output_format,
                        dictionary_locator, tuning["stability"], tuning["similarityBoost"],
                        tuning["style"], tuning["speakerBoost"], tuning["speed"],
                        timeout=GENERATION_TIMEOUT_SECONDS,
                    )
                except (subprocess.TimeoutExpired, TimeoutError) as error:
                    pending["state"] = "regeneration-timeout-unknown"
                    pending["timeoutFacts"] = _timeout_facts(error, candidate_path)
                    _atomic_write_json(pending_path, pending)
                    raise ValueError("Authorized regeneration timed out; all further paid retries are blocked.") from error
                if not isinstance(generation_metadata, dict):
                    raise ValueError("ElevenLabs generation metadata is not an object.")
                validation = _validate_candidate(
                    candidate_path, normalized_text, source_hash,
                    canonical_preview.get("cues") or [], identity, generation_metadata,
                )
                generated_this_call = True
                pending.update({"state": "validated", "generationMetadata": generation_metadata,
                                "validation": validation})
                _atomic_write_json(pending_path, pending)
            else:
                pending["state"] = "generation-reconciliation-blocked"
                pending["reconciliation"]["decision"] = "blocked-ambiguous-or-incomplete"
                _atomic_write_json(pending_path, pending)
                raise ValueError(
                    "ElevenLabs generation completion/charge state remains ambiguous; paid retry blocked with evidence: "
                    f"{pending_path}"
                )
        else:
            candidate_path = staging_dir / f"{record_id}-{transaction_hash}-{uuid.uuid4().hex}{suffix}"
            pending = {
                "schemaVersion": TRANSACTION_SCHEMA_VERSION, "state": "generation-started",
                "transactionId": transaction_id, "recordId": record_id,
                "candidatePath": str(candidate_path), "authoritativePath": str(authoritative_path),
                "sourceSha256": source_hash, "identity": identity,
                "courseCraftPreState": {
                    key: fields.get(key) for key in (*OWNED_UPDATE_FIELDS, RECORDED_FIELD)
                },
            }
            _atomic_write_json(pending_path, pending)
            try:
                generation_metadata = run_generation(
                    identity["voiceId"], spoken_text, candidate_path, model_id, output_format,
                    dictionary_locator, tuning["stability"], tuning["similarityBoost"],
                    tuning["style"], tuning["speakerBoost"], tuning["speed"],
                    timeout=GENERATION_TIMEOUT_SECONDS,
                )
            except (subprocess.TimeoutExpired, TimeoutError) as error:
                pending["state"] = "generation-timeout-unknown"
                pending["timeoutFacts"] = _timeout_facts(error, candidate_path)
                _atomic_write_json(pending_path, pending)
                raise ValueError(
                    f"ElevenLabs generation timed out with unknown write state; retry blocked. Reconciliation: {pending_path}"
                ) from error
            if not isinstance(generation_metadata, dict):
                raise ValueError("ElevenLabs generation metadata is not an object.")
            validation = _validate_candidate(
                candidate_path, normalized_text, source_hash, canonical_preview.get("cues") or [], identity,
                generation_metadata,
            )
            generated_this_call = True
            pending.update({"state": "validated", "generationMetadata": generation_metadata,
                            "validation": validation})
            _atomic_write_json(pending_path, pending)

        assert isinstance(validation, dict) and isinstance(generation_metadata, dict)
        output_hash = _required_string(validation, "outputSha256", "validated narration intent")
        if pending and pending.get("state") == "published":
            narration_binding = _verified_narration_provenance(folder, authoritative_path, output_hash)
        else:
            if not candidate_path.is_file() or _sha256_file(candidate_path) != output_hash:
                raise ValueError("Validated narration candidate is missing or changed; refusing regeneration.")
            publication = _publish_narration(folder, candidate_path, authoritative_path, output_hash)
            narration_binding = _verified_narration_provenance(folder, authoritative_path, output_hash)
            if _has_t04_provenance(folder) and narration_binding["output"] != publication:
                raise ValueError("Published narration output changed before manifest binding.")
            if not _has_t04_provenance(folder) and narration_binding != publication:
                raise ValueError("Published standalone narration binding changed before manifest binding.")
            pending.update({"state": "published", "narrationProvenance": narration_binding})
            _atomic_write_json(pending_path, pending)
        manifest = _publication_manifest(
            transaction_id=transaction_id, record_id=record_id,
            authoritative_path=authoritative_path, folder=folder,
            source_hash=source_hash, output_hash=output_hash, identity=identity,
            generation_metadata=generation_metadata, validation=validation,
            narration_binding=narration_binding,
        )
        _atomic_write_json(manifest_path, manifest)
        candidate_path.unlink(missing_ok=True)

    update_fields = _build_update_fields(
        transaction_id, source_hash, identity, generation_metadata
    )
    try:
        client.update_record("Demos", record_id, update_fields)
    except Exception as error:
        # The update may have persisted despite a transport timeout. Reconcile with
        # a fresh direct read before allowing any future retry.
        readback = client.get_record("Demos", record_id)
        readback_fields = _readback_fields(readback, record_id)
        if not _record_matches(readback_fields, update_fields):
            raise ValueError(
                "Narration registration failed or is in unknown state; the validated promoted take remains "
                f"unregistered at {authoritative_path}, and the prior CourseCraft fields were not replaced."
            ) from error
    else:
        # CourseCraftClient.get_record is the supported direct Airtable source path;
        # do not treat the mutation response as an uncached persistence readback.
        readback = client.get_record("Demos", record_id)
    readback_fields = _readback_fields(readback, record_id)
    if not _record_matches(readback_fields, update_fields):
        raise ValueError("Uncached narration registration readback did not match every owned field.")
    if RECORDED_FIELD in update_fields:
        raise AssertionError("Narration registration must never write Recorded.")
    if readback_fields.get(RECORDED_FIELD) != recorded_pre_state:
        raise ValueError("Uncached narration registration readback changed Recorded.")

    manifest = _read_manifest(manifest_path) or {}
    manifest["state"] = "registered"
    manifest["registeredAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest["courseCraftReadback"] = {key: readback_fields.get(key) for key in update_fields}
    _atomic_write_json(manifest_path, manifest)
    pending_path.unlink(missing_ok=True)
    return {
        "status": "generated" if generated_this_call else "registered-existing-promotion",
        "creditsSpent": generated_this_call,
        "recordId": record_id,
        "recordType": "demo",
        "transactionId": transaction_id,
        "authoritativePath": str(authoritative_path),
        "scriptNormalization": normalization_binding,
        "metadataPath": str(manifest_path),
        "sourceSha256": source_hash,
        "outputSha256": manifest["outputSha256"],
        "identity": identity,
        "validation": manifest["validation"],
        "derivedWavInput": manifest["derivedWavInput"],
        "courseCraftReadback": manifest["courseCraftReadback"],
    }
