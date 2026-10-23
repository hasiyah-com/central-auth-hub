"""Paired, staged-only country audit: never replaces the server artifact."""
import argparse
import hashlib
import json
import platform
import random
from pathlib import Path
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_fscore_support, roc_auc_score
from app.features import FEATURE_CONTRACT, FEATURE_NAMES
from point_scoring import scores_with_model
from scripts import generate_data as generator


def generate(seed, mode, normal, attack):
    state, previous = random.getstate(), generator.COUNTRY_COUNT_MODE
    try:
        random.seed(seed)
        generator.COUNTRY_COUNT_MODE = mode
        rows = [generator.normal_session() + [0] for _ in range(normal)]
        rows += [generator.anomaly_session() + [1] for _ in range(attack)]
        random.shuffle(rows)
        rows = np.asarray(rows, dtype=float)
        return rows[:, :-1], rows[:, -1].astype(int)
    finally:
        random.setstate(state)
        generator.COUNTRY_COUNT_MODE = previous


def metrics(y, scores, threshold):
    prediction = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(y, prediction, labels=[0, 1]).ravel()
    p, r, f, _ = precision_recall_fscore_support(y, prediction, average='binary', zero_division=0)
    return dict(threshold=float(threshold), tp=int(tp), fp=int(fp), fn=int(fn), tn=int(tn),
        precision=float(p), recall=float(r), f1=float(f), fpr=float(fp / (tn + fp)),
        roc_auc=float(roc_auc_score(y, scores)), ap=float(average_precision_score(y, scores)))


def slices(X, y, scores, threshold):
    masks = {'midnight': X[:, 0] == 0, 'night_0_5': X[:, 0] <= 5,
             'country_1': X[:, 5] == 1, 'country_2_plus': X[:, 5] >= 2}
    out = {}
    for name, mask in masks.items():
        selected = mask & (y == 0)
        out[name] = {'normal': int(selected.sum()), 'false_warn': int((scores[selected] >= threshold).sum()),
            'fpr': float((scores[selected] >= threshold).mean()) if selected.any() else None}
    return out


def evaluate(output, seeds, normal, attack):
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for seed in seeds:
        old, y = generate(seed, 'legacy-v0', normal, attack)
        new, yn = generate(seed, 'distinct-v1', normal, attack)
        assert np.array_equal(y, yn)
        assert np.array_equal(np.delete(old, 5, axis=1), np.delete(new, 5, axis=1))
        assert np.all(new[:, 5] >= 1)
        train, rest = train_test_split(np.arange(len(y)), test_size=.4, stratify=y, random_state=42)
        cal, test = train_test_split(rest, test_size=.5, stratify=y[rest], random_state=43)
        models = {}
        result = {'seed': seed, 'paired_other_features_exact': True, 'models': {},
            'split_rows': dict(train=len(train), calibration=len(cal), test=len(test)),
            'normal_train': int((y[train] == 0).sum())}
        for mode, data in [('legacy-v0', old), ('distinct-v1', new)]:
            model = IsolationForest(n_estimators=100, max_samples=256, contamination=.02,
                                    random_state=42, n_jobs=-1).fit(data[train][y[train] == 0])
            model.rba_feature_contract_ = FEATURE_CONTRACT
            model.rba_training_provenance_ = dict(source='paired-synthetic-country-audit', seed=seed,
                country_count_mode=mode, training_sha256=hashlib.sha256(data[train][y[train] == 0].tobytes()).hexdigest())
            models[mode] = model
            cs = np.array(scores_with_model(model, new[cal]))
            threshold = float(np.nextafter(np.quantile(cs[y[cal] == 0], .99, method='higher'), np.inf))
            scores = np.array(scores_with_model(model, new[test]))
            r = {'on_corrected_test': {'existing_warn': metrics(y[test], scores, .4606),
                'point_050': metrics(y[test], scores, .5), 'calibrated_1pct': metrics(y[test], scores, threshold)},
                'normal_slices_existing_warn': slices(new[test], y[test], scores, .4606),
                'normal_slices_calibrated': slices(new[test], y[test], scores, threshold),
                'on_legacy_test_existing_warn': metrics(y[test], np.array(scores_with_model(model, old[test])), .4606)}
            missing = new[test].copy()
            missing[:, 5] = 0
            r['constructed_country_0_stress'] = metrics(y[test], np.array(scores_with_model(model, missing)), threshold)
            result['models'][mode] = r
            if mode == 'distinct-v1':
                path = output / f'candidate_distinct_{seed}.pkl'
                joblib.dump(model, path)
                r['staged_model_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        v = [0,4,0,1,0,1,0,0,3.48,2,0,1,17.61,0,5.98,1,1,.86,1,1,25.97,0,0]
        result['representative_scores_not_actual_session'] = {mode: scores_with_model(m, [v])[0] for mode,m in models.items()}
        candidate = result['models']['distinct-v1']
        old_fixed = result['models']['legacy-v0']['on_corrected_test']['existing_warn']
        new_fixed = candidate['on_corrected_test']['existing_warn']
        result['screening_fixed_threshold'] = dict(fpr_at_most_1_1pct=new_fixed['fpr'] <= .011,
            midnight_fpr_at_most_3pct=candidate['normal_slices_existing_warn']['midnight']['fpr'] <= .03,
            recall_loss_at_most_0_5pp=200 * (old_fixed['tp'] - new_fixed['tp']) <= old_fixed['tp'] + old_fixed['fn'])
        reports.append(result)
        print(json.dumps(dict(seed=seed, old_on_corrected=old_fixed, new_on_corrected=new_fixed,
                              screening=result['screening_fixed_threshold'])), flush=True)
    report = dict(scope='Point IF only; synthetic row holdouts, not real traffic, independent users or end-to-end F1',
        activation='staged_only_not_approved', feature_names=FEATURE_NAMES, per_seed_generated_rows=normal+attack,
        runtime=dict(python=platform.python_version(), numpy=np.__version__, sklearn=sklearn.__version__), results=reports)
    (output / 'country_semantics_result.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', type=int, nargs='+', default=[202610231,202610232,202610233])
    parser.add_argument('--normal', type=int, default=20000)
    parser.add_argument('--attack', type=int, default=1000)
    args = parser.parse_args()
    if args.output.resolve() == Path('/app/models'):
        parser.error('Use a separate staging directory, not /app/models')
    evaluate(args.output, args.seeds, args.normal, args.attack)
