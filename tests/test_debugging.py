"""graphed-debug over the real skim: errors point at the USER's code, across process boundaries.

Pins (plan A.3 #8): a record-time type error carries the user's source line; a runtime,
DATA-DEPENDENT failure raised INSIDE a spawned worker reaches the driver as a real StageError
(never an opaque string) — with the failing op, the user's analysis frames (the buggy line in
debugging.py), the input forms, WHICH partition failed, and the underlying cause — and
format_traceback renders the arrowed user-code traceback from it.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("graphed_awkward")
pytest.importorskip("graphed_debug")
pytest.importorskip("graphed_exec_local")

import graphed_debug as gd  # noqa: E402

import debugging  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHERE = [os.path.join(HERE, "data", "Run2012B_SingleMu_50k.root") + ":Events"]


def test_record_time_errors_carry_the_users_line():
    import uproot
    from graphed import GraphedTypeError

    g = uproot.graphed(WHERE, library="ak")
    with pytest.raises(GraphedTypeError) as exc:
        _ = g.Jet_ptt  # a typo'd branch: caught AT RECORD TIME, before any data is read
    assert "test_debugging.py" in str(exc.value)  # ... pointing at THIS file's line


def test_worker_stage_errors_cross_the_process_boundary_intact():
    from graphed_exec_local import ProcessExecutor

    plan = debugging.faulty_plan(WHERE, chunksize=2**14)
    with pytest.raises(gd.StageError) as exc:  # a REAL StageError, re-raised by the driver
        ProcessExecutor(max_workers=2).run(plan)
    err = exc.value
    assert err.op == "ak.unflatten"
    assert err.cause_type == "ValueError"
    assert "Run2012B_SingleMu_50k.root@" in err.partition  # WHICH chunk failed
    assert any("debugging.py" in f.filename for f in err.frames)  # the user's analysis frames
    assert err.user_frame.filename.endswith("debugging.py")  # the closest user frame

    rendered = gd.format_traceback(err)
    assert "-->" in rendered and "debugging.py" in rendered  # the arrowed faulty line
    assert "ak.unflatten" in rendered and "ValueError" in rendered
