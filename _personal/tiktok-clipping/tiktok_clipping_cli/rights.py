"""Explicit campaign-scoped rights and edit requirements, never model authority."""
from __future__ import annotations
import re
from urllib.parse import urlparse
from .safety import SafetyError,edit_duration,edit_segments,keys,number,string


def validate_policy(policy, source):
    keys(policy, {'schema_version','campaign_id','brief_url','brief_content_sha256','source_url','source_sha256','source_bytes','video_reuse_allowed','original_audio_reuse_allowed','external_audio_allowed','full_source_repost_allowed','minimum_clip_seconds','required_caption_tokens','required_on_screen_text','clip_rules'})
    if type(policy['schema_version']) is not int or policy['schema_version'] not in (1,2):
        raise SafetyError('rights_policy_version_invalid')
    if policy['campaign_id']!=source['campaign']['id'] or policy['brief_url']!=source['reuse_evidence'] or policy['source_url']!=source['feed']:
        raise SafetyError('rights_policy_source_campaign_brief_mismatch')
    brief=urlparse(policy['brief_url'])
    if brief.scheme!='https' or brief.hostname!='docs.google.com' or not re.fullmatch(r'/document/d/[A-Za-z0-9_-]+/edit',brief.path) or brief.username or brief.password:
        raise SafetyError('rights_brief_url_invalid')
    for field in ('brief_content_sha256','source_sha256'):
        if not isinstance(policy[field],str) or not re.fullmatch('[a-f0-9]{64}',policy[field]):raise SafetyError('rights_sha256_invalid')
    number(policy['source_bytes'],1,30_000_000_000,integer=True)
    number(policy['minimum_clip_seconds'],1,60)
    if policy['video_reuse_allowed'] is not True or policy['original_audio_reuse_allowed'] is not True or policy['external_audio_allowed'] is not False or policy['full_source_repost_allowed'] is not False:
        raise SafetyError('rights_require_excerpt_and_original_source_audio_only')
    def texts(values, maximum):
        if not isinstance(values,list) or not 1<=len(values)<=8:raise SafetyError('rights_required_text_invalid')
        for value in values:
            string(value,maximum)
            if any(c in value for c in ('\n','\r','\\','{','}')):raise SafetyError('rights_required_text_markup_forbidden')
        if len(set(values)) != len(values):raise SafetyError('rights_required_text_duplicate')
    texts(policy['required_caption_tokens'],128);texts(policy['required_on_screen_text'],128)
    if policy['schema_version']==1 and 'Ad' not in policy['required_on_screen_text']:raise SafetyError('rights_ad_overlay_required')
    rules=policy['clip_rules']
    if not isinstance(rules,list) or len(rules)>8:raise SafetyError('rights_clip_rule_limit')
    for rule in rules:
        keys(rule,{'segments','caption_tokens','on_screen_text'})
        if not isinstance(rule['segments'],list) or not rule['segments']:raise SafetyError('rights_rule_cuts_required')
        for cut in rule['segments']:
            keys(cut, {'start_seconds','end_seconds'})
            number(cut['start_seconds']);number(cut['end_seconds'])
        start=min(c['start_seconds'] for c in rule['segments']);end=max(c['end_seconds'] for c in rule['segments'])
        edit_segments({'start_seconds':start,'end_seconds':end,'segments':rule['segments']})
        texts(rule['caption_tokens'],128);texts(rule['on_screen_text'],128)
    if policy['schema_version']==2:current_render_policy(policy)
    return policy


def current_render_policy(policy):
    """Historical policies stay readable; new media follows current preferences."""
    if policy.get('schema_version') != 2:raise SafetyError('current_no_ad_render_policy_required')
    labels = list(policy['required_on_screen_text']) + [label for rule in policy['clip_rules'] for label in rule['on_screen_text']]
    if any(re.search(r'\b(ad|advertisement|sponsored)\b|paid\s+partnership', label, re.IGNORECASE) for label in labels):
        raise SafetyError('campaign_requires_forbidden_on_video_disclaimer')
    return policy


def has_token(caption, token):
    alphabet = r'A-Za-z0-9._@#' if token.startswith('@') else r'\w@#'
    return re.search(r'(?<!['+alphabet+'])'+re.escape(token)+r'(?!['+alphabet+'])',caption,re.IGNORECASE) is not None


def required_overlays(policy, proposal):
    cuts=edit_segments(proposal)
    if edit_duration(proposal)<policy['minimum_clip_seconds']:raise SafetyError('rights_minimum_duration_not_met')
    overlays=list(policy['required_on_screen_text'])
    tokens=list(policy['required_caption_tokens'])
    matched=[rule for rule in policy['clip_rules'] if cuts==rule['segments']]
    allowed_claims=set()
    for rule in matched:
        tokens.extend(rule['caption_tokens']);overlays.extend(rule['on_screen_text'])
        allowed_claims.update(rule['caption_tokens']+rule['on_screen_text'])
    scoped_claims={claim for rule in policy['clip_rules'] for claim in rule['caption_tokens']+rule['on_screen_text']}
    if any(has_token(proposal['caption'],claim) for claim in scoped_claims-allowed_claims):
        raise SafetyError('clip_specific_claim_outside_qualified_edit')
    if any(not has_token(proposal['caption'],token) for token in tokens):raise SafetyError('rights_required_caption_token_missing')
    return list(dict.fromkeys(overlays))
