"""candidate-prices-v1.2 (D-56): increment stages, version compatibility with v1.1, and the state-level reporting table.
Synthetic checks always run; real-data checks only read existing outputs and skip on a fresh clone."""

import json
from pathlib import Path

import pandas as pd
import pytest

from Code.candidates import build_candidate_prices as b, datagov_extract as de, datagov_increment as inc
from Code.candidates import build_prices_v1_2 as v12, recent_prices as rp

V11, V12 = de.OUT / 'dataset_v1_1', de.OUT / 'dataset_v1_2'
real = pytest.mark.skipif(not (V12 / 'build_manifest.json').exists() or not (V11 / 'weekly_faq_only.parquet').exists(),
                          reason='v1.1 / v1.2 outputs not built in this checkout')


def test_increments_follow_the_frozen_stages_without_overlap_or_renaming():
    st = inc.stages()
    assert {k: st[k] for k in de.STAGES} == de.STAGES                      # S1-S3 definitions untouched
    assert 'S4' in st and st['S4']['start'] == '2026-10-21' and 'revision_probe' not in st['S4']
    for name, s in inc.INCREMENTS.items():
        assert len(de.stage_days(s['start'], s['end'])) * len(de.CROPS) == s['crop_days']
        assert all(s['start'] <= d <= s['end'] for _, d in s['partitions'])
    assert 'S4' not in de.STAGES and inc.OUT != de.OUT                     # nothing rebinds the frozen module at import


def test_last_complete_week_monday():
    assert v12.last_week({'x': {'end': '2026-10-25'}}) == '2026-10-19'     # Sunday end: that week is complete
    assert v12.last_week({'x': {'end': '2026-10-20'}}) == '2026-10-12'     # Tuesday end: back to the previous week
    assert v12.last_week(de.STAGES) == b.LAST_WEEK                         # the v1.1 rule reproduces v1.1's window


def test_state_labels_never_double_count_a_reported_market():
    r = pd.DataFrame({'crop': 'Onion', 'week_start': pd.to_datetime(['2026-04-06'] * 4 + ['2026-06-01'] * 2),
                      'state': ['Kerala', 'Kerala', 'Keralam', 'Keralam', 'Keralam', 'Keralam'],
                      'market': ['A APMC', 'B APMC', 'A Market', 'B Market', 'A Market', 'B Market'], 'price': [10, 20, 10, 20, 30, 40]})
    out = rp.resolve_state_labels(r)
    assert set(out.state) == {'Kerala'}
    wk = rp.weekly(out, 'datagov').set_index('week_start')
    assert wk.loc['2026-04-06', 'markets'] == 2 and wk.loc['2026-06-01', 'markets'] == 2   # overlap week not doubled


@real
def test_v1_2_extends_v1_1_without_changing_its_weeks():
    m = json.loads((V12 / 'build_manifest.json').read_text())
    assert m['version'] == 'candidate-prices-v1.2' and m['stages'] == ['S1', 'S2', 'S3', 'S4'] and m['weeks'] == ['2024-02-05', '2026-10-19']
    assert m['candidate_start'] == '2024-02-03' and m['r09u_approved'] is False
    assert 'increments_crop_day_manifest' in m['inputs'] and m['source']['resource_id'].startswith('35985678')
    assert [x['date'] for x in m['source_breaks']] == ['2024-02-03', '2025-11-07']
    k = ['Commodity', 'canonical_id', 'Variety', 'week_start']
    a = pd.read_parquet(V11 / 'weekly_faq_only.parquet').sort_values(k, ignore_index=True)
    w = pd.read_parquet(V12 / 'weekly_faq_only.parquet')
    w = w[w.week_start <= pd.Timestamp(b.LAST_WEEK)].sort_values(k, ignore_index=True)
    pd.testing.assert_frame_equal(a, w)                                    # every v1.1 weekly cell, byte for value


@real
def test_v1_1_still_matches_the_d52_freeze():
    from Code.candidates import persistence_test_candidate as pt
    pt.verify()


@pytest.mark.skipif(not rp.TABLE.exists(), reason='reporting table not built')
def test_reporting_table_segments_and_contract():
    t = pd.read_parquet(rp.TABLE)
    assert list(t.columns) == rp.COLS and not t.duplicated(['crop', 'state', 'week_start']).any()
    seg = t.groupby('source').week_start.agg(['min', 'max'])
    assert seg.loc['agmarknet_archive', 'min'] == rp.ARCHIVE_FIRST and seg.loc['agmarknet_archive', 'max'] == rp.ARCHIVE_LAST
    assert seg.loc['datagov', 'min'] == pd.Timestamp('2024-02-05') and seg.loc['datagov', 'max'] <= pd.Timestamp('2026-10-19')
    assert (t.week_start.dt.dayofweek == 0).all() and (t.modal_price_median > 0).all() and (t.records >= t.markets).all()
    assert not set(rp.STATE_ALIASES) & set(t.state)
    man = json.loads((rp.DEST / 'reporting_manifest.json').read_text())
    import hashlib
    assert man['sha256'] == hashlib.sha256(rp.TABLE.read_bytes()).hexdigest()
