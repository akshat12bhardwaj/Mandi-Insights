"""Paginated daily refresh, bounded backfill, and offline publication."""
import argparse
import json
from .pipeline import run


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--batch-only',action='store_true')
    p.add_argument('--backfill',action='store_true')
    p.add_argument('--lookback-days',type=int,default=7)
    p.add_argument('--budget',type=int,default=280)
    p.add_argument('--max-mb',type=int,default=50)
    p.add_argument('--crop',action='append',help='Prioritize one or more supported crops for bounded backfill')
    a=p.parse_args()
    try:
        result=run(a.lookback_days,a.budget,a.max_mb,a.execute,a.batch_only,a.backfill,crops=a.crop)
        print(json.dumps(result,indent=2))
        if result.get('status') in ('updated','unchanged','partial_update'):
            from .learning import dispatch
            dispatch()
        if result.get('status') in ('failed_previous_snapshot_retained','partial_update'):raise SystemExit(2)
    except (ValueError,OSError):
        p.exit(1,'Refresh stopped; previous valid publication retained. Inspect local sanitized refresh status.\n')


if __name__=='__main__':main()
