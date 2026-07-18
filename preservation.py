"""Checkpointing + analysis preservation for the ADL queries (M8/M9 over real benchmark data).

Two durability layers, demonstrated on the committed skim:

- **Checkpointing** (graphed-checkpoint): the q1 aggregation as a ``DurablePlan`` — the COMPILED
  query IR plus import-ref process/combine/empty — run through a content-addressed ``Store``.
  A crashed run resumes from committed partials alone, bit for bit; a finished store re-runs
  with everything skipped. All callables here are MODULE-LEVEL so a plan resolves them by import
  path on a machine with no analysis source files.
- **Preservation** (graphed-preserve): the q5 analysis captured as a self-contained
  content-addressed bundle whose preserved IR ENDS AT THE HISTOGRAM FILL — the fill is an
  External node and its canonical axes/storage spec IS its content-addressed payload
  (synthesized at build time from the node's own params; graphed-preserve M25). ``inspect()``
  renders it without executing; ``reproduce()`` returns the histogram itself, bit for bit.
  The preserved recording uses EXPLICIT kinematic formulas (the M9 interpreter evaluates
  through a bare awkward backend — vector behavior properties are not preserved; a documented
  improvement candidate).
"""

from __future__ import annotations

from typing import Any

import numpy as np

import uproot

Q1_BINS, Q1_LO, Q1_HI = 100, 0.0, 200.0


# ---- checkpointing glue (module-level: DurablePlan resolves these by import ref) -----------------
def q1_chunk(partition: Any, resources: Any) -> np.ndarray:
    """One partition's q1 contribution: read THIS slice's MET_pt from the ROOT file, histogram."""
    tree = uproot.open(f"{partition.uri}:{partition.tree}")
    met = tree["MET_pt"].array(entry_start=partition.entry_start, entry_stop=partition.entry_stop)
    return np.histogram(np.asarray(met), bins=Q1_BINS, range=(Q1_LO, Q1_HI))[0].astype(np.int64)


