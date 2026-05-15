"""Seed script: สร้าง user 100 คนสำหรับการพัฒนาและสาธิต.

รูปแบบ email:
  - นักศึกษา : <student_id>@uni.ac.th        เช่น 650001@uni.ac.th
  - อาจารย์  : <english_name><3 digits>@uni.ac.th  เช่น somchai006@uni.ac.th
  - เจ้าหน้าที่: <english_name><3 digits>@uni.ac.th  (รูปแบบเดียวกับอาจารย์)
  - admin    : admin<NN>@hub.local             เช่น admin01@hub.local

หมายเหตุ: เลข 3 หลักท้ายของอาจารย์+เจ้าหน้าที่ ไม่ซ้ำกัน

Run:
    docker compose exec hub-backend python -m app.seeds.seed_users
"""
import random
import re

from faker import Faker

from app.database import SessionLocal, Base, engine
from app.models import (
    User, Subsystem, AccessList, LoginSession, AuditLog, SecretRetrievalToken,
)

fake = Faker("th_TH")        # ชื่อ-สกุล ภาษาไทย สำหรับ full_name
fake_en = Faker("en_US")     # ชื่อภาษาอังกฤษ สำหรับสร้าง email ของอาจารย์/เจ้าหน้าที่
Faker.seed(42)
random.seed(42)

FACULTIES = [
    ("วิศวกรรมศาสตร์", ["คอมพิวเตอร์", "ไฟฟ้า", "เครื่องกล", "โยธา"]),
    ("แพทยศาสตร์", ["อายุรกรรม", "ศัลยกรรม", "กุมารเวชศาสตร์"]),
    ("วิทยาศาสตร์", ["คณิตศาสตร์", "ฟิสิกส์", "ชีววิทยา"]),
    ("มนุษยศาสตร์", ["ภาษาอังกฤษ", "ประวัติศาสตร์"]),
    ("บริหารธุรกิจ", ["การตลาด", "การเงิน", "การจัดการ"]),
]

POSITIONS_TEACHER = ["อ.", "ผศ.", "รศ.", "ศ."]
POSITIONS_STAFF = ["จนท. ฝ่ายหอพัก", "จนท. ฝ่ายห้องสมุด", "จนท. ฝ่ายทะเบียน"]

# ============ ตัวช่วยสร้างเลข 3 หลักที่ไม่ซ้ำกัน (สำหรับ teacher + staff) ============
_used_suffixes: set[int] = set()


def unique_suffix() -> str:
    """คืนเลข 3 หลัก (001-999) ที่ยังไม่เคยถูกใช้."""
    while True:
        n = random.randint(1, 999)
        if n not in _used_suffixes:
            _used_suffixes.add(n)
            return f"{n:03d}"


def en_name_slug() -> str:
    """สร้างชื่ออังกฤษ lowercase ตัวอักษร a-z เท่านั้น (สำหรับใส่ใน email)."""
    name = fake_en.first_name().lower()
    return re.sub(r"[^a-z]", "", name) or "user"


# ============ ตัวสร้าง user แต่ละประเภท ============

def make_student(i: int) -> dict:
    faculty, majors = random.choice(FACULTIES)
    major = random.choice(majors)
    year = random.randint(1, 4)
    student_id = f"65{str(i).zfill(4)}"          # 650001, 650002, ...
    return {
        "email": f"{student_id}@uni.ac.th",      # 650001@uni.ac.th
        "full_name": f"{fake.first_name()} {fake.last_name()}",
        "user_type": "student",
        "identifier": student_id,
        "faculty": faculty,
        "major": major,
        "year_or_position": str(year),
        "phone": fake.phone_number(),
        "address": fake.address(),
    }


def make_teacher(i: int) -> dict:
    faculty, majors = random.choice(FACULTIES)
    position = random.choice(POSITIONS_TEACHER)
    email_name = f"{en_name_slug()}{unique_suffix()}"   # somchai006
    return {
        "email": f"{email_name}@uni.ac.th",             # somchai006@uni.ac.th
        "full_name": f"{fake.first_name()} {fake.last_name()}",
        "user_type": "teacher",
        "identifier": f"T{str(i).zfill(4)}",
        "faculty": faculty,
        "major": random.choice(majors),
        "year_or_position": position,
        "phone": fake.phone_number(),
        "address": fake.address(),
    }


