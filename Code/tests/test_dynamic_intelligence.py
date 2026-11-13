"""Dynamic discovery, state classification and atomic serving contracts."""
import json
from datetime import timedelta
import pandas as pd
import pytest
from Code.daily.dataset import write_json
from Code.api import daily
from Code.intelligence import discovery,service as s,explanations as ex
from Code.intelligence.states import state_id,mode


def test_discovery_inventory_is_not_a_twenty_crop_forecast_allowlist(tmp_path,monkeypatch):
    monkeypatch.setattr(discovery,'ROOT',tmp_path);monkeypatch.setattr(discovery,'DAILY',tmp_path/'daily')
    inventory=tmp_path/'Dataset/India Commodity Wise Mandi Dataset';inventory.mkdir(parents=True)
    (inventory/'New commodity.csv').write_text('Not audited')
    rows=[]
    for i in range(25):
        folder=discovery.DAILY/f'archive/{i}';folder.mkdir(parents=True)
        for name in ('series.parquet','observations.parquet'):(folder/name).write_bytes(b'fixture')
        rows.append({'crop':f'Crop {i}','storage':f'archive/{i}','category':'Unclassified','usable_records':200,'daily_eligible_series':1})
    pd.DataFrame(rows).to_csv(discovery.DAILY/'crop_ranking.csv',index=False)
    write_json(discovery.DAILY/'refresh_manifest.json',{'partitions':{'one':{'crop':'Accepted new crop','date':'2026-11-11','records':10}}})
    result=discovery.discover()
    assert result['discovered_count']==27 and result['historical_count']==25
    assert len(result['crops'])==26
    assert next(r for r in result['discovery'] if r['crop']=='New commodity')['status']=='discovered'
    assert next(r for r in result['crops'] if r['crop']=='Accepted new crop').get('storage') is None


@pytest.mark.parametrize('a,b,expected',[('Orissa','Odisha','intrastate'),(' HR ','Haryana','intrastate'),('Haryana','Punjab','interstate'),('NCT of Delhi','Delhi','intrastate'),('','',None),(None,'Punjab',None),('Unknown','Unknown',None)])
def test_state_identifiers_and_missing_values(a,b,expected):assert mode(a,b)==expected


@pytest.fixture
def market_prices(monkeypatch):
    rows=[]
    for i,(crop,state) in enumerate([('Onion','Haryana'),('Onion','HR'),('Onion','Punjab'),('Potato','Gujarat'),('Potato','Madhya Pradesh'),('Onion','Unknown')]):
        rows.append({'series_id':str(i),'crop':crop,'state':state,'district':'D','market':f'Market {i}','variety':'Other','grade':'FAQ','source':'datagov','predicted_modal_price':1000+i*100,'last_observation_date':'2026-11-11','data_freshness':{'age_days':2},'coordinate':{'node':str(i),'lat':20+i,'lng':75,'precision':'Approximate'}})
    monkeypatch.setattr(s,'current_prices',lambda:rows)
    monkeypatch.setattr(s,'market_coordinate',lambda row:row['coordinate'])
    monkeypatch.setattr(s.daily,'snapshot',lambda:({},None,None,{'dataset_version':'new-version','sha256':'batch'}))
    monkeypatch.setattr(ex,'quality_for',lambda _:None)
    monkeypatch.setattr(s,'route_options',lambda a,b:[{'km':100.,'hours':2.,'objective':'approximate','basis':'Approximate distance scenario','origin':a,'destination':b}])
    return rows


def test_independent_rankings_and_dynamic_filters(market_prices):
    result=s.strategies(details=True)
    assert result['groups']['intrastate']['candidate_count']==2
    assert result['groups']['interstate']['candidate_count']==6
    assert result['candidate_count']==8
    assert result['filters']['crops']==['Onion','Potato']
    assert {r['id'] for r in result['filters']['states']}=={'HR','PB','GJ','MP'}
    assert result['dataset_version']=='new-version' and result['batch_id']=='batch'
    for category,group in result['groups'].items():
        assert all(r['trading_mode']==category for r in group['rows'])
        assert group['best']['decision']['scope']=='category_recommendation'
        assert all(r['buy']['grade']==r['sell']['grade'] for r in group['rows'])


@pytest.mark.parametrize('integrated', [False, True])
def test_invalid_filters_do_not_broaden_mode_both(market_prices, integrated):
    for filters in ({'crop': 'Brinjal'}, {'state': 'Unknown'}, {'crop': 'Onion', 'state': 'Gujarat'}):
        result = s.strategies(**filters, details=True, integrated=integrated)
        assert result['rows'] == []
        assert result['candidate_count'] == 0
        assert all(result['effective_filters'][key] for key in filters)


def test_valid_strategy_filters_are_crop_and_state_scoped(market_prices):
    result=s.strategies(crop='Onion',state='Gujarat',details=True)
    assert {r['id'] for r in result['filters']['states']}=={'HR','PB'}
    assert result['effective_filters']['state']=='GJ'
    result=s.strategies(crop='Onion',state='HR',mode='intrastate',details=True)
    assert result['candidate_count']==2
    assert all(state_id(r['buy']['state'])=='HR' and r['trading_mode']=='intrastate' for r in result['rows'])


