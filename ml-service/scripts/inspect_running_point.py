"""Read the live worker's model fingerprint through stateless Point inference.

Run inside the ML container: python -m scripts.inspect_running_point
Uses a synthetic probe; does not query users, mutate sequence history or load pickle.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from app.features import FEATURE_CONTRACT

PROBE = [0,4,0,1,0,1,0,0,3.48,2,0,1,17.61,0,5.98,1,1,.86,1,1,25.97,0,0]


def inspect(base_url, model_path, attempts=3):
    on_disk = hashlib.sha256(model_path.read_bytes()).hexdigest() if model_path.exists() else None
    results = []
    for _ in range(attempts):
        request = Request(base_url.rstrip('/') + '/v1/score',
            data=json.dumps(dict(features=PROBE, feature_contract=FEATURE_CONTRACT)).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(request, timeout=10) as response:
                body = json.load(response)
            meta, data = body.get('meta', {}), body.get('data', {})
            loaded = meta.get('model_sha256')
            results.append(dict(loaded_worker_sha256=loaded,
                disk_matches_worker=(on_disk == loaded if on_disk and loaded else None),
                feature_contract=meta.get('feature_contract'), probe_score=data.get('anomaly_score'),
                shap_count=len(data.get('explanation') or []), explainer=meta.get('explainer')))
        except Exception as exc:
            results.append({'error_type': type(exc).__name__})
    return dict(scope='synthetic stateless probe; not the screenshot session',
        on_disk_sha256=on_disk, attempts=results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:9000')
    parser.add_argument('--model-path', type=Path, default=Path('/app/models/iforest_v1.pkl'))
    parser.add_argument('--attempts', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.attempts <= 10:
        parser.error('--attempts must be 1..10')
    print(json.dumps(inspect(args.base_url, args.model_path, args.attempts), indent=2))
