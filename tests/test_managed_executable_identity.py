"""Effective executable identity must be checked, not argv alone."""
from pathlib import Path
import pytest
from chatglance.managed import _effective


def test_effective_unit_rejects_different_executable_with_same_argv():
    name = 'fixture-web.service'
    directory = Path('/fixture/units')
    body = '[Service]\nExecStart="/fixture/python" -m chatglance.cli runtime serve\n'
    state = {'FragmentPath': str(directory / name), 'DropInPaths': '', 'EnvironmentFiles': '',
             'ExecStart': '{ path=/different/executable ; argv[]="/fixture/python" -m chatglance.cli runtime serve ; ignore_errors=no ; }'}
    with pytest.raises(ValueError, match='ExecStart'):
        _effective(name, directory, body, state)


def test_effective_unit_accepts_matching_executable_and_argv():
    name = 'fixture-web.service'
    directory = Path('/fixture/units')
    body = '[Service]\nExecStart="/fixture/python" -m chatglance.cli runtime serve\n'
    state = {'FragmentPath': str(directory / name), 'DropInPaths': '', 'EnvironmentFiles': '',
             'ExecStart': '{ path=/fixture/python ; argv[]="/fixture/python" -m chatglance.cli runtime serve ; ignore_errors=no ; }'}
    assert _effective(name, directory, body, state) == []
