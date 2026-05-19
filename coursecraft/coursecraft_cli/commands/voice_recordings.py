"""Voice recording command module."""
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Optional

import typer

from ..client import ClientError, get_client
from ..output import print_error, print_json, print_success
from ..voice_recording_fields import (
    DICTATION_RECORDED_FIELD,
    ELEVENLABS_HISTORY_ITEM_ID_FIELD,
    ELEVENLABS_MODEL_ID_FIELD,
    ELEVENLABS_OUTPUT_FORMAT_FIELD,
    ELEVENLABS_REQUEST_ID_FIELD,
    ELEVENLABS_VOICE_ID_FIELD,
    VOICE_CHARACTER_COUNT_FIELD,
    VOICE_GENERATED_AT_FIELD,
    VOICE_RECORDING_ID_FIELD,
    VOICE_RECORDING_PATH_FIELD,
    VOICE_SOURCE_HASH_FIELD,
)

app = typer.Typer(help="Generate voice recordings for slides and demos")

ALLOWED_PATTERN_TRANSFORMS = {
    "dotted_identifier",
    "file_name",
    "literal",
    "powershell_command",
    "powershell_parameter",
    "powershell_variable",
    "windows_path",
}
PRONUNCIATION_DICTIONARY_NAME = "CourseCraft Voice Pronunciations"
ELEVENLABS_DICTIONARY_PAGE_SIZE = "100"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"


@app.callback()
def voice_recordings():
    """Generate voice recordings for slides and demos."""


def _strip_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return text


def _is_demo_cue_line(line: str) -> bool:
    normalized = _strip_markdown(line).strip()
    return re.match(
        r"^[^A-Za-z0-9]*(DEMO GOAL|ACTION|CALLOUT|EXPECTED|VISUAL|SCREEN|SETUP):",
        normalized,
        flags=re.IGNORECASE,
    ) is not None


@lru_cache(maxsize=1)
def _load_pronunciation_rules() -> tuple[dict[str, str], ...]:
    pronunciation_path = resources.files("coursecraft_cli").joinpath("voice_pronunciations.json")
    with pronunciation_path.open("r", encoding="utf-8") as pronunciation_file:
        rules = json.load(pronunciation_file)
    if not isinstance(rules, list):
        raise ValueError("Voice pronunciation dictionary rules must be a list.")

    normalized_rules = []
    seen_terms = set()
    for rule in rules:
        normalized_rule = _normalize_pronunciation_rule(rule, "packaged voice pronunciation dictionary")
        string_to_replace = normalized_rule["string_to_replace"]
        if "=" in string_to_replace:
            raise ValueError(f"Voice pronunciation dictionary rule cannot contain '=': {string_to_replace}")
        if string_to_replace in seen_terms:
            raise ValueError(f"Duplicate voice pronunciation dictionary rule: {string_to_replace}")
        seen_terms.add(string_to_replace)
        normalized_rules.append(normalized_rule)

    normalized_rules.sort(key=lambda item: len(item["string_to_replace"]), reverse=True)
    return tuple(normalized_rules)


