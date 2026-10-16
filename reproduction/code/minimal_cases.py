#!/usr/bin/env python3
"""Compute the constructed aggregation cases and the retained dyad metadata counts."""
from __future__ import annotations
import argparse, hashlib, json, platform, resource, sqlite3, sys, time
from pathlib import Path


def query(con, sql):
    return [list(r) for r in con.execute(sql)]


def album_recording_case():
    con=sqlite3.connect(':memory:')
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript('''CREATE TABLE album_credit(album TEXT PRIMARY KEY, artist INTEGER, producer INTEGER);
    CREATE TABLE recording(gid TEXT PRIMARY KEY, value REAL);
    CREATE TABLE track(album TEXT REFERENCES album_credit(album), position INTEGER, gid TEXT REFERENCES recording(gid), PRIMARY KEY(album, position));''')
    con.execute("INSERT INTO album_credit VALUES ('constructed_album_1',1,9)")
    con.executemany('INSERT INTO recording VALUES (?,?)', [(f'r{i:02}',float(i)) for i in range(1,13)])
    con.executemany('INSERT INTO track VALUES (?,?,?)',[('constructed_album_1',i,f'r{i:02}') for i in range(1,13)])
    sql_record='SELECT COUNT(DISTINCT r.gid) FROM album_credit a JOIN track t ON t.album=a.album JOIN recording r ON r.gid=t.gid'
    sql_album='SELECT COUNT(DISTINCT a.album) FROM album_credit a JOIN track t ON t.album=a.album JOIN recording r ON r.gid=t.gid'
    row=query(con,sql_record)[0][0]; target=query(con,sql_album)[0][0]
    return {'case':'constructed_album_credit_vs_recording_unit','input_truth':'one constructed album-credit; 12 recordings; no session truth','foreign_key_violations':query(con,'PRAGMA foreign_key_check'),'recording_count':row,'album_credit_count':target,'exact_join_row_duplicates':query(con,'SELECT COUNT(*)-COUNT(DISTINCT gid) FROM track')[0][0], 'key_only_detection':False,'declared_album_unit_disagreement':row!=target,'sql_recording':sql_record,'sql_album_credit':sql_album,'covered_by':'Declared measure grain plus multiplicity; established semantic aggregation baseline'}


def release_replication_case():
    con=sqlite3.connect(':memory:'); con.execute('PRAGMA foreign_keys=ON')
    con.executescript('''CREATE TABLE recording(gid TEXT PRIMARY KEY, value REAL); CREATE TABLE release(release TEXT PRIMARY KEY);
    CREATE TABLE track(release TEXT REFERENCES release(release), position INTEGER, gid TEXT REFERENCES recording(gid), PRIMARY KEY(release,position));''')
    con.execute("INSERT INTO recording VALUES ('r1',10)")
    con.executemany('INSERT INTO release VALUES (?)',[('rel1',),('rel2',)])
    con.executemany('INSERT INTO track VALUES (?,?,?)',[('rel1',1,'r1'),('rel2',1,'r1')])
    return {'case':'one_recording_two_releases','foreign_key_violations':query(con,'PRAGMA foreign_key_check'),'joined_rows':query(con,'SELECT COUNT(*) FROM recording r JOIN track t ON r.gid=t.gid')[0][0],'distinct_recordings':query(con,'SELECT COUNT(DISTINCT r.gid) FROM recording r JOIN track t ON r.gid=t.gid')[0][0],'recording_key_is_preserved':False,'key_only_detection':False,'covered_by':'Per-source identity counts, fanout rules, distinct grain or symmetric aggregates'}


def valid_multi_credit_case():
    members=[{'gid':'r1','artist':a,'producer':p} for a in (1,2) for p in (8,9)]
    per_producer={p:len({r['gid'] for r in members if r['producer']==p}) for p in (8,9)}
    allocation={p:sum(1/len(members) for r in members if r['producer']==p) for p in (8,9)}
    return {'case':'legal_multi_performer_multi_producer_credit','rows':members,'dyad_incidence_count':len(members),'distinct_recording_count':len({r['gid'] for r in members}),'participating_recordings_per_producer':per_producer,'fractional_mass_per_producer':allocation,'blanket_dedup_or_weighting_can_change_target':True,'correctness_requires_target_contract':True,'covered_by':'Intentional base-query duplication versus exploratory reweighing; target-dependent aggregation'}


