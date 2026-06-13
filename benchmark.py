"""The ADL benchmark harness (P2): entry-target partitioning, I/O metrics, one-pass queries.

Mirrors the original coffea harness's measurements — entries, chunks, bytes read, walltime,
us*core/evt, MB/s/core per (query x chunksize x workers) — on graphed's machinery:

- **entry-target partitioning**: the sweep varies ABSOLUTE chunk sizes (2^13 ... 2^21 events);
  partitions are built from uproot metadata entry counts (the same metadata read the coffea
  Runner does) and handed to ``hist.graphed``'s ``plan(partitions=...)``.
- **bytes read** come from uproot's own accounting (``file.source.num_requested_bytes``),
  measured around each partition's branch reads in the worker — reads are PROJECTED to the
  branches the query's graph actually accesses, so the number is the query's real I/O.
- a query is ONE compiled graph (q6's two histograms ride one multi-output compile and a single
  pass over the data).

The full 16 GB Run2012B_SingleMu.root sweep is LOCAL-ONLY (CI runners cannot hold the file);
CI exercises this harness on the committed 50k skim.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import uproot

import adl_graphed as adl


def entry_target_partitions(files: list[str], chunksize: int) -> tuple[Any, ...]:
    """Eager partitions of ~``chunksize`` entries per task, tiling each ``path:tree`` exactly
    (metadata entry counts only — no branch data is read here)."""
    from graphed_core import Partition

    out = []
    for where in files:
        path, _, tree = where.rpartition(":")
        n = uproot.open(where).num_entries
        out.extend(
            Partition(path, tree, lo, min(lo + chunksize, n))
            for lo in range(0, n, chunksize)
        )
    return tuple(out)


@dataclass(frozen=True)
class _Partial:
    """One partition's contribution: the per-fill histograms plus the I/O accounting."""

    hists: tuple[Any, ...]
    bytesread: int
    entries: int


@dataclass(frozen=True)
class _BenchFill:
    """The worker task (picklable; module-level): read EXACTLY the projected branches with byte
    accounting, evaluate every fill of the query through the ONE compiled graph, return partials."""

    ir: bytes
    source_name: str
    columns: tuple[str, ...]
    specs: tuple[str, ...]
    evaluators: tuple[tuple[str, Any], ...]
    backend_ref: str

    def __call__(self, partition: Any, resources: Any) -> _Partial:
        from graphed import evaluate_ir
        from graphed_histogram.boost import _resolve_backend

        directory = resources.open_once(partition.uri, uproot.open)
        before = directory.file.source.num_requested_bytes
        tree = directory[partition.tree]
        chunk = uproot.read_graphed_partition(partition, list(self.columns), tree=tree)
        nbytes = directory.file.source.num_requested_bytes - before
        fills = evaluate_ir(
            self.ir,
            _resolve_backend(self.backend_ref),
            {self.source_name: chunk},
            externals=dict(self.evaluators),
        )
        return _Partial(hists=tuple(fills), bytesread=int(nbytes), entries=len(chunk))


def _combine(a: _Partial, b: _Partial) -> _Partial:
    return _Partial(
        hists=tuple(x + y for x, y in zip(a.hists, b.hists)),
        bytesread=a.bytesread + b.bytesread,
        entries=a.entries + b.entries,
    )


@dataclass(frozen=True)
class _Empty:
    specs: tuple[str, ...]

    def __call__(self) -> _Partial:
        from graphed_histogram import zero_of

        return _Partial(
            hists=tuple(zero_of(s) for s in self.specs), bytesread=0, entries=0
        )


def build_plan(qname: str, files: list[str], chunksize: int) -> tuple[Any, list[str]]:
    """Record query ``qname``, compile ALL its fills into ONE graph, and build the measured plan
    over entry-target partitions. Returns ``(plan, histogram_labels)``."""
    return _build_plan_for(([qname], files, chunksize))


def build_combined_plan(
    files: list[str], chunksize: int, qnames: "list[str] | None" = None
) -> tuple[Any, list[str]]:
    """EVERY query's fills compiled into ONE graph and ONE plan — a single pass over the data
    evaluates all of them per partition. This is both the efficient way to run the full suite
    and the FAIR way to time it: each runner opens each file exactly once."""
    return _build_plan_for((list(qnames or adl.QUERIES), files, chunksize))


def _build_plan_for(spec: tuple[list[str], list[str], int]) -> tuple[Any, list[str]]:
    qnames, files, chunksize = spec
    from graphed import compile_ir
    from graphed_core.execution import Plan, Task
    from graphed_histogram import spec_of
    from uproot._graphed import _evaluation_columns

    g = uproot.graphed(files, library="ak", behavior=adl.behavior())
    staged: dict[str, Any] = {}
    for qname in qnames:
        one = adl.QUERIES[qname](g)
        if not isinstance(one, dict):
            one = {qname: one}
        for label, h in one.items():
            staged[
                label if label == qname or len(qnames) == 1 else f"{qname}/{label}"
            ] = h
    labels = list(staged)
    fill_nodes = [h.fill_nodes()[0] for h in staged.values()]
    session = g.session

    ((nid, source),) = session.sources().items()
    columns: set[str] = set()
    for node in fill_nodes:
        columns.update(_evaluation_columns(node, nid, source._common_keys))
    compiled = compile_ir(session, *fill_nodes)

    evaluators: dict[str, Any] = {}
    for h in staged.values():
        evaluators.update(h.evaluators())
    process = _BenchFill(
        ir=bytes(compiled.ir),
        source_name=session.source_name(nid),
        columns=tuple(k for k in source._common_keys if k in columns),
        specs=tuple(spec_of(h) for h in staged.values()),
        evaluators=tuple(evaluators.items()),
        backend_ref="adl_graphed:make_backend",
    )
    partitions = entry_target_partitions(files, chunksize)
    tasks = tuple(Task(i, p) for i, p in enumerate(partitions))
    plan = Plan(
        process=process, combine=_combine, empty=_Empty(process.specs), tasks=tasks
    )
    return plan, labels


def run_benchmark(
    qname: str,
    files: list[str],
    *,
    chunksize: int = 2**17,
    executor: Any | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """One measured benchmark point. ``executor=None`` runs the sequential reference runner;
    pass a (preferably persistent) executor for parallel points — its spawn cost then sits
    outside the measured loop, matching how the original harness reuses its pool."""
    from graphed_core.execution import SequentialRunner

    tic = time.perf_counter()
    plan, labels = build_plan(qname, files, chunksize)
    runner = executor if executor is not None else SequentialRunner()
    result = runner.run(plan)
    walltime = time.perf_counter() - tic
    partial = result.value
    import hist as _h

    entries = partial.entries
    return {
        "query": qname,
        "tgt_chunksize": chunksize,
        "chunks": result.n_partitions,
        "entries": entries,
        "bytesread": partial.bytesread,
        "walltime": walltime,
        "workers": workers,
        "us*core/evt": walltime * 1e6 * workers / entries if entries else float("nan"),
        "b/evt": partial.bytesread / entries if entries else float("nan"),
        "MB/s/core": partial.bytesread * 1e-6 / workers / walltime,
        "hists": {label: _h.Hist(h) for label, h in zip(labels, partial.hists)},
    }
