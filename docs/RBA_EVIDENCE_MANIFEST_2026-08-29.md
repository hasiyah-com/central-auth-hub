# ชุดหลักฐานการทดลอง RBA — Evidence Manifest (freeze)

**สร้างเมื่อ:** 2026-08-29 · **สร้างโดย:** `scripts/build_evidence_manifest.py`

เอกสารนี้ freeze ผลการทดลอง 4-Layer RBA เพื่อให้ตรวจสอบย้อนกลับได้ —
ตัวเลขที่อ้างในรายงาน/thesis ทุกตัวสาวกลับมาที่ commit + ไฟล์ + hash ในนี้ได้

**ตรวจสอบว่าหลักฐานยังไม่ถูกแก้:**

```bash
python scripts/build_evidence_manifest.py --verify
```

---

## 1. Provenance (commit)

| รายการ | ค่า |
|---|---|
| commit SHA (เต็ม) | `2f46ae1685faa13eda1ab173143b86ed70e49e2d` |
| commit SHA (สั้น) | `2f46ae1` |
| branch | `main` |
| working tree ตอนสร้าง manifest | มีไฟล์ที่ยังไม่ commit (ดู §5) |
| จำนวนไฟล์หลักฐาน | 48 |

> ⚠️ commit SHA ด้านบนคือ **commit ก่อนหน้า** ตอน generate — SHA ของ freeze commit เอง
> บันทึกไว้ที่ §5 (เขียนเพิ่มหลัง commit เสร็จ เพราะ SHA คำนวณจากเนื้อหาไฟล์รวมทั้ง manifest)

## 2. Configuration ที่ล็อก (ดึงจาก source จริง)

อ่านจาก `hub/backend/app/security/l3_sequence.py` ณ commit ข้างต้น

| ค่าคงที่ | ค่า | ความหมาย |
|---|---|---|
| `DIMS` | `6` | จำนวนมิติ residual ต่อเหตุการณ์ |
| `WINDOW` | `5` | ความยาว rolling window (เหตุการณ์) |
| `MAX_HISTORY` | `2000` | จำนวน residual สูงสุดที่เก็บ/ใช้ต่อคน |
| `CAL_FPR` | `0.001` | threshold anomaly = quantile(1 − ค่านี้) → p99.9 |
| `EXTREME_FPR` | `0.0003` | threshold extreme → p99.97 |
| `TIER_DIAGNOSTIC` | `100` | history ขั้นต่ำที่เริ่มให้คะแนน (log อย่างเดียว) |
| `TIER_WARN` | `1000` | history ขั้นต่ำที่ขึ้นธง monitoring l3_investigate ได้ |
| `TIER_CHALLENGE` | `2000` | history ขั้นต่ำที่บันทึก shadow_decision=would_challenge |
| `MODEL_VERSION` | `"iforest-l3-seq-v1"` | รหัสเวอร์ชันโมเดลที่เขียนลงทุก contract |

**สถาปัตยกรรมที่ล็อกคู่กัน:** residual 6 มิติ × [mean, slope, ptp] = 18 อินพุต ·
per-user IsolationForest (`n_estimators=100`, `contamination=0.02`) ·
L3 = แกน monitoring ล้วน (`normal` / `l3_investigate`) — ไม่แตะ access decision

ค่าคงที่ชุดเดียวกันนี้ต้องตรงกับ `ml-service/app/sequence.py` —
บังคับด้วย `tests/test_l3_sequence_client.py::test_constants_parity_hub_vs_ml_service`

## 3. Seeds

| ชุด | seeds |
|---|---|
| train / validation (dev) | `42, 43, 44, 45, 46` |
| final gate evaluation | `101, 102, 103, 104, 105` |
| IsolationForest random_state | `42 (คงที่ทุก fit)` |

**กติกาที่ยึด:** ชุด evaluation (101–105) ถูกสร้างใหม่ทั้ง normal และ attack
โมเดลไม่เคยเห็น · รันครั้งเดียว · **ห้ามปรับ threshold/โมเดล/ฟีเจอร์จากผลชุดนี้**

## 4. Hash ของไฟล์หลักฐาน (SHA-256)

### 4.1 รายงานการทดลอง

