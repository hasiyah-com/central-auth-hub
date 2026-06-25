"""Seed 24 ห้องในหอพัก: ตึก A/B × 3 ชั้น × 4 ห้อง × capacity 2.

รูปแบบ room_number: <ตึก><ชั้น><เลขห้อง>  เช่น A101, A102, B305

Run:
    docker compose exec subsystem-dorm python -m scripts.seed_rooms
"""

from app.database import Base, SessionLocal, engine
from app.models import Room

BUILDINGS = ["A", "B"]
FLOORS = [1, 2, 3]
ROOMS_PER_FLOOR = 4
CAPACITY = 2


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    existing = db.query(Room).count()
    if existing > 0:
        print(f"⚠️  มีห้อง {existing} ห้องอยู่แล้ว")
        ans = input("ต้องการลบของเก่าแล้ว seed ใหม่หรือไม่? (y/N): ").strip().lower()
        if ans != "y":
            print("ยกเลิก")
            db.close()
            return
        db.query(Room).delete()
        db.commit()
        print(f"✓ ลบห้องเก่า {existing} ห้องแล้ว")

    count = 0
    for building in BUILDINGS:
        for floor in FLOORS:
            for i in range(1, ROOMS_PER_FLOOR + 1):
                room_number = f"{building}{floor}{i:02d}"  # A101, A102, ...
                db.add(
                    Room(
                        building=building,
                        floor=floor,
                        room_number=room_number,
                        capacity=CAPACITY,
                        status="available",
                    )
                )
                count += 1
    db.commit()

    print(f"\n✅ Seed สำเร็จ — {count} ห้อง")
    print(f"   ตึก: {', '.join(BUILDINGS)}")
    print(f"   ชั้น: {FLOORS}")
    print(f"   ห้องต่อชั้น: {ROOMS_PER_FLOOR}")
    print(f"   ความจุ/ห้อง: {CAPACITY} คน")
    print("\nลองเปิด http://localhost:8001/rooms")
    db.close()


if __name__ == "__main__":
    seed()
