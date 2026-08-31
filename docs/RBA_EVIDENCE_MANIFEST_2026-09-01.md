# ชุดหลักฐานการทดลอง RBA — Evidence Manifest (freeze)

**สร้างเมื่อ:** 2026-09-01 · **สร้างโดย:** `scripts/build_evidence_manifest.py`

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
| commit SHA (เต็ม) | `3314ec22a22af88b6e0896aa6bcbc10c30fe7a57` |
| commit SHA (สั้น) | `3314ec2` |
| branch | `main` |
| working tree ตอนสร้าง manifest | มีไฟล์ที่ยังไม่ commit (ดู §5) |
| จำนวนไฟล์หลักฐาน | 54 |

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

**ครอบคลุม L3 ทั้งสองมุมมองตั้งแต่ 31 ส.ค. 2026** (B66) — เดิม point view
(IForest 23 ฟีเจอร์) ยังบวกคะแนนเข้า `aggregate()` ได้ถึง +0.40 ทั้งที่การทดลอง
ทุกชุดวัดด้วย `NEUTRAL` (= 0) · วัดจากข้อมูลจริง 1,024 sessions พบว่ากระทบ
**128 ครั้ง (12.5%) ของการตัดสิน** รวม block 22 ครั้ง → แก้ด้วย
`iforest_scorer.monitoring_only()` ทำให้ production ตรงกับตัวเลขที่วัดไว้
(ไม่ได้ปรับโมเดล/threshold ใดๆ — ดู `l3_unified_2026-08-31.md`)

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

> **หมายเหตุการคำนวณ:** hash คิดจาก**เนื้อหา**ไฟล์โดย normalize บรรทัดเป็น LF ก่อน
> (ไฟล์ไบนารีใช้ byte ดิบ) — repo ตั้ง `core.autocrlf=true` และไม่มี `.gitattributes`
> ถ้า hash จาก byte ดิบ ผู้ตรวจที่ clone บน Linux/macOS จะเห็น `--verify` ไม่ผ่าน
> **ทุกไฟล์** ทั้งที่ไม่มีใครแก้อะไร · วิธีนี้ทำให้ผลตรวจเหมือนกันทุกแพลตฟอร์ม

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
| `lc_4layer_2026-08-25.md` | 2,124 | `7fc67f5e0e68c34fe6f3cc8fef812c410291b7e1b9a470404850979920e79ee5` |
| `l3_ownership_nocampaign_2026-08-25.md` | 3,291 | `c46934aacff5d7088aa10fd60a1cbd107328ccbad93b7972b0bcd791d3d4fcd0` |
| `l3_campaign_2026-08-26.md` | 6,592 | `8599745a48d0961fb6ebbd59cf0dae8f7a9a2266cac61da2fe1f12146d5d8033` |
| `l3_sequence_channel_2026-08-26.md` | 6,471 | `f104634e03d8fbd8abedfac089cc86de26bc102e7448f2c1e80402e29afea24d` |
| `l3_raw_vs_effective_2026-08-26.md` | 5,786 | `c9e8e33db3cc5b8bcf8b54dd47871a9aa2dc438216ef3a9e18c370754cb3b86c` |
| `exp_4layer_full_2026-08-26.md` | 7,391 | `492741a9a1e1405c2c93ae3f0181dcb47182f45188d0e4612de684c6edd434c1` |
| `exp_l3_config_g_2026-08-26.md` | 8,090 | `6299396addb0046730032d73aa9c01d82956f76be6dac1e79db0d86e981f5aa7` |
| `exp_lc_v3_2026-08-26.md` | 3,286 | `d1d513a2819fa668f33387fd5a4dac17babce684463ca8b59a00d9a83682a44c` |
| `exp_thr_and_l2_fix_2026-08-26.md` | 8,063 | `c2ba34f6d19a169122a0a61a826dd1a257f2868534a5302d141a4837545a8f2e` |
| `exp_l3_window_2026-08-26.md` | 7,389 | `17b70609ac2cc1a6c4b7f8468746d903a038e93f6c68f73ec1b32bb55ea08f33` |
| `exp_campaign_level_2026-08-26.md` | 6,617 | `eff49a6d28f5bcc3683c2e2fc0f0cf1a15a498608f6a4e0c211a1534b503caa1` |
| `exp_final_synthetic_2026-08-26.md` | 10,751 | `6a27674da6fcdcf1ed54e77a4d61d3c7e9099a7ff705fc50f370a42018408004` |
| `exp_final_gate_2026-08-26.md` | 7,531 | `a1935237db7baec60c28bc325f0b9601fca9edccd62e7d83abe718137a092f4e` |
| `l3_service_split_2026-08-29.md` | 15,423 | `8a2d15b36964d042b0c77ab1582e7ed20c4e1462de617516121f39930cbdeed2` |
| `l3_stability_2026-08-29.md` | 17,341 | `2679b11175f42f44579fd65673abf1b0bd54dbb9bdf12c4c117239c72d0bf40d` |
| `l3_shadow_replay_2026-08-29.md` | 9,030 | `17b7e349c7422ffea810a82eb0a838dba2ef82c9ac04c8b75e535d1130f7def8` |
| `l3_unified_2026-08-31.md` | 24,327 | `c987b30d700fd29af24c589c9f59a79fe882b792a85845d905fc44121b116a44` |

