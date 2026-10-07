"""Failure-cost decisions and native-spawn boundary regression tests."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'plugin/scripts/model_routing.py'
spec = importlib.util.spec_from_file_location('model_routing', SCRIPT)
router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(router)


def request(**overrides):
    return dict(impact='local', recovery='easy', failed_attempts=0,
                available_models=[router.SOL, router.ASTRA]) | overrides


@pytest.mark.parametrize('impact,recovery,cost,model', [
    ('local', 'easy', 'low', router.SOL),
    ('component', 'easy', 'medium', router.SOL),
    ('local', 'costly', 'medium', router.SOL),
    ('critical', 'easy', 'high', router.ASTRA),
    ('local', 'irreversible', 'high', router.ASTRA),
    ('unknown', 'easy', 'high', router.ASTRA),
    ('local', 'unknown', 'high', router.ASTRA),
])
def test_failure_cost(impact, recovery, cost, model):
    result = router.route(request(impact=impact, recovery=recovery))
    assert result['failure_cost'] == cost
    assert result['spawn_args'] == dict(model=model, fork_turns='none')


def test_missing_assessment_defaults_high():
    assert router.route(dict(available_models=[router.ASTRA]))['failure_cost'] == 'high'


@pytest.mark.parametrize('failures', [1, 2])
def test_failed_sol_attempt_escalates(failures):
    result = router.route(request(failed_attempts=failures))
    assert result['spawn_args']['model'] == router.ASTRA
    assert result['escalated']


@pytest.mark.parametrize('failures', [3, 4])
def test_no_spawn_past_retry_limit(failures):
    result = router.route(request(failed_attempts=failures))
    assert result['action'] == 'stop'
    assert 'spawn_args' not in result


@pytest.mark.parametrize('overrides', [dict(failed_attempts=-1), dict(failed_attempts=True),
    dict(failed_attempts=1.5), dict(impact='typo'), dict(recovery='typo'),
    dict(available_models=None), dict(available_models='gpt-6-astra'), dict(extra=True)])
def test_invalid_input_refuses(overrides):
    with pytest.raises(ValueError):
        router.route(request(**overrides))


def test_unavailable_model_cannot_downgrade():
    result = router.route(request(impact='critical', available_models=[router.SOL]))
    assert result['action'] == 'blocked'
    assert 'spawn_args' not in result


@pytest.mark.parametrize('payload,code,action', [
    (json.dumps(request()), 0, 'spawn'),
    (json.dumps(request(failed_attempts=3)), 1, 'stop'),
    (json.dumps(request(available_models=[])), 1, 'blocked'),
    ('{bad', 2, 'blocked'),
    ('[]', 2, 'blocked'),
])
def test_cli(payload, code, action):
    result = subprocess.run([sys.executable, str(SCRIPT)], input=payload,
                            text=True, capture_output=True)
    assert result.returncode == code
    assert json.loads(result.stdout)['action'] == action
