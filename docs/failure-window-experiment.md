# ทดลองฟีเจอร์ความล้มเหลวช่วงสั้น — 6 ตุลาคม 2569

งานทดลองออฟไลน์ ไม่แก้โมเดลriskengineหรือpolicyปัจจุบัน และไม่รวมmain

## วิเคราะห์ข้อมูลเดิม

ผลseed1041/1042/1043เดิม: selected modelพลาด failed_spike71รายการ จาก108 มีfailed_logins_24h5–30 แต่ไม่มีtimestampของแต่ละfailure จึงคำนวณช่วง5–10นาที/จำนวนติดกันของ71แถวนั้นไม่ได้ ห้ามแต่งเวลาแล้วอ้างว่าเป็นข้อมูลจริง

## ฟีเจอร์ใหม่

| ฟีเจอร์ | ความหมาย | สูตร |
|---|---|---|
| log1p_failed_auth_5m | ล้มเหลว5นาทีก่อนหน้า | log(1+จำนวนล้มเหลว) |
| log1p_failed_auth_10m | ล้มเหลว10นาทีก่อนหน้า | log(1+จำนวนล้มเหลว) |
| log1p_consecutive_failed_auth_10m | จำนวนล้มเหลวติดกันมากสุดรายวิธีใน10นาที | log(1+max(count per method)) สำเร็จresetเฉพาะวิธีเดียวกัน |
| failed_auth_ratio_10m | สัดส่วนล้มเหลวต่อความพยายามที่มีหลักฐาน | fail/(fail+success); ไม่มีattemptให้0 |
| log1p_auth_attempts_10m | จำนวนความพยายามที่มีหลักฐานใน10นาที | log(1+fail+success) |

นับเฉพาะactionที่ระบุหลังผ่านปัจจัยแรก actor_idตรงบัญชี ช่วงเวลารวมจุดเริ่มต้นและไม่รวมnow ไม่รวมการยกเลิก หมดอายุ timeout หรือsuccessที่counterregression นับตามmethodเหมือนกฎปัจจุบัน รายชื่อactionกำหนดexplicitในfailure_window_features.py ไม่ครอบคลุมทุกวิธีหรือประเมินว่าไม่มีlogหมายถึงปกติจริง

## ข้อมูลและการฝึก

ชุดใหม่เป็นcontrolled synthetic failure-only ablation มีrapid/slow attack และnormal ordinary/typo_retry/legitimate_many ไม่ใช่ข้อมูลproductionหรือชุดบท4 ไม่ใช้เลขผล79.54%เดิมเทียบตรง เพราะรอบนี้ฟีเจอร์ที่ไม่เกี่ยวกับfailureกระจายเหมือนกันทั้งสองlabel เพื่อแยกผลของfailure features

seed2041/2042/2043 ชุดละ300ผู้ใช้18,000เหตุการณ์ รวม54,000 แยกผู้ใช้train60/validation15/calibration10/test15; ฝึกnormaltrainด้วย200ต้นไม้/max_samples512/max_features1.0 เลือกsubsetด้วยvalidationก่อนอ่านTEST แต่รายงานTESTทั้ง4subsetซึ่งกำหนดไว้ก่อนเป็นablation ตั้งthresholdP99normalcalibration ไม่เปลี่ยนตามTEST

ค่าtemporal personalizationอื่นยังlegacy synthetic ไม่ได้ยืนยันextractor23ตัวทั้งหมด และslow labelsมาจากscenarioซึ่งอาจซ้อนทับnormal ไม่ใช่หลักฐานโจมตีจริง

## ผลเฉลี่ย3รอบ

| ชุด | Recall | FPR | F1 |
|---|---:|---:|---:|
| base23 |3.68%|1.27%|0.061|
| +5/10min windows (25)|9.04%|1.04%|0.150|
| +streak/ratio (25)|5.48%|0.93%|0.093|
| +ครบ5 (28)|12.92%|1.23%|0.202|

all28จับ91/704; rapid60/358 slow31/346 และเตือนnormal91/7396 เปรียบเทียบกับกฎfailureเฉพาะส่วนใช้consecutive_countsจริงและเกณฑ์5challenge/10block: rapid358/358, slow0/346 กฎส่วนนี้ไม่เตือนnormalในชุดจำลองนี้ ผลนี้ไม่ใช่การreplayL1/L2เต็มกับDB และไม่ใช่หลักฐานว่าFPRกฎบนproductionเป็น0

L3พบเพิ่มจากกฎส่วนfailure31รายการ แต่มีnormalfalsepositive91 จึงยังไม่ควรเปิดchallengeด้วยโมเดล28features เป็นข้อมูลสำหรับออกแบบชั้น3ให้จับสัญญาณที่กฎไม่เห็น ไม่ใช้โมเดลแทนกฎความล้มเหลวรุนแรง

## การตรวจและข้อจำกัดนำไปใช้

7testwindow/resetmethod/actor/currentfuture/timezone/neutralcode/counterregressionผ่าน ตรวจสร้างใหม่ทั้งหมด54,000แถวแล้วได้featurevectorsตรงการทดลองทุกค่า และstreakบนTESTตรงกับconsecutive_countsของระบบจริง

โมเดลtrialถูกtag rba-failure-window-experiment-v1 รับ23/25/28ตามsubset ซึ่งไม่ใช่contractของproduction ห้ามนำpklในแพ็กไปแทนartifact23featuresโดยตรง ไม่wirehelperเข้าriskengineหรือJWTflow ไม่มีการขอยืนยันเพิ่มจากงานนี้

คำสั่งจากml-serviceในcheckoutเต็ม:

```bash
PYTHONPATH=.:scripts python scripts/experiment_failure_windows.py --seed 2041 --output /tmp/failure2041
```

ถ้าปรับจากผลนี้ต่อควรสร้างTESTใหม่ ต้องวัดประโยชน์ที่เพิ่มจากกฎเดิมและต้นทุนfalsepositiveก่อนใช้ตัดสินจริง