def test_empty_category_and_changed_compatibility_do_not_invent_pairs(market_prices):
    market_prices[1]['grade']='Different';market_prices[2]['source']='archive'
    result=s.strategies(crop='Potato',details=True)
    assert result['groups']['intrastate']['best'] is None
    assert result['groups']['intrastate']['empty_reason']
    assert result['groups']['interstate']['best']
    assert 'Onion' not in result['strategy_ready_crops']
    market_prices.clear()
    assert s.strategies(details=True)['rows']==[]


def test_region_aliases_and_unique_reference(monkeypatch):
    assert state_id('Andaman and Nicobar') == 'AN'
    assert state_id('Uttrakhand') == 'UK'
    assert state_id('Keralam') == 'KL'
    node = {'node_id': 'D:district', 'state': 'Uttarakhand', 'district': 'Dehradun',
            'latitude': 30, 'longitude': 78}
    nodes = [node]
    monkeypatch.setattr(s, 'nodes', lambda: nodes)
    assert s.coordinate('Uttrakhand', ' Dehradun ')['node'] == 'D:district'
    assert s.coordinate('Uttarakhand', 'Unknown') is None
    nodes.append({**node, 'node_id': 'D:other'})
    assert s.coordinate('Uttrakhand', 'Dehradun') is None


def test_planned_regions_use_feasible_trades_before_limits(market_prices, monkeypatch):
    from Code.intelligence import roads

    monkeypatch.setattr(s, 'warehouses', lambda: [])
    monkeypatch.setattr(roads, 'cached_geometry', lambda *args: None)
    monkeypatch.setitem(s.CONFIG['planning'], 'storage_pairs_per_mode', 1)
    result = s.strategies(mode='interstate', details=True, integrated=True)
    assert len(result['rows']) == 1
    assert result['groups']['interstate']['feasible_candidate_count'] == 6
    assert result['groups']['interstate']['evaluated_candidate_count'] == 1
    assert {r['id'] for r in result['filters']['states']} == {'HR', 'PB', 'GJ', 'MP'}
    result = s.strategies(crop='Potato', state='GJ', mode='interstate', details=True, integrated=True)
    assert {r['id'] for r in result['filters']['states']} == {'GJ', 'MP'}
    assert result['rows'][0]['buy_state_id'] == 'GJ'
    for state in ('GJ', 'unrecognized'):
        result = s.strategies(crop='Potato', state=state, mode='intrastate', details=True, integrated=True)
        assert not result['filters']['states'] and not result['rows']
        assert result['effective_filters']['state'] == state
        assert 'No eligible purchase market' in result['empty_explanation']

    # Different quote series at the same market are insufficient for a journey.
    market_prices[1]['market'] = market_prices[0]['market']
    result = s.strategies(mode='intrastate', details=True, integrated=True)
    assert not result['filters']['states'] and not result['rows']
    result = s.strategies(mode='interstate', quantity=100000, details=True, integrated=True)
    assert not result['filters']['states'] and not result['rows']


def test_shared_operating_assumptions_recalculate_both_categories(market_prices):
    result=s.strategies(quantity=250,capacity_q=80,rs_km=10,handling=30,loss=5,details=True)
    assert all(g['best'] for g in result['groups'].values())
    for row in result['rows']:
        assert row['trips']==4 and row['payload_q']==80
        assert row['transport']==4000 and row['handling']==7500
        assert row['quantity_q']==250 and row['handling_loss_pct']==5


def test_selected_eligible_pair_is_retained_below_visible_shortlist(market_prices):
    base=market_prices[0]
    market_prices.extend({**base,'series_id':f'extra{i}','market':f'Extra {i}','predicted_modal_price':3000+i*100} for i in range(11))
    chosen='extra10:0'
    result=s.strategies(selected_id=chosen,details=True)
    selected=next(r for r in result['rows'] if r['id']==chosen)
    assert selected['decision']['scope']=='selected_alternative'
    assert result['groups']['intrastate']['best']['id']!=chosen
    changed=s.strategies(selected_id=chosen,quantity=250,details=True)
    assert next(r for r in changed['rows'] if r['id']==chosen)['quantity_q']==250


def test_source_only_crop_can_enter_a_release_without_an_archive_quota(tmp_path,monkeypatch):
    from Code.daily import operational as op
    from Code.daily.dataset import sha
    monkeypatch.setattr(op,'ROOT',tmp_path);monkeypatch.setattr(op,'OUT',tmp_path/'daily')
    folder=op.OUT/'recent/new';folder.mkdir(parents=True)
    pd.DataFrame([{'series_id':'new','state':'Haryana','district':'D','market':'M','variety':'V','source':'datagov','grade':'FAQ'}]).to_parquet(folder/'series.parquet')
    pd.DataFrame([{'series_id':'new','date':pd.Timestamp('2026-11-11'),'price':1200}]).to_parquet(folder/'observations.parquet')
    source={'crop':'New commodity','storage':'recent/new','source_path':['accepted.json'],'source_sha256':'source','observations_sha256':sha(folder/'observations.parquet')}
    monkeypatch.setattr(op,'import_recent',lambda crop:source)
    dest,manifest=op.release(publish=False,catalog_override={'crops':[{'crop':'New commodity','category':'Unclassified'}]})
    assert manifest['sources'][0]['storage']=='recent/new'
    assert pd.read_parquet(dest/'registry.parquet').crop.tolist()==['New commodity']
    assert not (op.OUT/'release.json').exists()


