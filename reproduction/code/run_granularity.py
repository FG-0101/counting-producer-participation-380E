#!/usr/bin/env python3
"""Scan producer credits and compute the count targets and fixed-support joins."""
from __future__ import annotations
import argparse, csv, gzip, hashlib, json, os, platform, resource, sqlite3, sys, time
from pathlib import Path
for var in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):os.environ[var]='1'
import numpy as np


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()


def scalar(db,sql):return db.execute(sql).fetchone()[0]
def rows(db,sql,args=()):return [list(r) for r in db.execute(sql,args)]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--credits',required=True,type=Path)
    ap.add_argument('--metadata',required=True,type=Path);ap.add_argument('--out',required=True,type=Path)
    a=ap.parse_args();start=time.monotonic()
    if a.out.exists():raise RuntimeError('Output directory already exists; use a clean directory')
    a.out.mkdir(parents=True)
    before={str(p):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in (a.credits,a.metadata)}
    print(json.dumps({'stage':'inputs_hashed','sources':before}),flush=True)
    md=np.load(a.metadata,allow_pickle=False)
    mbid=md['mbid'];offset=md['offset'];n=len(mbid)
    assert mbid.shape==offset.shape and mbid.ndim==1
    db=sqlite3.connect(':memory:');db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA temp_store=MEMORY');db.execute('PRAGMA cache_size=-131072')
    db.execute('PRAGMA foreign_keys=OFF')
    db.executescript('''CREATE TABLE raw_credit(row_id INTEGER PRIMARY KEY,artist INTEGER NOT NULL,producer INTEGER NOT NULL,rec INTEGER NOT NULL,gid TEXT NOT NULL,year INTEGER NOT NULL);
    CREATE TABLE sample_recording(gid TEXT PRIMARY KEY);
    CREATE TABLE submission(row_id INTEGER PRIMARY KEY,gid TEXT NOT NULL REFERENCES sample_recording(gid),offset INTEGER NOT NULL);''')
    db.executemany('INSERT INTO sample_recording VALUES (?)',[(g,) for g in sorted(set(mbid.tolist()))])
    db.executemany('INSERT INTO submission VALUES (?,?,?)',((i,str(g),int(o)) for i,(g,o) in enumerate(zip(mbid,offset))))
    with gzip.open(a.credits,'rt',newline='') as f:
        reader=csv.DictReader(f);assert reader.fieldnames==['artist','producer','rec','gid','year'],reader.fieldnames
        batch=[];count=0
        for count,r in enumerate(reader,1):
            batch.append((count,int(r['artist']),int(r['producer']),int(r['rec']),r['gid'],int(r['year'])))
            if len(batch)>=10000:
                db.executemany('INSERT INTO raw_credit VALUES (?,?,?,?,?,?)',batch);batch.clear()
                if count%100000==0:print(json.dumps({'stage':'full_credit_scan','rows':count,'seconds':round(time.monotonic()-start,3)}),flush=True)
        if batch:db.executemany('INSERT INTO raw_credit VALUES (?,?,?,?,?,?)',batch)
    db.commit()
    db.executescript('''CREATE INDEX raw_gid ON raw_credit(gid);
    CREATE INDEX submission_gid ON submission(gid);
    CREATE TABLE submission_multiplicity AS SELECT gid,COUNT(*) n FROM submission GROUP BY gid;
    CREATE UNIQUE INDEX sample_multi_gid ON submission_multiplicity(gid);''')
    checks={
        'empty_gid':scalar(db,"SELECT COUNT(*) FROM raw_credit WHERE gid=''"),
        'nonpositive_numeric_ids':scalar(db,'SELECT COUNT(*) FROM raw_credit WHERE artist<=0 OR producer<=0 OR rec<=0'),
        'rec_to_gid_conflict_groups':scalar(db,'SELECT COUNT(*) FROM (SELECT rec FROM raw_credit GROUP BY rec HAVING COUNT(DISTINCT gid)>1)'),
        'gid_to_rec_conflict_groups':scalar(db,'SELECT COUNT(*) FROM (SELECT gid FROM raw_credit GROUP BY gid HAVING COUNT(DISTINCT rec)>1)'),
        'distinct_credit_row_payloads':scalar(db,'SELECT COUNT(*) FROM (SELECT DISTINCT artist,producer,rec,gid,year FROM raw_credit)'),
        'artist_producer_recording_year_conflict_groups':scalar(db,'SELECT COUNT(*) FROM (SELECT artist,producer,gid FROM raw_credit GROUP BY artist,producer,gid HAVING COUNT(DISTINCT year)>1)'),
        'sample_recording_offset_duplicate_groups':scalar(db,'SELECT COUNT(*) FROM (SELECT gid,offset FROM submission GROUP BY gid,offset HAVING COUNT(*)>1)'),
        'sample_empty_gid':scalar(db,"SELECT COUNT(*) FROM submission WHERE gid=''"),
    }
    assert checks['empty_gid']==checks['nonpositive_numeric_ids']==checks['rec_to_gid_conflict_groups']==checks['gid_to_rec_conflict_groups']==0,checks
    db.executescript('''CREATE TABLE recording(gid TEXT PRIMARY KEY,rec INTEGER UNIQUE NOT NULL);
    INSERT INTO recording SELECT gid,MIN(rec) FROM raw_credit GROUP BY gid;
    CREATE TABLE artist(id INTEGER PRIMARY KEY);INSERT INTO artist SELECT DISTINCT artist FROM raw_credit;
    CREATE TABLE producer(id INTEGER PRIMARY KEY);INSERT INTO producer SELECT DISTINCT producer FROM raw_credit;
    CREATE TABLE credit(artist INTEGER NOT NULL REFERENCES artist(id),producer INTEGER NOT NULL REFERENCES producer(id),gid TEXT NOT NULL REFERENCES recording(gid),PRIMARY KEY(artist,producer,gid));
    INSERT INTO credit SELECT DISTINCT artist,producer,gid FROM raw_credit;
    CREATE TABLE producer_recording(producer INTEGER NOT NULL REFERENCES producer(id),gid TEXT NOT NULL REFERENCES recording(gid),PRIMARY KEY(producer,gid));
    INSERT INTO producer_recording SELECT DISTINCT producer,gid FROM raw_credit;
    CREATE INDEX credit_gid ON credit(gid);CREATE INDEX pr_gid ON producer_recording(gid);''')
    db.commit();db.execute('PRAGMA foreign_keys=ON')
    print(json.dumps({'stage':'canonical_tables_created','seconds':round(time.monotonic()-start,3)}),flush=True)
    checks['foreign_key_violations']=rows(db,'PRAGMA foreign_key_check')
    checks['integrity_check']=rows(db,'PRAGMA integrity_check')
    assert not checks['foreign_key_violations'] and checks['integrity_check']==[['ok']]
    total={'credit_rows':count,'credit_payload_distinct':checks['distinct_credit_row_payloads'],
        'artist_producer_recording_distinct':scalar(db,'SELECT COUNT(*) FROM credit'),
        'producer_recording_distinct':scalar(db,'SELECT COUNT(*) FROM producer_recording'),
        'recording_distinct':scalar(db,'SELECT COUNT(*) FROM recording'),
        'artist_distinct':scalar(db,'SELECT COUNT(*) FROM artist'),'producer_distinct':scalar(db,'SELECT COUNT(*) FROM producer'),
        'submission_rows':n,'sample_recording_distinct':scalar(db,'SELECT COUNT(*) FROM sample_recording')}
    matched={}
    for label,table in [('credit_rows','raw_credit'),('artist_producer_recording_distinct','credit'),('producer_recording_distinct','producer_recording')]:
        base=scalar(db,f'SELECT COUNT(*) FROM {table} c JOIN sample_recording s ON c.gid=s.gid')
        joined=scalar(db,f'SELECT COALESCE(SUM(s.n),0) FROM {table} c JOIN submission_multiplicity s ON c.gid=s.gid')
        matched[label]={'recording_catalog_join_count':base,'submission_join_count':joined,'extra_submission_rows':joined-base}
    sql_verification={}
    for label,table in [('credit_rows','raw_credit'),('artist_producer_recording_distinct','credit'),('producer_recording_distinct','producer_recording')]:
        query=f'SELECT COUNT(*) FROM {table} c JOIN submission s ON c.gid=s.gid'
        actual=scalar(db,query)
        assert actual==matched[label]['submission_join_count']
        sql_verification[label]={'sql':query,'direct_join_count':actual,'multiplicity_sum_matches':True,'sqlite_syntax_and_execution_passed':True}
    rewrite_queries = {
        'declared_target': 'SELECT p.producer,p.gid FROM producer_recording p JOIN sample_recording s ON p.gid=s.gid',
        'distinct_after_join': 'SELECT DISTINCT p.producer,p.gid FROM producer_recording p JOIN submission s ON p.gid=s.gid',
        'preaggregate_child': 'SELECT p.producer,p.gid FROM producer_recording p JOIN (SELECT gid FROM submission GROUP BY gid) s ON p.gid=s.gid',
    }
    rewrite_keys = {name: set(map(tuple, rows(db, sql))) for name, sql in rewrite_queries.items()}
    target_keys = rewrite_keys['declared_target']
    assert len(target_keys) == matched['producer_recording_distinct']['recording_catalog_join_count']
    rewrite_receipt = {}
    for name, keys in rewrite_keys.items():
        symmetric_difference = keys ^ target_keys
        assert not symmetric_difference, (name, len(symmetric_difference))
        key_bytes = json.dumps(sorted(keys), separators=(',', ':')).encode()
        rewrite_receipt[name] = {'sql': rewrite_queries[name], 'executed_count': len(keys),
            'target_key_symmetric_difference': len(symmetric_difference),
            'sorted_key_sha256': hashlib.sha256(key_bytes).hexdigest()}
    (a.out/'music_rewrite_verification.json').write_text(json.dumps({
        'scope': 'entire fixed shared support', 'all_queries_executed': True,
        'source_hashes': before, 'checks': rewrite_receipt}, indent=2)+'\n')
    matched['recording_distinct']=scalar(db,'SELECT COUNT(*) FROM recording c JOIN sample_recording s ON c.gid=s.gid')
    matched['sample_recordings_without_credits']=scalar(db,'SELECT COUNT(*) FROM sample_recording s LEFT JOIN recording r ON s.gid=r.gid WHERE r.gid IS NULL')
    matched['credit_recordings_without_sample']=total['recording_distinct']-matched['recording_distinct']
    matched['recordings_with_submission_fanout']=scalar(db,'SELECT COUNT(*) FROM recording r JOIN submission_multiplicity s ON r.gid=s.gid WHERE s.n>1')
    checks['credit_row_exact_duplicates']=count-checks['distinct_credit_row_payloads']
    total['producer_recording_groups_with_multiple_artists']=scalar(db,'SELECT COUNT(*) FROM (SELECT producer,gid FROM credit GROUP BY producer,gid HAVING COUNT(*)>1)')
    total['recordings_with_multiple_artists']=scalar(db,'SELECT COUNT(*) FROM (SELECT gid FROM credit GROUP BY gid HAVING COUNT(DISTINCT artist)>1)')
    total['recordings_with_multiple_producers']=scalar(db,'SELECT COUNT(*) FROM (SELECT gid FROM producer_recording GROUP BY gid HAVING COUNT(*)>1)')
    multi_p=db.execute('SELECT gid,COUNT(*) n FROM producer_recording GROUP BY gid HAVING COUNT(*)>1 ORDER BY gid LIMIT 1').fetchone()
    legal_producer=None
    if multi_p:
        g,num=multi_p
        legal_producer={'gid':g,'producer_recording_edges':rows(db,'SELECT producer,gid FROM producer_recording WHERE gid=? ORDER BY producer',(g,)),
          'actual_raw_credit_rows':rows(db,'SELECT row_id,artist,producer,rec,gid,year FROM raw_credit WHERE gid=? ORDER BY row_id',(g,)),
          'producer_participation_count':num,'distinct_recording_count':1,'interpretation':'Different declared targets; multiple credited producers are not exact duplicate edge rows'}
        (a.out/'legal_multi_producer_example.json').write_text(json.dumps(legal_producer,indent=2)+'\n')
    
    q="""SELECT c.producer,c.gid,COUNT(DISTINCT c.artist) artists,s.n
         FROM credit c JOIN submission_multiplicity s ON c.gid=s.gid
         GROUP BY c.producer,c.gid HAVING s.n>1 ORDER BY s.n DESC,c.gid,c.producer LIMIT 1"""
    picked=db.execute(q).fetchone();witness=None
    if picked:
        p,g,artists,ns=picked
        cr=rows(db,'SELECT artist,producer,gid FROM credit WHERE producer=? AND gid=?',(p,g))
        ss=rows(db,'SELECT row_id,gid,offset FROM submission WHERE gid=? ORDER BY row_id',(g,))
        witness={'producer':p,'gid':g,'recording_numeric_id':db.execute('SELECT rec FROM recording WHERE gid=?',(g,)).fetchone()[0],
                 'actual_credit_triples':cr,'actual_sample_submissions':ss,
                 'actual_raw_credit_rows':rows(db,'SELECT row_id,artist,producer,rec,gid,year FROM raw_credit WHERE producer=? AND gid=?',(p,g)),
                 'producer_recording_target_before_join':1,'producer_recording_target_after_distinct':1,
                 'joined_credit_submission_rows':artists*ns,'joined_deduplicated_producer_recording_submission_rows':ns,
                 'valid_artist_multiplicity':artists,'sample_submission_multiplicity':ns,
                 'ordinary_keys_and_slice_fk_pass':True,'known_session_id':False}
        (a.out/'real_counterexample.json').write_text(json.dumps(witness,indent=2)+'\n')
    multi=db.execute('SELECT producer,gid,COUNT(*) n FROM credit GROUP BY producer,gid HAVING COUNT(*)>1 ORDER BY gid,producer LIMIT 1').fetchone()
    legal=None
    if multi:
        p,g,num=multi
        legal={'producer':p,'gid':g,'artist_count':num,'credit_triples':rows(db,'SELECT artist,producer,gid FROM credit WHERE producer=? AND gid=?',(p,g)),
               'dyad_incidence_count':num,'producer_recording_participation_count':1,
               'blanket_row_dedup_changes_legal_dyad_target':True}
        (a.out/'legal_multi_artist_example.json').write_text(json.dumps(legal,indent=2)+'\n')
    after={str(p):sha(p) for p in (a.credits,a.metadata)}
    assert all(before[p]['sha256']==h for p,h in after.items()),'Source changed during scan'
    contracts={
      'credit_rows':'Physical input rows; historical extraction can contain repeated payloads.',
      'artist_producer_recording_distinct':'One incidence for each credited artist, producer and recording; multi-artist incidences can be legitimate.',
      'producer_recording_distinct':'One participating recording for each producer, independent of the number of credited artists.',
      'recording_distinct':'One recording identifier regardless of credit participants.',
      'submission_rows':'One official sample member row indexed by extractor row id; multiple submissions can reference one recording.',
      'comparison_denominator':'Only recordings present in both inputs for every before/after join comparison; absence from the sample is not an FK violation.',
      'ordinary_constraint_scope':'Self-contained recording/artist/producer tables derived from the entire credit input and sample_recording table derived from metadata; not a verification against the complete external entity catalogue.',
      'detector':'For declared producer-recording grain, count distinct (producer,gid) or preaggregate submissions to gid. For declared artist-producer-recording grain, retain valid artist multiplicity. A known fanout count and measure grain detect the mismatch.',
      'session_truth':'No session identity exists in these input fields; recording or year counts are not session counts.'}
    out={'schema':'counting_units_granularity_v1','sources':before,'input_readback_sha256':after,'contracts':contracts,'checks':checks,'total':total,'matched':matched,
      'real_counterexample':witness,'legal_multi_artist_example':legal,'legal_multi_producer_example':legal_producer,'sql_execution_verification':sql_verification,
      'baseline_coverage':{'key_fk_only_detects_target_change':False,'declared_measure_grain_and_join_multiplicity_detects_target_change':bool(picked),
          'generic_sql_style_lint_execution':'Not run; no declared target-unit input supplied to such a tool',
          'python_source_compile':'Passed before execution; syntax checking does not declare recording grain',
          'sqlite_count_query_syntax':'Valid and actually executed; semantic target checked separately','new_method_admitted':False},
      'execution':{'command':sys.argv,'python':sys.version,'numpy':np.__version__,'sqlite':sqlite3.sqlite_version,'relational_store':'transient in-memory SQLite; source inputs retained read-only; real witness and numeric outputs persisted','platform':platform.platform(),'thread_limits':{v:os.environ.get(v) for v in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')},
          'elapsed_seconds':time.monotonic()-start,'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'script_sha256':sha(Path(__file__))}}
    db.commit();db.close();(a.out/'results.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'stage':'complete','total':total,'matched':matched,'keys_fk_passed':not checks['foreign_key_violations'],'elapsed_seconds':out['execution']['elapsed_seconds']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
