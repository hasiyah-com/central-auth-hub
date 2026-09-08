# ชุดหลักฐานการทดลอง RBA — Evidence Manifest (freeze)

**สร้างเมื่อ:** 2026-09-08 · **สร้างโดย:** `scripts/build_evidence_manifest.py`

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
| commit SHA (เต็ม) | `c81c1772ae0965b3658b82acb5ab4620df2e6e0b` |
| commit SHA (สั้น) | `c81c177` |
| branch | `feature/hybrid-risk-round2` |
| working tree ตอนสร้าง manifest | มีไฟล์ที่ยังไม่ commit (ดู §5) |
| จำนวนไฟล์หลักฐาน | 89 |

> commit SHA ด้านบนคือ **commit ก่อนหน้า** ตอน generate — SHA ของ freeze commit เอง
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
| `l3_unified_2026-08-31.md` | 26,772 | `1b9d3a0a75115470533d2d0112f50d0f688dca98586a851a5a353df3ce3c8932` |
| `l3_explainability_2026-09-01.md` | 19,027 | `13a9a74090d919e2e3eed8a405750c27468b3740ed1ebc8b8c767402ea4c284e` |
| `hybrid_risk_experiment_2026-09-03.md` | 45,293 | `ebe0d0c1f5d11a3149f82765394e55411588dde3b7d95a787ca34f77170d21d5` |
| `round2_statistics_2026-09-03.md` | 11,303 | `360c1f1d438d8cee33075473930ad6b1fc257505add5933c28fb2fba3b015894` |
| `hybrid_risk_round2_2026-09-04.md` | 14,681 | `ad0a90409d3120ea98ab717c9d299d81cafdb3410c2f25ce6b27458fdcb90622` |
| `hybrid_risk_round2b_2026-09-04.md` | 13,281 | `654de04be96fb490c5a6bdfadb1b01870f3c0d05ca4c38c2017a7ea2ea55bb86` |
| `hybrid_risk_round2c_2026-09-04.md` | 13,318 | `a5945b63d4eff154b8273d25a7e8bc8c5a1bc12f42504dc2c7f53e80c97f0f5c` |
| `cold_start_fpr_rootcause_2026-09-06.md` | 15,530 | `7b985c2686923eb95545c897da2bc86c2bb877583835b809660c995fbc42140a` |
| `cluster_aware_gate_2026-09-06.md` | 8,901 | `20730435ca8255bacb40211259809ad7b48a283946871ef48fe4d2359245bd08` |
| `l2_subsystem_family_grid_2026-09-06.md` | 11,315 | `38fd1af18a05ba7df1b4b3cf50ce3c0d82e47d72e55dbb0d04bf736dad6a6f6f` |
| `p48_population_and_audit_2026-09-08.md` | 6,725 | `354be7db91ed21080101b1b91ba199d77a54da2c9d5d57ea302934cc831de90d` |
| `p48_validation_2026-09-08.md` | 14,709 | `5416489826913a1dc30fdb8edfbed495aac385048d1692c1e440a18ded231d49` |

### 4.2 โค้ดที่ผลิตตัวเลข (harness ทดลอง + production ที่ถูกวัด)

