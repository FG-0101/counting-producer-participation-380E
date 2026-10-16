from pathlib import Path
import os
for variable in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS"):
 os.environ[variable]="1"
import collections, hashlib, json, platform, sqlite3, time
import numpy as np
ROOT=Path(__file__).resolve().parent
INPUT=ROOT.parent/"data"
RASTER=INPUT/"raster_panel.npz"
SEED=20261011

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for chunk in iter(lambda:f.read(8<<20),b''):h.update(chunk)
 return h.hexdigest()

def dump(p,data):p.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def m3(out):
 import pandas as pd
 path=INPUT/'schema_aware_records.parquet';data=pd.read_parquet(path)
 con=sqlite3.connect(':memory:');con.executescript('CREATE TABLE r(id INT PRIMARY KEY,p TEXT,d TEXT,c TEXT,n INTEGER);CREATE TABLE keyword(id INT,k TEXT);CREATE TABLE category_addition(id INT,c TEXT);')
 records=[];keywords=[];categories=[];sizes=[]
 for i,row in data.iterrows():
  n=int(row.n);assert n>0 and n==row.n
  k=sorted(set(str(x) for x in row.keyword_ids));c=sorted(set(json.loads(row.c_add))) if row.c_add and row.c_add!='[]' else []
  records.append((int(i),str(row.p),str(row.d.date()),str(row.c),n));keywords.extend((int(i),v) for v in k);categories.extend((int(i),v) for v in c);sizes.append((len(k),len(c),n))
 con.executemany('INSERT INTO r VALUES (?,?,?,?,?)',records);con.executemany('INSERT INTO keyword VALUES (?,?)',keywords);con.executemany('INSERT INTO category_addition VALUES (?,?)',categories)
 con.executescript('CREATE INDEX ki ON keyword(id);CREATE INDEX ci ON category_addition(id);')
 target=sum(n for k,c,n in sizes);cells=len(sizes);left=sum(max(k,1)*max(c,1)*n for k,c,n in sizes);inner=sum(k*c*n for k,c,n in sizes);eligible=sum(n for k,c,n in sizes if k and c)
 queries={
 'source_records':'SELECT SUM(n) FROM r',
 'naive_two_child_left_join':'SELECT SUM(r.n) FROM r LEFT JOIN keyword k USING(id) LEFT JOIN category_addition c USING(id)',
 'preaggregate_left_join':'SELECT SUM(r.n) FROM r LEFT JOIN (SELECT DISTINCT id FROM keyword) k USING(id) LEFT JOIN (SELECT DISTINCT id FROM category_addition) c USING(id)',
 'deduplicate_cell_after_left_join':'SELECT SUM(n) FROM (SELECT r.id,MAX(r.n) n FROM r LEFT JOIN keyword k USING(id) LEFT JOIN category_addition c USING(id) GROUP BY r.id)',
 'sum_distinct_weight':'SELECT SUM(DISTINCT r.n) FROM r LEFT JOIN keyword k USING(id) LEFT JOIN category_addition c USING(id)',
 'count_distinct_cell':'SELECT COUNT(DISTINCT r.id) FROM r LEFT JOIN keyword k USING(id) LEFT JOIN category_addition c USING(id)',
 'naive_two_child_inner_join':'SELECT SUM(r.n) FROM r JOIN keyword k USING(id) JOIN category_addition c USING(id)',
 'eligible_source_semijoin':'SELECT SUM(n) FROM r WHERE EXISTS (SELECT 1 FROM keyword k WHERE k.id=r.id) AND EXISTS (SELECT 1 FROM category_addition c WHERE c.id=r.id)'
 }
 timings=[]
 for name,query in queries.items():
  values=[];elapsed=[]
  for repeat in range(5):
   start=time.perf_counter();answer=con.execute(query).fetchone()[0];elapsed.append(time.perf_counter()-start);values.append(0 if answer is None else int(answer))
  assert len(set(values))==1;timings.append({'name':name,'query':query,'answer':values[0],'seconds':elapsed,'median_seconds':float(np.median(elapsed))})
 answers={r['name']:r['answer'] for r in timings};assert answers['source_records']==answers['preaggregate_left_join']==answers['deduplicate_cell_after_left_join']==target
 assert answers['naive_two_child_left_join']==left and answers['naive_two_child_inner_join']==inner and answers['eligible_source_semijoin']==eligible and answers['count_distinct_cell']==cells
 groups=collections.defaultdict(list)
 for i,p,d,c,n in records:groups[(d,c)].append((i,p,n))
 references=[];leak=0;empty=0;total=0
 for key,members in groups.items():
  platform=collections.Counter(p for i,p,n in members)
  for i,p,n in members:
   if len(members)<2:continue
   total+=1;contaminated=platform[p]>1;qualifying=len(members)-platform[p];leak+=contaminated;empty+=qualifying==0
   references.append({'cell':i,'platform':p,'group':list(key),'leave_one_cell_members':len(members)-1,'remaining_same_platform_cells':platform[p]-1,'exclude_platform_members':qualifying})
 result={'source':path.name,'source_sha256':sha(path),'aggregate_cells':cells,'represented_record_rows':target,'keyword_edges':len(keywords),'category_addition_edges':len(categories),'left_join_weighted_records':left,'left_join_extra_weight':left-target,'both_children_eligible_record_rows':eligible,'inner_join_weighted_records':inner,'tests':timings,'reference_groups':len(groups),'eligible_leave_one_cell_cases':total,'retaining_focal_platform_cases':leak,'empty_after_platform_exclusion_cases':empty,'counting_unit':'A reduced cell represents n source CSV rows. Cell ID is not a source statement ID. Results concern record-row weights and declared aggregate-cell membership.'}
 dump(out/'counting_units_regulatory_transfer.json',result);dump(out/'counting_units_all_reference_memberships.json',references)
 print(json.dumps({'stage':'counting_units','cells':cells,'target':target,'left':left,'reference_leaks':leak}),flush=True)
 return result
