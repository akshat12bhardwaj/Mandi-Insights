"""`exp-v3-prices` (D-58): persistence against three simple, never-scored alternatives on candidate-prices data, with a
chronological validation window and a later, untouched final test. Pre-registered: `register` writes the protocol
(exclusive create) before `validate` computes any score, and both refuse if the protocol file changed.

Forecast at origin week W (all inputs are weekly FAQ-only cells with week_start <= W of the same series):
  persistence        y(W)
  trailing_median_4w median of the observed cells in weeks W-3 .. W
  ewma_a05           exponentially weighted mean over the series' observed cells up to W (alpha 0.5, unadjusted)
  drift_4w           y(W) + h * (y(W) - y(W-4)) / 4 when y(W-4) exists, else y(W)
Rows: FAQ-only model-table rows eligible at the origin (D-41), every horizon 1 / 2 / 4, all methods on identical rows.
Validation: target-week Sundays VALIDATION; the D-52 test window (target Sundays 2026-07-05 .. 10-18) is consumed and
never compared on (D-53 item 9), and nothing on or after the final-test start is read.
Selection (per crop x horizon): the alternative with the lowest validation MAE advances only if its market-cluster
bootstrap skill interval at the Bonferroni level (27 comparisons) lies above 0; otherwise the cell is persistence-only.
Final test: target-week Sundays TEST, run once (lock) after the data is complete; acceptance in PROTOCOL['acceptance'].

Usage (repo root): python -m Code.candidates.exp_v3 register | validate | test --confirm-single-test-run exp-v3
"""
import hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from Code.candidates.datagov_extract import CROPS, OUT

DESIGN_DIR = OUT / 'experiment_design_v3'
PROTOCOL_PATH = DESIGN_DIR / 'exp_v3_protocol.json'
RUN_DIR = OUT / 'experiments' / 'exp_v3'
DATASET = OUT / 'dataset_v1_2'
SERIES = ['Commodity', 'canonical_id', 'Variety']
METHODS = ['persistence', 'trailing_median_4w', 'ewma_a05', 'drift_4w']
ALTERNATIVES = METHODS[1:]
HORIZONS = (1, 2, 4)
VALIDATION = ('2025-03-02', '2026-06-28')
CONSUMED = ('2026-07-05', '2026-10-18')         # D-52 test window: never compared on
TEST = ('2026-11-01', '2027-04-25')             # untouched final test (26 target weeks)
B, SEED = 10_000, 20261022
N_COMPARISONS = len(ALTERNATIVES) * len(CROPS) * len(HORIZONS)
PROTOCOL = {
    'experiment': 'exp-v3-prices', 'decision': 'D-58', 'design': 'faq_only', 'population': 'eligible_d41 at origin',
    'methods': METHODS, 'baseline': 'persistence', 'horizons': list(HORIZONS),
    'validation_target_sundays': list(VALIDATION), 'consumed_never_compared': list(CONSUMED), 'test_target_sundays': list(TEST),
    'metric': 'MAE (Rs/quintal) primary; RMSE, MAPE reported', 'skill': '1 - MAE(method) / MAE(persistence), identical rows',
    'bootstrap': {'cluster': 'market (canonical_id)', 'replicates': B, 'seed': SEED, 'statistic': 'skill (ratio of summed absolute errors)'},
    'selection': f'per crop x horizon, lowest validation MAE among {ALTERNATIVES}; advances only if its market-cluster skill interval '
                 f'at level 1 - 0.05/{N_COMPARISONS} has lower bound > 0; else persistence-only',
    'acceptance': 'an advanced method is accepted for a cell only if, on the test window: (1) market-cluster skill interval at level '
                  '1 - 0.05/k (k = number of advanced cells) has lower bound > 0; (2) the state-cluster 95% interval has lower bound > 0; '
                  '(3) the skill stays > 0 when any one state is left out. Otherwise persistence remains the forecast',
    'test_gate': 'run once, only when the dataset covers the last test target week and was retrieved >= 10 days after it '
                 '(late records, D-56 revision log); RUN_LOCK.json is created before any test row is read',
    'data': 'candidate-prices-v1.2 or a later version built with unchanged rules; versions are named in the run manifest',
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def register(path=PROTOCOL_PATH):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'x', encoding='utf-8', newline='\n') as fh:
        json.dump(PROTOCOL | {'registered_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')}, fh, indent=1)
    return sha(path)


def check_protocol(path=PROTOCOL_PATH):
    p = json.loads(Path(path).read_text(encoding='utf-8'))
    if {k: v for k, v in p.items() if k != 'registered_utc'} != PROTOCOL:
        raise SystemExit('protocol on disk differs from the code: the pre-registration is broken')
    return sha(path)


