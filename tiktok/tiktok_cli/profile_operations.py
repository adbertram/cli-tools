"""Read and update the owned profile bio through measured TikTok web controls."""
import time

from .client import ClientError


def _editor(page):
    button = page.get_by_role('button', name='Edit profile', exact=True)
    deadline = time.monotonic() + 15
    while not button.count() and time.monotonic() < deadline:
        time.sleep(0.25)
    if button.count() != 1:
        raise ClientError('TikTok owned profile editor unavailable; no save dispatched')
    button.click()
    field = page.get_by_role('textbox', name='Bio', exact=True)
    while not field.count() and time.monotonic() < deadline:
        time.sleep(0.25)
    if field.count() != 1:
        raise ClientError('TikTok bio editor unavailable; no save dispatched')
    return field


def bio(client, username, account_id, *, value=None, expected=None):
    identity = client.get_account(expected_username=username, expected_account_id=account_id)
    page = client._page('/@' + identity['username'])
    field = _editor(page)
    previous = field.input_value()
    if value is None:
        return {**identity, 'bio': previous}
    if expected is None or previous != expected:
        raise ClientError('TikTok bio changed or expected bio was not supplied; no write dispatched')
    if len(value) > 80:
        raise ClientError('TikTok bio exceeds the observed 80-character limit')
    if previous == value:
        return {**identity, 'bio': previous, 'previous_bio': previous, 'changed': False}
    field.fill(value)
    if field.input_value() != value:
        raise ClientError('TikTok bio editor did not retain the exact requested value; no save dispatched')
    page.get_by_role('button', name='Save', exact=True).click()
    deadline = time.monotonic() + 20
    while field.count() and time.monotonic() < deadline:
        time.sleep(0.25)
    if field.count():
        raise ClientError('TikTok profile editor did not close after save; outcome unknown, read bio before retrying')
    # A fresh navigation and editor readback proves persisted profile state.
    observed = None
    for attempt in range(5):
        page = client._page('/@' + identity['username'])
        observed = _editor(page).input_value()
        if observed == value:
            break
        if attempt < 4:
            time.sleep(2)
    if observed != value:
        raise ClientError('TikTok bio save outcome unknown; read bio before any further write')
    return {**identity, 'bio': observed, 'previous_bio': previous, 'changed': True}