| ไฟล์ | ขนาด (ไบต์) | SHA-256 |
|---|---|---|
| `ml-service/scripts/gen_v3.py` | 12,430 | `99d903b3c6d9305944942d0922ba594f95bbfb081649af3d100fc5a855993dce` |
| `ml-service/scripts/build_profiles_v2.py` | 49,911 | `27072fa701bb52a55d7e4ae45d3ee4905cd5f5a11ae125127c52f3898d6e38ef` |
| `ml-service/scripts/features_v2.py` | 17,938 | `420e12ed72834b86e95073f5e05f8b6458313bbae257e4cb8c2e452ab865739f` |
| `ml-service/scripts/exp_final_gate.py` | 21,520 | `4fe58fcd1aa3b85c000b5f30dd285b92cebedb21a0e59908df65e4b1cb8665eb` |
| `ml-service/scripts/exp_campaign_level.py` | 12,539 | `8e1e47c6142dc1adf05649f13182ef33e4c875570e5a9c13a3ceb89179c58436` |
| `ml-service/scripts/exp_final_synthetic.py` | 17,225 | `7f337bdf9b94d70327e89a6e08c9313553d7c560d9420259cd5e8aafd6928acf` |
| `ml-service/scripts/exp_lc_v3.py` | 14,828 | `0d4b1f7a304681ded11c794ca4b536f13893590e128de12a88d7a4c6a0b7830d` |
| `ml-service/scripts/exp_4layer_full.py` | 18,370 | `5abdce4e572c71591a7d467086696b1c04b1815e67b39387ff4cfa26e71d3fc2` |
| `ml-service/scripts/lc_l3_sequence.py` | 12,210 | `d23f7b8304537497da5100e8b3442dea26804ada24ce2d2966718a172e5bb3fe` |
| `ml-service/scripts/lc_l3_ownership.py` | 14,501 | `12e0b1caf7c047f31f1c0699bc4818ab05040a708b5b50ed23306a5cd2f91632` |
| `ml-service/scripts/lc_run_4layer.py` | 19,292 | `43b3ccab5d4cf3335105199013ff3549ece20e0075fd2030f7a67c8caebbc1a9` |
| `ml-service/app/sequence.py` | 23,815 | `8265a69245201a710ecb1e9451a4bdbe9fb3af89194e9d4e15f1425771937c06` |
| `hub/backend/app/security/l3_sequence.py` | 22,507 | `4934c0cd397f6b69c1a8c0fb382d1d123bfe2ebb60909db9436096af39f68bae` |
| `hub/backend/app/security/rule_engine.py` | 17,461 | `d775ba9908624842c134f31fd62af16255062fe4eb3de83375d8e085fdb72873` |
| `hub/backend/app/security/behavior_profiling.py` | 17,010 | `f8659bf7fb7771c51d0c574a14baaca2bd8d7716d9e8b74d13dd0b7732f7d855` |
| `hub/backend/app/security/risk_aggregator.py` | 4,040 | `51c2a61257481a07b6818ad5be6eb90e6aaa0e5fd036f91e6aa67ca9fd957b22` |
| `hub/backend/app/security/risk_engine.py` | 13,985 | `218291bb9688d3ad8cff9969f9b80f32796abd39a8b99ed9210861c23129ee3c` |
| `hub/backend/app/services/l3_sequence_client.py` | 10,959 | `e4b769401eaaba9b70c394198566c29bdc5824363b89b67b4f88c5fbf810def5` |
| `hub/backend/scripts/l3_shadow_replay.py` | 20,362 | `0926c7a6ea6ab29a30a81179f21a1d37d39264ed415cdc85dcd99eea64592cce` |
| `hub/backend/tests/test_l3_stability.py` | 25,969 | `80c0f24ce5ace243d3aa80616c223c3465ba901eb3983bbffb1d60ed6523fd86` |
| `hub/backend/tests/test_l3_access_monitoring_split.py` | 14,101 | `175a3734f66d3c70fd63f7db17cdeb087cf3b1b5e7475ee615a2ea57cc69d5a2` |
| `ml-service/app/l3_unified.py` | 14,310 | `292a930f10fbe27d181545007142493f85c8a9cbc46002df0598dfbc2690e0dc` |
| `ml-service/app/model.py` | 6,114 | `d2809ef440ef31ca44d9f830ad5d5473be3fa71f38d429fab76329cf576664f4` |
| `ml-service/app/main.py` | 13,780 | `07a801a9308d43989cebed895915ed9165d314eba408e72ef66fc38f92588fe4` |
| `hub/backend/app/security/iforest_scorer.py` | 3,969 | `40f8f959c0f1e6741e209db77e9224e7278eea99c6fc603da8d3966c8ed6f398` |
| `hub/backend/tests/test_l3_unified.py` | 15,375 | `cac6e7974f1994472f6de4b5c4997511d711ec6fd80c7cb9fb252457cd2e8a65` |
| `ml-service/scripts/exp_hybrid_gate.py` | 106,149 | `c9e84d73ebad8c690c5cc857e99497f75d63e13a6a188a54f39312e18746ead5` |
| `ml-service/scripts/exp_l2_family_grid.py` | 19,520 | `a3426547b22139e4e434365369f88c90b66e3f50b55207d2b5d3fd19dd0175e6` |
| `ml-service/scripts/exp_p48_validation.py` | 11,891 | `3b19c6ff3e635b415f9a1d5461243c99a76518f48380c74c504f2074c83849e0` |
| `ml-service/scripts/audit_p48_generator.py` | 5,964 | `2610860a133c280df44979c54daeed889120508fd1c0b82ae8778a1b84febea5` |
| `ml-service/scripts/population_p48.py` | 14,710 | `84a228040cf1fb8e7227b376f9d0fb736fe07b47319706e0f83fbd34aaace028` |
| `ml-service/scripts/gen_v3.py` | 12,430 | `99d903b3c6d9305944942d0922ba594f95bbfb081649af3d100fc5a855993dce` |
| `ml-service/scripts/hybrid_experiment/bootstrap.py` | 23,432 | `fe4b5b9ce27707c26d7fe0d09adc224c7b428ecfaa3fcac19f38f21c65c638aa` |
| `ml-service/scripts/hybrid_experiment/gate.py` | 5,358 | `cc5fc05aa31657d30ca7e8b7a9aecc2fc851cbe2c4621ab12fbe7ab09966b840` |
| `ml-service/scripts/hybrid_experiment/tune.py` | 15,620 | `2b34c8c2c28bc8bed87e2ac63f3e571a9cf82788706519d3ab2874d8ec34f6e4` |
| `ml-service/scripts/hybrid_experiment/dataset.py` | 10,292 | `46555443fcf6dab4a74026e8b0b7fb0d8e7aa4b2f7279710386c570bfb87e210` |
| `ml-service/scripts/hybrid_experiment/l2_family_variant.py` | 8,649 | `357f399b9da66da465bc307883ebe5ec98dc43c49ee5374052e5a99516695a07` |
| `hub/backend/app/security/risk_fusion.py` | 14,938 | `74b1f24d91f3d32762e2de7e4ab2a65123eef5e11c7940c2955dc801cd8f1744` |
| `hub/backend/app/security/policy_gate.py` | 6,661 | `f8b982e43c7667d4d424e3a0683df795333eb026938285ee186f045a5269f0bb` |
| `hub/backend/tests/test_cluster_aware_gate.py` | 13,764 | `3e616285e3a0146a0dcb6bf54e85fc81417de342ca4982325c83a6b0be1637c1` |
| `hub/backend/tests/test_population_p48.py` | 12,683 | `61ff85265dd75fa0a6c9879cfa792df6b2b0e8be7a7aea1bd97b7df041eb5db3` |
| `hub/backend/tests/test_l2_evidence_only.py` | 4,540 | `7adab5a00736745c99b0ef3cfa4b387625523f5cfec30b1ad23396584954103f` |
| `hub/backend/tests/test_l2_subsystem_family.py` | 11,474 | `14917d4e5f0f7cdebc36bdb62778135aa49ca38a7f017d1ea9ac29ff3431aa49` |
| `hub/backend/tests/test_l2_legacy_mode_parity.py` | 5,620 | `02a5d3839876f84b68aa7c7a152f81103dd2fbff44d02dfa9121f0e0aa8923f6` |
| `hub/backend/tests/test_scoring_freeze.py` | 5,431 | `bf46b515312e183e227220fdd7a4428c588c196355e1df276dffda21d326735d` |
| `hub/backend/tests/scoring_freeze.json` | 2,200 | `3941578f0299974ad98b1a75ba33f3affc4274889f00f329c12adbbe043ae3e6` |
| `docs/design/USER_POPULATION_P48_PREREG.md` | 14,230 | `a73d3e901e2dca57079efc534fb33a7872d3cce36d2c6e9d452f7fe2c0e894f8` |
| `docs/design/L2_SUBSYSTEM_NOVELTY_FAMILY.md` | 13,261 | `38b46274844efec8e42d447911a50b4e50eac2da6fd8603cba003f35e88b1169` |
| `docs/RBA_ROUND2_PROTOCOL.md` | 16,557 | `08a01720ec77f2cc77c71e15d5ccd1396488a79345abc06669423718949cf175` |
| `hub/backend/tests/test_l3_explainability.py` | 16,288 | `765b9bebaa31a725cd40246d255e7db7d03c384d3ec9c7c51d9f286323ed063f` |