@lru_cache(maxsize=1)
def _load_pronunciation_patterns() -> tuple[dict[str, str], ...]:
    patterns_path = resources.files("coursecraft_cli").joinpath("voice_pronunciation_patterns.json")
    with patterns_path.open("r", encoding="utf-8") as patterns_file:
        patterns = json.load(patterns_file)
    if not isinstance(patterns, list):
        raise ValueError("Voice pronunciation patterns must be a list.")

    normalized_patterns = []
    seen_names = set()
    for pattern in patterns:
        if not isinstance(pattern, dict):
            raise ValueError("Voice pronunciation pattern entries must be objects.")
        name = pattern.get("name")
        regex = pattern.get("pattern")
        transform = pattern.get("transform")
        spoken = pattern.get("spoken")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Voice pronunciation pattern entry is missing a name.")
        if name in seen_names:
            raise ValueError(f"Duplicate voice pronunciation pattern name: {name}")
        if not isinstance(regex, str) or not regex.strip():
            raise ValueError(f"Voice pronunciation pattern entry is missing a regex: {name}")
        if not isinstance(transform, str) or transform not in ALLOWED_PATTERN_TRANSFORMS:
            raise ValueError(f"Voice pronunciation pattern has unsupported transform: {name}")
        if transform == "literal" and (not isinstance(spoken, str) or not spoken.strip()):
            raise ValueError(f"Literal voice pronunciation pattern is missing spoken text: {name}")
        re.compile(regex)
        seen_names.add(name)
        normalized_pattern = {"name": name, "pattern": regex, "transform": transform}
        if isinstance(spoken, str):
            normalized_pattern["spoken"] = spoken
        normalized_patterns.append(normalized_pattern)
    return tuple(normalized_patterns)


@lru_cache(maxsize=1)
def _load_pronunciation_tokens() -> dict[str, dict[str, str]]:
    tokens_path = resources.files("coursecraft_cli").joinpath("voice_pronunciation_tokens.json")
    with tokens_path.open("r", encoding="utf-8") as tokens_file:
        tokens = json.load(tokens_file)
    if not isinstance(tokens, dict):
        raise ValueError("Voice pronunciation tokens must be an object.")

    normalized_tokens = {}
    for section_name in ["identifier_tokens", "file_extensions"]:
        section = tokens.get(section_name)
        if not isinstance(section, dict):
            raise ValueError(f"Voice pronunciation token section must be an object: {section_name}")
        normalized_section = {}
        for token, spoken in section.items():
            if not isinstance(token, str) or not token.strip():
                raise ValueError(f"Voice pronunciation token section has an invalid key: {section_name}")
            if not isinstance(spoken, str) or not spoken.strip():
                raise ValueError(f"Voice pronunciation token has invalid spoken text: {section_name}.{token}")
            normalized_section[token] = spoken
        normalized_tokens[section_name] = normalized_section
    return normalized_tokens


def _split_identifier(identifier: str) -> str:
    identifier_tokens = _load_pronunciation_tokens()["identifier_tokens"]
    identifier_parts = []
    for part in re.split(r"([._:-])", identifier):
        if part == ".":
            identifier_parts.append("dot")
        elif part == ":":
            identifier_parts.append("colon")
        elif part in {"_", "-"}:
            identifier_parts.append(" ")
        elif part:
            tokens = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+|[A-Z]+", part)
            identifier_parts.extend(identifier_tokens.get(token, token) for token in tokens)
    return re.sub(r"\s+", " ", " ".join(identifier_parts)).strip()


def _transform_file_name(file_name: str) -> str:
    stem, extension = file_name.rsplit(".", 1)
    spoken_extension = _load_pronunciation_tokens()["file_extensions"].get(extension.lower())
    if spoken_extension is None:
        raise ValueError(f"Unsupported voice pronunciation file extension: {extension}")
    return f"{_split_identifier(stem)} dot {spoken_extension}"


def _transform_windows_path(path: str) -> str:
    drive = path[:1]
    path_body = path[3:] if path.startswith(f"{drive}:\\") else path
    spoken_parts = [f"{drive.upper()} colon"]
    for component in path_body.split("\\"):
        if not component:
            continue
        spoken_parts.append("backslash")
        if re.search(r"\.[A-Za-z0-9]+$", component):
            spoken_parts.append(_transform_file_name(component))
        else:
            spoken_parts.append(_split_identifier(component))
    return " ".join(spoken_parts)


