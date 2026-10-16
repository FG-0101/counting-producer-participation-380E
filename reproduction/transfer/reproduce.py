from pathlib import Path
import argparse, json, sys, datetime
from code import experiment as E

def stable(x):
 if isinstance(x,dict):return {k:stable(v) for k,v in x.items() if k not in ("seconds","score_all_subsets_seconds","median_exact_subset_score_seconds","median_seconds","timings_seconds")}
 if isinstance(x,list):return [stable(v) for v in x]
 return x

def main():
 ap=argparse.ArgumentParser();ap.add_argument("output",type=Path);args=ap.parse_args()
 root=Path(__file__).resolve().parent
 if args.output.exists():raise SystemExit("Choose a new output directory")
 args.output.mkdir(parents=True)
 start=datetime.datetime.now(datetime.timezone.utc).isoformat()
 E.m3(args.output)
 from code.controls import run
 run(args.output)
 import pandas as pd, collections
 groups=[]
 frame=pd.read_parquet(root/"data/schema_aware_records.parquet")
 for (day,category),group in frame.groupby(["d","c"],sort=True):
  counts=collections.Counter(group.p.astype(str));size=len(group)
  groups.append({"date":str(day),"category":str(category),"cells":size,"eligible":size if size>1 else 0,"retained":sum(v for v in counts.values() if v>1) if size>1 else 0,"empty":sum(v for v in counts.values() if v==size) if size>1 else 0,"source_weight":int(group.n.sum())})
 (args.output/"reference_group_register.json").write_text(json.dumps(groups,indent=2)+"\n")
 checks=[]
 for path in sorted((root/"reference").glob("*.json")):
  actual=args.output/path.name
  a=json.loads(path.read_text());b=json.loads(actual.read_text())
  # Query timing fields are execution records, not fixed scientific targets.
  if path.name=="counting_units_regulatory_transfer.json":
   for item in a["tests"]:item.pop("seconds",None)
   for item in b["tests"]:item.pop("seconds",None)
  if stable(a)!=stable(b):raise RuntimeError("Stable result mismatch: "+path.name)
  checks.append({"file":path.name,"stable_fields_equal":True})
 receipt={"component":"counting_units","start_utc":start,"end_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"python":sys.version,"numpy":E.np.__version__,"sqlite":E.sqlite3.sqlite_version,"all_comparisons_pass":True,"comparisons":checks,"code_hashes":{p.relative_to(root).as_posix():E.sha(p) for p in (root/"code").glob("*.py")},"input_hashes":{p.relative_to(root).as_posix():E.sha(p) for p in (root/"data").rglob("*") if p.is_file()}}
 (args.output/"verification.json").write_text(json.dumps(receipt,indent=2)+"\n")
 print("PASS counting_units: "+str(len(checks))+" stable result files")

if __name__=="__main__":main()
