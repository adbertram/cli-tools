"""Field name mappings between CLI options and Airtable fields."""

from typing import Any, Dict, Mapping

FIELD_MAPPINGS = {
    'Courses': {
        'name': 'Name',
        'status': 'Status',
        'active': 'Active',
        'course_id': 'Course ID',
        'target_length': 'Target Length (Min)',
        'deadline': 'Deadline',
        'learning_objectives': 'Learning Objectives',
        'short_description': 'Short Description',
        'long_description': 'Long Description',
        'content_level': 'Content Level',
        'job_role': 'Job Role',
        'learner_profile': 'Learner Profile',
        'prerequisites': '(Required) Learner Prerequisites',
        'storyline': 'Storyline',
        'notes': 'Notes',
        'disabled': 'Disabled',
        'disabled_notes': 'Disabled Notes',
        'content_tags': 'Content Tags',
        'platform_versions': 'Platform/Tools',
        'skill_path': 'Skill Path',
        'path_placement': 'Path Placement',
        'powerpoint_slide_deck_version': 'PowerPoint Slide Deck Version',
        'research_report': 'Research Report',
        'course_requirements': 'Course Requirements',
        'course_requirements_link': 'Course Requirements Link',
        'course_requirements_review_ai': 'Course Requirements Review (AI)',
        'learning_objectives_override_state': 'Learning Objectives Override State',
        'learning_objectives_override_audit': 'Learning Objectives Override Audit',
        'course_outline_review_state': 'Course Outline Review State',
        'course_outline_submitted_revision': 'Course Outline Submitted Revision',
        'outline_draft': 'Outline Draft',
        'outline_draft_review_ai': 'Outline Draft Review (AI)',
        'outline_draft_human_verified': 'Outline Draft Human Verified',
        'outline_submitted_at': 'Course Outline Submitted Date',
        'feedback_sheet_id': 'Feedback Sheet ID',
        'feedback_requested': 'Feedback Requested',
        'feedback_requested_at': 'Feedback Requested At',
        'version_control': 'Version Control',
        'version': 'Version',
        'base_course': 'Base Course',
        'prior_course_inventory': 'Prior Course Inventory',
        'gap_analysis': 'Gap Analysis',
        'carry_forward_plan': 'Carry-Forward Plan',
        'carry_forward_plan_human_verified': 'Carry-Forward Plan Human Verified',
    },
    'Modules': {
        'brainstorming_outline': 'Brainstorming Outline',
        'description_human_verified': 'Description Human Verified',
        'learning_objectives_human_verified': 'Learning Objectives Human Verified',
        'brainstorming_outline_human_verified': 'Brainstorming Outline Human Verified',
        'name': 'Name',
        'status': 'Status',
        'order': 'Order',
        'course': 'Course Record ID',
        'target_length': 'Target Length (Min)',
        'demo_density': 'Demo Density',
        'learning_objectives': 'Learning Objectives',
        'description': 'Description',
        'notes': 'Notes',
        'module_plan_complete': 'Module Plan Complete',
        'module_review_complete': 'Module Review Complete',
        'plan_review_ai': 'Plan Review (AI)',
        'powerpoint_deck_review_ai': 'PowerPoint Deck Review (AI)',
        'slide_build_review_ai': 'Slide Build Review (AI)',
        'powerpoint_deck_human_verified': 'PowerPoint Deck Human Verified',
        'slide_narration_approved': 'Slide Narration Approved',
        'slide_narration_recorded': 'Slide Narration Recorded',
        'slide_narration_complete': 'Slide Narration Complete',
        'slide_deck_review_state': 'Slide Deck Review State',
        'slide_deck_submitted_revision': 'Slide Deck Submitted Revision',
        'module_video_review_state': 'Module Video Review State',
        'module_video_submitted_revisions': 'Module Video Submitted Revisions',
        'feedback_requested': 'Feedback Requested',
        'feedback_requested_at': 'Feedback Requested At',
        'version_control': 'Version Control',
        'base_record': 'Base Record',
    },
    'Clips': {
        'learning_objectives': 'Learning Objectives',
        'content_done': 'Clip Structure Confirmed',
        'id': 'ID',
        'name': 'Name',
        'status': 'Status',
        'order': 'Order',
        'module': 'Module Record ID',
        'target_length': 'Target Length (Min)',
        'description': 'Description',
        'story': 'Story',
        'notes': 'Notes',
        'clip_plan_review_ai': 'Clip Plan Review (AI)',
        'slide_narration_complete': 'Slide Narration Complete',
        'recording_review_human': 'Recording Human Verified',
        'feedback_requested': 'Feedback Requested',
        'feedback_requested_at': 'Feedback Requested At',
        'version_control': 'Version Control',
        'base_record': 'Base Record',
    },
    'Demos': {
        'clip_order': 'Clip Order',
        'estimated_length': 'Estimated Length',
        'notes_to_llm': 'Notes to LLM',
        'execution_method': 'Execution Method',
        'demo_environment': 'Demo Environment',
        'demo_review_complete': 'Demo Review Complete',
        'demo_edited': 'Demo Edited',
        'audio_synced': 'Audio Synced',
        'id': 'ID',
        'name': 'Name',
        'status': 'Status',
        'clip': 'Clip Record ID',
        'folder_root': 'Folder Root',
        'target_length': 'Target Length (Min)',
        'notes': 'Notes',
        'learner_takeaway': 'Learner Takeaway',
        'learner_takeaway_review_ai': 'Learner Takeaway Review (AI)',
        'demo_overview': 'Demo Overview',
        'demo_overview_review_ai': 'Demo Overview Review (AI)',
        'demo_overview_review_human': 'Demo Overview Human Verified',
        'environment_spec': 'Environment Spec',
        'environment_spec_review_ai': 'Environment Spec Review (AI)',
        'environment_prep_review_ai': 'Environment Prep Review (AI)',
        'action_summary': 'Action Summary',
        'action_summary_review_ai': 'Action Summary Review (AI)',
        'action_summary_review_human': 'Action Summary Human Verified',
        'walkthrough_test_complete': 'Walkthrough Test Complete',
        'script': 'Script',
        'script_review_ai': 'Script Review (AI)',
        'script_review_human': 'Script Human Verified',
        'recording_review_human': 'Recording Human Verified',
        'recorded': 'Recorded',
        'voice_recording_id': 'Voice Recording ID',
        'dictation_recorded': 'Dictation Recorded',
        'voice_source_hash': 'Voice Source Hash',
        'elevenlabs_voice_id': 'ElevenLabs Voice ID',
        'elevenlabs_model_id': 'ElevenLabs Model ID',
        'elevenlabs_output_format': 'ElevenLabs Output Format',
        'elevenlabs_request_id': 'ElevenLabs Request ID',
        'elevenlabs_history_item_id': 'ElevenLabs History Item ID',
        'voice_character_count': 'Voice Character Count',
        'voice_generated_at': 'Voice Generated At',
        'feedback_requested': 'Feedback Requested',
        'feedback_requested_at': 'Feedback Requested At',
        'version_control': 'Version Control',
        'base_record': 'Base Record',
    },
    'Slides': {
        'estimated_length': 'Estimated Length',
        'clip_slide_narration_complete': 'Clip Slide Narration Complete',
        'name': 'Name',
        'status': 'Status',
        'clip': 'Clip Record ID',
        'clip_order': 'Clip Order',
        'template': 'Template Record ID',
        'target_length': 'Target Length (Min)',
        'script': 'Script',
        'script_review_ai': 'Script Review (AI)',
        'build_instructions': 'Build Instructions',
        'notes': 'Notes',
        'designed': 'Designed',
        'built': 'Built',
        'recorded': 'Recorded',
        'slide_type_human_verified': 'Slide Type Human Verified',
        'script_human_verified': 'Script Human Verified',
        'dictation_recorded': 'Dictation Recorded',
        'feedback_requested': 'Feedback Requested',
        'feedback_requested_at': 'Feedback Requested At',
        'version_control': 'Version Control',
        'base_record': 'Base Record',
    },
    'Slide Templates': {
        'name': 'Name',
        'platform': 'Platform',
        'description': 'Description',
        'requirements': 'Requirements',
        'use_cases': 'Use Cases',
        'deck_number': 'Template Deck Number',
    },
    'Feedback': {
        'timestamp': 'Timestamp',
        'feedback': 'Feedback',
        'source': 'Source',
        'patterns_learned': 'Patterns Learned',
        'demo': 'Demo',
        'slide': 'Slide',
        'module': 'Module',
        'clip': 'Clip',
        'course': 'Course',
        'processing_status': 'Processing Status',
        'processed_at': 'Processed At',
        'remediation': 'Remediation',
        'element_type': 'Element Type',
        'attribute_name': 'Attribute Name',
        'attribute_snapshot': 'Attribute Snapshot',
        'selected_text': 'Selected Text',
    },
}


def collect_mapped_updates(
    table: str, option_values: Mapping[str, Any]
) -> Dict[str, Any]:
    """Collect provided scalar CLI options using ``FIELD_MAPPINGS``.

    Linked-record values, file reads, timestamps, and domain-specific lifecycle
    operations remain explicit command hooks. This helper is deliberately strict:
    an unmapped option is a programming error, not a silently skipped field.
    """
    if table not in FIELD_MAPPINGS:
        raise ValueError(f"Unknown table: {table}")

    mapping = FIELD_MAPPINGS[table]
    unknown = sorted(set(option_values) - set(mapping))
    if unknown:
        raise ValueError(
            f"Unknown mapped option(s) for table {table}: {', '.join(unknown)}"
        )

    return {
        mapping[option_name]: value
        for option_name, value in option_values.items()
        if value is not None
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
