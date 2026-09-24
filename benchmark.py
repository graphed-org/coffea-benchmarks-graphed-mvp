"""One measured ADL benchmark point, the columns of the original coffea harness.

Partitions are uproot's entry-target chunks (``graphed_partitions(step_size=...)``) and the plan is
``adl_graphed.query_plan``. Bytes are the compressed size of the branches the plan reads, from basket
metadata: graphed plans do not count the bytes a read requests.
"""

from __future__ import annotations

import time
from typing import Any

import hist
import uproot
from graphed.core.execution import SequentialRunner
from uproot._graphed import graphed_partitions

import adl_graphed as adl


def read_bytes(files: list[str], columns: Any) -> int:
    """Compressed bytes of ``columns`` over whole ``files`` (every partition tiles its file)."""
    return sum(uproot.open(f)["Events"][c].compressed_bytes for f in files for c in columns)


def run_benchmark(
    qname: str, files: list[str], *, chunksize: int = 2**17, executor: Any = None, workers: int = 1
) -> dict[str, Any]:
    """Build, run and measure query ``qname`` over ``files`` in ``chunksize``-entry partitions;
    ``executor=None`` runs sequentially."""
    tic = time.perf_counter()
    partitions = graphed_partitions(dict.fromkeys(files, "Events"), step_size=chunksize)
    plan = adl.query_plan(qname, files, partitions=partitions)
    result = (executor if executor is not None else SequentialRunner()).run(plan)
    walltime = time.perf_counter() - tic
    entries = sum(p.entry_stop - p.entry_start for p in partitions)
    nbytes = read_bytes(files, plan.process.columns)
    return {
        "query": qname,
        "tgt_chunksize": chunksize,
        "chunks": result.n_partitions,
        "entries": entries,
        "bytesread": nbytes,
        "walltime": walltime,
        "workers": workers,
        "us*core/evt": walltime * 1e6 * workers / entries,
        "b/evt": nbytes / entries,
        "MB/s/core": nbytes * 1e-6 / workers / walltime,
        "hists": {label: hist.Hist(h) for label, h in result.value.items()},
    }