| ไฟล์ | ขนาด (ไบต์) | SHA-256 |
|---|---|---|
| `profiles_v2_2026-08-21.md` | 8,821 | `96f0f3d2c69f9b6daa74e5ae7aa77e914961db9d2a918f92d55fb9106f5d1578` |
| `rba_4layer_v2_2026-08-21.md` | 19,221 | `3683e88242b68a718d922999732de2c973d205f38ff9840079befe88ee5a0b4c` |
| `learning_curve_v2_2026-08-21.md` | 7,831 | `91e9dc44f9d57bbdaea814d011b6c6fb5ce2f62a4738b9dc7a26f5613ff1b670` |
| `phase1_production_port_2026-08-21.md` | 6,302 | `d5504fcd6bb416378e8335cc8e0b6a62692e56b67f656efa8d3062a668a5c821` |
| `v7_generator_fix_2026-08-21.md` | 12,028 | `421e5994bc584b79d06e4f56fcd721b28480fcf38419610cce1e63fa4201c8d9` |
| `v2_to_v7_version_sweep_2026-08-21.md` | 11,902 | `6d03665f63cdf708ec9c166d04da30d5f9fa2745e70f947d16651dd61732b873` |
| `model_version_decision_2026-08-21.md` | 11,063 | `188bf10b7ef5253bd9019dd6b2ac60d3f84e8c5343623879dc7c968401cd4c6f` |
| `v8_verification_2026-08-23.md` | 8,444 | `9d26d8e8f26ab0a075ad11baba98fbe307f3493863161c7d4aaa47b41c398189` |
| `ablation_v8_vs_rule_2026-08-23.md` | 8,338 | `5a41d6dfc11d7f43499d8306a7cf446036d1dbbe9373015090f51242afb9217d` |
| `tier1_rarity_behavior_2026-08-25.md` | 8,665 | `e9ba4c5230e49d4491f0ba66d3c79a820c5e02be3e2cb853aec90c47531cb96f` |
| `tier2_cadence_signature_2026-08-25.md` | 7,136 | `30086b241711ac0d9650332cdb763960716f2573c12634705c22440e591ad528` |
| `lc_4layer_2026-08-25.md` | 2,124 | `aa9c4c24a7a1c8b6096097ccf7c83a617d9b3c0a26b5079e7724badacbd49c83` |
| `l3_ownership_nocampaign_2026-08-25.md` | 3,291 | `c46934aacff5d7088aa10fd60a1cbd107328ccbad93b7972b0bcd791d3d4fcd0` |
| `l3_campaign_2026-08-26.md` | 6,592 | `8599745a48d0961fb6ebbd59cf0dae8f7a9a2266cac61da2fe1f12146d5d8033` |
| `l3_sequence_channel_2026-08-26.md` | 6,471 | `f104634e03d8fbd8abedfac089cc86de26bc102e7448f2c1e80402e29afea24d` |
| `l3_raw_vs_effective_2026-08-26.md` | 5,786 | `c9e8e33db3cc5b8bcf8b54dd47871a9aa2dc438216ef3a9e18c370754cb3b86c` |
| `exp_4layer_full_2026-08-26.md` | 7,391 | `6f5fc943f00f756a83fa617fcb4a6d17b53261b0bb494f62245c7257acb3b814` |
| `exp_l3_config_g_2026-08-26.md` | 8,090 | `74be61c870491dfbce585c0196ae27414ab78b470fcfe88b4b3c321c9c2c565f` |
| `exp_lc_v3_2026-08-26.md` | 3,286 | `8285adc81f5d881748933ade44b19449a84087d349a7220c41b25262e38a67a5` |
| `exp_thr_and_l2_fix_2026-08-26.md` | 8,063 | `c2ba34f6d19a169122a0a61a826dd1a257f2868534a5302d141a4837545a8f2e` |
| `exp_l3_window_2026-08-26.md` | 7,389 | `dc4891f24d3f234f16ee80fc6f943fa4ae5d4f016e29a03fbdd8b65a1f684770` |
| `exp_campaign_level_2026-08-26.md` | 6,617 | `dc849647c5d107e31c55c50e97af92d9ca9a53fa30f4a3589698cb1b5c4791de` |
| `exp_final_synthetic_2026-08-26.md` | 10,751 | `6a27674da6fcdcf1ed54e77a4d61d3c7e9099a7ff705fc50f370a42018408004` |
| `exp_final_gate_2026-08-26.md` | 7,531 | `66312e5594fae9406993b9dc1452019ef9fb10d0b1d77326e2c29b55c7bf8871` |
| `l3_service_split_2026-08-29.md` | 15,423 | `8a2d15b36964d042b0c77ab1582e7ed20c4e1462de617516121f39930cbdeed2` |
| `l3_stability_2026-08-29.md` | 17,341 | `471333b6cc6d599345cab6277c64d779dc4b46f96d45eeed971b604c075b56ca` |
| `l3_shadow_replay_2026-08-29.md` | 9,030 | `17b7e349c7422ffea810a82eb0a838dba2ef82c9ac04c8b75e535d1130f7def8` |

### 4.2 โค้ดที่ผลิตตัวเลข (harness ทดลอง + production ที่ถูกวัด)

