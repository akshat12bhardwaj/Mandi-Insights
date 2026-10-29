"""State-level weekly price reporting table for the application, July 2020 onward (D-56). Reporting only: no model,
no forecast, no market-level continuity claim.

Two sources, never blended within a week:
  agmarknet_archive  Phase 5 cleaned mandi tables (the archived AGMARKNET copy), usable modal prices, complete weeks
                     2020-07-06 .. 2024-01-22 (the copy ends 2024-02-02, so its last week is partial and dropped).
                     Earlier weeks are already served by the Spark outputs (/api/markets/weekly).
  datagov            candidate-prices-v1.2, FAQ grade only (the grade the archive carried), usable_for_target, complete weeks.
Metric per crop x state x week: median modal price (Rs/quintal) over usable records, record and market counts; the
same definition as the Spark weekly summary (median of record modal prices), on cleaned records.

State labels: the feed renamed two states. STATE_ALIASES maps them to the label the application already uses. In a
state-week reported under both labels (Keralam 2026-04-01 .. 05-22 duplicated every Kerala record with identical prices;
Uttarakhand overlaps Uttrakhand around the 2025-11-07 relaunch) only the original label's records are used, so no
market is counted twice. Market identities are never merged.

Usage (repo root): python -m Code.candidates.recent_prices build
Output (git-ignored parquet; the data is not redistributed, D-56): Processed_Data/candidates/datagov_prices/reporting_v1/
"""
import hashlib, json, sys
from pathlib import Path

import pandas as pd

from Code.candidates.datagov_extract import CROPS, OUT

V12 = OUT / 'dataset_v1_2'
CLEANED = Path('Processed_Data/cleaned')
DEST = OUT / 'reporting_v1'
TABLE = DEST / 'weekly_state.parquet'
ARCHIVE_FIRST, ARCHIVE_LAST = pd.Timestamp('2020-07-06'), pd.Timestamp('2024-01-22')
STATE_ALIASES = {'Keralam': 'Kerala', 'Uttarakhand': 'Uttrakhand'}   # feed label -> application label
COLS = ['crop', 'state', 'week_start', 'source', 'records', 'markets', 'modal_price_median']


def week_start(d):
    d = pd.to_datetime(d).dt.normalize()
    return d - pd.to_timedelta(d.dt.dayofweek, unit='D')


def weekly(df, source):
    g = df.groupby(['crop', 'state', 'week_start'], observed=True)
    out = g.agg(records=('price', 'size'), markets=('market', 'nunique'), modal_price_median=('price', 'median')).reset_index()
    return out.assign(source=source)[COLS]


def resolve_state_labels(r):
    """Map aliases; where a crop-state-week has records under both labels, keep only the original label's records."""
    r = r.assign(source_state=r.state, state=r.state.replace(STATE_ALIASES))
    both = r.groupby(['crop', 'state', 'week_start'], observed=True).source_state.transform('nunique') > 1
    return r[~(both & r.source_state.isin(STATE_ALIASES))]


def archive():
    parts = []
    for c in CROPS:
        d = pd.read_parquet(CLEANED / f'mandi_cleaned_{c.lower()}.parquet',
                            columns=['state', 'market', 'reported_date', 'modal_price_rs_per_quintal', 'usable_modal_price'],
                            filters=[('reported_date', '>=', ARCHIVE_FIRST)])
        d = d[d.usable_modal_price].assign(crop=c, week_start=lambda x: week_start(x.reported_date), state=lambda x: x.state.astype(str),
                                           market=lambda x: x.market.astype(str), price=lambda x: x.modal_price_rs_per_quintal)
        parts.append(d[d.week_start.between(ARCHIVE_FIRST, ARCHIVE_LAST)])
    return weekly(pd.concat(parts, ignore_index=True), 'agmarknet_archive')


def datagov(last_week):
    parts = []
    for c in CROPS:
        d = pd.read_parquet(V12 / f'records_{c.lower()}.parquet',
                            columns=['State', 'Market', 'week_start', 'modal_price_rs_per_quintal', 'usable_for_target', 'in_faq_only', 'in_complete_week'])
        d = d[d.usable_for_target & d.in_faq_only & d.in_complete_week]
        parts.append(pd.DataFrame({'crop': c, 'state': d.State, 'market': d.Market, 'week_start': d.week_start,
                                   'price': d.modal_price_rs_per_quintal}))
    r = resolve_state_labels(pd.concat(parts, ignore_index=True))
    assert r.week_start.max() <= pd.Timestamp(last_week)
    return weekly(r, 'datagov')


def build():
    m = json.loads((V12 / 'build_manifest.json').read_text())
    t = pd.concat([archive(), datagov(m['weeks'][1])], ignore_index=True).sort_values(['crop', 'state', 'week_start'], ignore_index=True)
    assert not t.duplicated(['crop', 'state', 'week_start']).any(), 'a week from two sources'
    DEST.mkdir(parents=True, exist_ok=True)
    t.to_parquet(TABLE, index=False)
    man = {'table': TABLE.name, 'sha256': hashlib.sha256(TABLE.read_bytes()).hexdigest(), 'rows': len(t),
           'inputs': {'candidate_prices_v1_2_build_manifest': hashlib.sha256((V12 / 'build_manifest.json').read_bytes()).hexdigest()},
           'segments': {s: [str(g.week_start.min().date()), str(g.week_start.max().date())] for s, g in t.groupby('source')},
           'state_aliases': STATE_ALIASES, 'grade': 'FAQ (datagov); the archive carries no grade field',
           'source': m['source'], 'source_breaks': m['source_breaks'],
           'retrieved_utc_range': None}
    rec = pd.concat([pd.read_parquet(V12 / f'records_{c.lower()}.parquet', columns=['retrieved_utc']) for c in CROPS])
    man['retrieved_utc_range'] = [rec.retrieved_utc.min(), rec.retrieved_utc.max()]
    (DEST / 'reporting_manifest.json').write_text(json.dumps(man, indent=1))
    print(json.dumps({k: man[k] for k in ('rows', 'segments', 'retrieved_utc_range')}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(build() if sys.argv[1:] == ['build'] else print('usage: python -m Code.candidates.recent_prices build') or 2)
