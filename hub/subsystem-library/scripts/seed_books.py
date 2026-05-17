"""Seed 30 หนังสือ × 6 หมวด สำหรับ demo.

Run:
    docker compose exec subsystem-library python -m scripts.seed_books
"""
from app.database import Base, SessionLocal, engine
from app.models import Book

# (isbn, title, author, category, copies_total, description)
BOOKS = [
    # คอมพิวเตอร์
    ("9780262510875", "Structure and Interpretation of Computer Programs",
     "Harold Abelson, Gerald Jay Sussman", "คอมพิวเตอร์", 2,
     "หนังสือคลาสสิกของ MIT — สอนแนวคิดการเขียนโปรแกรมผ่าน Scheme"),
    ("9780131103627", "The C Programming Language",
     "Brian W. Kernighan, Dennis M. Ritchie", "คอมพิวเตอร์", 3, None),
    ("9780321125217", "Domain-Driven Design",
     "Eric Evans", "คอมพิวเตอร์", 2, None),
    ("9780132350884", "Clean Code",
     "Robert C. Martin", "คอมพิวเตอร์", 3,
     "หลักการเขียนโค้ดที่อ่านง่าย ดูแลรักษาได้"),
    ("9780201633610", "Design Patterns: Elements of Reusable OO Software",
     "GoF (Gamma, Helm, Johnson, Vlissides)", "คอมพิวเตอร์", 2, None),

    # วิศวกรรม
    ("9780073401102", "Fluid Mechanics", "Frank M. White", "วิศวกรรม", 2, None),
    ("9780470458365", "Materials Science and Engineering",
     "William D. Callister", "วิศวกรรม", 2, None),
    ("9780470547564", "Mechanical Engineering Design",
     "Joseph Edward Shigley", "วิศวกรรม", 2, None),
    ("9780133923605", "Electric Circuits", "James W. Nilsson", "วิศวกรรม", 3, None),
    ("9780136019695", "Engineering Mechanics: Statics",
     "Russell C. Hibbeler", "วิศวกรรม", 3, None),

    # วิทยาศาสตร์
    ("9780321809155", "University Physics", "Hugh D. Young", "วิทยาศาสตร์", 4, None),
    ("9781305580350", "Calculus: Early Transcendentals",
     "James Stewart", "วิทยาศาสตร์", 3, None),
    ("9780321910295", "Linear Algebra and Its Applications",
     "David C. Lay", "วิทยาศาสตร์", 2, None),
    ("9780815344643", "Molecular Biology of the Cell",
     "Bruce Alberts", "วิทยาศาสตร์", 2, None),
    ("9780131495081", "Organic Chemistry", "Paula Yurkanis Bruice", "วิทยาศาสตร์", 2, None),

    # มนุษยศาสตร์
    ("9789749725603", "ประวัติศาสตร์ไทยร่วมสมัย",
     "นิธิ เอียวศรีวงศ์", "มนุษยศาสตร์", 2,
     "ภาพรวมประวัติศาสตร์ไทยตั้งแต่รัตนโกสินทร์ถึงปัจจุบัน"),
    ("9780199585588", "A History of Thailand",
     "Chris Baker, Pasuk Phongpaichit", "มนุษยศาสตร์", 2, None),
    ("9780521336598", "An Introduction to Literary Studies",
     "Mario Klarer", "มนุษยศาสตร์", 2, None),
    ("9780393640533", "Sapiens: A Brief History of Humankind",
     "Yuval Noah Harari", "มนุษยศาสตร์", 3,
     "ประวัติศาสตร์มนุษยชาติตั้งแต่บรรพชนถึงปัจจุบัน"),
    ("9789747528947", "ไทยศึกษา: บทความรวมเล่ม",
     "หลายผู้แต่ง", "มนุษยศาสตร์", 2, None),

    # บริหารธุรกิจ
    ("9780062735225", "Good to Great", "Jim Collins", "บริหารธุรกิจ", 3,
     "ทำไมบริษัทบางแห่งถึงก้าวจากดีไปสู่ยอดเยี่ยมได้"),
    ("9780062060242", "The Lean Startup",
     "Eric Ries", "บริหารธุรกิจ", 3, None),
    ("9780670921607", "Thinking, Fast and Slow",
     "Daniel Kahneman", "บริหารธุรกิจ", 2, None),
    ("9781422157534", "Competitive Strategy",
     "Michael E. Porter", "บริหารธุรกิจ", 2, None),
    ("9780062273833", "Zero to One",
     "Peter Thiel", "บริหารธุรกิจ", 3, None),

    # คณิตศาสตร์ประยุกต์ / AI
    ("9780262035613", "Deep Learning",
     "Ian Goodfellow, Yoshua Bengio, Aaron Courville", "คอมพิวเตอร์", 2,
     "ตำราหลักของวงการ Deep Learning"),
    ("9780136042594", "Artificial Intelligence: A Modern Approach",
     "Stuart Russell, Peter Norvig", "คอมพิวเตอร์", 3, None),
    ("9781492032649", "Hands-On Machine Learning with Scikit-Learn, Keras & TensorFlow",
     "Aurélien Géron", "คอมพิวเตอร์", 2, None),
    ("9780387310732", "Pattern Recognition and Machine Learning",
     "Christopher Bishop", "วิทยาศาสตร์", 2, None),
    ("9780262018029", "Introduction to Algorithms",
     "CLRS (Cormen et al.)", "คอมพิวเตอร์", 3,
     "ตำรามาตรฐานของวิชา Algorithm"),
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    existing = db.query(Book).count()
    if existing > 0:
        print(f"⚠️  มีหนังสือ {existing} เล่มอยู่แล้ว")
        ans = input("ต้องการลบของเก่าแล้ว seed ใหม่หรือไม่? (y/N): ").strip().lower()
        if ans != "y":
            print("ยกเลิก")
            db.close()
            return
        # หมายเหตุ: ลบ books อาจ fail ถ้ามี borrowings — ในนั้นค่อยลบ borrowings ก่อน
        from app.models import Borrowing
        db.query(Borrowing).delete()
        db.query(Book).delete()
        db.commit()
        print(f"✓ ลบ books + borrowings เก่าแล้ว")

    for isbn, title, author, category, total, desc in BOOKS:
        db.add(Book(
            isbn=isbn,
            title=title,
            author=author,
            category=category,
            description=desc,
            copies_total=total,
            copies_available=total,
            status="active",
        ))
    db.commit()

    by_cat: dict[str, int] = {}
    for _, _, _, c, _, _ in BOOKS:
        by_cat[c] = by_cat.get(c, 0) + 1

    print(f"\n✅ Seed สำเร็จ — {len(BOOKS)} เล่ม")
    for cat, n in by_cat.items():
        print(f"   {cat}: {n} เล่ม")
    print("\nลองเปิด http://localhost:8002/books")
    db.close()


if __name__ == "__main__":
    seed()