def hist_add(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a + b


def hist_empty() -> np.ndarray:
    return np.zeros(Q1_BINS, dtype=np.int64)


def durable_q1_plan(files: list[str], chunksize: int = 2**13) -> Any:
    """q1 as a durable, content-addressed plan: the COMPILED query IR is the plan's identity."""
    from graphed import compile_ir
    from graphed.core import DurablePlan, OpSpec

    import adl_graphed as adl
    import benchmark

    g = uproot.graphed(files, library="ak", behavior=adl.behavior())
    (fill,) = adl.QUERIES["q1"](g).fill_nodes()
    compiled = compile_ir(g.session, fill)
    return DurablePlan(
        ir=bytes(compiled.ir),
        process=OpSpec.from_ref("preservation:q1_chunk"),
        combine=OpSpec.from_ref("preservation:hist_add"),
        empty=OpSpec.from_ref("preservation:hist_empty"),
        partitions=benchmark.entry_target_partitions(files, chunksize),
        read_columns=("MET_pt",),
    )


# ---- preservation glue ----------------------------------------------------------------------------
Q5_HIST = {"name": "met", "bins": 100, "lo": 0.0, "hi": 200.0}


def _pair_mass(a: Any, b: Any) -> Any:
    """Explicit dimuon invariant mass (preserved analyses avoid behavior properties)."""
    px = a.pt * np.cos(a.phi) + b.pt * np.cos(b.phi)
    py = a.pt * np.sin(a.phi) + b.pt * np.sin(b.phi)
    pz = a.pt * np.sinh(a.eta) + b.pt * np.sinh(b.eta)
    e = np.sqrt((a.pt * np.cosh(a.eta)) ** 2 + a.mass**2) + np.sqrt(
        (b.pt * np.cosh(b.eta)) ** 2 + b.mass**2
    )
    return np.sqrt(np.maximum(e**2 - (px**2 + py**2 + pz**2), 0.0))


def load_events(skim_path: str) -> Any:
    """The skim's q5 inputs as ONE in-memory awkward record (what the bundle content-addresses)."""
    import awkward as ak

    raw = uproot.open(skim_path + ":Events").arrays(
        ["Muon_pt", "Muon_eta", "Muon_phi", "Muon_mass", "Muon_charge", "MET_pt"]
    )
    return ak.Array(
        {
            "Muon": ak.zip(
                {
                    "pt": raw.Muon_pt,
                    "eta": raw.Muon_eta,
                    "phi": raw.Muon_phi,
                    "mass": raw.Muon_mass,
                    "charge": raw.Muon_charge,
                }
            ),
            "MET_pt": raw.MET_pt,
        }
    )


def record_q5(events: Any) -> tuple[Any, Any]:
    """Record q5 (formula-based) over an in-memory events record, ENDING AT a histogram fill:
    (session, fill_node). The fill is the analysis terminal — no value/weight/spec triple."""
    import boost_histogram as bh
    import graphed_histogram as gh
    from graphed import Session
    from graphed.awkward import AwkwardBackend, from_awkward, gak

    s = Session(AwkwardBackend())
    g = from_awkward(s, "events", events)
    mu = g.Muon
    pair = gak.combinations(mu, 2, fields=["mu1", "mu2"])
    mass = _pair_mass(pair.mu1, pair.mu2)
    opposite = pair.mu1.charge != pair.mu2.charge
    good = gak.any((mass > 60.0) & (mass < 120.0) & opposite, axis=1)
    h = gh.boost.Histogram(
        bh.axis.Regular(Q5_HIST["bins"], Q5_HIST["lo"], Q5_HIST["hi"]), storage=bh.storage.Double()
    )
    h.fill(g.MET_pt[good])
    return s, h.fill_nodes()[0]


def preserve_q5(root: Any, skim_path: str) -> tuple[Any, Any]:
    """Build the q5 preservation bundle under ``root``; returns (bundle, build-time reference
    histogram). The HISTOGRAM IS PART OF THE PAYLOAD: the fill node's canonical spec is its
    content-addressed payload, synthesized at build — payloads={} and no histogram= spec."""
    from graphed.preserve import build_bundle

    events = load_events(skim_path)
    session, fill = record_q5(events)
    reference = session.materialize(fill)  # the eager twin: a filled boost histogram
    bundle = build_bundle(root, session=session, value=fill, datasets={"events": events}, payloads={})
    return bundle, reference


# ---- re-running the PRESERVED analysis: optimize, re-target, parallelize --------------------------
def optimized_ir(bundle: Any) -> tuple[bytes, dict[str, Any]]:
    """The bundle's IR, REDUCED for execution. The bundle deliberately preserves opt_level=0
    (auditable, 1:1 with the user's ops, no stage fusion); a re-run reduces it first — DCE + CSE +
    equality-saturation stage fusion — and the returned stats make the collapse visible."""
    from graphed.core import GraphStore

    raw = bundle.store.get(bundle.manifest["analysis"]["ir"])
    assert raw is not None, "bundle IR missing from its store"
    g = GraphStore.deserialize(raw)
    reduced, report = g.reduce()  # the preserved output marks ride in the bytes
    preserved_kinds = sorted({n["kind"] for n in g.nodes()})
    stats = {
        "preserved_nodes": g.node_count(),
        "preserved_kinds": preserved_kinds,
        "reduced_nodes": reduced.node_count(),
        "reduced_kinds": sorted({n["kind"] for n in reduced.nodes()}),
        "stage_members": [n.get("n_members", 0) for n in reduced.nodes() if n["kind"] == "stage"],
        "report": report,
    }
    return bytes(reduced.serialize()), stats


def _events_slice(partition: Any) -> Any:
    """Read ONE partition's q5 inputs from a ROOT file into the preserved record shape."""
    import awkward as ak

    raw = uproot.open(f"{partition.uri}:{partition.tree}").arrays(
        ["Muon_pt", "Muon_eta", "Muon_phi", "Muon_mass", "Muon_charge", "MET_pt"],
        entry_start=partition.entry_start,
        entry_stop=partition.entry_stop,
    )
    return ak.Array(
        {
            "Muon": ak.zip(
                {
                    "pt": raw.Muon_pt,
                    "eta": raw.Muon_eta,
                    "phi": raw.Muon_phi,
                    "mass": raw.Muon_mass,
                    "charge": raw.Muon_charge,
                }
            ),
            "MET_pt": raw.MET_pt,
        }
    )


from dataclasses import dataclass as _dataclass  # noqa: E402


@_dataclass(frozen=True)
class _RetargetFill:
    """Worker task (picklable): evaluate the REDUCED preserved IR — which ENDS AT the histogram
    fill — over one partition of a NEW input file. Each chunk yields a filled histogram."""

    ir: bytes
    spec: str

    def __call__(self, partition: Any, resources: Any) -> Any:
        from graphed import evaluate_ir
        from graphed_histogram.boost import FillEvaluator

        chunk = _events_slice(partition)
        chash = __import__("graphed_histogram").content_hash(self.spec)
        evaluator = FillEvaluator(spec=self.spec, n_axes=1, has_weight=False, has_sample=False)
        (filled,) = evaluate_ir(
            self.ir, _bare_backend(), {"events": chunk}, externals={chash: evaluator}
        )
        return filled


def _bare_backend() -> Any:
    from graphed.awkward import AwkwardBackend

    return AwkwardBackend()


@_dataclass(frozen=True)
class _ZeroOf:
    spec: str

    def __call__(self) -> Any:
        import graphed_histogram as gh

        return gh.zero_of(self.spec)


def _hist_sum(a: Any, b: Any) -> Any:
    return a + b


def rerun_preserved(
    bundle: Any, files: list[str], *, executor: Any = None, chunksize: int = 2**13
) -> tuple[Any, dict[str, Any]]:
    """Re-target the preserved analysis at NEW input files and run its OPTIMIZED graph partition
    by partition through any R7 executor. Returns (the aggregated histogram, optimization stats)."""
    from graphed.core.execution import SequentialRunner
    from graphed.core.execution import Plan, Task

    import benchmark

    ir, stats = optimized_ir(bundle)
    entry = next(e for e in bundle.manifest["externals"] if e["kind"] == "histogram")
    spec = bundle.store.get(entry["store"]).decode()  # the preserved PAYLOAD: the canonical spec
    process = _RetargetFill(ir=ir, spec=spec)
    parts = benchmark.entry_target_partitions(files, chunksize)
    plan = Plan(
        process=process, combine=_hist_sum, empty=_ZeroOf(spec),
        tasks=tuple(Task(i, p) for i, p in enumerate(parts)),
    )
    runner = executor if executor is not None else SequentialRunner()
    return runner.run(plan).value, stats
