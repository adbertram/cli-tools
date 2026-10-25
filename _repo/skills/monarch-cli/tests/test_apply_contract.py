"""Saved approvals keep exact matching and reuse already-created rules."""
import runpy
import shlex
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
APPLY = runpy.run_path(str(SCRIPTS / "apply-approved-updates.sh"))


def test_saved_equals_commands_use_eq_and_dedupe():
    command = "monarch rules create --merchant 'equals:Texas Roadhouse' --set-category cat"
    assert APPLY["rule_argv"](command) == ["monarch", "rules", "create", "--merchant", "eq:Texas Roadhouse", "--set-category", "cat"]
    parsed = APPLY["parse_rule_command"](command)
    existing = [{"id": "existing", "merchantCriteria": [{"operator": "eq", "value": "texas roadhouse"}], "setCategoryAction": {"id": "cat"}}]
    assert APPLY["find_matching_rule"](parsed, existing) == "existing"
    existing[0]["setCategoryAction"]["id"] = "other"
    assert APPLY["find_matching_rule"](parsed, existing) is None


def test_generator_maps_equals_without_changing_contains():
    for matcher, expected in [("equals", "eq"), ("contains", "contains")]:
        result = subprocess.run([sys.executable, str(SCRIPTS / "build-rule-command.sh"), "--merchant", "Texas Roadhouse", "--match", matcher, "--category-id", "cat"], capture_output=True, text=True, check=True)
        argv = shlex.split(result.stdout)
        assert argv[argv.index("--merchant") + 1] == f"{expected}:Texas Roadhouse"


def test_verification_checks_nested_category_and_review_status():
    import json
    import pytest

    obj = {"getTransaction": {"category": {"id": "cat"}, "needsReview": False}}
    assert APPLY["verify_transaction"](json.dumps(obj), "cat", True) == {"verified_category": "cat", "verified_needs_review": False}
    with pytest.raises(ValueError, match="category mismatch"):
        APPLY["verify_transaction"](json.dumps(obj), "other", True)
    obj["getTransaction"]["needsReview"] = True
    with pytest.raises(ValueError, match="needsReview mismatch"):
        APPLY["verify_transaction"](json.dumps(obj), "cat", True)
    assert APPLY["verify_transaction"](json.dumps(obj), "cat", False)["verified_needs_review"] is True


def test_split_render_and_apply_dry_run(tmp_path):
    import json
    renderer = runpy.run_path(str(SCRIPTS / 'build-output.sh'))
    row = dict(row=1, transaction_id='txn', vendor='Amazon', amount=-32.48,
               description='matched order', current_category='Shopping', suggested_category='Split by item',
               needs_input=False, recommended_rule='Apply once — suppressed: multi-category merchant', rule_command=None,
               splits=[dict(item_price='10', amount='-10.83', category_id='a', category='Books', notes='book'),
                       dict(item_price='20', amount='-21.65', category_id='b', category='Household', notes='cleaner')])
    decisions = {'rows':[row], 'category_id_by_name': {'Books':'a','Household':'b'}}
    assert renderer['validate'](decisions) == []
    rendered = renderer['render'](decisions)
    assert '| 1.1 |' in rendered and 'Books' in rendered and '| 1.2 |' in rendered
    path = tmp_path / 'decisions.json'
    path.write_text(json.dumps(decisions))
    output = subprocess.run([sys.executable,str(SCRIPTS/'apply-approved-updates.sh'),'--decisions',str(path),'--approved','1','--dry-run'],capture_output=True,text=True,check=True)
    result = json.loads(output.stdout)
    assert result['updates'][0]['status'] == 'ok'
    assert 'transactions split txn' in result['updates'][0]['command']
    assert result['rules_created'] == []
    row['rule_command'] = 'monarch rules create --merchant contains:Amazon --set-category a'
    assert renderer['validate'](decisions)
    path.write_text(json.dumps(decisions))
    output = subprocess.run([sys.executable,str(SCRIPTS/'apply-approved-updates.sh'),'--decisions',str(path),'--approved','1','--dry-run'],capture_output=True,text=True)
    assert output.returncode == 1
