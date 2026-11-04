"""Five-model comparison. ALL training rows are SELECTed from SQLite.

Target: requested energy in the forecast hour (kWh).
Classification: independently trained high-demand alarm, energy >= 30 kWh.
No random split: first 2/3 of days train, next 1/6 validate, last 1/6 test.
"""
import argparse
import json
import pickle
import time
import tracemalloc
import warnings
from pathlib import Path
import numpy as np
from sklearn.tree import DecisionTreeRegressor, DecisionTreeClassifier
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.neural_network import MLPRegressor, MLPClassifier
from sklearn.svm import SVR, SVC
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.compose import TransformedTargetRegressor
from sklearn.metrics import (accuracy_score, precision_score, recall_score, f1_score,
                             mean_absolute_error, mean_squared_error, r2_score,
                             balanced_accuracy_score, confusion_matrix, average_precision_score)
from station_store import DB, database

ARTIFACTS = Path(__file__).with_name('artifacts')
THRESHOLD_KWH = 30.0


def features(day, hour):
    # Calendar features are known BEFORE the forecast hour starts.
    return [hour, np.sin(2*np.pi*hour/24), np.cos(2*np.pi*hour/24), day % 7]


def scores(y, pred, probabilities=None):
    actual_class = y >= THRESHOLD_KWH
    predicted_class = pred >= THRESHOLD_KWH if probabilities is None else probabilities >= .5
    return {'accuracy': float(accuracy_score(actual_class, predicted_class)),
            'precision': float(precision_score(actual_class, predicted_class, zero_division=0)),
            'recall': float(recall_score(actual_class, predicted_class, zero_division=0)),
            'f1': float(f1_score(actual_class, predicted_class, zero_division=0)),
            'balanced_accuracy': float(balanced_accuracy_score(actual_class,predicted_class)),
            'confusion_matrix_tn_fp_fn_tp': confusion_matrix(actual_class,predicted_class,labels=[False,True]).ravel().tolist(),
            'average_precision': float(average_precision_score(actual_class,probabilities if probabilities is not None else pred)),
            'rmse_kwh': float(np.sqrt(mean_squared_error(y, pred))),
            'mae_kwh': float(mean_absolute_error(y, pred)), 'r2': float(r2_score(y, pred)),
            'positive_samples': int(actual_class.sum()), 'negative_samples':int((~actual_class).sum()),
            'majority_baseline_accuracy':float(max(actual_class.mean(),1-actual_class.mean())),
            'samples': len(y)}


