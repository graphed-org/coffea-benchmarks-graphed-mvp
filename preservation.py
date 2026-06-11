"""Checkpointing + analysis preservation for the ADL queries (M8/M9 over real benchmark data).

Two durability layers, demonstrated on the committed skim:

- **Checkpointing** (graphed-checkpoint): the q1 aggregation as a ``DurablePlan`` — the COMPILED
  query IR plus import-ref process/combine/empty — run through a content-addressed ``Store``.
  A crashed run resumes from committed partials alone, bit for bit; a finished store re-runs
  with everything skipped. All callables here are MODULE-LEVEL so a plan resolves them by import
  path on a machine with no analysis source files.
- **Preservation** (graphed-preserve): the q5 analysis captured as a self-contained
  content-addressed bundle (IR + datasets + histogram spec), ``inspect()``-able without
  executing and ``reproduce()``-able bit for bit. The preserved recording uses EXPLICIT
  kinematic formulas (the M9 interpreter evaluates through a bare awkward backend — vector
  behavior properties are not preserved; a documented improvement candidate).
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
    from graphed_core import DurablePlan, OpSpec

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


def record_q5(events: Any) -> tuple[Any, Any, Any]:
    """Record q5 (formula-based) over an in-memory events record: (session, value, weight)."""
    from graphed import Session
    from graphed_awkward import AwkwardBackend, from_awkward, gak

    s = Session(AwkwardBackend())
    g = from_awkward(s, "events", events)
    mu = g.Muon
    pair = gak.combinations(mu, 2, fields=["mu1", "mu2"])
    mass = _pair_mass(pair.mu1, pair.mu2)
    opposite = pair.mu1.charge != pair.mu2.charge
    good = gak.any((mass > 60.0) & (mass < 120.0) & opposite, axis=1)
    value = g.MET_pt[good]
    weight = gak.ones_like(value, dtype="float64")
    return s, value, weight


def preserve_q5(root: Any, skim_path: str) -> tuple[Any, np.ndarray]:
    """Build the q5 preservation bundle under ``root``; returns (bundle, build-time reference)."""
    import awkward as ak
    from graphed_preserve import build_bundle

    events = load_events(skim_path)
    session, value, weight = record_q5(events)
    vals = np.asarray(ak.Array(session.materialize(value)))
    reference = np.histogram(
        np.round(vals, 6), bins=Q5_HIST["bins"], range=(Q5_HIST["lo"], Q5_HIST["hi"])
    )[0]
    bundle = build_bundle(
        root,
        session=session,
        value=value,
        weight=weight,
        datasets={"events": events},
        payloads={},
        histogram=Q5_HIST,
    )
    return bundle, reference.astype(np.float64)
