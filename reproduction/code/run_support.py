#!/usr/bin/env python3
"""Replay artist-year membership and focal-producer exclusions from the selected archived feature rows."""
import argparse,csv,gzip,hashlib,json,os,resource,sys,time,zipfile
from pathlib import Path
for var in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):os.environ[var]='1'
import numpy as np
from numpy.lib import format as fmt

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for x in iter(lambda:f.read(1<<20),b''):h.update(x)
 return h.hexdigest()

def blocks(z,name,batch=10000):
 with z.open(name) as f:
  ver=fmt.read_magic(f)
  if ver==(1,0):shape,order,dtype=fmt.read_array_header_1_0(f)
  elif ver==(2,0):shape,order,dtype=fmt.read_array_header_2_0(f)
  else:raise RuntimeError(ver)
  assert not order and not dtype.hasobject
  width=int(np.prod(shape[1:])) if len(shape)>1 else 1
  for start in range(0,shape[0],batch):
   n=min(batch,shape[0]-start);b=f.read(n*width*dtype.itemsize)
   assert len(b)==n*width*dtype.itemsize
   arr=np.frombuffer(b,dtype=dtype).reshape((n,)+shape[1:])
   yield start,arr,shape
  assert f.read(1)==b''

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--credits',type=Path,required=True);ap.add_argument('--features',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--artist',type=int,default=528068);ap.add_argument('--producer',type=int,default=761795);a=ap.parse_args();start=time.monotonic()
 if a.out.exists():raise RuntimeError('Use clean output directory')
 a.out.mkdir(parents=True);source={str(p):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in (a.credits,a.features)}
 target=[];total=0
 with gzip.open(a.credits,'rt',newline='') as f:
  for total,r in enumerate(csv.DictReader(f),1):
   if int(r['artist'])==a.artist:target.append({'source_row':total,**{k:(v if k=='gid' else int(v)) for k,v in r.items()}})
 assert 0<len(target)<=10000
 wanted={r['gid'] for r in target};index={};values={}
 original_rows=np.load(a.features,allow_pickle=False)['source_row_index']
 with zipfile.ZipFile(a.features) as z:
  for offset,arr,shape in blocks(z,'mbid.npy'):
   for j,g in enumerate(arr):
    g=str(g)
    if g in wanted and g not in index:index[g]=offset+j
  byindex={i:g for g,i in index.items()}
  for offset,arr,shape in blocks(z,'M.npy'):
   for i in [i for i in byindex if offset<=i<offset+len(arr)]:
    v=arr[i-offset];values[byindex[i]]={'array_row':int(original_rows[i]),'finite_all_83':bool(np.isfinite(v).all())}
 eligible=[r for r in target if values.get(r['gid'],{}).get('finite_all_83',False)]
 groups={}
 for r in eligible:groups.setdefault(r['year'],[]).append(r)
 cases=[]
 for year,group in sorted(groups.items()):
  focal_gids={r['gid'] for r in group if r['producer']==a.producer}
  for focal in [r for r in group if r['producer']==a.producer]:
   old=[r for r in group if r['source_row']!=focal['source_row']]
   other=[r for r in group if r['gid'] not in focal_gids]
   cases.append({'year':year,'focal_row':focal,'old_usable':len(group)>=2,'old_baseline_source_rows':[r['source_row'] for r in old],
    'old_baseline_focal_producer_rows':sum(r['producer']==a.producer for r in old),
    'other_producer_baseline_recordings':len({r['gid'] for r in other}),
    'other_producer_baseline_source_rows':[r['source_row'] for r in other]})
 after={str(p):sha(p) for p in (a.credits,a.features)}
 assert all(source[p]['sha256']==h for p,h in after.items())
 out={'schema':'counting_units_e35_support_v1','sources':source,'readback_sha256':after,'full_credit_rows_scanned':total,'artist':a.artist,'producer':a.producer,'artist_credit_rows_total':len(target),'focal_credit_rows_total':sum(r['producer']==a.producer for r in target),'all_artist_credit_rows':target,'feature_membership':values,
  'artist_distinct_gids_in_feature_archive':len(index),'artist_credit_rows_finite_all_83':len(eligible),
  'focal_rows_eligible':sum(r['producer']==a.producer for r in eligible),
  'focal_old_usable_rows':sum(c['old_usable'] for c in cases),
  'old_usable_rows_with_focal_support_overlap':sum(c['old_usable'] and c['old_baseline_focal_producer_rows']>0 for c in cases),
  'old_usable_rows_without_declared_other_producer_support':sum(c['old_usable'] and c['other_producer_baseline_recordings']==0 for c in cases),
  'cases':cases,'boundary':'Exact archived e35 complete-case and artist-year support selection for one prespecified artist/producer. PR rows supply a finite year, hence the global have-year flag holds. No old regression, residualization or producer-direction projection replay; no session truth.',
  'execution':{'command':sys.argv,'python':sys.version,'numpy':np.__version__,'elapsed_seconds':time.monotonic()-start,'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'script_sha256':sha(Path(__file__))}}
 (a.out/'results.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n');print(json.dumps({k:out[k] for k in ['full_credit_rows_scanned','artist_distinct_gids_in_feature_archive','artist_credit_rows_finite_all_83','focal_old_usable_rows','old_usable_rows_with_focal_support_overlap','old_usable_rows_without_declared_other_producer_support']}),flush=True)
if __name__=='__main__':main()
