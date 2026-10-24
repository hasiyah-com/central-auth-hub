"""Export known research bytes and truthful shadow metadata; never rewrites the model."""

import argparse, hashlib, json, math, os
from pathlib import Path
from app.features import FEATURE_NAMES, FEATURE_CONTRACT

EXPECTED = "71de43c4214f6db5d46dbec8ec7baf31f3d9429af0632fb19c8cd67a419f61ca"


def prepare(model, freeze, out):
    content = Path(model).read_bytes()
    config = json.loads(Path(freeze).read_text())["models"]["IF-mixed5"]
    sha = hashlib.sha256(content).hexdigest()
    if (
        sha != EXPECTED
        or config["artifact_sha256"] != sha
        or not math.isfinite(config["threshold"])
    ):
        raise ValueError("not_the_audited_artifact")
    target = Path(out)
    target.mkdir(parents=True, exist_ok=True)
    if any(p.name != ".gitignore" for p in target.iterdir()):
        raise ValueError("output_must_be_empty")
    manifest = dict(
        version="if-candidate-shadow-v1",
        mode="shadow",
        input_contract=FEATURE_CONTRACT,
        training_semantics="offline-r79-mirror-not-live-certified",
        features=FEATURE_NAMES,
        artifact_sha256=sha,
        sklearn_version="1.5.2",
        raw_threshold=config["threshold"],
        score_transform="sigmoid_5_negative_decision",
        source_provenance=dict(
            experiment="NF frozen IF-mixed5",
            model_selection="diagnostic_only_not_approved_for_enforcement",
            freeze_sha256=hashlib.sha256(Path(freeze).read_bytes()).hexdigest(),
            input_semantics="23-feature offline lifecycle mirror; live database semantic equivalence not certified",
        ),
    )
    (target / "IF-mixed5.joblib").write_bytes(content)
    payload = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (target / "manifest.json").write_bytes(payload)
    for p in target.iterdir():
        os.chmod(p, 0o644)
    return dict(
        artifact_sha256=sha, manifest_sha256=hashlib.sha256(payload).hexdigest()
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.model, args.freeze, args.out), indent=2))