def _transform_pronunciation_pattern(match: re.Match, pattern: dict[str, str]) -> str:
    matched_text = match.group(0)
    transform = pattern["transform"]
    if transform == "literal":
        return f" {pattern['spoken']} "
    if transform == "powershell_command":
        return _split_identifier(matched_text.replace("-", " "))
    if transform == "powershell_parameter":
        return f"dash {_split_identifier(matched_text[1:])}"
    if transform == "powershell_variable":
        if matched_text == "$_":
            return "dollar underscore"
        return f"dollar {_split_identifier(matched_text[1:])}"
    if transform == "dotted_identifier":
        return _split_identifier(matched_text)
    if transform == "file_name":
        return _transform_file_name(matched_text)
    if transform == "windows_path":
        return _transform_windows_path(matched_text)
    raise ValueError(f"Unsupported voice pronunciation transform: {transform}")


def _apply_pronunciation_patterns(text: str) -> str:
    spoken_text = text
    for pattern in _load_pronunciation_patterns():
        regex = re.compile(pattern["pattern"])
        spoken_text = regex.sub(lambda match: _transform_pronunciation_pattern(match, pattern), spoken_text)
    return spoken_text


def _normalize_pronunciation_rule(rule: dict, context: str) -> dict[str, str]:
    if not isinstance(rule, dict):
        raise ValueError(f"Voice pronunciation dictionary rule must be an object: {context}")
    string_to_replace = rule.get("string_to_replace")
    rule_type = rule.get("type")
    alias = rule.get("alias")
    if not isinstance(string_to_replace, str) or not string_to_replace.strip():
        raise ValueError(f"Voice pronunciation dictionary rule is missing string_to_replace: {context}")
    if rule_type != "alias":
        raise ValueError(f"Unsupported voice pronunciation dictionary rule type: {rule_type}")
    if not isinstance(alias, str) or not alias.strip():
        raise ValueError(f"Voice pronunciation dictionary rule is missing alias: {string_to_replace}")
    return {"string_to_replace": string_to_replace, "type": "alias", "alias": alias}


def _canonical_pronunciation_rules(rules, context: str) -> tuple[dict[str, str], ...]:
    normalized_rules = [_normalize_pronunciation_rule(rule, context) for rule in rules]
    normalized_rules.sort(key=lambda item: (item["string_to_replace"], item["type"], item["alias"]))
    return tuple(normalized_rules)


def _alias_rule_argument(rule: dict[str, str]) -> str:
    return f"{rule['string_to_replace']}={rule['alias']}"


def _extend_pronunciation_rule_args(args: list[str], rules: tuple[dict[str, str], ...]) -> None:
    for rule in rules:
        args.extend(["--alias-rule", _alias_rule_argument(rule)])


def _run_elevenlabs_json(args: list[str]) -> dict:
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout.strip())
    if not isinstance(payload, dict):
        raise ValueError(f"ElevenLabs command returned non-object JSON: {' '.join(args[:3])}")
    return payload


