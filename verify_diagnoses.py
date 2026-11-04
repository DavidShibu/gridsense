"""Read-only audit of saved models and the current DB; run before retraining."""
import json
import pickle
import sqlite3
from contextlib import closing
from pathlib import Path
import numpy as np
from sklearn.metrics import confusion_matrix
from ml_train import features

root=Path(__file__).resolve().parent
report=json.loads((root/'artifacts/ml_comparison.json').read_text())
with closing(sqlite3.connect(f'file:{(root/"station.db").as_posix()}?mode=ro',uri=True)) as conn:
    rows=conn.execute('SELECT day,hour,energy_kwh FROM demand_samples WHERE dataset=? ORDER BY day,hour',(report['dataset'],)).fetchall()
rows=[r for r in rows if r[0] in report['test_days']]
x=np.array([features(d,h) for d,h,y in rows]); y=np.array([r[2] for r in rows])
predictions={name:np.maximum(0,pickle.loads((root/'artifacts'/f'{name}.pkl').read_bytes()).predict(x)) for name in report['models']}
reference=next(iter(predictions.values()))
result={'test_positive_count':int((y>=30).sum()),'test_negative_count':int((y<30).sum()),
        'majority_baseline_accuracy':float(max((y>=30).mean(),(y<30).mean())),
        'models':{n:{'threshold_confusion_matrix':confusion_matrix(y>=30,p>=30,labels=[False,True]).tolist(),
                     'different_binary_predictions_vs_first':int(np.count_nonzero((p>=30)!=(reference>=30))),
                     'max_raw_prediction_difference_vs_first':float(abs(p-reference).max()),
                     'saved_inference_p95_ms':report['models'][n]['computational']['inference_p95_ms']}
                  for n,p in predictions.items()}}
(root/'artifacts/diagnosis_before.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
