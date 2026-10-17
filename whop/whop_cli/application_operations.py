"""Campaign application forms and one-attempt, read-back-verified applications.

Contracts measured from the Content Rewards web app on 2026-10-15. The app's
applyToCampaignAction sends applicationId, campaignId, response and
socialAccountIds. Its separate motivation control is not in that request.
"""
from urllib.parse import urlsplit

from cli_tools_shared.exceptions import ClientError

from .client import FETCH_JS, decode_action, identifier
from .submission_operations import journal_lock

APPLICATION_STATUSES = {'pending', 'approved', 'rejected', 'withdrawn'}


def existing_application(client, campaign_id: str) -> dict | None:
    payload = client.applications()
    if not isinstance(payload, dict) or payload.get('partialFailure') is not False:
        raise ClientError('campaign_applications_incomplete')
    rows = payload.get('applications')
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get('campaignId'), str)
        or row.get('status') not in APPLICATION_STATUSES for row in rows
    ):
        raise ClientError('campaign_applications_schema_changed')
    matches = [row for row in rows if row['campaignId'] == campaign_id]
    if len(matches) > 1:
        raise ClientError('campaign_application_ambiguous')
    return matches[0] if matches else None


def application_form(client, campaign_id: str) -> dict:
    identifier(campaign_id)
    campaign = client._rest('/api/campaign/campaigns/' + campaign_id)['data']
    if not isinstance(campaign, dict) or campaign.get('id') != campaign_id:
        raise ClientError('campaign_application_campaign_changed')
    configuration = campaign.get('configuration')
    application = configuration.get('application') if isinstance(configuration, dict) else None
    if campaign.get('requiresApplication') is not True or not isinstance(application, dict):
        raise ClientError('campaign_application_form_unavailable')
    application_id = application.get('id')
    if not isinstance(application_id, str):
        raise ClientError('campaign_application_form_schema_changed')
    identifier(application_id)
    form = client._rest('/api/application/application-forms/' + application_id, {'campaignId': campaign_id})['data']
    if not isinstance(form, dict) or form.get('id') != application_id or not isinstance(form.get('fields'), list):
        raise ClientError('campaign_application_form_schema_changed')
    return {'campaign_id': campaign_id, 'application_id': application_id, 'form': form}


def validate_answers(form: dict, answers: dict) -> None:
    fields = form['fields']
    names = [field.get('name') for field in fields if isinstance(field, dict)]
    if len(names) != len(fields) or any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        raise ClientError('campaign_application_form_schema_changed')
    if not isinstance(answers, dict) or set(answers) - set(names):
        raise ClientError('campaign_application_answers_unknown_fields')
    for field in fields:
        name, kind = field['name'], field.get('type')
        required = field.get('required')
        if type(required) is not bool:
            raise ClientError('campaign_application_form_schema_changed')
        if kind not in {'input', 'textarea', 'select', 'checkbox', 'file'}:
            raise ClientError('campaign_application_field_type_unsupported')
        if name not in answers:
            if required:
                raise ClientError('campaign_application_answer_required: ' + name)
            continue
        value = answers[name]
        valid = False
        if kind in {'input', 'textarea'}:
            valid = isinstance(value, str) and len(value) <= (255 if kind == 'input' else 1024)
            minimum = field.get('minLength', 1 if required else 0)
            if type(minimum) is not int or minimum < 0:
                raise ClientError('campaign_application_form_schema_changed')
            valid = valid and (len(value) >= minimum if required or value else True)
            if valid and kind == 'input' and field.get('format') == 'url' and value:
                parsed = urlsplit(value)
                valid = parsed.scheme in {'http', 'https'} and bool(parsed.netloc)
            elif kind == 'input' and field.get('format') not in {None, 'url'}:
                raise ClientError('campaign_application_field_format_unsupported')
        elif kind == 'checkbox':
            valid = type(value) is bool and (not required or value is True)
        elif kind == 'select':
            options = field.get('options')
            if not isinstance(options, list) or any(not isinstance(option, str) for option in options):
                raise ClientError('campaign_application_form_schema_changed')
            if field.get('multiple') is True:
                valid = isinstance(value, list) and all(item in options for item in value) and (not required or bool(value))
            else:
                valid = isinstance(value, str) and (value in options or value == '' and not required)
        elif kind == 'file':
            raise ClientError('campaign_application_file_upload_unsupported: ' + name)
        if not valid:
            raise ClientError('campaign_application_answer_invalid: ' + name)


