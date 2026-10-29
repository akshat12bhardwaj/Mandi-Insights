"""Build `candidate-prices-v1.2` (D-56): candidate-prices-v1.1's rules unchanged, plus the accepted increments (S4+).

`build_candidate_prices.py` and `price_policy.py` are bound by the D-52 freeze, so they are not edited. This wrapper
runs the frozen builder with four rebound module globals:
  VERSIONS      + 'v1.2' (same switches as v1.1; dest dataset_v1_2/)
  STAGES        S1-S3 plus the increments (Code/candidates/datagov_increment.py)
  LAST_WEEK     the Monday of the last complete week inside the increments
  load_accepted reads each stage's crop-days from its own manifest (S1-S3: the frozen one; S4+: increments/)
v1, v1.1 and every D-52 artefact are untouched. Identities: only the 440 approved D-50 pairs; markets first seen in an
increment stay their own identity. After the build, the increments manifest hash and the source/licence evidence are
added to build_manifest.json.

Usage (repo root): python -m Code.candidates.build_prices_v1_2 [--dest <folder>]
"""
import json, sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from Code.candidates import build_candidate_prices as b, datagov_extract as de, datagov_increment as inc, price_policy as pp

VERSION = {'version': 'candidate-prices-v1.2', 'dest': 'dataset_v1_2', 'd41_full_count': True, 'dedup_type_variants': True,
           'changes': b.VERSIONS['v1.1']['changes'] + [
               'B1 (D-56): adds the accepted increment stages after S3 (S4: 2026-10-21 .. 2026-10-25), fetched and accepted with the '
               'S1-S3 rule into their own manifest; weekly cells extend to the last complete week. No rule, threshold, identity or '
               'grade decision changed. Late-arriving records are not back-filled into held days (revision_log.csv)']}
SOURCE = {'resource_id': '35985678-0d79-46b4-9ed6-6f13308a1d24', 'title': 'Variety-wise Daily Market Prices Data of Commodity',
          'publisher': 'Directorate of Marketing and Inspection (DMI), Department of Agriculture and Farmers Welfare, MoA&FW',
          'portal': 'data.gov.in (Open Government Data Platform India)',
          'licence_evidence': 'resource page field_data_licence is empty; the portal footer states "Content is owned by the respective '
                              'Ministries/Departments/Organizations and licensed under the Government Open Data License-India." '
                              '(page retrieved 2026-10-29, Dataset_Candidates/datagov_licence/2026-10-29/)',
          'licence_status': 'portal-level GODL-India statement only; no resource-specific licence stated. Local analysis and the '
                            'local application only; record-level and derived tables are not committed or redistributed (D-56)'}
SOURCE_BREAKS = [{'date': '2024-02-03', 'what': 'source changes from the archived AGMARKNET copy to data.gov.in retrievals'},
                 {'date': '2025-11-07', 'what': 'Agmarknet 2.0 relaunch: market renaming and a new grade taxonomy; most market '
                                                'histories are not linked across it'}]


def last_week(stages):
    """Monday of the last complete Monday-Sunday week inside the stages' date range."""
    end = date.fromisoformat(max(s['end'] for s in stages.values()))
    sunday = end - timedelta(days=(end.weekday() + 1) % 7)
    return (sunday - timedelta(days=6)).isoformat()


def load_accepted(root, stages):
    """price_policy.load_accepted, with each stage's crop-days read from that stage's own manifest."""
    frames, used = [], 0
    mans = {False: de.read_manifest(root / de.OUT / 'crop_day_manifest.csv'), True: de.read_manifest(root / inc.OUT / 'crop_day_manifest.csv')}
    for s in stages:
        man = mans[s in inc.INCREMENTS]
        for d in de.stage_days(b.STAGES[s]['start'], b.STAGES[s]['end']):
            for c in de.CROPS:
                row = man.get((c, d))
                if not row or row['status'] != 'pass':
                    raise SystemExit(f'{c} {d} is not an accepted crop-day ({row["status"] if row else "missing"}); stage {s} incomplete')
                recs = json.loads(de.raw_paths(root / de.RAW, c, d)[0].read_bytes())['records']
                frames.append(pd.DataFrame(recs, dtype=str).assign(
                    source_stage=s, content_sha256=row['content_sha256'], retrieved_utc=row['retrieved_utc'],
                    raw_index=range(len(recs)), raw_value_types=['str' if isinstance(r.get('Modal_Price'), str) else 'num' for r in recs]))
                used += 1
    return pd.concat(frames, ignore_index=True), used


def main(argv=None):
    stages = inc.stages()
    b.VERSIONS = {**b.VERSIONS, 'v1.2': VERSION}
    b.STAGES, b.LAST_WEEK, pp.load_accepted = stages, last_week(stages), load_accepted
    argv = list(argv or [])
    rc = b.main(['--version', 'v1.2'] + argv)
    dest = Path(argv[argv.index('--dest') + 1]) if '--dest' in argv else Path.cwd() / b.OUT / VERSION['dest']
    m = json.loads((dest / 'build_manifest.json').read_text())
    m['inputs']['increments_crop_day_manifest'] = b.file_sha(Path.cwd() / inc.OUT / 'crop_day_manifest.csv')
    m.update(source=SOURCE, source_breaks=SOURCE_BREAKS, weeks=[b.FIRST_WEEK, b.LAST_WEEK])
    (dest / 'build_manifest.json').write_text(json.dumps(m, indent=1, default=str))
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