| ไฟล์ | ขนาด (ไบต์) | SHA-256 |
|---|---|---|
| `ml-service/scripts/gen_v3.py` | 11,872 | `7b63149d74ab487178301abc362c6729665c465b92978e25fb5107777abe695b` |
| `ml-service/scripts/build_profiles_v2.py` | 51,232 | `a03f4c365c2781f1d83299ecc9b55750d5434636937540e33865601926b1c991` |
| `ml-service/scripts/features_v2.py` | 18,366 | `ed9618f074e4352ad9124adb8c22e766657a244478a4ec86b5dc87d82ac41ef3` |
| `ml-service/scripts/exp_final_gate.py` | 22,076 | `ddfb33bfc1472a5ab55581f7b2307d80209ad20b82193424c80b6fea3b6100bb` |
| `ml-service/scripts/exp_campaign_level.py` | 12,553 | `9cd30886ffc70af524fdce38dc0becf5e5cb1efc3d4f0e8a7894fce64e8250da` |
| `ml-service/scripts/exp_final_synthetic.py` | 17,225 | `501b40bea8970610b83394ba44ab9311910db9fd39013da65d37a275034d3b30` |
| `ml-service/scripts/exp_lc_v3.py` | 14,828 | `0d4b1f7a304681ded11c794ca4b536f13893590e128de12a88d7a4c6a0b7830d` |
| `ml-service/scripts/exp_4layer_full.py` | 18,370 | `5abdce4e572c71591a7d467086696b1c04b1815e67b39387ff4cfa26e71d3fc2` |
| `ml-service/scripts/lc_l3_sequence.py` | 12,210 | `081509b30d317f48e6883815b12efde8dcbf5681920c01f2559f64376fd1ee98` |
| `ml-service/scripts/lc_l3_ownership.py` | 14,856 | `4729d9caf92a30fe8df9d9c22cd69573520b23504f0031a90050161464ae8cef` |
| `ml-service/scripts/lc_run_4layer.py` | 19,744 | `b971f84e83f69c1350aae18eb6b48ca9172b5a0ec66583c464f1b6a47bc26c32` |
| `ml-service/app/sequence.py` | 15,202 | `f90b146fe67e477f1a432b92adffd4d0b1a1c57fbe1e86f4187912a3b9a4973c` |
| `hub/backend/app/security/l3_sequence.py` | 22,954 | `a468dd46968fd5802bae1498c6f3b4556df62e324e5c71c43244aee0faf681cc` |
| `hub/backend/app/security/rule_engine.py` | 13,750 | `a905bfc396d742b59a76c2717cce8900accc98bb220a387faf136f7eb6ac7498` |
| `hub/backend/app/security/behavior_profiling.py` | 15,813 | `278a9373b020a663ad2fc9f7e43e85bfcc0a6102b1d9469fdc6e020e19d27d0e` |
| `hub/backend/app/security/risk_aggregator.py` | 4,040 | `51c2a61257481a07b6818ad5be6eb90e6aaa0e5fd036f91e6aa67ca9fd957b22` |
| `hub/backend/app/security/risk_engine.py` | 8,427 | `45446d58f2d001f97d151e59bbfade4e165b1694c956fe9f1fb3aa4f0e324096` |
| `hub/backend/app/services/l3_sequence_client.py` | 3,511 | `05112f9a8ab8e22a29ebf9032dab631d7918f4c43532b3f47b1e20d41f069352` |
| `hub/backend/scripts/l3_shadow_replay.py` | 20,780 | `96f3561086e878437990cdb0bce91cf4f6161509d774a2f9832faa8fc8d6d0e1` |
| `hub/backend/tests/test_l3_stability.py` | 24,665 | `8c24d6167e7edfd40354ec816da6cdd2c3551d53c324c4f830c0540e4485eff0` |
| `hub/backend/tests/test_l3_access_monitoring_split.py` | 8,040 | `6de5aa94b40ea63bb075972edc9d64d6994f549a207abebb35629ff1d5c54fc7` |

## 5. Freeze commit

<!-- FREEZE_COMMIT -->
_(เติมหลัง commit — ดู `git log --oneline -1` หรือ tag `rba-freeze-2026-08-29`)_

## 6. ข้อมูลที่ไม่อยู่ใน git (โดยตั้งใจ)

ตามข้อกำหนด **ข้อมูลจริงห้ามขึ้น git เด็ดขาด** — ไฟล์ต่อไปนี้อยู่ใน `.gitignore`
และ **ไม่ได้** อยู่ใน manifest นี้:

| ประเภท | ที่อยู่ | เหตุผล |
|---|---|---|
| โปรไฟล์ผู้ใช้จริง (anchor) | `ml-service/data/*.xlsx`, `real_*.csv` | PII — อีเมล/ชื่อ/แผนก |
| login ที่ generate จาก anchor | `ml-service/data/user_logins*.csv` | สาวกลับหาบุคคลได้ |
| ฟีเจอร์/โมเดลรายคน | `ml-service/data/*.csv`, `ml-service/models/` | derived จาก PII |
| residual history | Redis `l3resid:{user_id}` | runtime เท่านั้น ไม่ persist ลงไฟล์ |

ผู้ตรวจที่ต้องการทำซ้ำต้องใช้ anchor ของตนเอง แล้วรัน harness ตาม §4.2
(ทุกสคริปต์รับ `--users` และ `--seeds` เป็นอาร์กิวเมนต์)