### 4.2 โค้ดที่ผลิตตัวเลข (harness ทดลอง + production ที่ถูกวัด)

| ไฟล์ | ขนาด (ไบต์) | SHA-256 |
|---|---|---|
| `ml-service/scripts/gen_v3.py` | 11,872 | `50b1d94c2d4c6015c7ea9542577df2e3a5f747fb1581dd8b68fd1699d3be7111` |
| `ml-service/scripts/build_profiles_v2.py` | 51,232 | `6bcd45ea93f800b2748b5c4535071725027b2046b91bf8e4a92701a6e9f14ae0` |
| `ml-service/scripts/features_v2.py` | 18,366 | `1717e70f8905ad0e05e05dfc65f3780a5a332021da991a3d0182b0c8391b3510` |
| `ml-service/scripts/exp_final_gate.py` | 22,076 | `6036ecc2944aacd55c9b1255a5c61caccd9a7f5ed86c21cdaac0bd8cd80d82c7` |
| `ml-service/scripts/exp_campaign_level.py` | 12,553 | `9cd30886ffc70af524fdce38dc0becf5e5cb1efc3d4f0e8a7894fce64e8250da` |
| `ml-service/scripts/exp_final_synthetic.py` | 17,225 | `7f337bdf9b94d70327e89a6e08c9313553d7c560d9420259cd5e8aafd6928acf` |
| `ml-service/scripts/exp_lc_v3.py` | 14,828 | `0d4b1f7a304681ded11c794ca4b536f13893590e128de12a88d7a4c6a0b7830d` |
| `ml-service/scripts/exp_4layer_full.py` | 18,370 | `5abdce4e572c71591a7d467086696b1c04b1815e67b39387ff4cfa26e71d3fc2` |
| `ml-service/scripts/lc_l3_sequence.py` | 12,210 | `d23f7b8304537497da5100e8b3442dea26804ada24ce2d2966718a172e5bb3fe` |
| `ml-service/scripts/lc_l3_ownership.py` | 14,856 | `ff415e436b2ee0de2d0b8a79e8e577041ba8f2f967f93d3b17ac9389dcffffbb` |
| `ml-service/scripts/lc_run_4layer.py` | 19,744 | `78d6278c29793f789c899811f54a42fe7f4201ed117fdeda427d9cecf190e009` |
| `ml-service/app/sequence.py` | 19,463 | `a3834d0cffb7aafa05971b265fc81ed8da5415d6f9bec90c528f4532bbc26d82` |
| `hub/backend/app/security/l3_sequence.py` | 22,954 | `0acf7905a223d58c7c1b1a0bbd0491eaea3be1eb7e31ae15f34f29f5ecd3bdda` |
| `hub/backend/app/security/rule_engine.py` | 13,750 | `a905bfc396d742b59a76c2717cce8900accc98bb220a387faf136f7eb6ac7498` |
| `hub/backend/app/security/behavior_profiling.py` | 15,813 | `e971771fadbaa96f30c8597a00bafd22982392f224e2ae1b51123fe2f9f010f7` |
| `hub/backend/app/security/risk_aggregator.py` | 4,040 | `51c2a61257481a07b6818ad5be6eb90e6aaa0e5fd036f91e6aa67ca9fd957b22` |
| `hub/backend/app/security/risk_engine.py` | 11,859 | `f86bb1ae4a8268d14ccb306ac05d265a30266f89273cf6e5bc70fcdcdc9a6b26` |
| `hub/backend/app/services/l3_sequence_client.py` | 9,901 | `8d2048b71a1b9de8357c345d3d40a889c929267475c7c326c82954496f466ad2` |
| `hub/backend/scripts/l3_shadow_replay.py` | 20,780 | `3ccee42a89f32d16fe8acb9d207b58151cdebe839d49768366fdfa41386bfddc` |
| `hub/backend/tests/test_l3_stability.py` | 25,969 | `80c0f24ce5ace243d3aa80616c223c3465ba901eb3983bbffb1d60ed6523fd86` |
| `hub/backend/tests/test_l3_access_monitoring_split.py` | 13,649 | `4e4b391c42abfd1d177db4516e710998bbb57da5394528af61f2b623954403fe` |
| `ml-service/app/l3_unified.py` | 11,806 | `cb4458c9561f7bd8cd5bfa7d3b28ac843261e2e050670511abfa9586ba9b1f38` |
| `ml-service/app/model.py` | 6,114 | `d2809ef440ef31ca44d9f830ad5d5473be3fa71f38d429fab76329cf576664f4` |
| `ml-service/app/main.py` | 13,814 | `8e1d3df54887b039808f1524fe3753638c486c1efb3539c1bfa4791e2dc0b009` |
| `hub/backend/app/security/iforest_scorer.py` | 3,969 | `40f8f959c0f1e6741e209db77e9224e7278eea99c6fc603da8d3966c8ed6f398` |
| `hub/backend/tests/test_l3_unified.py` | 15,101 | `2774c4ad706ffc0d4796aca0489c389970617337953c9d1a1d575eb10f60b094` |

