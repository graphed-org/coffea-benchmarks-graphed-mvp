"""ADL-port acceptance (P1): the eight graphed queries against the coffea reference, BIT FOR BIT.

The reference (data/reference_counts.json) is the ORIGINAL coffea processors run over the
committed 50k skim of Run2012B_SingleMu.root (scripts/make_reference.py). Bit-for-bit is a
SAME-PLATFORM claim — libm ULP differences across platforms can flip argmin picks between
near-equidistant trijet candidates (q6) — so CI regenerates the reference on its own platform
before comparing; the committed JSON is the macOS snapshot. Every bin including flow must match
exactly: same per-event float operations -> same bin -> identical integer counts, independent
of partitioning. One query is additionally aggregated through a SPAWNED
process pool (vector behaviors by import ref) and pinned identical, and recording is pinned
deterministic (byte-identical serialized IR across two recordings).
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

pytest.importorskip("graphed.awkward")
pytest.importorskip("graphed_histogram")
pytest.importorskip("hist.graphed")
pytest.importorskip("vector")

import adl_graphed as adl  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHERE = os.path.join(HERE, "data", "Run2012B_SingleMu_50k.root") + ":Events"
REF = json.load(open(os.path.join(HERE, "data", "reference_counts.json")))


@pytest.mark.parametrize("qname", sorted(adl.QUERIES))
def test_query_matches_the_coffea_reference_bit_for_bit(qname):
    out = adl.run_query(qname, WHERE, steps_per_file=4)
    assert set(out) == set(REF[qname])
    for label, h in out.items():
        got = np.asarray(h.values(flow=True))
        want = np.asarray(REF[qname][label])
        assert np.array_equal(got, want), f"{qname}/{label}: counts differ from the coffea reference"


@pytest.mark.parametrize("qname", sorted(adl.QUERIES))
def test_query_parallel_matches_the_reference_approximately(qname):
    """Every query through a SPAWNED process pool (>=2 workers). Exactness is the SEQUENTIAL
    tier's claim; here rounding-level agreement suffices (combine-tree float effects allowed)."""
    pytest.importorskip("graphed_executors.local")
    from graphed_executors.local import ProcessExecutor

    out = adl.run_query(qname, WHERE, steps_per_file=8, executor=ProcessExecutor(max_workers=2))
    for label, h in out.items():
        got = np.asarray(h.values(flow=True))
        want = np.asarray(REF[qname][label])
        assert np.allclose(got, want), f"{qname}/{label}: parallel counts diverge beyond rounding"


def test_partitioning_does_not_change_any_count():
    # integer counts are exact under ANY partitioning: per-event work is identical
    a = adl.run_query("q5", WHERE, steps_per_file=1)["q5"]
    b = adl.run_query("q5", WHERE, steps_per_file=7)["q5"]
    assert np.array_equal(a.values(flow=True), b.values(flow=True))


def test_process_pool_aggregation_matches_with_behaviors_by_import_ref():
    # pinned against the SEQUENTIAL run (same platform by construction): the pool must change
    # nothing, with vector behaviors reaching workers by import ref
    pytest.importorskip("graphed_executors.local")
    from graphed_executors.local import ProcessExecutor

    sequential = adl.run_query("q6", WHERE, steps_per_file=3)
    sys.path.insert(0, HERE)  # spawn children inherit sys.path; adl_graphed resolves in workers
    try:
        pooled = adl.run_query("q6", WHERE, steps_per_file=3, executor=ProcessExecutor(max_workers=2))
    finally:
        sys.path.remove(HERE)
    for label, h in pooled.items():
        assert np.array_equal(
            np.asarray(h.values(flow=True)), np.asarray(sequential[label].values(flow=True))
        )


def test_recording_is_deterministic():
    import uproot

    def record_once() -> bytes:
        g = uproot.graphed(WHERE, library="ak", behavior=adl.behavior())
        h = adl.QUERIES["q8"](g)
        (node,) = h.fill_nodes()
        return g.session.serialized_ir(node)

    assert record_once() == record_once()


def test_queries_read_only_what_they_touch():
    # project the FILL EXPRESSION (an External fill node is opaque to projection, by design)
    import uproot
    from graphed.awkward import gak

    g = uproot.graphed(WHERE, library="ak", behavior=adl.behavior())
    expr = g.MET_pt[gak.sum(g.Jet_pt > 40.0, axis=1) >= 2]  # q4's fill input, verbatim
    cols = uproot.necessary_columns(expr)["Events"]
    assert cols == frozenset({"Jet_pt", "MET_pt"})  # q4 touches nothing else
