"""สร้างประชากรสังเคราะห์จากรูปแบบรวมของ CSV จริง โดยไม่ส่งออก PII.

อินพุตคือ directory ที่แตก ZIP แล้วและมี ``login_sessions5.csv`` พร้อมตาราง
ประกอบ ผู้รันต้องเก็บ directory นี้ไว้นอก Git. ผลลัพธ์มีเพียง alias R01..R48,
ค่าพารามิเตอร์รวม, roster และ users.xlsx ที่เป็นตัวตนสังเคราะห์ทั้งหมด

เอกสารผูกพัน: ``docs/design/REAL_SEEDED_POPULATION_V1_PREREG.md``
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import random
import re
import uuid
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

POP_SEED = 770927
N_TOTAL = 48
N_VALIDATION = 32
N_HOLDOUT = 16
ALIAS_PREFIX = "R"

AUTH_FAILURE_ACTIONS = frozenset(
    {
        "hub_login_failed_inactive",
        "hub_login_failed_google_sub_mismatch",
        "hub_login_failed_line_sub_mismatch",
        "oauth_login_failed_inactive",
        "oauth_login_failed_google_sub_mismatch",
        "oauth_passkey_login_failed",
        "passkey_login_failed",
        "risk_mfa_verify_failed",
        "stepup_totp_failed",
    }
)
SCOPE_WEIGHTS = {
    "email": 0.1,
    "name": 0.1,
    "faculty": 0.3,
    "major": 0.3,
    "student_id": 0.6,
    "employee_id": 0.6,
}


def _read(root: Path, name: str) -> pd.DataFrame:
    p = root / name
    if not p.exists():
        raise FileNotFoundError(f"missing required input: {p}")
    return pd.read_csv(p, low_memory=False)


def _times(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        if c.endswith("_at") or c == "created_at":
            df[c] = pd.to_datetime(df[c], errors="coerce", utc=True)
    return df


def _weights(values) -> dict:
    c = Counter(str(v) for v in values if pd.notna(v))
    total = sum(c.values())
    return {k: v / total for k, v in c.items()} if total else {}


def _renorm(d: dict[str, float]) -> dict[str, float]:
    d = {str(k): max(float(v), 0.0) for k, v in d.items() if float(v) > 0}
    total = sum(d.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in d.items()}


def _perturb_mix(mix: dict[str, float], rng: random.Random) -> dict[str, float]:
    if not mix:
        return {}
    vals = {k: rng.gammavariate(max(v * 30.0, 0.5), 1.0) for k, v in mix.items()}
    return _renorm(vals)


def _device_key(row: pd.Series) -> str:
    device = str(row.get("device_type") or "").lower()
    os_name = str(row.get("os_name") or "").lower()
    browser = str(row.get("browser") or "").lower()
    if "tablet" in device or "ipad" in os_name:
        return "ipad_fb"
    if "android" in os_name:
        return "android15_vivo" if "15" in os_name else "android10_k"
    if "mobile" in device or "iphone" in os_name or "ios" in os_name:
        return "iphone_safari" if "safari" in browser else "iphone_fb"
    if "edge" in browser:
        return "win11_edge130"
    return "win10_chrome151"


def _scope_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    raw = str(value).strip()
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, (list, tuple)):
            return [str(x) for x in parsed]
    except (ValueError, SyntaxError):
        pass
    raw = raw.strip("{}[]")
    return [x.strip().strip("'\"") for x in raw.split(",") if x.strip()]


def _scope_score(value) -> float:
    return min(1.0, sum(SCOPE_WEIGHTS.get(x, 0.1) for x in _scope_list(value)))


def _subsystem_map(sessions: pd.DataFrame) -> dict[str, str]:
    ids = [str(x) for x in sessions["subsystem_id"].dropna().unique()]
    counts = sessions["subsystem_id"].astype(str).value_counts()
    ids.sort(key=lambda x: (-int(counts.get(x, 0)), x))
    names = ["SUB_A", "SUB_B"]
    return {sid: names[min(i, len(names) - 1)] for i, sid in enumerate(ids)}


def _global_weekend_rate(sessions: pd.DataFrame) -> float:
    ts = sessions["created_at"].dropna()
    return float((ts.dt.weekday >= 5).mean()) if len(ts) else 0.2


def _linked_failures(audit: pd.DataFrame, uid: str) -> pd.DataFrame:
    if audit.empty:
        return audit
    actor = audit["actor_id"].astype(str) == uid
    target = audit["target_id"].astype(str) == uid
    return audit[(actor | target) & audit["action"].isin(AUTH_FAILURE_ACTIONS)]


def derive_prototypes(root: Path) -> tuple[list[dict], dict]:
    sessions = _times(_read(root, "login_sessions5.csv"))
    passkeys = _times(_read(root, "passkey_credentials.csv"))
    access = _times(_read(root, "access_list1.csv"))
    audit = _times(_read(root, "audit_logs1.csv"))
    users = _times(_read(root, "users1.csv"))
    subsystems = _times(_read(root, "subsystems1.csv"))

    sessions = sessions[
        ~sessions["is_attack_ip"].fillna(False).astype(bool)
        & ~sessions["is_account_takeover"].fillna(False).astype(bool)
    ].copy()
    if sessions.empty:
        raise ValueError("no candidate-normal login sessions")

    sub_map = _subsystem_map(sessions)
    scope_by_sub = {
        str(r["id"]): _scope_score(r.get("scope")) for _, r in subsystems.iterrows()
    }
    user_by_id = {str(r["id"]): r for _, r in users.iterrows()}
    global_weekend = _global_weekend_rate(sessions)
    end = sessions["created_at"].max()
    protos = []

    for uid_value, g in sessions.groupby("user_id", sort=False):
        uid = str(uid_value)
        g = g.sort_values("created_at").copy()
        ts = g["created_at"].dropna()
        if ts.empty:
            continue
        n = len(g)
        hour_counts = ts.dt.hour.value_counts()
        n_peaks = 1 if n < 10 else (2 if n < 50 else 3)
        peaks = [int(x) for x in hour_counts.head(n_peaks).index]
        circular = np.minimum(
            np.abs(ts.dt.hour.to_numpy() - np.median(ts.dt.hour)),
            24 - np.abs(ts.dt.hour.to_numpy() - np.median(ts.dt.hour)),
        )
        spread = float(np.clip(np.std(circular) * 1.5 + 1.5, 1.5, 4.5))
        weekend = (int((ts.dt.weekday >= 5).sum()) + 5 * global_weekend) / (n + 5)

        devices = _weights(g.apply(_device_key, axis=1)) or {"win10_chrome151": 1.0}
        mapped_subs = ["HUB" if pd.isna(x) else sub_map[str(x)] for x in g["subsystem_id"]]
        subs = _weights(mapped_subs) or {"HUB": 1.0}
        methods = _weights(g["login_method"]) or {"google": 1.0}

        gaps = ts.diff().dt.total_seconds().div(60).dropna()
        durations = (
            pd.to_datetime(g["logout_at"], errors="coerce", utc=True) - g["created_at"]
        ).dt.total_seconds().div(60)
        durations = durations[(durations > 0) & np.isfinite(durations)]
        med_dur = float(durations.median()) if len(durations) else 20.0
        log_sd = float(np.std(np.log(np.maximum(durations, 0.5)))) if len(durations) > 1 else 1.5

        pk = passkeys[passkeys["user_id"].astype(str) == uid]
        active_pk = pk[pk["revoked_at"].isna()] if "revoked_at" in pk else pk
        if len(active_pk):
            oldest = active_pk["created_at"].min()
            last_used = active_pk["last_used_at"].max()
            age = max(1, int((end - oldest).total_seconds() / 86400)) if pd.notna(oldest) else 30
            last_days = max(0, int((end - last_used).total_seconds() / 86400)) if pd.notna(last_used) else 30
            passkey = {"count": min(2, len(active_pk)), "age_days": min(age, 365), "last_used_days": min(last_days, 30)}
        else:
            passkey = {"count": 0, "age_days": 0, "last_used_days": 0}

        perms = access[access["user_id"].astype(str) == uid]
        change_times = pd.concat([perms["granted_at"], perms["revoked_at"]]).dropna()
        perm_age = min(365, max(0, int((end - change_times.max()).total_seconds() / 86400))) if len(change_times) else 365
        fails = _linked_failures(audit, uid)
        fail_rate = min(0.06, len(fails) / max(n + len(fails), 1))

        nonnull_subs = [str(x) for x in g["subsystem_id"].dropna()]
        scope_vals = [scope_by_sub.get(x, 0.3) for x in nonnull_subs]
        scope = min((0.3, 0.5, 0.8, 1.0), key=lambda x: abs(x - (float(np.median(scope_vals)) if scope_vals else 0.3)))
        urow = user_by_id.get(uid)
        mfa = bool(urow.get("mfa_always", False)) if urow is not None else False

        protos.append(
            {
                "rows": int(np.clip(n, 40, 160)),
                "hour_peaks": peaks,
                "hour_spread": spread,
                "weekend_rate": float(np.clip(weekend, 0.0, 0.7)),
                "devices": devices,
                "drift": float(np.clip(1 / max(n, 5), 0.05, 0.20)),
                "subsystems": subs,
                "sticky": float(np.clip(max(subs.values()), 0.70, 1.0)),
                "dur": (math.log(float(np.clip(med_dur, 8, 45))), float(np.clip(log_sd, 1.2, 2.2))),
                "overlap": float(np.clip((g["logout_at"].isna().mean() if "logout_at" in g else 0.05), 0.0, 0.15)),
                "active_sub": 2 if len(subs) > 1 else 1,
                "methods": methods,
                "passkey": passkey,
                "fail_rate": float(fail_rate),
                "scope": float(scope),
                "perm_age": int(perm_age),
                "incidents": 0,
                "mfa_always": mfa,
                "observed_gap_median_min": float(gaps.median()) if len(gaps) else None,
            }
        )

    if len(protos) < 2:
        raise ValueError("need at least two real behavior prototypes")
    meta = {
        "candidate_normal_sessions": int(len(sessions)),
        "source_users_with_sessions": int(len(protos)),
        "confirmed_attack_rows": 0,
        "real_values_exported": False,
    }
    return protos, meta


def generate_population(prototypes: list[dict], seed: int = POP_SEED, n: int = N_TOTAL) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        base = dict(rng.choice(prototypes))
        peaks = []
        for h in base["hour_peaks"]:
            v = (int(h) + rng.choice([-1, 0, 0, 0, 1])) % 24
            if v not in peaks:
                peaks.append(v)
        devices = _perturb_mix(base["devices"], rng) or {"win10_chrome151": 1.0}
        subs = _perturb_mix(base["subsystems"], rng) or {"HUB": 1.0}
        methods = _perturb_mix(base["methods"], rng) or {"google": 1.0}
        pk = dict(base["passkey"])
        if pk["count"]:
            pk["age_days"] = int(np.clip(pk["age_days"] * rng.uniform(0.7, 1.3), 7, 365))
            pk["last_used_days"] = int(np.clip(pk["last_used_days"] + rng.randint(-3, 3), 0, 30))
        out.append(
            {
                "alias": f"{ALIAS_PREFIX}{i + 1:02d}",
                "rows": int(np.clip(base["rows"] * rng.uniform(0.75, 1.25), 40, 160)),
                "hour_peaks": peaks or [12],
                "hour_spread": float(np.clip(base["hour_spread"] * rng.uniform(0.8, 1.2), 1.5, 4.5)),
                "weekend_rate": float(np.clip(base["weekend_rate"] + rng.uniform(-0.05, 0.05), 0.0, 0.7)),
                "devices": devices,
                "drift": float(np.clip(base["drift"] * rng.uniform(0.8, 1.2), 0.05, 0.20)),
                "subsystems": subs,
                "sticky": float(np.clip(max(subs.values()), 0.70, 1.0)),
                "dur": (
                    float(np.clip(base["dur"][0] + rng.uniform(-0.15, 0.15), math.log(8), math.log(45))),
                    float(np.clip(base["dur"][1] * rng.uniform(0.9, 1.1), 1.2, 2.2)),
                ),
                "overlap": float(np.clip(base["overlap"] + rng.uniform(-0.02, 0.02), 0.0, 0.15)),
                "active_sub": 2 if len(subs) > 1 else 1,
                "methods": methods,
                "passkey": pk,
                "fail_rate": float(np.clip(base["fail_rate"] * rng.uniform(0.7, 1.3), 0.0, 0.06)),
                "scope": base["scope"],
                "perm_age": int(np.clip(base["perm_age"] * rng.uniform(0.8, 1.2), 1, 365)),
                "incidents": 0,
                "mfa_always": base["mfa_always"] if rng.random() < 0.8 else not base["mfa_always"],
            }
        )
    return out


def split_population(profiles: list[dict], seed: int = POP_SEED) -> tuple[list[dict], list[dict]]:
    rows = list(profiles)
    random.Random(seed).shuffle(rows)
    return rows[:N_VALIDATION], rows[N_VALIDATION : N_VALIDATION + N_HOLDOUT]


def build_synthetic_identities(profiles: list[dict], out_xlsx: Path, out_roster: Path) -> dict[str, str]:
    rows = []
    roster = {}
    namespace = uuid.UUID("9e2bd57f-06a4-4a41-bd10-2a326b06e68d")
    for p in profiles:
        alias = p["alias"]
        email = f"risk-{alias.lower()}@uni.ac.th"
        uid = str(uuid.uuid5(namespace, alias))
        roster[alias] = email
        rows.append(
            {
                "id": uid,
                "email": email,
                "user_type": "student" if int(alias[1:]) % 3 else "staff",
                "full_name": f"Synthetic {alias}",
                "faculty": "synthetic",
                "year_or_position": "experiment",
            }
        )
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_excel(out_xlsx, index=False)
    out_roster.write_text(json.dumps(roster, indent=2) + "\n", encoding="utf-8")
    return roster


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def privacy_scan(paths: list[Path]) -> dict:
    forbidden = re.compile(r"(?:@gmail\.com|@pnu\.ac\.th|\b(?:\d{1,3}\.){3}\d{1,3}\b)", re.I)
    findings = []
    for path in paths:
        if path.suffix.lower() not in {".json", ".md", ".csv"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if forbidden.search(text):
            findings.append(path.name)
    return {"passed": not findings, "files_with_forbidden_patterns": findings}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", type=Path, required=True)
    ap.add_argument("--source-zip", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    prototypes, source_meta = derive_prototypes(args.input_dir)
    profiles = generate_population(prototypes)
    val, hold = split_population(profiles)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    users_xlsx = args.out_dir / "synthetic_users.xlsx"
    roster_json = args.out_dir / "roster_real_seeded_v1.json"
    build_synthetic_identities(profiles, users_xlsx, roster_json)

    summary = {
        "population": "real_seeded_v1",
        "population_seed": POP_SEED,
        "source": {
            **source_meta,
            "zip_sha256": _sha256(args.source_zip) if args.source_zip else None,
        },
        "split": {
            "validation": [p["alias"] for p in val],
            "holdout": [p["alias"] for p in hold],
        },
        "population_summary": {
            "n_profiles": len(profiles),
            "passkey_profiles": sum(p["passkey"]["count"] > 0 for p in profiles),
            "multi_device_profiles": sum(len(p["devices"]) > 1 for p in profiles),
            "multi_subsystem_profiles": sum(len(p["subsystems"]) > 1 for p in profiles),
            "weekend_rate_range": [round(min(p["weekend_rate"] for p in profiles), 4), round(max(p["weekend_rate"] for p in profiles), 4)],
        },
        "privacy": {
            "raw_identifiers_in_output": False,
            "aliases_only": True,
            "real_values_exported": False,
        },
    }
    spec_path = args.out_dir / "population_spec.json"
    summary_path = args.out_dir / "population_summary.json"
    spec_path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scan = privacy_scan([spec_path, summary_path, roster_json])
    if not scan["passed"]:
        raise RuntimeError(f"privacy scan failed: {scan}")
    print(json.dumps({"profiles": len(profiles), "validation": len(val), "holdout": len(hold), "privacy_scan": scan}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
