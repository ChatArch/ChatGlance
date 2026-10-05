"""Model the real systemctl omission of empty list properties."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from chatglance import managed


@pytest.mark.parametrize('unit,body', [
    ('fixture.service', '[Service]\nExecStart=/fixture/python -m chatglance.cli runtime serve\n'),
    ('fixture.timer', '[Timer]\nUnit=fixture.service\n'),
])
def test_empty_systemd_list_properties_are_normalized(tmp_path, monkeypatch, unit, body):
    stdout = f'ActiveState=inactive\nFragmentPath={tmp_path / unit}\nDropInPaths=\n'
    if unit.endswith('.service'):
        stdout += 'ExecStart={ path=/fixture/python ; argv[]=/fixture/python -m chatglance.cli runtime serve ; ignore_errors=no ; }\n'
    monkeypatch.setattr(managed.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout))
    state = managed.unit_states([unit])[unit]
    assert state['EnvironmentFiles'] == ''
    assert managed._effective(unit, tmp_path, body, state) == []


def test_missing_fragment_remains_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(managed.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='ActiveState=inactive\n'))
    state = managed.unit_states(['fixture.service'])['fixture.service']
    with pytest.raises(ValueError):
        managed._effective('fixture.service', tmp_path, '[Service]\nExecStart=/fixture/python\n', state)
