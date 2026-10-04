"""Quota display shows both real windows without changing reset policy selection."""
from copy import deepcopy
import re

from chatglance.account_limits import _primary_window, render_account_limits_html
from test_reset_guard_rendering import profile


def blocks(row):
    text = render_account_limits_html({'codex': [row]})
    found = re.findall(r'<section class="quota-window" data-window-seconds="(\d+)">(.*?)</section>', text, re.S)
    return {int(seconds): body for seconds, body in found}


def test_short_and_weekly_progress_are_separate_and_policy_stays_weekly():
    row = profile()
    views = blocks(row)
    assert list(views) == [18000, 604800]
    assert '5小时额度' in views[18000] and '99.0%' in views[18000]
    assert '2027-01-15' in views[18000]
    assert '总额度（7天窗口）' in views[604800] and '12.0%' in views[604800]
    assert '2027-01-20' in views[604800]
    assert '99.0%' not in views[604800]
    assert _primary_window(row)['used_percent'] == 12


def test_weekly_only_account_does_not_get_an_invented_short_window():
    row = profile(); row['windows'] = row['windows'][1:]
    assert list(blocks(row)) == [604800]


def test_missing_policy_window_does_not_relabel_short_quota_as_weekly():
    row = profile(); row['windows'] = row['windows'][:1]
    views = blocks(row)
    assert '99.0%' in views[18000]
    assert '—' in views[604800] and '99.0%' not in views[604800]
    assert _primary_window(row) is None


def test_duplicate_short_window_is_unknown_instead_of_selecting_arbitrarily():
    row = profile(); row['windows'].append(deepcopy(row['windows'][0]))
    views = blocks(row)
    assert '—' in views[18000] and '99.0%' not in views[18000]
    assert '12.0%' in views[604800]


def test_minutes_only_snapshots_identify_both_windows():
    row = profile()
    for window in row['windows']: window.pop('window_seconds')
    assert list(blocks(row)) == [18000, 604800]


def test_model_specific_limits_do_not_create_another_main_quota_bar():
    row = profile(); row['windows'][0]['name'] = 'model_specific_window'
    assert list(blocks(row)) == [604800]
