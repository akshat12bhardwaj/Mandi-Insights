"""Explain pair support by stage, keeping compatibility separate from mapping."""
from collections import Counter,defaultdict
from . import service as s
from .states import state_id,mode

def audit():
    prices=s.current_prices();result=[]
    for crop in sorted({r['crop'] for r in prices}):
        rows=[r for r in prices if r['crop']==crop]
        mapped=[r for r in rows if s.market_coordinate(r) and state_id(r['state'])]
        def counts(values):
            count=Counter()
            for a in values:
                for b in values:
                    if a['series_id']!=b['series_id'] and all(a[k]==b[k] for k in ('crop','variety','grade','source')):
                        category=mode(a['state'],b['state'])
                        if category:count[category]+=1
            return {m:count[m] for m in ('intrastate','interstate')}
        raw=counts(rows);usable=counts(mapped)
        groups=defaultdict(set)
        for r in rows:groups[(r['variety'],r['grade'],r['source'])].add(state_id(r['state']))
        reasons={}
        for category in ('intrastate','interstate'):
            if usable[category]:reasons[category]=f"{usable[category]} mapped compatible pairs. Approximate logistics are allowed; an exact road path is not required."
            elif raw[category]:reasons[category]=f"{raw[category]} compatible pairs exist before mapping, but at least one endpoint lacks an accepted location reference."
            else:reasons[category]='No exact crop, variety, grade and source match exists '+('across recognized states.' if category=='interstate' else 'within a recognized state.')
        result.append({'crop':crop,'forecasts':len(rows),'mapped_forecasts':len(mapped),'states':dict(Counter(r['state'] for r in rows)),
                       'mapped_states':dict(Counter(r['state'] for r in mapped)),'raw_compatible_pairs':raw,'eligible_pairs':usable,
                       'compatibility_groups':[{'variety':k[0],'grade':k[1],'source':k[2],'state_ids':sorted(v- {None})} for k,v in groups.items()],
                       'reasons':reasons,'unknown_state_forecasts':sum(state_id(r['state']) is None for r in rows)})
    return result