def _get_required_elevenlabs_string(payload: dict, field_name: str, context: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ElevenLabs {context} response is missing {field_name}.")
    return value


def _list_pronunciation_dictionaries() -> list[dict]:
    dictionaries = []
    cursor = None
    while True:
        args = [
            "elevenlabs",
            "pronunciation-dictionaries",
            "list",
            "--page-size",
            ELEVENLABS_DICTIONARY_PAGE_SIZE,
        ]
        if cursor is not None:
            args.extend(["--cursor", cursor])
        payload = _run_elevenlabs_json(args)
        page_dictionaries = payload.get("pronunciation_dictionaries")
        if not isinstance(page_dictionaries, list):
            raise ValueError("ElevenLabs pronunciation dictionary list response is missing pronunciation_dictionaries.")
        for dictionary in page_dictionaries:
            if not isinstance(dictionary, dict):
                raise ValueError("ElevenLabs pronunciation dictionary list response contains a non-object dictionary.")
            dictionaries.append(dictionary)
        has_more = payload.get("has_more")
        if not isinstance(has_more, bool):
            raise ValueError("ElevenLabs pronunciation dictionary list response is missing has_more.")
        if not has_more:
            return dictionaries
        next_cursor = payload.get("next_cursor")
        if not isinstance(next_cursor, str) or not next_cursor.strip():
            raise ValueError("ElevenLabs dictionary list has_more=true but next_cursor is empty.")
        cursor = next_cursor


def _sync_pronunciation_dictionary() -> str:
    packaged_rules = _load_pronunciation_rules()
    dictionaries = _list_pronunciation_dictionaries()
    matches = [
        dictionary
        for dictionary in dictionaries
        if dictionary.get("name") == PRONUNCIATION_DICTIONARY_NAME
    ]
    if len(matches) > 1:
        raise ValueError(
            f"Expected exactly one pronunciation dictionary named {PRONUNCIATION_DICTIONARY_NAME}, got {len(matches)}"
        )

    if not matches:
        create_args = [
            "elevenlabs",
            "pronunciation-dictionaries",
            "create-from-rules",
            "--name",
            PRONUNCIATION_DICTIONARY_NAME,
        ]
        _extend_pronunciation_rule_args(create_args, packaged_rules)
        created_dictionary = _run_elevenlabs_json(create_args)
        dictionary_id = _get_required_elevenlabs_string(created_dictionary, "id", "create-from-rules")
        version_id = _get_required_elevenlabs_string(created_dictionary, "version_id", "create-from-rules")
        return f"{dictionary_id}:{version_id}"

    dictionary = matches[0]
    dictionary_id = _get_required_elevenlabs_string(dictionary, "id", "list")
    current_dictionary = _run_elevenlabs_json([
        "elevenlabs",
        "pronunciation-dictionaries",
        "get",
        dictionary_id,
    ])
    current_version_id = _get_required_elevenlabs_string(current_dictionary, "latest_version_id", "get")
    current_rules = current_dictionary.get("rules")
    if not isinstance(current_rules, list):
        raise ValueError("ElevenLabs pronunciation dictionary get response is missing rules.")

    if _canonical_pronunciation_rules(current_rules, "ElevenLabs pronunciation dictionary") == _canonical_pronunciation_rules(
        packaged_rules,
        "packaged voice pronunciation dictionary",
    ):
        return f"{dictionary_id}:{current_version_id}"

    set_rules_args = [
        "elevenlabs",
        "pronunciation-dictionaries",
        "set-rules",
        dictionary_id,
    ]
    _extend_pronunciation_rule_args(set_rules_args, packaged_rules)
    updated_dictionary = _run_elevenlabs_json(set_rules_args)
    updated_dictionary_id = _get_required_elevenlabs_string(updated_dictionary, "id", "set-rules")
    if updated_dictionary_id != dictionary_id:
        raise ValueError(f"ElevenLabs set-rules returned unexpected dictionary ID: {updated_dictionary_id}")
    updated_version_id = _get_required_elevenlabs_string(updated_dictionary, "version_id", "set-rules")
    return f"{dictionary_id}:{updated_version_id}"


def _to_spoken_text(script: str, record_type: str) -> str:
    if record_type not in {"slide", "demo"}:
        raise ValueError(f"Unsupported record type: {record_type}")

    lines = []
    for line in script.splitlines():
        if record_type == "demo" and _is_demo_cue_line(line):
            continue
        stripped = _strip_markdown(line).strip()
        if stripped:
            lines.append(stripped)
    spoken_text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if not spoken_text:
        raise ValueError("Script has no speakable narration text.")
    return re.sub(r"\s+", " ", _apply_pronunciation_patterns(spoken_text)).strip()


def _load_record(client, record_type: str, record_id: str) -> dict:
    table_name = "Slides" if record_type == "slide" else "Demos"
    record = client.get_record(table_name, record_id)
    if not record:
        raise ValueError(f"{record_type.title()} not found: {record_id}")
    return record


def _run_elevenlabs(
    voice_id: str,
    spoken_text: str,
    output_path: Path,
    model_id: str,
    output_format: str,
    pronunciation_dictionary_locator: str,
    stability: Optional[float],
    similarity_boost: Optional[float],
    style: Optional[float],
    speaker_boost: Optional[bool],
    speed: Optional[float],
) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "elevenlabs",
        "speech",
        "create",
        voice_id,
        spoken_text,
        "--output",
        str(output_path),
        "--model-id",
        model_id,
        "--output-format",
        output_format,
        "--pronunciation-dictionary",
        pronunciation_dictionary_locator,
    ]
    if stability is not None:
        args.extend(["--stability", str(stability)])
    if similarity_boost is not None:
        args.extend(["--similarity-boost", str(similarity_boost)])
    if style is not None:
        args.extend(["--style", str(style)])
    if speaker_boost is not None:
        args.append("--speaker-boost" if speaker_boost else "--no-speaker-boost")
    if speed is not None:
        args.extend(["--speed", str(speed)])
    metadata = _run_elevenlabs_json(args)
    if not output_path.exists():
        raise ValueError(f"ElevenLabs did not create output file: {output_path}")
    if output_path.stat().st_size == 0:
        raise ValueError(f"ElevenLabs created an empty output file: {output_path}")
    return metadata


