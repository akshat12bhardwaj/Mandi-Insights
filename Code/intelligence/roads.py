"""Directed road paths on the existing local OSM graph; no network requests."""
import json
from functools import lru_cache
from threading import Lock
import hashlib
import os
import numpy as np
import pandas as pd
from shapely.geometry import LineString
from Code.routing import network as nw,pipeline as pl
from Code.routing.router import shortest_from,path,edge_sum
from Code.daily.dataset import write_json,sha
from .build import OUT

DEST=OUT/'phase3/roads_v1'
_route_lock = Lock()
_recent_paths = {}
_path_revision = 0


def path_revision():
    return _path_revision


def cached_geometry(points, objective):
    from Code.routing.osm import OSM_DIR, SNAPSHOT
    key = (points, objective)
    if key in _recent_paths:
        return _recent_paths[key]
    name = hashlib.sha256(repr(key).encode()).hexdigest()
    file = OSM_DIR / f'journey-paths-{SNAPSHOT}' / (name + '.json')
    try:
        return json.loads(file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=1)
def _road_network():
    from Code.routing import osm
    files = [osm.zone_dir(zone) / member for zone in osm.ZONES for member in osm.MEMBERS[:2]]
    if not all(file.exists() for file in files):
        return None
    import joblib
    from scipy.spatial import cKDTree
    signature = hashlib.sha256(repr([(str(file), file.stat().st_mtime_ns, file.stat().st_size) for file in files]).encode()).hexdigest()[:16]
    cached = osm.OSM_DIR / f'journey-graph-v1-{signature}.joblib'
    try:
        graph = joblib.load(cached, mmap_mode='r')
    except (OSError, ValueError, EOFError):
        graph = nw.build_graph(nw.load_lines())
        temporary = cached.with_suffix(f'.{os.getpid()}.tmp')
        try:
            joblib.dump(graph, temporary)
            temporary.replace(cached)
        except OSError:
            temporary.unlink(missing_ok=True)
    core = np.flatnonzero(graph.in_core & graph.two_way)
    return graph, core, cKDTree(pl._xyz(graph.lat[core], graph.lon[core]))


def local_geometry(origin, destination, objective, warehouse=None):
    global _path_revision
    points = (origin, warehouse, destination) if warehouse else (origin, destination)
    with _route_lock:
        cached = cached_geometry(points, objective)
        if cached is not None:
            return cached
        result = _local_geometry(points, objective)
        if result['geometry']:
            from Code.routing.osm import OSM_DIR, SNAPSHOT
            if len(_recent_paths) >= 256:
                _recent_paths.pop(next(iter(_recent_paths)))
            _recent_paths[(points, objective)] = result
            _path_revision += 1
            name = hashlib.sha256(repr((points, objective)).encode()).hexdigest()
            file = OSM_DIR / f'journey-paths-{SNAPSHOT}' / (name + '.json')
            try:
                file.parent.mkdir(parents=True, exist_ok=True)
                write_json(file, result)
            except OSError:
                pass
        return result


@lru_cache(maxsize=256)
def _local_geometry(points, objective):
    network = _road_network()
    if network is None:
        return {'geometry': None}
    graph, core, tree = network
    lat, lon = np.asarray(points).T
    _, neighbors = tree.query(pl._xyz(lat, lon))
    vertices = core[neighbors]
    from Code.routing.router import haversine_km
    gaps = haversine_km(lat, lon, graph.lat[vertices], graph.lon[vertices])
    if any(gaps > pl.MAX_ACCESS_GAP_KM):
        return {'geometry': None}
    line = []
    stop_index = None
    km = hours = inbound_hours = 0
    for a, b in zip(vertices, vertices[1:]):
        _, pred = shortest_from(graph.time if objective == 'fastest' else graph.dist, int(a))
        seq = path(pred, int(a), int(b))
        if not seq or len(seq) < 2:
            return {'geometry': None}
        km += edge_sum(graph.dist, seq)
        hours += edge_sum(graph.time, seq)
        geometry = LineString(np.column_stack([graph.lon[seq], graph.lat[seq]])).simplify(pl.SIMPLIFY_DEG)
        leg = np.round(np.asarray(geometry.coords)[:, ::-1], 5).tolist()
        if line:
            stop_index = len(line) - 1
        else:
            inbound_hours = hours
        line.extend(leg[1:] if line else leg)
    return {'geometry': line, 'stop_index': stop_index, 'road_km': round(km, 1),
            'road_hours': round(hours, 2), 'inbound_hours': round(inbound_hours, 2), 'source': 'Local OpenStreetMap road graph'}


