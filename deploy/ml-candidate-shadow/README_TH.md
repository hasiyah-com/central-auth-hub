# ทดลอง IF ตัวใหม่แบบ shadow แยกจากระบบเดิม

ค่าเริ่มต้นปิด ไม่มีการทับโมเดลliveหรือเปลี่ยนthresholdเดิม ช่องนี้เก็บdiagnosticเท่านั้น ไม่ยกwarn/challenge ไม่ขอMFA ไม่ส่งincidentemail ไม่เพิ่มข้อมูลให้sequence/trustedhistory

## สิ่งที่ต้องมี
โค้ดbranchนี้ผ่านCIก่อนนำไปรวม/ใช้งาน มีDockerและprivate networkที่Hubต่ออยู่ ใช้ชุดartifactที่เตรียมจากIF-mixed5ที่ตรวจแล้ว (ไม่ใช่ไฟล์โมเดลเดิมของserver) ตัวโมเดลมีSHA256:
`71de43c4214f6db5d46dbec8ec7baf31f3d9429af0632fb19c8cd67a419f61ca`

โครงสร้างไฟล์บนserverต้องเป็น:
```
deploy/ml-candidate-shadow/artifacts/IF-mixed5.joblib
deploy/ml-candidate-shadow/artifacts/manifest.json
```
ไฟล์สองรายการนี้อยู่ในชุดส่งมอบ ไม่ต้องcommitweightsหรือsecretเข้าGitHub โมเดลเก่าและkeyJWTเดิมใช้ต่อไป