# ---------------------------------------------------------------- forecasts
def origin_features(weekly):
    """Per series and observed week W: the trailing median and EWMA, from cells with week_start <= W only."""
    w = weekly.sort_values(SERIES + ['week_start']).reset_index(drop=True)
    g = w.groupby(SERIES, observed=True, sort=False)
    w['ewma_a05'] = g.target_median.transform(lambda s: s.ewm(alpha=0.5, adjust=False).mean())
    roll = (w.set_index('week_start').groupby(SERIES, observed=True, sort=False).target_median
            .rolling('28D').median().reset_index())                    # weeks W-3 .. W (28 days ending at W's Monday)
    w = w.merge(roll.rename(columns={'target_median': 'trailing_median_4w'}), on=SERIES + ['week_start'], how='left', validate='1:1')
    return w[SERIES + ['week_start', 'ewma_a05', 'trailing_median_4w']].rename(columns={'week_start': 'origin_week_start'})


def forecasts(mt, weekly):
    f = mt.merge(origin_features(weekly), on=SERIES + ['origin_week_start'], how='left', validate='m:1')
    assert f[['ewma_a05', 'trailing_median_4w']].notna().all().all(), 'every origin is an observed week'
    f['persistence'] = f.y_origin
    f['drift_4w'] = np.where(f.lag4.notna(), f.y_origin + f.horizon_weeks * (f.y_origin - f.lag4) / 4, f.y_origin)
    return f


def rows(mt, period):
    a, z = (pd.Timestamp(x) for x in period)
    sunday = mt.target_week_start + pd.Timedelta(days=6)
    r = mt[mt.eligible_d41 & sunday.between(a, z)].assign(target_sunday=sunday)
    c0, c1 = (pd.Timestamp(x) for x in CONSUMED)
    if period != tuple(TEST) and (r.target_sunday.between(c0, c1).any() or (r.target_sunday >= pd.Timestamp(TEST[0])).any()):
        raise SystemExit('validation rows reach the consumed D-52 window or the final test')
    return r


# ---------------------------------------------------------------- scoring
def skill_boot(f, method, cluster, b=B, seed=SEED):
    """Point skill and bootstrap replicates, resampling whole clusters (ratio of summed absolute errors)."""
    e = f.assign(em=(f[method] - f.y_target).abs(), ep=(f.persistence - f.y_target).abs()).groupby(cluster, observed=True)[['em', 'ep']].sum()
    point = 1 - e.em.sum() / e.ep.sum()
    rng = np.random.default_rng([seed, int.from_bytes(f'{method}|{cluster}'.encode(), 'little') % 2 ** 32])
    w = rng.multinomial(len(e), np.full(len(e), 1 / len(e)), size=b)
    reps = 1 - (w @ e.em.to_numpy()) / (w @ e.ep.to_numpy())
    return point, reps, len(e)