def contamination_case():
    focal=[10.0]*12; nonfocal=[0.0]; all_rows=focal+nonfocal
    mean=sum(all_rows)/len(all_rows)
    leave_one_record=(mean*len(all_rows)-focal[0])/(len(all_rows)-1)
    old_delta=focal[0]-leave_one_record
    target_delta=focal[0]-sum(nonfocal)/len(nonfocal)
    assert abs(old_delta-target_delta/12)<1e-12
    return {'case':'leave_one_record_does_not_leave_focal_producer_out','values_are':'controlled synthetic scalars','focal_recordings':len(focal),'nonfocal_recordings':len(nonfocal),'leave_one_record_baseline':leave_one_record,'other_producer_baseline':0.0,'old_displacement':old_delta,'declared_other_producer_displacement':target_delta,'ratio_old_to_declared':old_delta/target_delta,'key_only_detection':False,'simple_support_overlap_assertion_detects':True,'covered_by':'Query/input support contract; exact producer exclusion assertion'}


def temporal_case():
    obs=[{'year':2000,'value':10.0},{'year':2010,'value':30.0}]; t0=2000; window=5
    current=[r for r in obs if abs(r['year']-t0)<=window]
    return {'case':'career_mean_vs_declared_window','values_are':'controlled synthetic scalars','event_year':t0,'window':window,'records':obs,'career_mean':sum(r['value'] for r in obs)/len(obs),'window_mean':sum(r['value'] for r in current)/len(current),'outside_window_count':sum(abs(r['year']-t0)>window for r in obs),'keys_unique':True,'simple_temporal_support_assertion_detects':True,'covered_by':'Declared temporal predicate and support assertion; not a novel event inference method'}


def local_metadata(path):
    src=json.loads(path.read_text()); rows=src['producer_rows']; t0=int(src['first_year_from_event']); counts={}
    for r in rows: counts[r['year']]=counts.get(r['year'],0)+1
    return {'case':'bounded_real_first_dyad_metadata','source_evidence':str(path),'n_rows':len(rows),'n_distinct_recordings':len({r['gid'] for r in rows}),'n_distinct_credited_years':len(counts),'rows_per_credited_year':counts,'event_year':t0,'within_W5':sum(abs(int(r['year'])-t0)<=5 for r in rows),'outside_W5':sum(abs(int(r['year'])-t0)>5 for r in rows),'highest_rank_before_feature_filter':len(rows),'known_album_or_session_id':False,'old_regression_replayed':False,'old_complete_case_membership_tested':False,'meaning':'Prefix rows expose ranking and support candidates, not the final regression sample or real session count.'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--local-metadata',type=Path);args=ap.parse_args()
    start=time.perf_counter();cases=[album_recording_case(),release_replication_case(),valid_multi_credit_case(),contamination_case(),temporal_case()]
    if args.local_metadata: cases.append(local_metadata(args.local_metadata))
    assert cases[0]['recording_count']==12 and cases[0]['album_credit_count']==1
    assert cases[1]['joined_rows']==2 and cases[1]['distinct_recordings']==1
    assert cases[2]['dyad_incidence_count']==4 and cases[2]['distinct_recording_count']==1
    assert all(v==1 for v in cases[2]['participating_recordings_per_producer'].values())
    assert cases[4]['career_mean']==20 and cases[4]['window_mean']==10
    out={'schema':'counting_units_minimal_cases_v1','case_results':cases,'scope':'mechanism verification and baseline coverage; no corpus detection rate or novel-method claim','execution':{'python':sys.version,'platform':platform.platform(),'sqlite':sqlite3.sqlite_version,'command':sys.argv,'elapsed_seconds':time.perf_counter()-start,'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({'cases':len(cases),'all_assertions_passed':True,'output':str(args.output),'elapsed_seconds':out['execution']['elapsed_seconds']},indent=2))

if __name__=='__main__':main()
