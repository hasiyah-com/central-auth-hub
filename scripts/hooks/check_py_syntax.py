"""Claude Code PostToolUse hook — run py_compile หลัง Edit/Write .py

Advisory: print error ไป stderr แต่ exit 0 (ไม่ block flow)
ทำให้ Claude เห็น error แล้วแก้รอบถัดไป
"""
import json
import py_compile
import sys


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    if event.get("tool_name") not in ("Write", "Edit"):
        return 0

    file_path = event.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        return 0

    try:
        py_compile.compile(file_path, doraise=True)
    except py_compile.PyCompileError as e:
        print(f"[py_compile] SYNTAX ERROR ใน {file_path}:\n{e.msg}", file=sys.stderr)
    except FileNotFoundError:
        # ไฟล์อาจถูกลบหรือยังไม่ flush — ข้าม
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
