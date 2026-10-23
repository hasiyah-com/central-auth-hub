"""RED/GREEN contract for domain self-registration and scoped invitations."""
from types import SimpleNamespace

from app.services.provisional_registration import (
    allowed_email_domain,
    can_provisional_access,
    google_identity_can_register,
    lowest_subsystem_role,
    normalize_email,
)


def test_domain_match_is_exact_and_case_insensitive():
    assert allowed_email_domain("New.User@Student.UNI.ac.th", ["student.uni.ac.th"])
    assert not allowed_email_domain("attacker@evil-student.uni.ac.th", ["student.uni.ac.th"])
    assert not allowed_email_domain("attacker@student.uni.ac.th.evil.com", ["student.uni.ac.th"])


def test_google_email_must_be_verified_before_registration():
    assert google_identity_can_register(
        {"email": "new@student.uni.ac.th", "email_verified": True},
        ["student.uni.ac.th"],
    )
    assert not google_identity_can_register(
        {"email": "new@student.uni.ac.th", "email_verified": False},
        ["student.uni.ac.th"],
    )
    assert not google_identity_can_register(
        {"email": "new@student.uni.ac.th"}, ["student.uni.ac.th"]
    )


def test_email_normalization_rejects_ambiguous_values():
    assert normalize_email("  New.User@UNI.AC.TH ") == "new.user@uni.ac.th"


def test_lowest_role_is_first_configured_role():
    assert lowest_subsystem_role(SimpleNamespace(allowed_roles=["member", "operator"])) == "member"
    assert lowest_subsystem_role(SimpleNamespace(allowed_roles=[])) == "user"


def test_provisional_user_is_scoped_to_explicit_active_membership():
    user = SimpleNamespace(status="provisional")
    assert can_provisional_access(user, membership_exists=True, denied=False)
    assert not can_provisional_access(user, membership_exists=False, denied=False)
    assert not can_provisional_access(user, membership_exists=True, denied=True)


def test_active_user_does_not_use_provisional_override():
    assert not can_provisional_access(
        SimpleNamespace(status="active"), membership_exists=True, denied=False
    )
