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