def test_served_pointer_survives_in_progress_or_failed_refresh(tmp_path,monkeypatch):
    monkeypatch.setattr(daily,'OUT',tmp_path)
    old={'release':{'release':'old'},'batch':{'sha256':'old-batch'},'auxiliary':{'coverage':'immutable/coverage.json'}}
    write_json(tmp_path/'serving.json',old)
    write_json(tmp_path/'batch.json',{'sha256':'new-uncommitted'})
    assert daily.serving()==old
    assert daily.auxiliary_path('coverage',tmp_path/'coverage.json')==tmp_path/'immutable/coverage.json'
    token=daily.BUILDING.set(True)
    try:assert daily.serving() is None
    finally:daily.BUILDING.reset(token)
    assert daily.serving()['batch']['sha256']=='old-batch'


def test_new_commodity_uses_unchanged_market_series_eligibility():
    from Code.daily.operational import forecast_source
    from Code.daily.policy import now_ist
    issue=pd.Timestamp(now_ist());target=pd.Timestamp(issue.date())
    dates=pd.date_range(target-pd.Timedelta(days=370),target-pd.Timedelta(days=1),periods=200).normalize().unique()
    h=pd.DataFrame({'series_id':'new-crop','date':dates,'price':1200.,'available_at':str(issue-timedelta(hours=1)),'source_row':'synthetic','availability_basis':'actual_retrieval_timestamp'})
    registry=pd.DataFrame([{'series_id':'new-crop','crop':'New validated commodity','category':'Unclassified','state':'Haryana','district':'D','market':'M','variety':'V','source':'datagov','grade':'FAQ'}]).set_index('series_id')
    assert forecast_source(h,registry,issue,'new-release')[0]['predicted_modal_price']==1200
    short=forecast_source(h.tail(50),registry,issue,'new-release')[0]
    assert short['predicted_modal_price'] is None and short['status']=='insufficient_history'
    assert s._crop_storage('Unknown','Unclassified')=='unsupported'


def test_failed_new_publication_retains_prices_catalog_and_filter_views(tmp_path,monkeypatch):
    from Code.intelligence import pipeline as p
    monkeypatch.setattr(p,'DAILY',tmp_path/'daily');p.DAILY.mkdir()
    monkeypatch.setattr(p,'OUT',tmp_path/'intelligence');monkeypatch.setattr(p,'STATE',tmp_path/'state')
    monkeypatch.setattr(ex,'QUALITY',tmp_path/'quality.json');monkeypatch.setattr(daily,'OUT',p.DAILY)
    catalog={'crops':[{'crop':'Tomato'}]}
    monkeypatch.setattr(p,'catalog',lambda:catalog);monkeypatch.setattr(p,'discover',lambda:catalog)
    write_json(p.DAILY/'release.json',{'release':'old'})
    write_json(p.DAILY/'batch.json',{'sha256':'old','path':'old.sqlite','dataset_version':'old','target_date':str(p.now_ist().date())})
    write_json(p.STATE/'coverage.json',{'dataset_version':'old','crops':['Tomato']})
    write_json(p.STATE/'last_success.json',{'dataset_version':'old'})
    p.publish_serving_snapshot()
    old={path:path.read_bytes() for path in (p.DAILY/'release.json',p.DAILY/'batch.json',p.DAILY/'serving.json',p.STATE/'coverage.json',p.STATE/'last_success.json')}
    dest=tmp_path/'new';dest.mkdir();write_json(dest/'manifest.json',{})
    monkeypatch.setattr(p.op,'release',lambda **kwargs:(dest,{}))
    monkeypatch.setattr(p.op,'batch',lambda **kwargs:write_json(p.DAILY/'batch.json',{'sha256':'new','target_date':str(p.now_ist().date())}))
    def fail_after_new_coverage():
        write_json(p.STATE/'coverage.json',{'dataset_version':'new','crops':['Uncommitted']})
        raise ValueError('Injected publication failure')
    monkeypatch.setattr(p,'audit',fail_after_new_coverage)
    with pytest.raises(ValueError,match='Injected publication failure'):p.run(batch_only=True)
    assert all(path.read_bytes()==content for path,content in old.items())
    assert daily.serving()['batch']['dataset_version']=='old'
    assert json.loads(daily.auxiliary_path('coverage',None).read_text())['crops']==['Tomato']
    assert not (p.DAILY/'update.lock').exists()