def _get_required_field(fields: dict, field_name: str):
    if field_name not in fields:
        raise ValueError(f"Slide is missing required field: {field_name}")
    return fields[field_name]


def _get_single_linked_value(fields: dict, field_name: str):
    value = _get_required_field(fields, field_name)
    if not isinstance(value, list) or len(value) != 1:
        raise ValueError(f"Slide field must contain exactly one value: {field_name}")
    return value[0]


def _build_output_path(record_type: str, record: dict, output_dir: Path, table_name: str, record_id: str) -> Path:
    if record_type == "demo":
        return output_dir / f"{table_name.lower()}" / f"{record_id}.mp3"

    fields = record.get("fields", {})
    module_number = _get_single_linked_value(fields, "Module Number")
    slide_number = _get_required_field(fields, "Clip Order")
    slide_title = _get_required_field(fields, "Name")
    if not isinstance(module_number, int):
        raise ValueError("Slide Module Number must be an integer.")
    if not isinstance(slide_number, int):
        raise ValueError("Slide Clip Order must be an integer.")
    if not isinstance(slide_title, str) or not slide_title.strip():
        raise ValueError("Slide Name must be a non-empty string.")
    if "/" in slide_title:
        raise ValueError("Slide Name cannot contain '/'.")
    return output_dir / f"m{module_number}" / "slides" / f"{slide_number} - {slide_title}.mp3"


