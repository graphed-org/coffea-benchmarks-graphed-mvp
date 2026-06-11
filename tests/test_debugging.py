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


def test_the_user_traceback_survives_higher_optimization_levels():
    """opt_level=0 executes 1:1; opt_level>=1 fuses maximal op runs into stages — the buggy op
    is BURIED inside a multi-member fused stage, yet the StageError lands on the SAME user line:
    every fused member keeps its own SourceFrame through lowering."""
    import awkward as ak
    import uproot
    from graphed import Session
    from graphed_awkward import AwkwardBackend, from_awkward

    raw = uproot.open(WHERE[0]).arrays(["Jet_pt"], entry_stop=1000)
    s = Session(AwkwardBackend())
    g = from_awkward(s, "events", ak.Array({"Jet_pt": raw.Jet_pt}))
    bad = debugging.faulty_q4(g)

    lowered0 = gd.lower(s, bad, opt_level=0)
    lowered1 = gd.lower(s, bad, opt_level=1)
    assert lowered0.one_to_one and all(len(st.members) == 1 for st in lowered0.stages)
    fused = next(st for st in lowered1.stages if any(m.op == "ak.unflatten" for m in st.members))
    assert len(fused.members) > 1  # the buggy op rides INSIDE a fused stage at opt_level=1
    member = next(m for m in fused.members if m.op == "ak.unflatten")
    assert member.provenance.filename.endswith("debugging.py")  # provenance per fused MEMBER

    errors = {}
    for lvl in (0, 1):
        with pytest.raises(gd.StageError) as exc:
            gd.run(s, bad, opt_level=lvl, partition=f"lvl{lvl}")
        errors[lvl] = exc.value
    assert errors[0].opt_level == 0 and errors[1].opt_level == 1
    for err in errors.values():
        assert err.op == "ak.unflatten"
        assert err.user_frame.filename.endswith("debugging.py")
    # the SAME user line at both levels — optimization never costs the traceback
    assert errors[0].user_frame.lineno == errors[1].user_frame.lineno
    assert errors[0].user_frame.lineno == member.provenance.lineno
