"""Source-mapped error debugging for ADL-style analyses (graphed-debug / M6, on real skim data).

A runtime failure in a graphed analysis is never an opaque remote string: it surfaces as a
``StageError`` carrying the failing OP, the recorded SOURCE FRAMES (pointing at the user's own
analysis line), the input FORMS, the PARTITION that failed, and the underlying cause — and it
PICKLES intact across a process boundary, so a worker's failure re-raises in the driver still
pointing at the user's code (plan A.3 #8, the dask failure this fixes).

``faulty_q4`` carries a deliberate, DATA-DEPENDENT bug (off-by-one ``unflatten`` counts) that
the record-time typetracer cannot see — only a worker hitting real data trips it.
"""

from __future__ import annotations

from typing import Any

import numpy as np

import uproot


def faulty_q4(g: Any) -> Any:
    """A buggy take on q4's jet handling: rebuild the jagged jets from flat pt — with the
    counts off by one. Records cleanly; fails on real data."""
    from graphed_awkward import gak

    flat_pt = gak.flatten(g.Jet_pt, axis=1)
    counts = gak.num(g.Jet_pt, axis=1) + 1  # BUG: off-by-one counts
    rebuilt = gak.unflatten(flat_pt, counts, axis=0)  # <-- graphed-debug points HERE
    return gak.sum(rebuilt, axis=1)


def run_faulty_chunk(partition: Any, resources: Any) -> Any:
    """Worker task (module-level, picklable): record + run the faulty analysis over THIS
    partition's real data. ``graphed_debug.run`` raises the source-mapped ``StageError``, which
    crosses the process boundary intact."""
    import awkward as ak
    import graphed_debug as gd
    from graphed import Session
    from graphed_awkward import AwkwardBackend, from_awkward

    raw = uproot.open(f"{partition.uri}:{partition.tree}").arrays(
        ["Jet_pt"], entry_start=partition.entry_start, entry_stop=partition.entry_stop
    )
    s = Session(AwkwardBackend())
    g = from_awkward(s, "events", ak.Array({"Jet_pt": raw.Jet_pt}))
    bad = faulty_q4(g)
    return gd.run(
        s, bad, opt_level=1,
        partition=f"{partition.uri}@{partition.entry_start}:{partition.entry_stop}",
    )


def _sum(a: Any, b: Any) -> Any:
    return a + b


def _zero() -> Any:
    return np.zeros(1)


def faulty_plan(files: list[str], chunksize: int = 2**14) -> Any:
    """The faulty analysis as a task graph over real partitions (for the process-pool demo)."""
    from graphed_core.execution import Plan, Task

    import benchmark

    parts = benchmark.entry_target_partitions(files, chunksize)
    return Plan(
        process=run_faulty_chunk, combine=_sum, empty=_zero,
        tasks=tuple(Task(i, p) for i, p in enumerate(parts)),
    )