def _build_update_fields(
    record_type: str,
    record_id: str,
    output_path: Path,
    voice_id: str,
    model_id: str,
    output_format: str,
    pronunciation_dictionary_locator: str,
    spoken_text: str,
    stability: Optional[float],
    similarity_boost: Optional[float],
    style: Optional[float],
    speaker_boost: Optional[bool],
    speed: Optional[float],
    metadata: dict,
) -> dict:
    source_hash = hashlib.sha256(spoken_text.encode("utf-8")).hexdigest()
    recording_payload = {
        "model_id": model_id,
        "output_format": output_format,
        "pronunciation_dictionary_locator": pronunciation_dictionary_locator,
        "similarity_boost": similarity_boost,
        "speaker_boost": speaker_boost,
        "speed": speed,
        "spoken_text": spoken_text,
        "stability": stability,
        "style": style,
        "voice_id": voice_id,
    }
    recording_hash = hashlib.sha256(
        json.dumps(recording_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    update_fields = {
        VOICE_RECORDING_ID_FIELD: f"coursecraft:{record_type}:{record_id}:{recording_hash}",
        VOICE_RECORDING_PATH_FIELD: str(output_path),
        VOICE_SOURCE_HASH_FIELD: source_hash,
        ELEVENLABS_VOICE_ID_FIELD: voice_id,
        ELEVENLABS_MODEL_ID_FIELD: model_id,
        ELEVENLABS_OUTPUT_FORMAT_FIELD: output_format,
        ELEVENLABS_REQUEST_ID_FIELD: metadata["request_id"],
        ELEVENLABS_HISTORY_ITEM_ID_FIELD: metadata["history_item_id"],
        VOICE_CHARACTER_COUNT_FIELD: metadata["character_count"],
        VOICE_GENERATED_AT_FIELD: datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    update_fields[DICTATION_RECORDED_FIELD] = True
    return update_fields


@app.command("generate")
def generate_voice_recording(
    slide: Optional[str] = typer.Option(None, "--slide", help="Slide record ID"),
    demo: Optional[str] = typer.Option(None, "--demo", help="Demo record ID"),
    voice_id: str = typer.Option(..., "--voice-id", help="ElevenLabs voice ID"),
    model_id: str = typer.Option(
        DEFAULT_MODEL_ID,
        "--model-id",
        help="ElevenLabs model ID. Defaults to eleven_multilingual_v2 because Eleven v3 does not currently support PVCs.",
    ),
    output_format: str = typer.Option(..., "--output-format", help="ElevenLabs output format"),
    output_dir: Path = typer.Option(..., "--output-dir", help="Directory for generated audio files"),
    stability: Optional[float] = typer.Option(None, "--stability", min=0, max=1, help="ElevenLabs voice stability"),
    similarity_boost: Optional[float] = typer.Option(None, "--similarity-boost", min=0, max=1, help="ElevenLabs similarity boost"),
    style: Optional[float] = typer.Option(None, "--style", min=0, max=1, help="ElevenLabs style exaggeration"),
    speaker_boost: Optional[bool] = typer.Option(None, "--speaker-boost/--no-speaker-boost", help="ElevenLabs speaker boost"),
    speed: Optional[float] = typer.Option(None, "--speed", min=0.7, max=1.2, help="ElevenLabs voice speed"),
):
    """Generate a voice recording for one slide or demo script."""
    try:
        if (slide is None and demo is None) or (slide is not None and demo is not None):
            print_error("Provide exactly one of --slide or --demo.")
            raise typer.Exit(1)

        record_type = "slide" if slide is not None else "demo"
        record_id = slide if slide is not None else demo
        if record_id is None:
            raise ValueError("Missing record ID.")

        client = get_client()
        table_name = "Slides" if record_type == "slide" else "Demos"
        record = _load_record(client, record_type, record_id)
        script = record.get("fields", {}).get("Script")
        if not script:
            raise ValueError(f"{record_type.title()} has no Script to record: {record_id}")

        spoken_text = _to_spoken_text(script, record_type)
        output_path = _build_output_path(record_type, record, output_dir, table_name, record_id)
        pronunciation_dictionary_locator = _sync_pronunciation_dictionary()
        metadata = _run_elevenlabs(
            voice_id,
            spoken_text,
            output_path,
            model_id,
            output_format,
            pronunciation_dictionary_locator,
            stability,
            similarity_boost,
            style,
            speaker_boost,
            speed,
        )
        update_fields = _build_update_fields(
            record_type,
            record_id,
            output_path,
            voice_id,
            model_id,
            output_format,
            pronunciation_dictionary_locator,
            spoken_text,
            stability,
            similarity_boost,
            style,
            speaker_boost,
            speed,
            metadata,
        )
        client.update_record(table_name, record_id, update_fields)
        print_success(f"Generated voice recording for {record_type}: {record_id}")
        print_json({"record_id": record_id, "record_type": record_type, "output_path": str(output_path)})

    except subprocess.CalledProcessError as e:
        print_error(e.stderr.strip())
        raise typer.Exit(1)
    except (ClientError, ValueError, json.JSONDecodeError, KeyError) as e:
        print_error(str(e))
        raise typer.Exit(1)


COMMAND_CREDENTIALS = {
    "generate": [
        "custom"
    ]
}
