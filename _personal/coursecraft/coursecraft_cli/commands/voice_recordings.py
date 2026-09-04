"""Voice recording command module."""
import json
import math
import re
import subprocess
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Optional

import typer

from cli_tools_shared.output import command
from ..client import ClientError, get_client
from ..coursecraft_project import (
    coursecraft_project_root,
    load_coursecraft_module,
    resolve_course_folder,
)
from ..narration_transaction import (
    _run_json,
    generate_authoritative_demo_narration,
    load_production_config,
    validate_manual_narration_take,
)
from ..output import print_error, print_json

app = typer.Typer(help="Generate demo voice recordings")

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
# ElevenLabs `pronunciation-dictionaries list` caps --limit at 100 and returns a
# flat JSON array (it flattens pagination internally), so a single max-limit
# request returns every dictionary for this account.
ELEVENLABS_DICTIONARY_LIMIT = "100"
NARRATION_WORDS_PER_MINUTE = 180
CANONICAL_SCRIPT_CONTRACT_RELATIVE_PATH = Path(
    ".agents/skills/demo/artifacts/script/tools/script_contract.py"
)
CANONICAL_STATE_WINDOWS_RELATIVE_PATH = Path(
    ".agents/skills/demo/artifacts/script/tools/state_windows.py"
)


@lru_cache(maxsize=1)
def _load_canonical_script_contract():
    """Load CourseCraft's sole Script-owned parser/normalizer/anchor producer."""
    return load_coursecraft_module(
        CANONICAL_SCRIPT_CONTRACT_RELATIVE_PATH,
        "coursecraft_canonical_demo_script_contract",
    )


@lru_cache(maxsize=1)
def _load_canonical_state_windows():
    """Load CourseCraft's sole Script-to-walk cue parity implementation."""
    return load_coursecraft_module(
        CANONICAL_STATE_WINDOWS_RELATIVE_PATH,
        "coursecraft_canonical_demo_state_windows",
    )


def _canonical_demo_preview(script: str, max_total_words: Optional[int] = None) -> tuple[object, dict]:
    contract = _load_canonical_script_contract()
    parsed = contract.parse_script(script, max_total_words=max_total_words)
    return parsed, parsed.preview()


def _resolve_demo_narration_contract(fields: dict) -> tuple[object, dict]:
    """Resolve the record-owned budget and run the canonical Script contract."""
    script = fields.get("Script")
    if not isinstance(script, str) or not script.strip():
        raise ValueError("Demo has no Script to preview or record.")

    raw_target_minutes = fields.get("Target Length (Min)")
    if isinstance(raw_target_minutes, bool) or not isinstance(
        raw_target_minutes, (int, float, str)
    ):
        raise ValueError("Demo Target Length (Min) must be one positive number.")
    try:
        target_minutes = float(raw_target_minutes)
    except (TypeError, ValueError):
        raise ValueError("Demo Target Length (Min) must be one positive number.") from None
    if not math.isfinite(target_minutes) or target_minutes <= 0:
        raise ValueError("Demo Target Length (Min) must be one positive number.")

    max_total_words = round(target_minutes * NARRATION_WORDS_PER_MINUTE)
    parsed, preview = _canonical_demo_preview(script, max_total_words=max_total_words)
    preview["narrationBudget"] = {
        "sourceField": "Target Length (Min)",
        "targetLengthMinutes": target_minutes,
        "wordsPerMinute": NARRATION_WORDS_PER_MINUTE,
        "maxTotalWords": max_total_words,
    }
    return parsed, preview


def validate_manual_demo_narration(
    fields: dict,
    script: str,
    take_path: Path,
) -> dict:
    """Prove a manual take speaks a candidate demo Script before its write.

    ``take_path`` is derived by the caller from Folder Root; a demo never stores it.
    """
    candidate_fields = dict(fields)
    candidate_fields["Script"] = script
    _, preview = _resolve_demo_narration_contract(candidate_fields)
    return validate_manual_narration_take(
        take_path,
        preview["normalizedNarration"],
        preview.get("cues") or [],
    )


def _resolve_demo_manifest(fields: dict, explicit_manifest: Optional[Path] = None) -> Path:
    if explicit_manifest is not None:
        return explicit_manifest.expanduser().resolve()
    folder_root = fields.get("Folder Root")
    if not isinstance(folder_root, str) or not folder_root.strip():
        raise ValueError("Demo is missing Folder Root; cannot locate walkthrough.json.")
    return resolve_course_folder(folder_root) / "walkthrough.json"


