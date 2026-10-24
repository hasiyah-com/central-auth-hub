"""Central trusted domains for provisional user registration.

The Hub owns the master allowlist.  A subsystem may select only a subset of
that list, and an email must match both layers before an identity is created.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import AppSetting, Subsystem

_KEY = "trusted_registration_domains"
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)


def clean_domains(values: list[str] | None) -> list[str]:
    return sorted(
        {
            value.strip().lower().lstrip("@")
            for value in (values or [])
            if value and value.strip().lstrip("@")
        }
    )


def invalid_domains(values: list[str] | None) -> list[str]:
    """Return normalized values that are not valid DNS domain names."""
    return [domain for domain in clean_domains(values) if not _DOMAIN_RE.fullmatch(domain)]


def domains_are_trusted(selected: list[str] | None, trusted: list[str] | None) -> bool:
    return set(clean_domains(selected)).issubset(set(clean_domains(trusted)))


def email_allowed_by_both_layers(
    email: str,
    subsystem_domains: list[str] | None,
    trusted_domains: list[str] | None,
) -> bool:
    from app.services.provisional_registration import allowed_email_domain

    return allowed_email_domain(email, subsystem_domains) and allowed_email_domain(
        email, trusted_domains
    )


def get_trusted_registration_domains(db: Session) -> list[str]:
    row = db.query(AppSetting).filter(AppSetting.key == _KEY).first()
    if row is not None:
        return clean_domains((row.value or {}).get("domains", []))

    # Backward-compatible bootstrap: the first deployment trusts the union of
    # domains that admins already approved on existing subsystems.  The first
    # central edit persists an explicit master list.
    configured = db.query(Subsystem.allowed_email_domains).all()
    return clean_domains(
        [domain for (domains,) in configured for domain in (domains or [])]
    )


def set_trusted_registration_domains(
    db: Session, domains: list[str], *, actor_id
) -> list[str]:
    cleaned = clean_domains(domains)
    row = db.query(AppSetting).filter(AppSetting.key == _KEY).first()
    if row is None:
        row = AppSetting(key=_KEY, value={"domains": cleaned}, updated_by=actor_id)
        db.add(row)
    else:
        row.value = {"domains": cleaned}
        row.updated_by = actor_id
    db.flush()
    return cleaned


def untrusted_domains(
    selected: list[str] | None, trusted: list[str] | None
) -> list[str]:
    return sorted(set(clean_domains(selected)) - set(clean_domains(trusted)))
