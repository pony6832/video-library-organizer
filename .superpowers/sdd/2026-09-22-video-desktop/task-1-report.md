# Task 1 report — 2026-09-22

Status: implemented four scoped fixes, verified, ready for review.

## Changes

- Worker-supplied run IDs preserve a pending stop request. Only the standalone `begin_run` branch clears an old stop at its explicit resume boundary.
- Resumed force runs refresh video/image counts, bytes and total count in one SQLite write transaction, returning refreshed durable data while preserving stop and preparation state.
- Strict Excel loading normalizes `KeyError` and `ValueError` to `ReviewedPathsError`; permission errors retain their existing behavior.
- Installer failures after replacement rename the failed installation to a unique validated sibling and copy the old backup back to the original destination. The backup and failed installation remain recoverable; rollback errors report both paths. Exact sibling paths, parent ancestors and directory trees are checked for reparse points before moves/restoration. No recursive delete was introduced.

## TDD evidence

Read test-driven-development and writing-good-tests before changes.

The default `python` lacked openpyxl, so collection could not run. Switched to the existing project `.venv/Scripts/python.exe`; no dependency installation was needed.

RED: targeted tests were written before production edits and run with the project interpreter:

1. Stopped supplied force run performed one image call instead of zero.
2. Resumed inventory returned total_media=1 instead of 2.
3. Malformed XLSX ZIP escaped as KeyError for missing Content_Types.xml.
4. Installer failed after copying the new installation and left the original marker absent at its installed location. An initial assertion on English error text was adjusted for existing Windows PowerShell 5 UTF-8 decoding, then this test was rerun and failed on the intended restoration assertion.

GREEN focused command:

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -m pytest -q tests/test_batch_analysis.py tests/test_run_state.py tests/test_excel_catalog.py tests/test_installer.py tests/test_installer_portability.py
```

Result: **49 passed in 5.36s**, exit 0.

Full suite, run once after implementation:

```powershell
.venv/Scripts/python.exe -m pytest -q
```

Result: **208 passed, 2 skipped in 14.01s**, exit 0. `git diff --check` passed (only existing Git LF/CRLF conversion notices).

## Boundaries / concerns

- No API request, credential access, real dependency download, real desktop shortcut change, installed Skill change, or source media modification.
- Installer regression executes the real installer with command-boundary doubles; it injects venv failure after source copy. It verifies old user-data restoration plus retained backup and failed folders. It is not a full network installation/shortcut smoke test.
- If filesystem access fails during rollback or reparse validation rejects unexpected content, installer fails closed and retains recovery evidence rather than deleting or forcefully retrying.
