"""Shared Airtable fields for generated voice recordings."""

VOICE_RECORDING_ID_FIELD = "Voice Recording ID"
VOICE_RECORDING_PATH_FIELD = "Voice Recording Path"
VOICE_SOURCE_HASH_FIELD = "Voice Source Hash"
ELEVENLABS_VOICE_ID_FIELD = "ElevenLabs Voice ID"
ELEVENLABS_MODEL_ID_FIELD = "ElevenLabs Model ID"
ELEVENLABS_OUTPUT_FORMAT_FIELD = "ElevenLabs Output Format"
ELEVENLABS_REQUEST_ID_FIELD = "ElevenLabs Request ID"
ELEVENLABS_HISTORY_ITEM_ID_FIELD = "ElevenLabs History Item ID"
VOICE_CHARACTER_COUNT_FIELD = "Voice Character Count"
VOICE_GENERATED_AT_FIELD = "Voice Generated At"
DICTATION_RECORDED_FIELD = "Dictation Recorded"


def get_voice_recording_invalidation_fields() -> dict:
    """Return fields that must be cleared when narration source text changes."""
    return {
        DICTATION_RECORDED_FIELD: False,
        VOICE_RECORDING_ID_FIELD: "",
        VOICE_RECORDING_PATH_FIELD: "",
        VOICE_SOURCE_HASH_FIELD: "",
        ELEVENLABS_VOICE_ID_FIELD: "",
        ELEVENLABS_MODEL_ID_FIELD: "",
        ELEVENLABS_OUTPUT_FORMAT_FIELD: "",
        ELEVENLABS_REQUEST_ID_FIELD: "",
        ELEVENLABS_HISTORY_ITEM_ID_FIELD: "",
        VOICE_CHARACTER_COUNT_FIELD: "",
        VOICE_GENERATED_AT_FIELD: "",
    }
