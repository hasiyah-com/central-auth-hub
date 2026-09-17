"""ตัวกันไฟล์บีบอัดและไฟล์ key ใน pre-commit — เขียนก่อน implementation (RED).

ที่มา (17 ก.ย. 2569): `hub/backend.zip` ขนาด 13 MB วางอยู่ใน repo โดยไม่อยู่ใน
.gitignore และมี `keys/jwt_private.pem` กับ `keys/hub-key-2_private.pem` **ตัวเดียวกับที่
ระบบใช้อยู่** · `detect-private-key` ตรวจเนื้อไฟล์ข้อความ มองไม่เห็นของที่อยู่ใน zip
ถ้ามีใคร `git add -A` key จะหลุดขึ้น git ทันที

hook อยู่ที่ `scripts/hooks/block_archives.py` ซึ่งไม่ได้ mount ในคอนเทนเนอร์ —
เทสนี้รันบน host และ skip ในคอนเทนเนอร์
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_parents = ROOT.parents
REPO = _parents[1] if len(_parents) > 1 else ROOT
HOOK = REPO / "scripts" / "hooks" / "block_archives.py"
GITIGNORE = REPO / ".gitignore"
PRECOMMIT = REPO / ".pre-commit-config.yaml"

pytestmark = pytest.mark.skipif(
    not (REPO / "scripts" / "hooks").exists(),
    reason="scripts/hooks ไม่ได้ mount ในคอนเทนเนอร์ — ตรวจบน host",
)


def _hook():
    if not HOOK.exists():
        pytest.fail(f"ยังไม่มี {HOOK}")
    spec = importlib.util.spec_from_file_location("block_archives", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "path",
    [
        "hub/backend.zip",
        "ml-service.rar",
        "scripts.7z",
        "backup/db.tar",
        "backup/db.tar.gz",
        "backup/db.tgz",
        "dump.sql.gz",
        "keys/client.p12",
        "keys/client.pfx",
        "certs/server.key",
        "hub\\backend\\old.zip",
    ],
)
def test_archives_and_key_containers_are_blocked(path):
    assert _hook().main(["hook", path]) == 1, path


@pytest.mark.parametrize(
    "path",
    [
        "hub/backend/app/main.py",
        "docs/report.docx",
        "docs/slides.pptx",
        "docs/diagram.svg",
        "hub/backend/app/security/artifacts/calibration_v1.json",
        "docs/keyboard-shortcuts.md",
    ],
)
def test_ordinary_files_pass(path):
    assert _hook().main(["hook", path]) == 0, path


def test_hook_is_registered_in_pre_commit():
    text = PRECOMMIT.read_text(encoding="utf-8")
    assert "scripts/hooks/block_archives.py" in text


@pytest.mark.parametrize("pattern", ["*.zip", "*.rar", "*.7z", "*.tar", "*.tgz"])
def test_gitignore_covers_archives(pattern):
    lines = {
        line.strip() for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
    }
    assert pattern in lines, f".gitignore ไม่มี {pattern}"