def interval(reps, alpha):
    lo, hi = np.percentile(reps, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def score(f, b=B):
    out = []
    for (crop, h), g in f.groupby(['Commodity', 'horizon_weeks'], sort=True):
        for m in METHODS:
            err = g[m] - g.y_target
            row = {'crop': crop, 'horizon_weeks': h, 'method': m, 'rows': len(g), 'markets': g.canonical_id.nunique(),
                   'states': g.state.nunique(), 'mae': float(err.abs().mean()), 'rmse': float(np.sqrt((err ** 2).mean())),
                   'mape_pct': float((err.abs() / g.y_target).mean() * 100)}
            if m != 'persistence':
                p, reps, n = skill_boot(g, m, 'canonical_id', b)
                row |= {'skill': float(p), 'n_market_clusters': n}
                row['skill_ci95_low'], row['skill_ci95_high'] = interval(reps, 0.05)
                row['skill_bonferroni_low'], row['skill_bonferroni_high'] = interval(reps, 0.05 / N_COMPARISONS)
            out.append(row)
    return pd.DataFrame(out)


def select(s):
    alt = s[s.method != 'persistence']
    best = alt.loc[alt.groupby(['crop', 'horizon_weeks']).mae.idxmin()]
    return best.assign(advances=best.skill_bonferroni_low > 0)[['crop', 'horizon_weeks', 'method', 'skill', 'skill_bonferroni_low', 'advances']]


def load(dataset=DATASET):
    mt = pd.read_parquet(Path(dataset) / 'model_table_faq_only.parquet')
    weekly = pd.read_parquet(Path(dataset) / 'weekly_faq_only.parquet')
    mt = mt.assign(state=mt.canonical_id.str.split('|').str[0])
    return mt, weekly


def validate(dataset=DATASET, out=RUN_DIR / 'validation', b=B):
    psha = check_protocol()
    mt, weekly = load(dataset)
    v = rows(mt, VALIDATION)
    weekly = weekly[weekly.week_start <= v.origin_week_start.max()]       # no cell after the last validation origin is read
    f = forecasts(v, weekly)
    s = score(f, b)
    s.loc[s.method == 'persistence', 'skill'] = 0.0
    q = f.assign(quarter=f.target_sunday.dt.to_period('Q').astype(str))
    by_q = pd.concat([score(g, 200).assign(quarter=k) for k, g in q.groupby('quarter')])[['quarter', 'crop', 'horizon_weeks', 'method', 'rows', 'mae', 'skill']]
    sel = select(s)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    files = {'by_crop.csv': s, 'by_crop_quarter.csv': by_q, 'selection.csv': sel}
    for n, t in files.items():
        t.to_csv(out / n, index=False)
    man = {'experiment': 'exp-v3-prices', 'stage': 'validation', 'protocol_sha256': psha,
           'dataset_build_manifest_sha256': sha(Path(dataset) / 'build_manifest.json'),
           'target_sundays': [str(f.target_sunday.min().date()), str(f.target_sunday.max().date())],
           'latest_cell_read': str(weekly.week_start.max().date()), 'bootstrap': {'replicates': b, 'seed': SEED},
           'code_sha256': sha(__file__), 'outputs_sha256': {n: sha(out / n) for n in files}}
    (out / 'run_manifest.json').write_text(json.dumps(man, indent=1))
    return s, sel


def accept(f, method, k, b=B):
    """The pre-registered acceptance rule for one advanced cell on the test rows."""
    p, reps, n = skill_boot(f, method, 'canonical_id', b)
    m_lo = interval(reps, 0.05 / max(k, 1))[0]
    _, sreps, ns = skill_boot(f, method, 'state', b)
    s_lo = interval(sreps, 0.05)[0] if ns >= 2 else float('nan')
    loso = {s: float(skill_boot(f[f.state != s], method, 'canonical_id', 1)[0]) for s in sorted(f.state.unique())} if ns >= 2 else {}
    ok = bool(m_lo > 0 and ns >= 2 and s_lo > 0 and loso and min(loso.values()) > 0)
    return {'method': method, 'skill': float(p), 'market_clusters': n, 'market_bonferroni_low': m_lo, 'state_clusters': ns,
            'state_ci95_low': s_lo, 'leave_one_state_out_min': min(loso.values()) if loso else float('nan'), 'accepted': ok}


def test(confirm, dataset=DATASET, out=RUN_DIR / 'test', selection=RUN_DIR / 'validation' / 'selection.csv', b=B):
    """The single final test. Refuses until the data covers the whole window and has settled; never run before then."""
    if confirm != 'exp-v3':
        raise SystemExit('the single final test needs --confirm-single-test-run exp-v3')
    psha = check_protocol()
    m = json.loads((Path(dataset) / 'build_manifest.json').read_text())
    last_monday = pd.Timestamp(TEST[1]) - pd.Timedelta(days=6)
    if pd.Timestamp(m['weeks'][1]) < last_monday:
        raise SystemExit(f'the dataset ends at week {m["weeks"][1]}; the final test needs every week to {last_monday.date()}')
    rec = pd.read_parquet(Path(dataset) / 'records_onion.parquet', columns=['retrieved_utc', 'reported_date'])
    late = rec[rec.reported_date > pd.Timestamp(TEST[1]) - pd.Timedelta(days=7)].retrieved_utc.min()
    if pd.isna(late) or pd.Timestamp(late) < pd.Timestamp(TEST[1], tz='UTC') + pd.Timedelta(days=10):
        raise SystemExit('the last test weeks were retrieved < 10 days after the window: late records may still arrive')
    sel = pd.read_csv(selection)
    out = Path(out)
    if out.exists():
        raise SystemExit(f'{out} exists: the final test is run once')
    out.mkdir(parents=True)
    with open(out / 'RUN_LOCK.json', 'x', encoding='utf-8') as fh:
        json.dump({'utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'protocol_sha256': psha}, fh)
        fh.flush(); os.fsync(fh.fileno())
    mt, weekly = load(dataset)
    t = rows(mt, TEST)
    f = forecasts(t, weekly[weekly.week_start <= t.origin_week_start.max()])
    s = score(f, b)
    adv = sel[sel.advances]
    acc = pd.DataFrame([{'crop': r.crop, 'horizon_weeks': r.horizon_weeks,
                         **accept(f[(f.Commodity == r.crop) & (f.horizon_weeks == r.horizon_weeks)], r.method, len(adv), b)}
                        for r in adv.itertuples()])
    files = {'by_crop.csv': s, 'acceptance.csv': acc}
    for n, x in files.items():
        x.to_csv(out / n, index=False)
    done = {'protocol_sha256': psha, 'dataset_build_manifest_sha256': sha(Path(dataset) / 'build_manifest.json'),
            'selection_sha256': sha(selection), 'outputs_sha256': {n: sha(out / n) for n in files},
            'utc': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    with open(out / 'RUN_COMPLETED.json', 'x', encoding='utf-8') as fh:
        json.dump(done, fh, indent=1)
    return s, acc


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['register']:
        print(register())
    elif a[:1] == ['validate']:
        s, sel = validate()
        print(s.round(4).to_string(index=False)); print(sel.to_string(index=False))
    elif a[:1] == ['test']:
        test(a[2] if a[1:2] == ['--confirm-single-test-run'] else '')
    else:
        print(__doc__); sys.exit(2)
