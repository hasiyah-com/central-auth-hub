"""Controlled synthetic audit-trace ablation, not replay of real user logs."""
import argparse,csv,json,hashlib,math,random,sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
import joblib,numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score,average_precision_score
ROOT=Path(__file__).resolve().parents[2]
# Import ML schema before resolving the independent backend module via importlib.
from app.features import FEATURE_NAMES as BASE_NAMES
from point_scoring import scores_with_model
import importlib.util
# Backend app and ML app are different packages. Load pure helpers under their own names.
time_spec=importlib.util.spec_from_file_location('offline_feature_time',ROOT/'hub/backend/app/services/feature_time.py');tm=importlib.util.module_from_spec(time_spec);time_spec.loader.exec_module(tm)
spec=importlib.util.spec_from_file_location('offline_failure_windows',ROOT/'hub/backend/app/services/failure_window_features.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
NEW_NAMES=helper.FEATURE_NAMES;extract=helper.extract_failure_window_features;FAIL_ACTIONS=helper.FAIL_ACTIONS
from generate_data import normal_session
SUBSETS={'base23':list(range(23)),'short_windows25':list(range(25)),'streak_ratio25':list(range(23))+[25,26],'all28':list(range(28))}

def groups_split(groups,seed):
    users=np.unique(groups);tr,rest=train_test_split(users,test_size=.4,random_state=seed);val,rest=train_test_split(rest,train_size=.375,random_state=seed+1);cal,te=train_test_split(rest,train_size=.4,random_state=seed+2)
    return {n:np.flatnonzero(np.isin(groups,u)) for n,u in zip(['train','validation','calibration','test'],[tr,val,cal,te])}

def threshold(scores,y):return float(np.quantile(np.asarray(scores)[y==0],.99,method='higher'))
def metrics(scores,y,t):
    pred=np.asarray(scores)>t
    return dict(threshold=t,attack=int((y==1).sum()),caught=int(pred[y==1].sum()),missed=int((~pred[y==1]).sum()),normal=int((y==0).sum()),false_positive=int(pred[y==0].sum()),recall=float(pred[y==1].mean()),fpr=float(pred[y==0].mean()),f1=float(f1_score(y,pred)),pr_auc=float(average_precision_score(y,scores)))

def generate(seed,users=300,events_per_user=60):
    random.seed(seed);rows=[];audit=[]
    for user in range(users):
        subject=f'audit-user-{user:04d}'
        for session in range(events_per_user):
            now=datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(days=session,hours=user%24)
            attack=int(session>=10 and random.random()<.10)
            variant=random.choice(['rapid','slow']) if attack else random.choices(['ordinary','typo_retry','legitimate_many'],[70,25,5])[0]
            count=random.choice([5,10,15,20,30]) if attack else (0 if variant=='ordinary' else random.choice([1,2,3]) if variant=='typo_retry' else random.choice([5,10,15]))
            trace=[]
            if attack:
                # Rapid attacks concentrate failures; slow attacks deliberately overlap benign windows.
                for k in range(count):
                    seconds=(count-k)*3 if variant=='rapid' else (count-k)*180
                    trace.append(dict(created_at=now-timedelta(seconds=seconds),actor_id=subject,action='risk_mfa_verify_failed'))
            elif count:
                # Multiple successful sessions reset consecutive failures. Some legit users retry in a burst.
                for k in range(count):
                    seconds=(count-k)*30 if variant=='typo_retry' else (count-k)*600
                    t=now-timedelta(seconds=seconds)
                    trace.append(dict(created_at=t,actor_id=subject,action='stepup_totp_failed'))
                    if variant=='legitimate_many':trace.append(dict(created_at=t+timedelta(seconds=20),actor_id=subject,action='stepup_totp_success'))
                trace.append(dict(created_at=now-timedelta(seconds=1),actor_id=subject,action='stepup_totp_success'))
            for e in trace:e["metadata_json"]={"method":"totp","code":"invalid_code"} if e["action"] in FAIL_ACTIONS else {"method":"totp"}
            vector=normal_session();vector[0]=float(tm.as_bangkok(now).hour);vector[1]=float(tm.as_bangkok(now).weekday())
            # All non-failure fields follow the same distribution for both labels; this isolates the ablation.
            vector[10]=float(sum(e['action'] in FAIL_ACTIONS and now-timedelta(hours=24)<=e['created_at']<now for e in trace))
            extra=extract(trace,now,subject)
            rows.append(dict(subject=subject,now=now.isoformat(),label=attack,variant=variant,features=vector+extra))
            audit.extend(dict(subject=subject,session=session,created_at=e['created_at'].isoformat(),actor_id=e['actor_id'],action=e['action'],metadata_json=e['metadata_json']) for e in trace)
    return rows,audit

def run(output,seed):
    if output.exists():raise ValueError('use fresh output')
    rows,audit=generate(seed);output.mkdir(parents=True);X=np.array([r['features'] for r in rows]);y=np.array([r['label'] for r in rows]);g=np.array([r['subject'] for r in rows]);parts=groups_split(g,seed)
    models={};validation={};tr,val,cal,te=[parts[n] for n in ['train','validation','calibration','test']]
    for name,indices in SUBSETS.items():
        model=IsolationForest(n_estimators=200,max_samples=512,max_features=1.0,contamination=.02,random_state=seed,n_jobs=2).fit(X[tr][y[tr]==0][:,indices]);models[name]=model
        vs=scores_with_model(model,X[val][:,indices]);validation[name]=metrics(vs,y[val],threshold(vs,y[val]))
    # Select before evaluating test; all four test results are a prespecified ablation.
    selected=max(validation,key=lambda n:(validation[n]['recall'],validation[n]['pr_auc']))
    results={};predictions=[]
    for name,indices in SUBSETS.items():
        model=models[name];cs=scores_with_model(model,X[cal][:,indices]);t=threshold(cs,y[cal]);ts=scores_with_model(model,X[te][:,indices]);results[name]=metrics(ts,y[te],t)
        results[name]['attack_variants']={v:dict(total=int(sum(rows[j]['variant']==v and y[j]==1 for j in te)),caught=int(sum(rows[j]['variant']==v and y[j]==1 and ts[k]>t for k,j in enumerate(te)))) for v in ['rapid','slow']}
        for k,j in enumerate(te):predictions.append(dict(model=name,subject=rows[j]['subject'],captured_at=rows[j]['now'],variant=rows[j]['variant'],label=int(y[j]),score=ts[k],threshold=t,detected=int(ts[k]>t),**{n:float(X[j,i]) for i,n in enumerate(BASE_NAMES+NEW_NAMES)}))
        model.rba_feature_contract_='rba-failure-window-experiment-v1';model.rba_feature_names_=[(BASE_NAMES+NEW_NAMES)[i] for i in indices]
        if name in ['base23',selected]:joblib.dump(model,output/f'{name}.pkl')
    with (output/'predictions.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(predictions[0]));w.writeheader();w.writerows(predictions)
    with (output/'samples.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(BASE_NAMES+NEW_NAMES+['label','subject','variant','captured_at']);w.writerows(r['features']+[r['label'],r['subject'],r['variant'],r['now']] for r in rows)
    (output/'audit_events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in audit))
    result=dict(seed=seed,rows=len(rows),users=len(set(g)),feature_names=BASE_NAMES+NEW_NAMES,subset_names={n:[(BASE_NAMES+NEW_NAMES)[i] for i in inds] for n,inds in SUBSETS.items()},split={n:dict(rows=len(i),users=len(set(g[i]))) for n,i in parts.items()},validation=validation,selected_on_validation=selected,test=results,dataset_sha256=hashlib.sha256((output/'samples.csv').read_bytes()).hexdigest(),limitations=['Controlled synthetic failure-only ablation, not production or Chapter 4.','Non-failure features sampled identically for attack/normal; temporal personalization outside failure windows is still legacy synthetic.','Slow attack windows intentionally overlap normal.','Attempts ratio uses only explicitly supported post-primary audit actions; cannot infer coverage of all methods.','Future/current events excluded. No new live features or risk policy activated.'])
    (output/'results.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(seed=seed,selected=selected,test=results),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seed',type=int,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.output,a.seed)
