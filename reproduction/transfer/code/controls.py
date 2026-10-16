import json, sqlite3, time
from . import experiment as E

def run(O):
 def dump(name,x):E.dump(O/name,x)
 con=sqlite3.connect(':memory:');rows=[]
 for size in (100,1000,10000):
  for cap in (0,1,2,4,8,16):
   con.executescript('DROP TABLE IF EXISTS b;DROP TABLE IF EXISTS x;DROP TABLE IF EXISTS y;CREATE TABLE b(id INTEGER PRIMARY KEY,w INTEGER);CREATE TABLE x(id INTEGER,v INTEGER);CREATE TABLE y(id INTEGER,v INTEGER);')
   data=[(i,1+i%5,i%(cap+1),(i*7+3)%(cap+1)) for i in range(size)]
   con.executemany('INSERT INTO b VALUES (?,?)',[(i,w) for i,w,k,l in data]);con.executemany('INSERT INTO x VALUES (?,?)',[(i,j) for i,w,k,l in data for j in range(k)]);con.executemany('INSERT INTO y VALUES (?,?)',[(i,j) for i,w,k,l in data for j in range(l)])
   con.executescript('CREATE INDEX xi ON x(id);CREATE INDEX yi ON y(id);')
   expected=sum(w for i,w,k,l in data);left=sum(w*max(1,k)*max(1,l) for i,w,k,l in data);inner=sum(w*k*l for i,w,k,l in data);eligible=sum(w for i,w,k,l in data if k and l)
   q={'left':'SELECT SUM(w) FROM b LEFT JOIN x USING(id) LEFT JOIN y USING(id)','preaggregate':'SELECT SUM(w) FROM b LEFT JOIN (SELECT DISTINCT id FROM x) x USING(id) LEFT JOIN (SELECT DISTINCT id FROM y) y USING(id)','semijoin':'SELECT SUM(w) FROM b WHERE EXISTS (SELECT 1 FROM x WHERE x.id=b.id) AND EXISTS (SELECT 1 FROM y WHERE y.id=b.id)','inner':'SELECT SUM(w) FROM b JOIN x USING(id) JOIN y USING(id)','distinct_weight':'SELECT SUM(DISTINCT w) FROM b LEFT JOIN x USING(id) LEFT JOIN y USING(id)'}
   answers={};timings={}
   for name,query in q.items():
    vals=[];ts=[]
    for repeat in range(3):
     t=time.perf_counter();v=con.execute(query).fetchone()[0];ts.append(time.perf_counter()-t);vals.append(int(v or 0))
    assert len(set(vals))==1;answers[name]=vals[0];timings[name]=ts
   assert answers['left']==left and answers['preaggregate']==expected and answers['inner']==inner and answers['semijoin']==eligible
   row={'size':size,'maximum_child_count':cap,'base_weight':expected,'left_weight':left,'inner_weight':inner,'eligible_weight':eligible,'distinct_weight':answers['distinct_weight'],'answers':answers,'sql':q,'timings_seconds':timings};rows.append(row);print(json.dumps({k:row[k] for k in ['size','maximum_child_count','base_weight','left_weight']}),flush=True)
 dump('counting_units_scaling_controls.json',rows)
 con.executescript('DROP TABLE b;DROP TABLE x;CREATE TABLE b(id INTEGER PRIMARY KEY,w INTEGER);CREATE TABLE x(id INTEGER,v INTEGER);INSERT INTO b VALUES (1,2),(2,2),(3,5);INSERT INTO x VALUES (1,0),(1,1),(3,0);')
 q={'predicate_in_on':'SELECT SUM(w) FROM b LEFT JOIN x ON b.id=x.id AND x.v=1','predicate_in_where':'SELECT SUM(w) FROM b LEFT JOIN x ON b.id=x.id WHERE x.v=1','exists_target':'SELECT SUM(w) FROM b WHERE EXISTS (SELECT 1 FROM x WHERE x.id=b.id AND x.v=1)','distinct_weight':'SELECT SUM(DISTINCT w) FROM b LEFT JOIN x ON b.id=x.id AND x.v=1'}
 a={k:int(con.execute(v).fetchone()[0] or 0) for k,v in q.items()};assert a=={'predicate_in_on':9,'predicate_in_where':2,'exists_target':2,'distinct_weight':7};dump('counting_units_filter_fixture.json',{'base':[(1,2),(2,2),(3,5)],'child':[(1,0),(1,1),(3,0)],'sql':q,'answers':a});con.close()
