"""The P2 harness over the committed skim (CI-safe; the 16 GB sweep is local-only).

Pins: a measured benchmark point reports complete, sane metrics (entries == the skim, chunks == the ceiling,
bytes read positive and bounded by the file size — reads are PROJECTED); the histograms it
produces agree with the acceptance reference; parallel points run through a process pool.
"""

from __future__ import annotations

import json
import math
import os

import numpy as np
import pytest

pytest.importorskip("graphed.awkward")
pytest.importorskip("graphed_histogram")
pytest.importorskip("hist.graphed")
pytest.importorskip("coffea.nanoevents")

import benchmark  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIM = os.path.join(HERE, "data", "Run2012B_SingleMu_50k.root")
WHERE = [SKIM]
REF = json.load(open(os.path.join(HERE, "data", "reference_counts.json")))
N = 50_000


def test_benchmark_point_metrics_and_counts():
    point = benchmark.run_benchmark("q4", WHERE, chunksize=2**13)
    assert point["entries"] == N
    assert point["chunks"] == math.ceil(N / 2**13)
    assert (
        0 < point["bytesread"] <= 2 * os.path.getsize(SKIM)
    )  # projected reads, real accounting
    assert point["walltime"] > 0 and point["MB/s/core"] > 0
    got = np.asarray(point["hists"]["q4"].values(flow=True))
    assert np.allclose(got, np.asarray(REF["q4"]["q4"]))


def test_projection_shrinks_the_bytes_read():
    # q1 touches only MET_pt; q7 touches eleven branches: q1 must read far less
    q1 = benchmark.run_benchmark("q1", WHERE, chunksize=2**14)
    q7 = benchmark.run_benchmark("q7", WHERE, chunksize=2**14)
    assert q1["bytesread"] < q7["bytesread"] / 3


def test_q6_is_one_pass_with_two_histograms():
    point = benchmark.run_benchmark("q6", WHERE, chunksize=2**14)
    assert set(point["hists"]) == {"trijetpt", "maxbtag"}
    for label, h in point["hists"].items():
        assert np.allclose(
            np.asarray(h.values(flow=True)), np.asarray(REF["q6"][label])
        )


def test_parallel_point_through_a_persistent_pool():
    pytest.importorskip("graphed_executors.local")
    from graphed_executors.local import ProcessExecutor

    with ProcessExecutor(max_workers=2, persistent=True) as ex:
        point = benchmark.run_benchmark(
            "q5", WHERE, chunksize=2**14, executor=ex, workers=2
        )
    assert point["entries"] == N
    assert np.allclose(
        np.asarray(point["hists"]["q5"].values(flow=True)), np.asarray(REF["q5"]["q5"])
    )


def test_combined_plan_matches_per_query_plans():
    """All eight queries in ONE plan (one data pass) reproduce each per-query plan's histograms
    exactly — the speedup benchmark times this combined plan so that both runners open each
    file exactly once (resource symmetry)."""
    from graphed.core.execution import SequentialRunner

    import adl_graphed as adl

    combined = SequentialRunner().run(adl.query_plan(list(adl.QUERIES), WHERE, steps_per_file=2)).value
    for qname in ("q1", "q5", "q7"):
        per_query = SequentialRunner().run(adl.query_plan(qname, WHERE, steps_per_file=2)).value
        assert np.array_equal(
            np.asarray(combined[qname].values(flow=True)), np.asarray(per_query[qname].values(flow=True))
        )
