"""Field name mappings between CLI and Airtable."""

FIELD_MAPPINGS = {
    'Courses': {
        'name': 'Name',
        'status': 'Status',
        'active': 'Active',
        'course_id': 'Course ID',
        'target_length': 'Target Length (Min)',
        'learning_objectives': 'Learning Objectives',
        'short_description': 'Short Description',
        'long_description': 'Long Description',
        'content_level': 'Content Level',
        'job_role': 'Job Role',
        'learner_profile': 'Learner Profile',
        'prerequisites': '(Required) Learner Prerequisites',
        'storyline': 'Storyline',
        'notes': 'Notes',
        'content_tags': 'Content Tags',
        'platform_versions': 'Platform/Tools',
        'skill_path': 'Skill Path',
        'path_placement': 'Path Placement',
    },
    'Modules': {
        'name': 'Name',
        'status': 'Status',
        'order': 'Order',
        'course': 'Course Record ID',
        'target_length': 'Target Length (Min)',
        'learning_objectives': 'Learning Objectives',
        'description': 'Description',
    },
    'Clips': {
        'name': 'Name',
        'status': 'Status',
        'order': 'Order',
        'module': 'Module Record ID',
        'target_length': 'Target Length (Min)',
        'story': 'Story',
    },
    'Demos': {
        'name': 'Name',
        'status': 'Status',
        'clip': 'Clip Record ID',
        'idea': 'Idea',
        'action_summary': 'Action Summary',
        'script': 'Script',
        'demo_walkthrough_script_path': 'Demo Walkthrough Script Path',
        'demo_walkthrough_script_created': 'Demo Walkthrough Script Created',
        'voice_recording_id': 'Voice Recording ID',
        'dictation_recorded': 'Dictation Recorded',
        'voice_recording_path': 'Voice Recording Path',
        'voice_source_hash': 'Voice Source Hash',
        'elevenlabs_voice_id': 'ElevenLabs Voice ID',
        'elevenlabs_model_id': 'ElevenLabs Model ID',
        'elevenlabs_output_format': 'ElevenLabs Output Format',
        'elevenlabs_request_id': 'ElevenLabs Request ID',
        'elevenlabs_history_item_id': 'ElevenLabs History Item ID',
        'voice_character_count': 'Voice Character Count',
        'voice_generated_at': 'Voice Generated At',
    },
    'Slides': {
        'name': 'Name',
        'status': 'Status',
        'clip': 'Clip Record ID',
        'clip_order': 'Clip Order',
        'template': 'Template Record ID',
        'script': 'Script',
        'build_instructions': 'Build Instructions',
        'voice_recording_id': 'Voice Recording ID',
        'dictation_recorded': 'Dictation Recorded',
        'voice_recording_path': 'Voice Recording Path',
        'voice_source_hash': 'Voice Source Hash',
        'elevenlabs_voice_id': 'ElevenLabs Voice ID',
        'elevenlabs_model_id': 'ElevenLabs Model ID',
        'elevenlabs_output_format': 'ElevenLabs Output Format',
        'elevenlabs_request_id': 'ElevenLabs Request ID',
        'elevenlabs_history_item_id': 'ElevenLabs History Item ID',
        'voice_character_count': 'Voice Character Count',
        'voice_generated_at': 'Voice Generated At',
    },
    'Slide Templates': {
        'name': 'Name',
        'platform': 'Platform',
        'description': 'Description',
        'requirements': 'Requirements',
        'use_cases': 'Use Cases',
        'deck_number': 'Template Deck Number',
    },
}


def validate_field(field: str, table: str) -> str:
    """Validate CLI field name and return Airtable field name.

    Args:
        field: CLI field name (e.g., 'module')
        table: Table name (e.g., 'Clips')

    Returns:
        Airtable field name (e.g., 'Module Record ID')

    Raises:
        ValueError: If field not found in mapping
    """
    if table not in FIELD_MAPPINGS:
        raise ValueError(f"Unknown table: {table}")

    if field not in FIELD_MAPPINGS[table]:
        valid_fields = ', '.join(FIELD_MAPPINGS[table].keys())
        raise ValueError(f"Unknown field '{field}' for table {table}. Valid fields: {valid_fields}")

    return FIELD_MAPPINGS[table][field]
