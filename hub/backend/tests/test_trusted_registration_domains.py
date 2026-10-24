"""RED/GREEN contracts for the central registration-domain allowlist."""

from app.services.registration_domains import (
    clean_domains,
    domains_are_trusted,
    email_allowed_by_both_layers,
    invalid_domains,
)


def test_clean_domains_normalizes_at_prefix_case_and_duplicates():
    assert clean_domains([" @UNI.AC.TH ", "uni.ac.th", "student.uni.ac.th"]) == [
        "student.uni.ac.th",
        "uni.ac.th",
    ]


def test_invalid_domains_rejects_email_urls_and_malformed_labels():
    assert invalid_domains(
        ["uni.ac.th", "user@uni.ac.th", "https://uni.ac.th", "-uni.ac.th", "localhost"]
    ) == ["-uni.ac.th", "https://uni.ac.th", "localhost", "user@uni.ac.th"]


def test_subsystem_domains_must_be_subset_of_central_domains():
    trusted = ["uni.ac.th", "student.uni.ac.th"]
    assert domains_are_trusted(["uni.ac.th"], trusted)
    assert not domains_are_trusted(["evil.example"], trusted)
    assert not domains_are_trusted(["student.uni.ac.th", "evil.example"], trusted)


def test_registration_email_must_match_both_central_and_subsystem_layers():
    assert email_allowed_by_both_layers(
        "new@uni.ac.th", ["uni.ac.th"], ["uni.ac.th", "staff.uni.ac.th"]
    )
    assert not email_allowed_by_both_layers(
        "new@staff.uni.ac.th", ["uni.ac.th"], ["uni.ac.th", "staff.uni.ac.th"]
    )
    assert not email_allowed_by_both_layers(
        "new@uni.ac.th", ["uni.ac.th"], ["staff.uni.ac.th"]
    )
    assert not email_allowed_by_both_layers(
        "new@uni.ac.th.evil.com", ["uni.ac.th"], ["uni.ac.th"]
    )
