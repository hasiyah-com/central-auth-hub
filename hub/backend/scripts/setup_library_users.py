"""One-shot setup script for Subsystem B (ระบบห้องสมุด).

Creates / updates:
1. Two Hub users (furafae@gmail.com → staff, 6660506018@pnu.ac.th → student)
2. Subsystem "ระบบห้องสมุด" with status='active' (skips manual approval)
3. access_list rows:
     - furafae@gmail.com    → role_in_sub = "librarian"
     - 6660506018@pnu.ac.th → role_in_sub = "member"

Prints the freshly-generated client_id + client_secret to stdout
so they can be copied into hub/subsystem-library/.env.

Run inside hub-backend container:
    docker exec hub-backend python -m scripts.setup_library_users
"""
from __future__ import annotations

from datetime import datetime

from app.database import SessionLocal
from app.models import AccessList, Subsystem, User
from app.services.secret_service import generate_client_credentials, hash_secret


LIBRARY_CALLBACK = "http://localhost:8002/oauth/callback"
LIBRARY_SCOPE = ["openid", "profile", "email"]
SUBSYSTEM_NAME = "ระบบห้องสมุด"

USERS = [
    {
        "email": "furafae@gmail.com",
        "full_name": "Furafae (Librarian)",
        "user_type": "staff",
        "identifier": "S9001",
        "faculty": "สำนักหอสมุด",
        "year_or_position": "บรรณารักษ์",
        "role_in_sub": "librarian",
    },
    {
        "email": "6660506018@pnu.ac.th",
        "full_name": "นักศึกษา 6660506018",
        "user_type": "student",
        "identifier": "6660506018",
        "faculty": "ยังไม่ระบุ",
        "year_or_position": "ปริญญาตรี",
        "role_in_sub": "member",
    },
]


def upsert_user(db, spec: dict) -> User:
    user = db.query(User).filter(User.email == spec["email"]).one_or_none()
    if user is None:
        user = User(
            email=spec["email"],
            full_name=spec["full_name"],
            user_type=spec["user_type"],
            identifier=spec["identifier"],
            faculty=spec["faculty"],
            year_or_position=spec["year_or_position"],
            status="active",
        )
        db.add(user)
        db.flush()
        print(f"[+] created user: {user.email} ({user.user_type}) id={user.id}")
    else:
        # Refresh metadata in case the user existed with stale info
        user.full_name = user.full_name or spec["full_name"]
        user.user_type = user.user_type or spec["user_type"]
        user.identifier = user.identifier or spec["identifier"]
        user.faculty = user.faculty or spec["faculty"]
        user.year_or_position = user.year_or_position or spec["year_or_position"]
        user.status = "active"
        print(f"[=] user exists: {user.email} id={user.id}")
    return user


def upsert_subsystem(db, owner: User) -> tuple[Subsystem, str]:
    """Returns (Subsystem, plaintext_client_secret).

    Always regenerates client_secret (since the previous one isn't recoverable).
    """
    client_id, client_secret = generate_client_credentials()

    sub = (
        db.query(Subsystem)
        .filter(Subsystem.name == SUBSYSTEM_NAME)
        .one_or_none()
    )
    if sub is None:
        sub = Subsystem(
            name=SUBSYSTEM_NAME,
            description="Subsystem B — ระบบห้องสมุดนักศึกษา (Senior Project)",
            client_id=client_id,
            client_secret_hash=hash_secret(client_secret),
            redirect_uris=[LIBRARY_CALLBACK],
            scope=LIBRARY_SCOPE,
            status="active",
            owner_user_id=owner.id,
            approved_at=datetime.utcnow(),
        )
        db.add(sub)
        db.flush()
        print(f"[+] created subsystem: {SUBSYSTEM_NAME} id={sub.id}")
    else:
        sub.client_id = client_id
        sub.client_secret_hash = hash_secret(client_secret)
        sub.redirect_uris = [LIBRARY_CALLBACK]
        sub.scope = LIBRARY_SCOPE
        sub.status = "active"
        sub.approved_at = sub.approved_at or datetime.utcnow()
        print(f"[=] subsystem exists, rotated client_id + secret: id={sub.id}")
    return sub, client_secret


def upsert_access(db, sub: Subsystem, user: User, role_in_sub: str, granted_by: User):
    row = (
        db.query(AccessList)
        .filter(
            AccessList.subsystem_id == sub.id,
            AccessList.user_id == user.id,
        )
        .one_or_none()
    )
    if row is None:
        row = AccessList(
            subsystem_id=sub.id,
            user_id=user.id,
            role_in_sub=role_in_sub,
            granted_by=granted_by.id,
        )
        db.add(row)
        print(f"[+] access_list: {user.email} → {role_in_sub}")
    else:
        row.role_in_sub = role_in_sub
        row.revoked_at = None
        print(f"[=] access_list updated: {user.email} → {role_in_sub}")


def main():
    db = SessionLocal()
    try:
        users = [upsert_user(db, spec) for spec in USERS]
        librarian = users[0]  # use librarian as owner of the subsystem
        sub, plaintext_secret = upsert_subsystem(db, owner=librarian)
        for spec, user in zip(USERS, users):
            upsert_access(db, sub, user, spec["role_in_sub"], granted_by=librarian)
        db.commit()
        # Capture values BEFORE session closes (avoid DetachedInstanceError)
        client_id_out = sub.client_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print("\n" + "=" * 64)
    print("DONE — put these in hub/subsystem-library/.env then restart container:")
    print(f"LIBRARY_CLIENT_ID={client_id_out}")
    print(f"LIBRARY_CLIENT_SECRET={plaintext_secret}")
    print("=" * 64)


if __name__ == "__main__":
    main()
