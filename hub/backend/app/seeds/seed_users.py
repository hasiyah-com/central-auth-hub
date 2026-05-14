"""Seed script: สร้าง user 100 คนสำหรับการพัฒนาและสาธิต.

Run:
    docker compose exec hub-backend python -m app.seeds.seed_users
"""
import random
import sys

from faker import Faker

from app.database import SessionLocal, Base, engine
from app.models import User

fake = Faker("th_TH")
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


def make_student(i: int):
    faculty, majors = random.choice(FACULTIES)
    major = random.choice(majors)
    year = random.randint(1, 4)
    student_id = f"65{str(i).zfill(4)}"
    first = fake.first_name()
    last = fake.last_name()
    # email pattern: firstname.lastname[id]@uni.ac.th (English transliteration in real univ)
    email_id = f"student{i:03d}"
    return {
        "email": f"{email_id}@student.uni.ac.th",
        "full_name": f"{first} {last}",
        "user_type": "student",
        "identifier": student_id,
        "faculty": faculty,
        "major": major,
        "year_or_position": str(year),
        "phone": fake.phone_number(),
        "address": fake.address(),
    }


def make_teacher(i: int):
    faculty, majors = random.choice(FACULTIES)
    position = random.choice(POSITIONS_TEACHER)
    return {
        "email": f"teacher{i:03d}@uni.ac.th",
        "full_name": f"{fake.first_name()} {fake.last_name()}",
        "user_type": "teacher",
        "identifier": f"T{str(i).zfill(4)}",
        "faculty": faculty,
        "major": random.choice(majors),
        "year_or_position": position,
        "phone": fake.phone_number(),
        "address": fake.address(),
    }


def make_staff(i: int):
    return {
        "email": f"staff{i:03d}@uni.ac.th",
        "full_name": f"{fake.first_name()} {fake.last_name()}",
        "user_type": "staff",
        "identifier": f"S{str(i).zfill(4)}",
        "faculty": None,
        "major": None,
        "year_or_position": random.choice(POSITIONS_STAFF),
        "phone": fake.phone_number(),
        "address": fake.address(),
    }


def make_admin(i: int):
    return {
        "email": f"admin{i:02d}@hub.local",
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
    """Create 70 students + 15 teachers + 10 staff + 5 admins = 100 users."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Clear existing dev seed (optional — comment out if you want to preserve)
    existing = db.query(User).count()
    if existing > 0:
        print(f"⚠️  พบ user {existing} คนใน DB อยู่แล้ว")
        ans = input("ต้องการลบของเดิม และ seed ใหม่ทั้งหมดหรือไม่? (y/N): ").strip().lower()
        if ans == "y":
            db.query(User).delete()
            db.commit()
            print("✓ ลบ user เดิมแล้ว")
        else:
            print("ยกเลิก")
            return

    records = []
    for i in range(1, 71):
        records.append(make_student(i))
    for i in range(1, 16):
        records.append(make_teacher(i))
    for i in range(1, 11):
        records.append(make_staff(i))
    for i in range(1, 6):
        rec = make_admin(i)
        records.append(rec)

    for r in records:
        user = User(**r)
        if r["user_type"] == "admin":
            user.is_hub_admin = True
        db.add(user)

    db.commit()

    # Summary
    counts = {
        "student": db.query(User).filter(User.user_type == "student").count(),
        "teacher": db.query(User).filter(User.user_type == "teacher").count(),
        "staff": db.query(User).filter(User.user_type == "staff").count(),
        "admin": db.query(User).filter(User.user_type == "admin").count(),
    }
    print("\n✅ Seed สำเร็จ!")
    for ut, c in counts.items():
        print(f"   {ut}: {c} คน")
    print(f"   รวม: {sum(counts.values())} คน")
    print("\nลองดูที่ http://localhost:8000/admin/users/count")

    db.close()


if __name__ == "__main__":
    seed()