def train(db=DB, output=ARTIFACTS, dataset='synthetic-history-v5'):
    with database(db) as conn:
        rows = conn.execute('SELECT day,hour,energy_kwh,source FROM demand_samples WHERE dataset=? ORDER BY day,hour', (dataset,)).fetchall()
    days = sorted({r['day'] for r in rows})
    if len(days) < 18 or any(sum(r['day'] == d for r in rows) != 24 for d in days):
        raise ValueError('Need at least 18 complete days in SQLite. Run simulator.py --history through Node-RED first.')
    first, second = len(days)*2//3, len(days)*5//6
    groups = [set(days[:first]), set(days[first:second]), set(days[second:])]
    splits = []
    for group in groups:
        subset = [r for r in rows if r['day'] in group]
        splits.append((np.array([features(r['day'],r['hour']) for r in subset]),
                       np.array([r['energy_kwh'] for r in subset])))
    (x,y),(xv,yv),(xt,yt) = splits
    for label, values in [('train',y),('validation',yv),('test',yt)]:
        if len(np.unique(values >= THRESHOLD_KWH)) != 2:
            raise ValueError(f'{label} must contain both demand classes; collect more representative data')
    from xgboost import XGBRegressor, XGBClassifier
    boost_options = dict(n_estimators=120, max_depth=3, learning_rate=.05,
                         subsample=.9, colsample_bytree=1., tree_method='hist',
                         n_jobs=1, random_state=42)
    models = {
        'traditional_decision_tree': DecisionTreeRegressor(max_depth=6, min_samples_leaf=8, random_state=42),
        'ensemble_random_forest': RandomForestRegressor(n_estimators=80, max_depth=8, min_samples_leaf=4, n_jobs=1, random_state=42),
        'deep_ann': TransformedTargetRegressor(
            regressor=make_pipeline(StandardScaler(), MLPRegressor(hidden_layer_sizes=(64,32,16),
                activation='relu', solver='adam', max_iter=600, random_state=42, early_stopping=False)),
            transformer=StandardScaler()),
        'traditional_svr': TransformedTargetRegressor(
            regressor=make_pipeline(StandardScaler(), SVR(C=10., epsilon=.1, kernel='rbf')),
            transformer=StandardScaler()),
        'ensemble_xgboost': XGBRegressor(objective='reg:squarederror', **boost_options)}
    classifiers = {
        'traditional_decision_tree':DecisionTreeClassifier(max_depth=6,min_samples_leaf=8,class_weight='balanced',random_state=42),
        'ensemble_random_forest':RandomForestClassifier(n_estimators=80,max_depth=8,min_samples_leaf=4,class_weight='balanced_subsample',n_jobs=1,random_state=42),
        'deep_ann':make_pipeline(StandardScaler(),MLPClassifier(hidden_layer_sizes=(64,32,16),
                     max_iter=600,random_state=42,early_stopping=False)),
        'traditional_svr': make_pipeline(StandardScaler(), SVC(
            C=10., kernel='rbf', probability=True, class_weight='balanced', random_state=42)),
        'ensemble_xgboost': XGBClassifier(objective='binary:logistic', eval_metric='logloss',
            scale_pos_weight=float(np.sum(y < THRESHOLD_KWH)/np.sum(y >= THRESHOLD_KWH)),
            **boost_options)}
    yc=(y>=THRESHOLD_KWH).astype(int)
    # Oversample ONLY the ANN training split. Validation/test prevalence stays untouched.
    rng=np.random.default_rng(42)
    groups_by_class=[np.flatnonzero(yc==c) for c in (0,1)]
    count=max(map(len,groups_by_class))
    balanced_indices=np.concatenate([np.concatenate([g,rng.choice(g,count-len(g),replace=True)]) for g in groups_by_class])
    rng.shuffle(balanced_indices)
    output = Path(output)
    output.mkdir(exist_ok=True, parents=True)
    comparisons = {}
    test_probabilities = {}
    for name, model in models.items():
        classifier=classifiers[name]
        tracemalloc.start()
        start = time.perf_counter()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            model.fit(x,y)
            if name=='deep_ann':
                classifier.fit(x[balanced_indices],yc[balanced_indices])
            else:
                classifier.fit(x,yc)
        training_time = time.perf_counter()-start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        # Warm-up excluded; serial single-sample end-to-end model prediction latency.
        model.predict(xv[:1])
        timings = []
        for i in range(50):
            start = time.perf_counter()
            model.predict(xv[i % len(xv):i % len(xv)+1])
            timings.append((time.perf_counter()-start)*1000)
        blob = pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL)
        classifier_blob=pickle.dumps(classifier,protocol=pickle.HIGHEST_PROTOCOL)
        (output/f'{name}.pkl').write_bytes(blob)
        (output/f'{name}_classifier.pkl').write_bytes(classifier_blob)
        pv=classifier.predict_proba(xv)[:,1]
        pt=classifier.predict_proba(xt)[:,1]
        test_probabilities[name]=pt
        comparisons[name] = {'validation': scores(yv, np.maximum(0,model.predict(xv)),pv),
            'test': scores(yt,np.maximum(0,model.predict(xt)),pt),
            'thresholded_regression_test': scores(yt,np.maximum(0,model.predict(xt))),
            'computational': {'training_seconds': training_time,
                'inference_mean_ms': float(np.mean(timings)), 'inference_p95_ms': float(np.percentile(timings,95)),
                'peak_traced_memory_bytes': peak, 'model_size_bytes': len(blob)+len(classifier_blob),
                'regressor_size_bytes':len(blob),'classifier_size_bytes':len(classifier_blob),
                'measurement_scope':'Training/memory/size include regressor + classifier. Control inference measures regressor only.'},
            'warnings': [str(w.message) for w in caught]}
    baseline = float(np.mean(y))
    baseline_val = scores(yv, np.full_like(yv,baseline))
    eligible = [n for n,m in comparisons.items() if m['computational']['inference_p95_ms'] <= 100
                and m['validation']['rmse_kwh'] <= baseline_val['rmse_kwh']]
    selected = min(eligible, key=lambda n:comparisons[n]['validation']['rmse_kwh']) if eligible else 'constant_baseline'
    report = {'created_at':time.time(), 'dataset':dataset, 'source': sorted({r['source'] for r in rows}),
              'training_days':days[:first], 'validation_days':days[first:second], 'test_days':days[second:],
              'classification_definition': f'Actual energy >= {THRESHOLD_KWH} kWh; independent classifier probability >=0.5. Threshold fixed before test evaluation.',
              'imbalance_handling':'Balanced tree/forest/SVC weights; XGBoost training-only class ratio; ANN training-only oversampling; validation/test unchanged.',
              'test_binary_disagreements':{a:{b:int(np.count_nonzero((pa>=.5)!=(pb>=.5))) for b,pb in test_probabilities.items()} for a,pa in test_probabilities.items()},
              'memory_definition':'Peak tracemalloc-tracked allocations during fit, not total process RSS or GPU memory',
              'selection_rule':'Lowest validation RMSE among models beating constant baseline and p95 inference <=100ms; test set never selects model',
              'models':comparisons, 'baseline_validation':baseline_val,
              'baseline_test':scores(yt,np.full_like(yt,baseline)), 'selected_model':selected}
    bundle = {'model':models.get(selected), 'baseline':baseline, 'report':report}
    # Atomic publication prevents a running service reading a partial pickle.
    tmp = output/'bundle.tmp'
    tmp.write_bytes(pickle.dumps(bundle))
    tmp.replace(output/'bundle.pkl')
    (output/'ml_comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (output/'classification_predictions.json').write_text(json.dumps({'actual_high_demand':(yt>=THRESHOLD_KWH).astype(int).tolist(),
        'probabilities':{n:p.tolist() for n,p in test_probabilities.items()}},indent=2),encoding='utf-8')
    with database(db) as conn:
        conn.execute('INSERT INTO ml_evaluations VALUES (?,?)',(report['created_at'],json.dumps(report)))
    return report


def predict(bundle, hour):
    day, h = divmod(int(hour)+1,24)
    start = time.perf_counter()
    value = bundle['baseline'] if bundle['model'] is None else float(bundle['model'].predict([features(day,h)])[0])
    return max(0,value), (time.perf_counter()-start)*1000


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',type=Path,default=DB)
    parser.add_argument('--output',type=Path,default=ARTIFACTS)
    args = parser.parse_args()
    report = train(args.db,args.output)
    print(json.dumps(report,indent=2))