## 5. Freeze commit

<!-- FREEZE_COMMIT -->
| tag | commit | คืออะไร |
|---|---|---|
| `rba-freeze-2026-08-29` | `74bda639014a13abb851af9f5dd8a772fda21f36` | จุดที่ผลการทดลองรอบ L3 ถูก freeze |
| `rba-expert-review-2026-09-01-r2` | `e4c559308dd608e7a71a74854361b51920a8fe6a` | ส่งตรวจรอบ 2 แก้ไขครั้งที่ 1 **(เก็บไว้ ไม่ย้าย)** |
| `rba-hybrid-round1-failed-gate-2026-09-03` | `git rev-parse rba-hybrid-round1-failed-gate-2026-09-03^{commit}` | Hybrid gate รอบ 1 — ไม่ผ่าน |
| `p48-validation-inconclusive` | commit ที่บรรจุไฟล์นี้ — `git rev-parse p48-validation-inconclusive^{commit}` | **รอบนี้** — ประเมินบนประชากร 48 โปรไฟล์ · challenge verdict = inconclusive |

### สถานะที่ freeze ไว้ในรอบนี้

| รายการ | ค่า |
|---|---|
| challenge verdict | **inconclusive** ทุกขนาดข้อมูล (ค่าจุด 0.79–0.87% · ขอบบน CI 1.18% · งบ 1.00%) |
| block / warn verdict | passed ทั้งคู่ |
| P48-holdout (16 โปรไฟล์) | **ไม่เคยถูกเปิด** — สงวนไว้สำหรับ external validation / งานต่อยอด |
| threshold / scoring / generator | ไม่ปรับเพิ่มหลังการวัด · scoring freeze ด้วย `hub/backend/tests/scoring_freeze.json` |
| Hybrid RBA + L3 | **Shadow** |
| การตัดสินการเข้าถึงจริง | policy / baseline ที่อนุมัติไว้เดิม |

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
