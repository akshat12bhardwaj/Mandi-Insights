"""Incremental data.gov.in price stages after S3 (D-56), run with the unchanged S1-S3 extractor.

`datagov_extract.py`, `price_policy.py` and `build_candidate_prices.py` are bound by the D-52 freeze, so they are not
edited. This module rebinds two of the extractor's module globals for the duration of one run:
  STAGES -> S1-S3 plus the INCREMENTS below (the S1-S3 definitions are untouched);
  OUT    -> Processed_Data/candidates/datagov_prices/increments/  (its own crop-day manifest, request log and reports),
so the S1-S3 manifest that candidate-prices-v1.1 hashes as an input is never rewritten. Raw responses go to the same
raw folder under new dates (a date already held is never re-fetched by a stage; see `revisions` for that).

Every increment uses the S1-S3 acceptance rule: two fetches per crop-day, count == total == distinct, identical sets,
no malformed records, one state-partition check per stage.

Usage (repo root):
  python -m Code.candidates.datagov_increment S4 [--dry-run]
  python -m Code.candidates.datagov_increment revisions S4     # re-fetch the probe days once, log differences only
"""
import csv, json, sys
from datetime import datetime, timezone
from pathlib import Path

from Code.candidates import datagov_extract as de

# Each increment ends on a Sunday at least 3 days before retrieval, so late-arriving reports have had time to land
# (the API's updated_date ran ~2 days behind on 2026-10-24). shortcut: fixed lag, measured by `revisions`; upgrade to a
# rule derived from the revision log once several increments exist.
INCREMENTS = {
    'S4': {'start': '2026-10-21', 'end': '2026-10-25', 'crop_days': 15, 'budget': 80, 'partitions': [('Onion', '2026-10-22')],
           'revision_probe': ['2026-10-18', '2026-10-19', '2026-10-20']},
}
OUT = de.OUT / 'increments'


def stages():
    clash = set(INCREMENTS) & set(de.STAGES)
    assert not clash, f'increment names reuse frozen stages: {clash}'
    last = max(s['end'] for s in de.STAGES.values())
    for name, s in sorted(INCREMENTS.items()):
        assert s['start'] > last, f'{name} overlaps earlier stages (starts {s["start"]}, previous end {last})'
        last = s['end']
    return {**de.STAGES, **{k: {x: v for x, v in s.items() if x != 'revision_probe'} for k, s in INCREMENTS.items()}}


def run_stage(argv):
    de.STAGES, de.OUT = stages(), OUT      # rebinding, not mutation: the frozen STAGES dict object is unchanged
    sys.argv = ['datagov_increment'] + argv
    return de.main()


def revisions(stage):
    """One fetch per crop of each probe day (already held from an earlier stage); compare with the held raw file.
    Writes revision_log.csv only. The held raw files and every built dataset are left exactly as they are."""
    root = Path.cwd(); key = de.load_key(root)
    if not key:
        print('No key. Not run.'); return 2
    out = root / OUT; out.mkdir(parents=True, exist_ok=True)
    path = out / 'revision_log.csv'; new = not path.exists()
    rows = []
    for d in INCREMENTS[stage]['revision_probe']:
        for c in de.CROPS:
            held = json.loads(de.raw_paths(root / de.RAW, c, d)[0].read_bytes())['records']
            code, body, secs = de.api_get(key, json.loads(de.params(c, d)))
            if de.classify(code, body) != 'ok':
                rows.append([stage, c, d, len(held), '', '', '', f'http {code}', datetime.now(timezone.utc).isoformat(timespec='seconds')])
                continue
            now = json.loads(body)['records']
            a, b = {de.rid(r) for r in held}, {de.rid(r) for r in now}
            rows.append([stage, c, d, len(held), len(now), len(b - a), len(a - b), 'ok', datetime.now(timezone.utc).isoformat(timespec='seconds')])
    with open(path, 'a', newline='') as fh:
        w = csv.writer(fh, lineterminator='\n')
        if new:
            w.writerow(['stage', 'commodity', 'date', 'held_records', 'refetched_records', 'added', 'removed', 'outcome', 'utc'])
        w.writerows(rows)
    print(json.dumps(rows, indent=1))
    return 0


if __name__ == '__main__':
    a = sys.argv[1:]
    sys.exit(revisions(a[1]) if a[:1] == ['revisions'] else run_stage(a))
