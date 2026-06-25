"""Stream-sample the real RBA dataset (Wiefling 2022, ~9 GB) -> small base CSV.

ดึงข้อมูล "จริง" จาก rba-dataset.csv โดยไม่โหลดทั้งไฟล์ (reservoir sampling สตรีมทีละแถว):
  - normal  10,000 แถว  : Is Account Takeover=False AND Is Attack IP=False AND Login Successful=True
  - anomaly    100 แถว  : Is Account Takeover=True   (ground-truth ATO ที่หายากในชุดจริง)

Output: ml-service/data/rba_base_sample.csv (raw RBA columns + label + source)
  label: 0=normal, 1=anomaly   (เก็บไว้ใช้ "วัดผล" เท่านั้น ไม่ป้อนเข้าโมเดล unsupervised)

Run (local):
    py ml-service/scripts/sample_rba_base.py
หรือกำหนด path เอง:
    py ml-service/scripts/sample_rba_base.py "C:/path/rba-dataset.csv" "ml-service/data/rba_base_sample.csv"
"""

import csv
import random
import sys
from pathlib import Path

random.seed(42)

DEFAULT_INPUT = r"C:\Users\hasiy\Downloads\rba-dataset\rba-dataset.csv"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "rba_base_sample.csv"

NORMAL_TARGET = 10_000
ANOMALY_TARGET = 100

# RBA column indices
C_TS = 1
C_COUNTRY = 5
C_LOGIN_OK = 13
C_ATTACK_IP = 14
C_ATO = 15

csv.field_size_limit(10_000_000)


def is_true(v: str) -> bool:
    return v.strip().lower() == "true"


def main():
    in_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not Path(in_path).exists():
        print(f"❌ ไม่พบไฟล์อ้างอิง: {in_path}")
        sys.exit(1)

    normal_res: list[list[str]] = []  # reservoir 10,000
    anomaly_res: list[list[str]] = []  # reservoir 100
    n_normal_seen = 0
    n_anomaly_seen = 0
    header: list[str] = []

    print(f"📖 อ่านไฟล์อ้างอิง (สตรีม): {in_path}")
    with open(in_path, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        for i, row in enumerate(reader, 1):
            if len(row) < 16:
                continue
            ato = is_true(row[C_ATO])
            attack_ip = is_true(row[C_ATTACK_IP])
            login_ok = is_true(row[C_LOGIN_OK])

            if ato:
                # anomaly pool (rare) — reservoir sample
                n_anomaly_seen += 1
                if len(anomaly_res) < ANOMALY_TARGET:
                    anomaly_res.append(row)
                else:
                    j = random.randint(0, n_anomaly_seen - 1)
                    if j < ANOMALY_TARGET:
                        anomaly_res[j] = row
            elif login_ok and not attack_ip:
                # clean-normal pool — reservoir sample
                n_normal_seen += 1
                if len(normal_res) < NORMAL_TARGET:
                    normal_res.append(row)
                else:
                    j = random.randint(0, n_normal_seen - 1)
                    if j < NORMAL_TARGET:
                        normal_res[j] = row

            if i % 1_000_000 == 0:
                print(
                    f"  ...{i:,} rows | normal_seen={n_normal_seen:,} "
                    f"anomaly_seen={n_anomaly_seen:,} "
                    f"(kept N={len(normal_res):,} A={len(anomaly_res)})"
                )

    out_header = header + ["label", "source"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(out_header)
        for r in normal_res:
            w.writerow(r + ["0", "rba"])
        for r in anomaly_res:
            w.writerow(r + ["1", "rba"])

    print("\n✅ เสร็จ — base sample จากข้อมูลจริง")
    print(f"   normal  kept: {len(normal_res):,} (seen {n_normal_seen:,})")
    print(f"   anomaly kept: {len(anomaly_res):,} (seen {n_anomaly_seen:,})")
    print(f"   output: {out_path}")


if __name__ == "__main__":
    main()