def make_staff(i: int) -> dict:
    email_name = f"{en_name_slug()}{unique_suffix()}"   # รูปแบบเดียวกับอาจารย์
    return {
        "email": f"{email_name}@uni.ac.th",
        "full_name": f"{fake.first_name()} {fake.last_name()}",
        "user_type": "staff",
        "identifier": f"S{str(i).zfill(4)}",
        "faculty": None,
        "major": None,
        "year_or_position": random.choice(POSITIONS_STAFF),
        "phone": fake.phone_number(),
        "address": fake.address(),
    }


def make_admin(i: int) -> dict:
    return {
        "email": f"admin{i:02d}@hub.local",             # เหมือนเดิม
        "full_name": f"Admin {i}",
        "user_type": "admin",
        "identifier": f"A{str(i).zfill(2)}",
        "faculty": None,
        "major": None,
        "year_or_position": "Hub Administrator",
        "phone": fake.phone_number(),
        "address": None,
    }


def seed():
    """สร้าง 70 students + 15 teachers + 10 staff + 5 admins = 100 users.

    หมายเหตุสำคัญ:
      - re-seed จะลบ seed users (email @uni.ac.th / @hub.local)
      - และลบตารางลูกที่อ้างอิง user: access_list, login_sessions,
        subsystems, secret_retrieval_tokens, audit_logs
        (เพราะ Foreign Key — ลบ user ไม่ได้ถ้ายังมีตารางลูกอ้างอิง)
      - user ที่เพิ่มเอง (เช่น Gmail admin) จะ *ไม่ถูกลบ*
        แต่ subsystem ที่ทดสอบไว้จะถูกล้าง (สร้างใหม่ได้ง่าย)
    """
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # นับ seed users เดิม (เฉพาะ @uni.ac.th และ @hub.local)
    seed_existing = (
        db.query(User)
        .filter(
            (User.email.like("%@uni.ac.th")) | (User.email.like("%@hub.local"))
        )
        .count()
    )
    if seed_existing > 0:
        print(f"⚠️  พบ seed users เดิม {seed_existing} คน")
        print("   การ re-seed จะล้าง: access_list, login_sessions, subsystems,")
        print("   secret_retrieval_tokens, audit_logs ด้วย (เพราะ Foreign Key)")
        ans = input("ต้องการ re-seed หรือไม่? (y/N): ").strip().lower()
        if ans != "y":
            print("ยกเลิก")
            db.close()
            return

        # ลบตารางลูกก่อน ตามลำดับ Foreign Key (children -> parents)
        db.query(SecretRetrievalToken).delete(synchronize_session=False)
        db.query(AccessList).delete(synchronize_session=False)
        db.query(LoginSession).delete(synchronize_session=False)
        db.query(AuditLog).delete(synchronize_session=False)
        db.query(Subsystem).delete(synchronize_session=False)
        db.commit()
        print("✓ ล้างตารางลูกแล้ว (access_list, login_sessions, subsystems, ...)")

        # ตอนนี้ลบ seed users ได้แล้ว (ไม่มีตารางลูกอ้างอิง)
        deleted = (
            db.query(User)
            .filter(
                (User.email.like("%@uni.ac.th"))
                | (User.email.like("%@hub.local"))
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        print(f"✓ ลบ seed users เดิม {deleted} คน (user ที่เพิ่มเองไม่ถูกแตะต้อง)")

    records = []
    for i in range(1, 71):
        records.append(make_student(i))
    for i in range(1, 16):
        records.append(make_teacher(i))
    for i in range(1, 11):
        records.append(make_staff(i))
    for i in range(1, 6):
        records.append(make_admin(i))

    for r in records:
        user = User(**r)
        if r["user_type"] == "admin":
            user.is_hub_admin = True
        db.add(user)

    db.commit()

    # สรุปผล
    counts = {
        "student": db.query(User).filter(User.user_type == "student").count(),
        "teacher": db.query(User).filter(User.user_type == "teacher").count(),
        "staff": db.query(User).filter(User.user_type == "staff").count(),
        "admin": db.query(User).filter(User.user_type == "admin").count(),
    }
    print("\n✅ Seed สำเร็จ!")
    for ut, c in counts.items():
        print(f"   {ut}: {c} คน")
    print(f"   รวม (seed): {sum(counts.values())} คน")

    # แสดงตัวอย่าง email แต่ละประเภท
    print("\nตัวอย่าง email:")
    for ut in ["student", "teacher", "staff", "admin"]:
        sample = db.query(User).filter(User.user_type == ut).first()
        if sample:
            print(f"   {ut:9s}: {sample.email}")

    print("\nลองดูที่ http://localhost:8000/admin/users/count")
    db.close()


if __name__ == "__main__":
    seed()