def _validate_manifest_anchors(manifest_path: Path, parsed: object) -> dict:
    result = {
        "valid": False,
        "manifestPath": str(manifest_path),
        "errors": [],
        "anchors": [],
    }
    if not manifest_path.is_file():
        result["errors"].append(f"Manifest not found: {manifest_path}")
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        step_cues = _load_canonical_state_windows()._step_cues(parsed, manifest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        result["errors"].append(str(error))
        return result
    result["anchors"] = [
        {
            "stepOrder": step_order,
            "scriptCueOrder": cue_index + 1,
            "scriptCue": parsed.cues[cue_index].text,
        }
        for step_order, cue_index in sorted(step_cues.items())
    ]
    result["valid"] = True
    return result


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


def _run_elevenlabs_json(args: list[str], expected_type: type):
    return _run_json(
        args,
        timeout=None,
        expected_type=expected_type,
        context="ElevenLabs command",
    )


def _get_required_elevenlabs_string(payload: dict, field_name: str, context: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ElevenLabs {context} response is missing {field_name}.")
    return value


def _list_pronunciation_dictionaries() -> list[dict]:
    payload = _run_elevenlabs_json([
        "elevenlabs",
        "pronunciation-dictionaries",
        "list",
        "--limit",
        ELEVENLABS_DICTIONARY_LIMIT,
    ], list)
    dictionaries = []
    for dictionary in payload:
        if not isinstance(dictionary, dict):
            raise ValueError("ElevenLabs pronunciation dictionary list response contains a non-object dictionary.")
        dictionaries.append(dictionary)
    return dictionaries


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
        created_dictionary = _run_elevenlabs_json(create_args, dict)
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
    ], dict)
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
    updated_dictionary = _run_elevenlabs_json(set_rules_args, dict)
    updated_dictionary_id = _get_required_elevenlabs_string(updated_dictionary, "id", "set-rules")
    if updated_dictionary_id != dictionary_id:
        raise ValueError(f"ElevenLabs set-rules returned unexpected dictionary ID: {updated_dictionary_id}")
    updated_version_id = _get_required_elevenlabs_string(updated_dictionary, "version_id", "set-rules")
    return f"{dictionary_id}:{updated_version_id}"


def _load_demo(client, record_id: str) -> dict:
    record = client.get_record("Demos", record_id)
    if not record:
        raise ValueError(f"Demo not found: {record_id}")
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
    *,
    timeout: int,
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
    metadata = _run_json(args, timeout=timeout)
    if not isinstance(metadata, dict):
        raise ValueError("ElevenLabs speech create returned non-object JSON.")
    if not output_path.exists():
        raise ValueError(f"ElevenLabs did not create output file: {output_path}")
    if output_path.stat().st_size == 0:
        raise ValueError(f"ElevenLabs created an empty output file: {output_path}")
    if metadata.get("character_count") in (None, ""):
        metadata["character_count"] = len(spoken_text)
        metadata["character_count_provenance"] = "submitted_spoken_text_length"
    if metadata.get("output_path") in (None, ""):
        metadata["output_path"] = str(output_path)
    return metadata


@app.command("preview")
@command
def preview_demo_narration(
    demo: str = typer.Option(..., "--demo", help="Demo record ID"),
    manifest: Optional[Path] = typer.Option(
        None,
        "--manifest",
        help="Walkthrough manifest path (defaults to <Folder Root>/walkthrough.json)",
    ),
):
    """Preview normalized demo narration and validate Script cues/manifest anchors without mutation."""
    try:
        record = _load_demo(get_client(), demo)
        fields = record.get("fields", {})
        parsed, preview = _resolve_demo_narration_contract(fields)
        preview["cueValidation"] = {
            "valid": True,
            "cueCount": len(preview["cues"]),
            "errors": [],
        }
        manifest_path = _resolve_demo_manifest(fields, manifest)
        preview["anchorValidation"] = _validate_manifest_anchors(manifest_path, parsed)
        preview.update(
            {
                "recordId": demo,
                "recordType": "demo",
                "readOnly": True,
                "valid": (
                    preview["cueValidation"]["valid"]
                    and preview["anchorValidation"]["valid"]
                ),
            }
        )
        print_json(preview)
        if not preview["valid"]:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except (ClientError, ValueError, OSError, json.JSONDecodeError, KeyError) as error:
        print_error(str(error))
        raise typer.Exit(1)


@app.command("generate")
@command
def generate_voice_recording(
    demo: str = typer.Option(..., "--demo", help="Demo record ID"),
):
    """Generate the authoritative narration take for one demo Script.

    Voice, model, output format, tuning, and output location all come from the
    CourseCraft production narration contract; the command takes no overrides.
    """
    try:
        client = get_client()
        record = _load_demo(client, demo)
        fields = record.get("fields", {})
        script = fields.get("Script")
        if not script:
            raise ValueError(f"Demo has no Script to record: {demo}")

        parsed, canonical_preview = _resolve_demo_narration_contract(fields)
        normalized_source_text = canonical_preview["normalizedNarration"]
        execution_method = fields.get("Execution Method")
        if execution_method in ("Automated Walkthrough", "Manual Step-Through"):
            anchor_validation = _validate_manifest_anchors(
                _resolve_demo_manifest(fields),
                parsed,
            )
            if not anchor_validation["valid"]:
                raise ValueError(
                    f"{execution_method} narration generation blocked: run "
                    f"coursecraft voice-recordings preview --demo {demo} and resolve cue/anchor validation."
                )
        spoken_text = re.sub(
            r"\s+", " ", _apply_pronunciation_patterns(normalized_source_text)
        ).strip()
        production_config = load_production_config(coursecraft_project_root())
        pronunciation_dictionary_locator = _sync_pronunciation_dictionary()
        result = generate_authoritative_demo_narration(
            client=client,
            record=record,
            record_id=demo,
            normalized_text=normalized_source_text,
            canonical_preview=canonical_preview,
            spoken_text=spoken_text,
            production_config=production_config,
            dictionary_locator=pronunciation_dictionary_locator,
            run_generation=_run_elevenlabs,
        )
        print_json(result)

    except subprocess.CalledProcessError as e:
        print_error(e.stderr.strip())
        raise typer.Exit(1)
    except (ClientError, ValueError, json.JSONDecodeError, KeyError) as e:
        print_error(str(e))
        raise typer.Exit(1)


COMMAND_CREDENTIALS = {
    "preview": [
        "custom"
    ],
    "generate": [
        "custom"
    ]
}
