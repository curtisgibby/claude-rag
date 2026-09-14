"""
Tests for the exclusive modifiedTime bound on incremental meeting-doc pulls.

Verifies:
  - A document whose modifiedTime equals the watermark is excluded.
  - A document strictly newer than the watermark is kept.
  - A document older than the watermark is excluded.
  - A document edited mid-run (strictly newer) still survives the filter.
  - No filtering happens on a full pull (no watermark).
  - A missing modifiedTime does not crash the filter.

The bug this guards against: Drive's ">" on modifiedTime is inclusive, so a
document whose stamp equals the bound is returned anyway. Because the watermark
is the max modifiedTime of the previous pull, the newest document's stamp always
equals it — so that document was re-fetched and re-embedded on every run,
forever, and the watermark never advanced past it. Observed 2026-09-14 after two
runs re-indexed the same document while the watermark sat still.

Drive is stubbed; no network access occurs.
"""

import sys
from pathlib import Path
from unittest.mock import patch

# Make scripts/ importable from the tests/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import drive_collector

WATERMARK = "2026-09-11T22:21:38.531Z"


def _drive_returns(*docs):
    """Stub one Drive files.list page containing exactly these documents."""

    class _Response:
        status_code = 200

        def json(self):
            return {"files": list(docs)}

    return patch("requests.get", return_value=_Response())


def _doc(name, modified):
    return {"id": name, "name": name, "modifiedTime": modified}


def _list(modified_after=WATERMARK):
    return drive_collector._list_meeting_docs(
        "token", "Notes by Gemini", modified_after=modified_after
    )


def test_document_equal_to_the_watermark_is_excluded():
    # Drive hands this back despite the ">" in the query. This is the case that
    # was re-indexing the same document every morning.
    with _drive_returns(_doc("boundary", WATERMARK)):
        assert _list() == []


def test_strictly_newer_document_is_kept():
    newer = _doc("newer", "2026-09-11T22:21:38.532Z")
    with _drive_returns(newer):
        assert _list() == [newer]


def test_older_document_is_excluded():
    with _drive_returns(_doc("older", "2026-09-10T00:00:00.000Z")):
        assert _list() == []


def test_document_edited_mid_run_still_survives():
    # The reason the watermark is the max of what was fetched rather than the
    # run's clock: an edit landing after we read the document gets a strictly
    # greater stamp, so the next run must still see it.
    mid_run = _doc("edited-during-run", "2026-09-11T22:21:38.900Z")
    with _drive_returns(mid_run):
        assert _list() == [mid_run]


def test_full_pull_does_not_filter():
    boundary = _doc("boundary", WATERMARK)
    old = _doc("old", "2020-01-01T00:00:00.000Z")
    with _drive_returns(boundary, old):
        assert _list(modified_after=None) == [boundary, old]


def test_missing_modified_time_does_not_crash():
    with _drive_returns({"id": "x", "name": "no timestamp"}):
        assert _list() == []


def test_mixed_batch_keeps_only_strictly_newer():
    boundary = _doc("boundary", WATERMARK)
    newer = _doc("newer", "2026-09-12T08:00:00.000Z")
    older = _doc("older", "2026-09-01T08:00:00.000Z")
    with _drive_returns(newer, boundary, older):
        assert _list() == [newer]