@lru_cache(maxsize=2)
def _load(signature):
    manifest=json.loads((DEST/'manifest.json').read_text())
    if sha(DEST/'routes.parquet')!=manifest['route_sha256']:raise ValueError('Directed route artifact checksum mismatch')
    table=pd.read_parquet(DEST/'routes.parquet')
    return {(r['origin'],r['destination'],r['objective']):r for r in table.to_dict('records')}


def saved(origin,destination):
    file=DEST/'routes.parquet'
    if not file.exists() or not (DEST/'manifest.json').exists():return []
    data=_load(file.stat().st_mtime_ns)
    return [data[(origin,destination,o)] for o in ('shortest','fastest') if (origin,destination,o) in data]


def geometry(origin,destination,objective):
    rows=saved(origin,destination)
    row=next((r for r in rows if r['objective']==objective),None)
    return json.loads(row['geometry']) if row else None


def build():
    from . import service as s
    if (DEST/'manifest.json').exists():print('Existing directed routing cache retained.');return
    endpoints={}
    market={r['node_id']:r for r in s.nodes()}
    facilities=s.warehouses()
    # Focus finite offline computation on current leading trades in every crop.
    for crop in sorted({r['crop'] for r in s.current_prices()}):
        rows,_=s.strategies(crop=crop)
        for scenario in rows[:2]:
            for side in ('buy','sell'):
                key=scenario[side]['coordinate']['node'];r=market[key]
                endpoints[key]={'id':key,'lat':r['latitude'],'lng':r['longitude'],'kind':'market_reference','source':r.get('location_meaning','District reference')}
        if rows:
            a=rows[0]['buy']['coordinate']
            compatible=[w for w in facilities if crop in w['supported_crops'] and w['free_t']>=10]
            if compatible:
                w=min(compatible,key=lambda w:s.distance(a,{'lat':w['latitude'],'lng':w['longitude']}))
                endpoints[w['warehouse_id']]={'id':w['warehouse_id'],'lat':w['latitude'],'lng':w['longitude'],'kind':'warehouse','source':'Existing reported OSM facility point/outline centroid'}
    if not endpoints:return
    DEST.mkdir(parents=True,exist_ok=True);write_json(DEST/'endpoints.json',list(endpoints.values()))
    print('Loading existing OSM roads for',len(endpoints),'endpoints',flush=True)
    graph=nw.build_graph(nw.load_lines())
    rows=list(endpoints.values());vertices,gaps=pl.snap_points(np.array([r['lat'] for r in rows]),np.array([r['lng'] for r in rows]),graph)
    results=[]
    for i,origin in enumerate(rows):
        if gaps[i]>pl.MAX_ACCESS_GAP_KM:continue
        for objective,weight in [('shortest',graph.dist),('fastest',graph.time)]:
            _,pred=shortest_from(weight,int(vertices[i]))
            for j,dest in enumerate(rows):
                if i==j or gaps[j]>pl.MAX_ACCESS_GAP_KM:continue
                seq=path(pred,int(vertices[i]),int(vertices[j]))
                if not seq or len(seq)<2:continue
                line=LineString(np.column_stack([graph.lon[seq],graph.lat[seq]])).simplify(pl.SIMPLIFY_DEG)
                results.append({'origin':origin['id'],'destination':dest['id'],'objective':objective,
                                'road_km':round(edge_sum(graph.dist,seq),3),'road_hours':round(edge_sum(graph.time,seq),3),
                                'origin_gap_km':float(gaps[i]),'destination_gap_km':float(gaps[j]),
                                'geometry':json.dumps(np.round(np.asarray(line.coords)[:,::-1],5).tolist(),separators=(',',':'))})
        print('Directed paths from',origin['id'],flush=True)
    frame=pd.DataFrame(results);frame.to_parquet(DEST/'routes.parquet',index=False)
    write_json(DEST/'manifest.json',{'version':'directed-operational-roads-v1','snapshot':'2026-10-22','endpoints':len(rows),'directed_route_options':len(frame),
                                   'route_sha256':sha(DEST/'routes.parquet'),'graph':graph.stats,
                                   'precision':'Road network between snapped references; access gaps are not verified entrance roads','attribution':'© OpenStreetMap contributors, ODbL; Geofabrik extracts'})


if __name__=='__main__':build()
