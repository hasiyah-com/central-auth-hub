"""Rules shared by OAuth self-registration and developer-scoped invitations."""
from __future__ import annotations
from datetime import datetime
from email_validator import EmailNotValidError, validate_email
from sqlalchemy.orm import Session

def normalize_email(value: str) -> str:
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError("รูปแบบอีเมลไม่ถูกต้อง") from exc

def normalized_domains(domains: list[str] | None) -> set[str]:
    return {item.strip().lower().lstrip("@") for item in (domains or []) if item and item.strip().lstrip("@")}

def allowed_email_domain(email: str, domains: list[str] | None) -> bool:
    try:
        domain = normalize_email(email).rsplit("@", 1)[1]
    except (ValueError, IndexError):
        return False
    return domain in normalized_domains(domains)

def google_identity_can_register(userinfo: dict, domains: list[str] | None) -> bool:
    return bool(userinfo.get("email_verified") is True and allowed_email_domain(str(userinfo.get("email") or ""), domains))

def lowest_subsystem_role(subsystem) -> str:
    roles = list(getattr(subsystem, "allowed_roles", None) or [])
    return roles[0] if roles else "user"

def can_provisional_access(user, *, membership_exists: bool, denied: bool) -> bool:
    return bool(getattr(user, "status", None) == "provisional" and membership_exists and not denied)

def create_provisional_identity(db: Session, *, subsystem, email: str, full_name: str,
    identifier: str | None, faculty: str | None, major: str | None,
    google_sub: str | None, source: str, invited_by=None):
    from app.models import AccessList, SubsystemChangeRequest, User
    clean_email = normalize_email(email)
    if not allowed_email_domain(clean_email, subsystem.allowed_email_domains):
        raise ValueError("โดเมนอีเมลไม่ได้รับอนุญาตสำหรับระบบย่อยนี้")
    user = db.query(User).filter(User.email == clean_email).first()
    if user and user.status not in {"provisional", "active"}:
        raise ValueError(f"บัญชีนี้ไม่สามารถสมัครได้ (status={user.status})")
    if not user:
        user = User(email=clean_email, google_sub=google_sub,
            full_name=(full_name or clean_email.split("@", 1)[0]).strip(), user_type="student",
            identifier=(identifier or "").strip() or None, faculty=(faculty or "").strip() or None,
            major=(major or "").strip() or None, status="provisional",
            email_verified=bool(google_sub), email_verified_at=datetime.utcnow() if google_sub else None)
        db.add(user); db.flush()
    elif google_sub:
        if user.google_sub and user.google_sub != google_sub:
            raise ValueError("Google account ไม่ตรงกับบัญชีที่เชิญไว้")
        user.google_sub = google_sub; user.email_verified = True
        if not user.email_verified_at: user.email_verified_at = datetime.utcnow()
        if full_name: user.full_name = full_name.strip()
        if identifier: user.identifier = identifier.strip()
        if faculty: user.faculty = faculty.strip()
        if major: user.major = major.strip()
    membership = db.query(AccessList).filter(AccessList.subsystem_id == subsystem.id, AccessList.user_id == user.id).first()
    if membership:
        if membership.entry_type == "deny": raise ValueError("บัญชีนี้ถูกปฏิเสธสิทธิ์ในระบบย่อย")
        membership.revoked_at = None
        membership.role_in_sub = membership.role_in_sub or lowest_subsystem_role(subsystem)
        membership.source = source
    else:
        membership = AccessList(subsystem_id=subsystem.id, user_id=user.id,
            role_in_sub=lowest_subsystem_role(subsystem), entry_type="allow", source=source,
            granted_by=getattr(invited_by, "id", None))
        db.add(membership)
    pending = next((req for req in db.query(SubsystemChangeRequest).filter(
        SubsystemChangeRequest.subsystem_id == subsystem.id,
        SubsystemChangeRequest.request_type == "user_registration",
        SubsystemChangeRequest.status == "pending").all()
        if str((req.payload or {}).get("user_id")) == str(user.id)), None)
    if not pending and user.status == "provisional":
        pending = SubsystemChangeRequest(subsystem_id=subsystem.id, requested_by=user.id,
            request_type="user_registration", status="pending", payload={
                "user_id": str(user.id), "email": user.email, "full_name": user.full_name,
                "identifier": user.identifier, "faculty": user.faculty, "major": user.major,
                "source": source, "invited_by": str(invited_by.id) if invited_by else None,
                "initial_role": membership.role_in_sub})
        db.add(pending); db.flush()
    return user, membership, pending
