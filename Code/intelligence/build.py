"""Reproduce the quota-free catalog; optionally evaluate only 2010–2018 data."""
import argparse
import json
import pandas as pd
from Code.daily.dataset import OUT as DAILY, ROOT, write_json, sha

OUT = ROOT / 'Processed_Data/intelligence_v1'


def build(evaluate=False):
    from .discovery import build as discover
    catalog=discover()
    if evaluate:
        from Code.daily import evaluate as ev
        # New destination. The historical source archives remain read-only.
        ev.OUT = OUT
        entries = [{**r, 'storage': str((DAILY / r['storage']).resolve())} for r in catalog['crops'] if r.get('storage')]
        ev.study({'crops': entries})
    print(json.dumps({'crops': [r['crop'] for r in catalog['crops']], 'evaluation': evaluate}, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evaluate', action='store_true')
    build(p.parse_args().evaluate)