def apply_campaign(client, campaign_id: str, *, answers: dict, social_account_ids: list[str], expected_account_id: str, confirm: bool) -> dict:
    if confirm is not True:
        raise ClientError('campaign_application_confirmation_required')
    with journal_lock(client.config) as database:
        database.execute("""CREATE TABLE IF NOT EXISTS campaign_applications (
            actor TEXT NOT NULL, experience TEXT NOT NULL, campaign TEXT NOT NULL,
            PRIMARY KEY(actor, experience, campaign))""")
        database.commit()
        return _apply_campaign(client, database, campaign_id, answers=answers,
                               social_account_ids=social_account_ids,
                               expected_account_id=expected_account_id)


def _apply_campaign(client, database, campaign_id: str, *, answers: dict, social_account_ids: list[str], expected_account_id: str) -> dict:
    identifier(campaign_id)
    identifier(expected_account_id)
    actor = client.account()
    if actor['id'] != expected_account_id:
        raise ClientError('campaign_application_actor_changed')
    existing = existing_application(client, campaign_id)
    if existing is not None:
        return {'status': 'existing', 'campaign_id': campaign_id, 'application': existing}
    origin, experience_path = client._location()
    binding = (expected_account_id, origin + experience_path, campaign_id)
    if database.execute('SELECT 1 FROM campaign_applications WHERE actor=? AND experience=? AND campaign=?', binding).fetchone():
        raise ClientError('campaign_application_outcome_unknown')
    form = application_form(client, campaign_id)
    if form['form'].get('status') != 'active':
        raise ClientError('campaign_application_form_not_active')
    validate_answers(form['form'], answers)
    if not social_account_ids or len(set(social_account_ids)) != len(social_account_ids):
        raise ClientError('campaign_application_social_accounts_required')
    linked = client.linked_accounts(1000, require_complete=True)
    if any(identifier(account_id) not in {row.get('id') for row in linked} for account_id in social_account_ids):
        raise ClientError('campaign_application_social_account_not_owned')
    suffix = '/campaigns/' + campaign_id
    document = client._action_document(suffix)
    action = client._discover_action(document, 'applyToCampaignAction', suffix, fresh=True)
    _, path = client._location()
    body = {'applicationId': form['application_id'], 'campaignId': campaign_id,
            'response': answers, 'socialAccountIds': social_account_ids}
    if client.account()['id'] != expected_account_id:
        raise ClientError('campaign_application_actor_changed')
    # Commit durable intent under the shared profile lock before any write.
    database.execute('INSERT INTO campaign_applications(actor,experience,campaign) VALUES(?,?,?)', binding)
    database.commit()
    # Never use the read transport's retries for a write. Readback decides success.
    try:
        response = document.evaluate(FETCH_JS, {'path': path + suffix, 'action': action, 'body': [body]})
        if not isinstance(response, dict) or response.get('status') != 200:
            raise ClientError('campaign_application_dispatch_uncertain')
        client._success(decode_action(response.get('text')))
    except Exception:
        try:
            observed = existing_application(client, campaign_id)
        except Exception:
            observed = None
        if observed is None:
            raise ClientError('campaign_application_outcome_unknown') from None
    else:
        try:
            observed = existing_application(client, campaign_id)
        except Exception:
            raise ClientError('campaign_application_outcome_unknown') from None
        if observed is None:
            raise ClientError('campaign_application_outcome_unknown')
    return {'status': 'applied', 'campaign_id': campaign_id, 'application': observed}
