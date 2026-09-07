"""First-phase cleanup acceptance using the existing real-browser fixture."""
from legoscout_cli.ledger import build_record, db
from legoscout_cli.sources import registry
from test_build_record_comps import (
    _appraisal, _bricklink_not_found, _one_set, _record, _set_comps,
    _EBAY_UNAVAILABLE,
)
from test_minifig_display_e2e import (
    _close, _legacy_deal, _pw, _result, _scratch_server, _session,
)


def test_should_preserve_deal_filters_reject_and_refresh_without_prospects(monkeypatch, tmp_path):
    with _scratch_server(monkeypatch, tmp_path, _legacy_deal(), with_crops=False) as base_url:
        session = _session()
        try:
            _pw(session, 'open', base_url, '--browser', 'chrome')
            state = _result(_pw(session, 'run-code', '''async (page) => {
                await page.locator('tr[data-k="k-bid|browser-legacy"]').waitFor();
                return {heading: await page.getByRole('heading').innerText(),
                    prospects: await page.getByText('Prospects', {exact:true}).count()};
            }'''))
            assert state == {'heading': 'LEGO Scout — Deals', 'prospects': 0}
            searched = _result(_pw(session, 'run-code', '''async (page) => {
                await page.locator('#q').fill('No matching listing');
                const empty = await page.locator('#tbody tr[data-k]').count();
                await page.locator('#q').fill('Legacy minifigure');
                return {empty, matched: await page.locator('#tbody tr[data-k]').getAttribute('data-k')};
            }'''))
            assert searched == {'empty': 0, 'matched': 'k-bid|browser-legacy'}
            filtered = _result(_pw(session, 'run-code', '''async (page) => {
                await page.locator('#q').fill('');
                await page.locator('#catfilters').getByRole('button', {name:'bulk',exact:true}).click();
                const bulk = await page.locator('#tbody tr[data-k]').count();
                await page.locator('#catfilters').getByRole('button', {name:'minifigure',exact:true}).click();
                return {bulk, minifigures: await page.locator('#tbody tr[data-k]').count()};
            }'''))
            assert filtered == {'bulk': 0, 'minifigures': 1}
            rejected = _result(_pw(session, 'run-code', '''async (page) => {
                const row=page.locator('tr[data-k="k-bid|browser-legacy"]');
                const response=page.waitForResponse(r=>r.url().endsWith('/status'));
                await row.getByRole('button', {name:'Reject',exact:true}).click();
                const status=(await response).status();
                await row.waitFor({state:'detached'});
                return {status, count:await row.count()};
            }'''))
            assert rejected == {'status': 200, 'count': 0}
            assert db.get_deal('k-bid|browser-legacy', path=str(tmp_path/'ledger.db'))['status'] == 'rejected'
            shown = _result(_pw(session, 'run-code', '''async (page) => {
                const loaded=page.waitForResponse(r=>r.url().includes('/rows.json?all=1'));
                await page.locator('#showall').check(); await loaded;
                await page.locator('#filters').getByRole('button', {name:'rejected',exact:true}).click();
                const row=page.locator('tr[data-k="k-bid|browser-legacy"]');
                await row.waitFor();
                const refreshed=page.waitForResponse(r=>r.url().includes('/rows.json?all=1'));
                await page.getByRole('button', {name:'↻ Refresh',exact:true}).click(); await refreshed;
                await row.waitFor();
                return {count:await row.count(), label:await row.locator('.act').innerText()};
            }'''))
            assert shown == {'count': 1, 'label': 'Rejected'}
            assert db.get_deal('k-bid|browser-legacy', path=str(tmp_path/'ledger.db'))['status'] == 'rejected'
        finally:
            _close(session)


def test_should_render_built_partial_lot_profit_and_incomplete_marker(monkeypatch, tmp_path):
    with _scratch_server(monkeypatch, tmp_path, _legacy_deal(), with_crops=False) as base_url:
        path = str(tmp_path/'ledger.db')
        monkeypatch.setattr(registry, 'sources', registry.Registry(path))
        comps = _set_comps(_one_set(), {
            'set_no': '99999999-1', 'bricklink': _bricklink_not_found('99999999-1'),
            'ebay': dict(_EBAY_UNAVAILABLE),
        })
        record = build_record.build_deal_record(
            _record('k-bid|browser-partial', title='Two-set Falcon lot'),
            _appraisal('k-bid|browser-partial', 'set'),
            first_seen_at='2026-09-07T00:00:00Z', last_seen_at='2026-09-07T00:00:00Z',
            comps=comps, fee_rate=0.13, favorite_sellers=set(),
        )
        db.upsert_deals([record], path=path)
        session = _session()
        try:
            _pw(session, 'open', base_url, '--browser', 'chrome')
            rendered = _result(_pw(session, 'run-code', '''async (page) => {
                const row=page.locator('tr[data-k="k-bid|browser-partial"]');
                await row.waitFor();
                const profit=await row.locator('td').nth(8).locator('.sc').innerText();
                await row.locator('.exp').click();
                const detail=page.locator('tr.det .dgrid > div').filter({has:page.locator('.dk', {hasText:'Potential profit'})});
                return {profit, detailProfit:await detail.locator('.dv').innerText()};
            }'''))
            assert rendered == {'profit': '$135.00', 'detailProfit': '$135.00*'}
            stored = db.get_deal('k-bid|browser-partial', path=path)
            assert stored['potential_profit'] == 135.0
            assert stored['profit_incomplete'] is True
        finally:
            _close(session)