## 5. Freeze commit

<!-- FREEZE_COMMIT -->
| tag | commit | คืออะไร |
|---|---|---|
| `rba-freeze-2026-08-29` | `74bda639014a13abb851af9f5dd8a772fda21f36` | จุดที่ **ผลการทดลอง** ถูก freeze — ตัวเลข recall/FPR ทั้งหมดมาจากจุดนี้ |
| `rba-expert-review-2026-08-29` | `2bdbeb1348e77133415b084bf64c7093b3795319` | ส่งตรวจรอบ 1 = freeze + stability (B62/B63) + แยก access/monitoring (เฉพาะ sequence view) |
| `rba-expert-review-2026-09-01` | commit ที่บรรจุไฟล์นี้ — `git rev-parse rba-expert-review-2026-09-01^{commit}` | **ส่งตรวจรอบ 2** = รอบ 1 + L3 orchestrator เดียว + ถอด IForest ออกจาก access (B66) |

**commit ของโค้ด/หลักฐานในรอบนี้:** `3314ec22a22af88b6e0896aa6bcbc10c30fe7a57`
(hash ทุกไฟล์ใน §4 คำนวณจาก tree ณ commit นี้ — manifest ถูก commit ตามมาทีหลัง
เพราะไฟล์บรรจุ SHA ของ commit ที่บรรจุตัวมันเองไม่ได้)

### เปลี่ยนอะไรจากรอบ 1

| | รอบ 1 (29 ส.ค.) | รอบ 2 (1 ก.ย.) |
|---|---|---|
| L3 sequence view ไม่แตะ access | ✅ | ✅ |
| **L3 point view (IForest 23 ฟีเจอร์) ไม่แตะ access** | ❌ บวกได้ถึง +0.40 | ✅ `monitoring_only()` |
| SHAP อธิบาย sequence-residual | ❌ | ✅ 18 มิติ |
| duplicate_ratio / unique_to_l3 ใน runtime | ❌ | ✅ |
| point + sequence เป็นผล L3 เดียว | ❌ แยกสองระบบ | ✅ `POST /v1/l3-evaluate` |
| `--verify` ใช้ได้ข้ามแพลตฟอร์ม | ❌ hash ผูกกับ CRLF ของ Windows | ✅ normalize เป็น LF ก่อน hash |

> 🔴 **สิ่งที่ผู้ตรวจรอบ 1 ควรทราบ:** ตัวเลขประสิทธิภาพในรอบ 1 วัดด้วย
> `aggregate(rule, beh, NEUTRAL)` (IForest = 0) แต่ระบบที่รันจริงตอนนั้นบวกคะแนน
> IForest เข้าไปด้วย — วัดจาก `login_sessions` จริง 1,024 รายการพบว่ากระทบ
> **128 ครั้ง (12.5%) ของการตัดสิน** (allow→warn 65 · warn→challenge 41 ·
> **challenge→block 22**) · รอบ 2 แก้ให้ production ตรงกับตัวเลขที่วัด
> **ตัวเลขการทดลองไม่ถูกแก้ ไม่มีการปรับโมเดล/threshold/ฟีเจอร์ใดๆ**
> รายละเอียด: `hub/backend/tests/reports/l3_unified_2026-08-31.md` §1 · B66

> ⚠️ **ข้อจำกัดที่ทราบและยังไม่แก้ (B67):** SHAP ของ sequence view **อิ่มตัว**เมื่อจุด
> หลุด distribution ทุกมิติ — ซึ่งคือกรณีที่มันยิงจริง · ชื่อฟีเจอร์ใน `top_factors`
> จึงยืนยันได้แค่ "ผิดปกติเชิงร่วม" บอกไม่ได้ว่ามิติไหนเป็นสาเหตุ
> (index mapping เองถูกต้อง ยืนยันแล้ว 6/6 ในย่านที่แยกแยะได้)

> 📌 **hash ของรอบ 1 คิดคนละวิธี** — manifest รอบ 1 hash จาก byte ดิบของ working tree
> (CRLF บน Windows) ส่วนรอบนี้ normalize เป็น LF ก่อน · ตัวเลข hash สองรอบจึงเทียบกัน
> ตรงๆ ไม่ได้ แม้เนื้อหาไฟล์จะเหมือนกัน — ให้ `--verify` ด้วยสคริปต์ที่อยู่ใน tag เดียวกัน

**ตรวจสอบชุดที่ส่งตรวจ:**

```bash
git checkout rba-expert-review-2026-09-01
python scripts/build_evidence_manifest.py --verify
python scripts/scan_history_pii.py --self-test    # ยืนยันว่าตัวสแกนยังจับได้จริง
```

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
