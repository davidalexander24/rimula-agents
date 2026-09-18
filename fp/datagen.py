"""Generate documented synthetic historical formulation records."""
from __future__ import annotations
import argparse, json, os, time
import numpy as np
import pandas as pd
from scipy.stats import qmc
from fp.palette import INGREDIENTS, PROCESS, bounds, complete, meets_specs
from fp.virtual_lab import VirtualLab

ARCHETYPES={
 "gel_light":[5,2,.5,1,3,1,.3,.35,.5,.8,5000,3,70],
 "light_cream":[4,3,2,3,8,2,.2,.1,.15,.8,6000,5,75],
 "rich_cream":[3,2,4,5,16,3,.1,0,0,.8,7000,6,80],
 "active_serum":[6,8,0,.5,1,0,.5,.2,.3,.6,3000,2,65],
}

def _valid_row(vals):
 f=dict(zip(INGREDIENTS+PROCESS,vals)); f=complete(f)
 return f if f["AQUA"]>=50 and not any(np.isnan(float(f.get(k,0))) for k in INGREDIENTS+PROCESS) else None

def generate(n_lhs=240,n_arch=40,seed=20260917,variants=("v1","v2","v3")):
 rng=np.random.RandomState(seed); b=bounds(); cols=INGREDIENTS+PROCESS
 rows=[]; rejected=0
 while len(rows)<n_lhs:
  x=qmc.LatinHypercube(d=len(cols),seed=seed+len(rows)).random(n_lhs-len(rows))
  for i in range(len(x)):
   vals=[b[k][0]+x[i,j]*(b[k][1]-b[k][0]) for j,k in enumerate(cols)]
   f=_valid_row(vals)
   if f: rows.append(("lhs",f))
   else: rejected+=1
 centers=ARCHETYPES
 for name,center in centers.items():
  for j in range(n_arch):
   vals=[]
   for k,v in zip(cols,center):
    lo,hi=b[k]; sd=.15*max(abs(v),hi-lo*.05,1e-6); vals.append(float(np.clip(rng.normal(v,sd),lo,hi)))
   f=_valid_row(vals)
   if f: rows.append(("archetype:"+name,f))
   else: rejected+=1
 rows=rows[:n_lhs+n_arch*len(centers)]
 out={}; manifest={"seed":seed,"n_lhs":n_lhs,"n_archetype":n_arch*len(centers),"rejected":rejected,"variants":{}}
 for variant in variants:
  lab=VirtualLab(variant,seed=seed); records=[]; hits=0
  for idx,(source,f) in enumerate(rows,1):
   y=lab.run_batch(f,seed_override=seed+idx)
   rec={"record_id":f"H{idx:04d}","source":source,**{k:float(f[k]) for k in INGREDIENTS+['AQUA']},**{k:float(f[k]) for k in PROCESS},**y,"STABLE":int(y["STABLE"]),"variant":variant}
   records.append(rec)
  df=pd.DataFrame(records); out[variant]=df
  specs={"NIACINAMIDE_MIN_PCT":4,"VISCOSITY_CP":[4000,12000],"PH":[5,6.5],"D50_UM_MAX":3,"STABLE":True,"COST_IDR_PER_KG_MAX":50000}
  hits=int(sum(meets_specs(r, y, specs)["ALL"] for r,y in zip(df.to_dict('records'),df.to_dict('records'))))
  manifest["variants"][variant]={"rows":len(df),"hit_rate_random":hits/len(df)}
 return out,manifest

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',default='data/virtual_lab');p.add_argument('--variants',nargs='+',default=['v1','v2','v3']);a=p.parse_args(); os.makedirs(a.out,exist_ok=True)
 t=time.time(); data,m=generate(variants=tuple(a.variants)); m['generated_seconds']=time.time()-t
 for v,df in data.items(): df.to_csv(os.path.join(a.out,f'historical_{v}.csv'),index=False)
 with open(os.path.join(a.out,'generation_manifest.json'),'w') as f: json.dump(m,f,indent=2)
 print(json.dumps(m,indent=2))
if __name__=='__main__':main()
