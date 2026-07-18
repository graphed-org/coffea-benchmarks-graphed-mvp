"""Checkpointing + preservation over the real skim (the M8/M9 layers on ADL data).

Pins: a resumable q1 run equals the harness's q1 counts; a CRASHED run (kill after 3 committed
partitions) resumes from the store alone, bit for bit, executing only the remainder; a finished
store re-runs with everything skipped; the q5 preservation bundle inspect()s without executing
and reproduce()s its build-time reference exactly, with totals consistent with the acceptance
reference.
"""

from __future__ import annotations

import json
import math
import os

import numpy as np
import pytest

pytest.importorskip("graphed.awkward")
pytest.importorskip("graphed.checkpoint")
pytest.importorskip("graphed.preserve")
pytest.importorskip("vector")

import benchmark  # noqa: E402
import preservation  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIM = os.path.join(HERE, "data", "Run2012B_SingleMu_50k.root")
WHERE = [SKIM + ":Events"]
REF = json.load(open(os.path.join(HERE, "data", "reference_counts.json")))
N, CHUNK = 50_000, 2**13


def _q1_reference() -> np.ndarray:
    return np.asarray(
        benchmark.run_benchmark("q1", WHERE, chunksize=CHUNK)["hists"]["q1"].values()
    )


def test_resumable_q1_matches_and_a_second_run_skips_everything(tmp_path):
    from graphed.checkpoint import Store, run_resumable

    plan = preservation.durable_q1_plan(WHERE, CHUNK)
    store = Store(tmp_path / "store")
    res = run_resumable(plan, store)
    assert res.report.executed == math.ceil(N / CHUNK)
    assert np.array_equal(np.asarray(res.value, dtype=float), _q1_reference())

    again = run_resumable(plan, store)  # the store already holds every partial
    assert again.report.executed == 0
    assert again.report.skipped == math.ceil(N / CHUNK)
    assert np.array_equal(np.asarray(again.value), np.asarray(res.value))


def test_crashed_run_resumes_bit_for_bit(tmp_path):
    from graphed.checkpoint import Store, run_resumable
    from graphed.checkpoint.runner import _SimulatedInterrupt

    plan = preservation.durable_q1_plan(WHERE, CHUNK)
    store = Store(tmp_path / "store")
    with pytest.raises(_SimulatedInterrupt):
        run_resumable(plan, store, _kill_after=3)  # crash mid-run: 3 partials committed
    assert len(store.completed()) == 3

    res = run_resumable(plan, store)  # resume on the same store
    assert res.report.skipped == 3 and res.report.executed == math.ceil(N / CHUNK) - 3
    assert res.report.did_less_work
    assert np.array_equal(np.asarray(res.value, dtype=float), _q1_reference())


def test_preserved_q5_bundle_inspects_and_reproduces(tmp_path):
    import boost_histogram as bh
    from graphed.preserve import inspect as inspect_bundle
    from graphed.preserve import reproduce

    bundle, build_reference = preservation.preserve_q5(tmp_path / "bundle", SKIM)

    # THE HISTOGRAM IS PART OF THE PAYLOAD (graphed-preserve M25): the fill node's canonical
    # spec is a content-addressed external payload, synthesized at build (payloads={} above)
    entry = next(e for e in bundle.manifest["externals"] if e["kind"] == "histogram")
    assert entry["content_hash"].startswith("sha256:")
    assert bundle.manifest["analysis"]["histogram"] is None  # no spec triple: the fill IS terminal

    rendered = inspect_bundle(bundle)  # renders WITHOUT executing or resolving data
    assert "events" in rendered and "histogram" in rendered
    assert "PRESERVATION RISK" not in rendered

    got = reproduce(bundle)  # the histogram ITSELF comes back
    assert isinstance(got, bh.Histogram)
    assert np.array_equal(got.values(flow=True), build_reference.values(flow=True))

    # consistent with the acceptance reference: same selection, totals agree (flow-inclusive)
    assert float(got.sum(flow=True)) == float(np.asarray(REF["q5"]["q5"]).sum())


def test_rerun_of_the_preserved_analysis_optimizes_retargets_and_parallelizes(tmp_path):
    import shutil

    pytest.importorskip("graphed_exec_local")
    from graphed_exec_local import ProcessExecutor
    from graphed.preserve import reproduce

    bundle, _build_ref = preservation.preserve_q5(tmp_path / "bundle", SKIM)

    # the bundle preserves opt_level=0 (auditable, NO stages); the re-run REDUCES it first.
    # the preserved graph now INCLUDES the histogram fill (an external node)
    _ir, stats = preservation.optimized_ir(bundle)
    assert "stage" not in stats["preserved_kinds"]  # 1:1 with the user's ops as preserved
    assert "external" in stats["preserved_kinds"]  # the FILL is preserved, in the graph
    assert "stage" in stats["reduced_kinds"]  # fused for execution
    assert "external" in stats["reduced_kinds"]  # ... with the fill still its terminal
    assert stats["reduced_nodes"] < stats["preserved_nodes"] / 2  # the collapse is real
    assert sum(stats["stage_members"]) > 0  # the user's ops live INSIDE the stages

    # re-target at a DIFFERENT input dataset (a copy under a new name) through a process pool;
    # each worker evaluates the REDUCED IR whose terminal is the fill -> per-chunk histograms
    retarget = tmp_path / "Run2012B_SingleMu_50k_retarget.root"
    shutil.copy(SKIM, retarget)
    rerun, _ = preservation.rerun_preserved(
        bundle, [str(retarget) + ":Events"], executor=ProcessExecutor(max_workers=2)
    )
    assert np.array_equal(
        np.asarray(rerun.values(flow=True)), np.asarray(reproduce(bundle).values(flow=True))
    )