## 1. ตรวจไฟล์และสร้างคีย์ใหม่
อ่านmanifestSHAจากชุดส่งมอบ หรือรันจากrootของcheckout:
```
python -c "import hashlib; print(hashlib.sha256(open('deploy/ml-candidate-shadow/artifacts/manifest.json','rb').read()).hexdigest())"
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
คีย์ที่สร้างใหม่ใช้ร่วมเฉพาะcandidateและHub เก็บเป็นsecretของระบบdeploy ไม่ส่งกลับมาในแชต ไม่ใช้คีย์ตัวอย่างในเทส ไม่ใช้JWT/SESSION/clientsecretมาแทน

## 2. สร้างserviceใหม่ในprivate network
ใช้Compose `docker-compose.ml-candidate-shadow.yml` โดยตั้งตัวแปร3รายการในdeploymentของcandidate:
```
CANDIDATE_SHADOW_KEY=<คีย์ใหม่จากข้อ1>
CANDIDATE_MANIFEST_SHA256=<hashของmanifestจากข้อ1>
SHADOW_NETWORK_NAME=<ชื่อprivate Docker networkที่Hubใช้อยู่>
```
Composeนี้เป็นproject/serviceแยก ไม่มีpublicport ไม่มีproxyroute ไม่ใช้DB/Redis ไม่มีvolumeร่วมกับโมเดลlive หากใช้Dokployให้เพิ่มserviceใหม่สำหรับComposeนี้และตรวจmountไฟล์artifact ไม่แก้serviceMLเดิม

CLIทางเลือกจากrootcheckout:
```
docker compose -f docker-compose.ml-candidate-shadow.yml up -d --build
docker compose -f docker-compose.ml-candidate-shadow.yml ps
docker compose -f docker-compose.ml-candidate-shadow.yml logs --tail 50
```
รอhealthready (ตรวจทั้งhash/โหลด/scaler/IF/SHAPwarmup) ถ้าผิดhashหรือsecretไม่ครบserviceไม่พร้อม แต่ไม่ไปเปลี่ยนMLเดิม

## 3. ตั้งHubสำหรับshadow
ตั้งเฉพาะตัวแปรใหม่ของHub:
```
L3_CANDIDATE_SHADOW_ENABLED=true
L3_CANDIDATE_SHADOW_URL=http://ml-candidate-shadow:9001/v1/shadow-score
L3_CANDIDATE_SHADOW_KEY=<คีย์ใหม่เดียวกับservice>
L3_CANDIDATE_SHADOW_MODEL_SHA256=71de43c4214f6db5d46dbec8ec7baf31f3d9429af0632fb19c8cd67a419f61ca
L3_CANDIDATE_SHADOW_RAW_THRESHOLD=0.0918450679660674
L3_CANDIDATE_SHADOW_TIMEOUT_SECONDS=0.25
```
คงค่าML_SERVICE_URL,โมเดลlive,rolecalibration,thresholdและfallback/trialเดิมไว้ทั้งหมด ไม่ใช้C3_PGE_SHADOW_ENABLEDแทนตัวแปรนี้ (คนละการเปรียบเทียบ) ไม่ตั้งglobalriskshadowเพื่อแทนการแยกcandidate

โค้ดเรียกcandidateเฉพาะเมื่อL1+L2ปล่อยallow หลังคำนวณผลเข้าถึงจากนโยบายเดิมแล้ว แม้fallbackเดิมยกallowเป็นwarnอยู่ก็ไม่ถูกยกเลิก เพิ่มแค่ `risk_breakdown.if_candidate_shadow`

## 4. ตรวจจากcontainerHubก่อนใช้ผล
หลังdeployโค้ดและตัวแปรHub ให้รันในconsoleของHub:
```
cd /app
python -m scripts.preflight_if_candidate_shadow
```
ต้องได้ `passed:true`, `status:evaluated`, `mode:shadow`, `applied_to_access:false`, modelSHAตรงและexplanation23รายการ นี่เป็นprobeสังเคราะห์ ไม่ใช่การยืนยันผลล็อกอินจริงหรือsemanticparityDBทุกกรณี

จากนั้นทดลองล็อกอินบัญชีทดสอบที่เป็นallow ตรวจรายละเอียดเซสชัน/JSONของriskbreakdown ต้องมีcandidateSHAและinputSHA และผลMFA/สิทธิ์เหมือนbaseline ตรวจwarn/challenge/blockด้วยว่าคงเดิมและไม่เรียกcandidate จุดนี้ต้องตรวจบนserverจริงอีกครั้ง

## 5. อ่านผลให้ถูก
`raw_score=-decision_function`, `score=sigmoid(5*raw_score)`; threshold0.091845…แปลงเป็นsigmoidประมาณ0.6128303891 แต่ค่านั้นใช้กับcandidateเท่านั้น ไม่ใช่thresholdlive0.4606 และไม่ใช่probabilityการโจมตี

`flagged`คือธงจากcandidate ไม่ใช่decisionเข้าถึง คะแนนและSHAPไม่ถูกบวกกับlive รูปแบบSHAPใช้negative mean correctedpathlength ไม่ใช่riskpointsหรือprobability ต้องอ่านร่วมกับค่าสถานะ

ถ้าล่ม/timeout/responseผิด/SHAPเสีย จะเห็นstatusunavailable/timeout/invalid_response/degraded_shap ช่องเดิมทำงานต่อ หากเรียกพร้อมกันเกิน4งานต่อHubprocessจะได้busyทันที ไม่สะสมคิวไม่จำกัด candidateprocessมีขีดจำกัด8connectionsและล็อกการคำนวณภายใน เวลารอnetworkตั้งไว้0.25วินาที ไม่ใช่การรับรองwallclockแบบhardrealtimeเมื่อเครื่องขาดCPU

## 6. หยุดshadow
เปลี่ยนHub `L3_CANDIDATE_SHADOW_ENABLED=false` แล้วrestart/redeployHubตามวิธีเดิม จากนั้นจึงหยุดcandidateถ้าไม่ใช้:
```
docker compose -f docker-compose.ml-candidate-shadow.yml down
```
อย่าใช้คำสั่งdownกับComposeหลัก โมเดลliveไม่ถูกเปลี่ยนตั้งแต่ต้นจึงไม่มีการคัดลอกโมเดลกลับ

## ขอบเขตการผ่าน
เทสlocalครอบคลุมartifactจริง/HTTP/score/23SHAP/ความผิดพลาดและผลdecisionเดิม รวมCIตรวจcontainerเพิ่มเติม แต่การประเมินperformance/memoryของเครื่องserverจริงและการตรวจผลล็อกอินจริงยังต้องทำตามข้อ4 ไม่ใช่อนุมัติenforceและไม่เปลี่ยนข้อสรุปความแม่นยำของงานวิจัย
