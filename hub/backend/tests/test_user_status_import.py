"""Excel status-import validation before any user mutation."""

import base64
from io import BytesIO

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app.routers.users import _read_status_file, _validate_status_rows


def _file(rows):
    book = Workbook()
    book.active.title = "status_updates"
    book.active.append(["email", "new_status"])
    for row in rows:
        book.active.append(row)
    output = BytesIO()
    book.save(output)
    return base64.b64encode(output.getvalue()).decode()


def test_import_reads_and_normalizes_excel():
    rows = _read_status_file(_file([[" User@Example.com ", " Suspended "]]))
    assert rows == [(2, "user@example.com", "suspended")]


def test_import_rejects_oversized_and_bad_excel():
    with pytest.raises(HTTPException) as bad:
        _read_status_file("not excel")
    assert bad.value.status_code == 422
    with pytest.raises(HTTPException) as oversized:
        _read_status_file("A" * 1_500_000)
    assert oversized.value.status_code == 422


def test_import_preview_reports_duplicate_missing_and_self_lockout(db, admin_user):
    rows = [
        (2, admin_user.email.lower(), "suspended"),
        (3, admin_user.email.lower(), "active"),
        (4, "no-such-user-123@example.com", "active"),
    ]
    _, valid, errors = _validate_status_rows(rows, db, admin_user)
    assert valid == []
    assert [error["row"] for error in errors] == [2, 3, 4]


def _create_file(rows):
    from app.routers.users import _CREATE_COLUMNS
    book = Workbook()
    book.active.title = "new_users"
    book.active.append(_CREATE_COLUMNS)
    for row in rows:
        book.active.append(row)
    output = BytesIO()
    book.save(output)
    return base64.b64encode(output.getvalue()).decode()


def test_create_import_reads_full_template_and_defaults_status():
    from app.routers.users import _read_create_file
    encoded = _create_file([[" Person@Example.com ", "Test Person", "Student", "00123",
                             "Engineering", "CS", "2", "0812345678", ""]])
    rows = _read_create_file(encoded)
    assert rows[0][1] == {
        "email": "person@example.com", "full_name": "Test Person", "user_type": "student",
        "identifier": "00123", "faculty": "Engineering", "major": "CS",
        "year_or_position": "2", "phone": "0812345678", "status": "active",
    }


def test_create_import_rejects_existing_and_duplicate_rows(db, admin_user):
    from app.routers.users import _read_create_file, _validate_create_rows
    rows = _read_create_file(_create_file([
        [admin_user.email, "Existing", "student", "", "", "", "", "", "active"],
        ["new-bulk-test@example.com", "New", "student", "BULK-TEST-ID-2026", "", "", "", "", "active"],
        ["new-bulk-test@example.com", "Duplicate", "student", "BULK-TEST-ID-2026", "", "", "", "", "active"],
    ]))
    valid, errors = _validate_create_rows(rows, db)
    assert len(valid) == 1
    assert [error["row"] for error in errors] == [2, 4]


def test_create_import_rejects_invalid_type_and_required_fields(db):
    from app.routers.users import _read_create_file, _validate_create_rows
    rows = _read_create_file(_create_file([
        ["no-name@example.com", "", "student", "", "", "", "", "", ""],
        ["wrong-type@example.com", "Name", "visitor", "", "", "", "", "", "active"],
    ]))
    valid, errors = _validate_create_rows(rows, db)
    assert not valid
    assert [error["row"] for error in errors] == [2, 3]


def test_create_user_phone_limit_applies_to_form_and_excel(db):
    from pydantic import ValidationError
    from app.routers.users import UserCreate, UserUpdate, _read_create_file, _validate_create_rows
    fields = {"email": "new-phone-limit@example.com", "full_name": "Phone Limit", "user_type": "student"}
    UserCreate(**fields, phone="0812345678")
    for schema, data in ((UserCreate, {**fields, "phone": "08123456789"}),
                         (UserUpdate, {"phone": "08123456789"})):
        with pytest.raises(ValidationError):
            schema(**data)
    rows = _read_create_file(_create_file([
        [fields["email"], fields["full_name"], "student", "", "", "", "", "08123456789", "active"]
    ]))
    valid, errors = _validate_create_rows(rows, db)
    assert not valid and errors[0]["row"] == 2
