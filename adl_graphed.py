"""The eight ADL benchmark queries on graphed — recorded once, executed partition by partition.

The porting idiom (no schema layer): each query zips exactly the collections it needs from the
NanoAOD branches with ``gak.zip(..., with_name="Momentum4D")`` and leans on vector behaviors for
kinematics; every query ends in a deferred ``hist.graphed`` fill whose plan any R7 executor
aggregates. Vector behaviors reach process workers by IMPORT REF (``adl_graphed:make_backend``)
— never by pickling the behavior dict.

Δ-quantities (delta_phi, delta_r) are written as explicit formulas.
"""

from __future__ import annotations

from typing import Any

import numpy as np

import hist.graphed as hg
from graphed_awkward import gak


def make_backend() -> Any:
    """Worker evaluation backend (import-ref target): vector behaviors registered."""
    import vector
    from graphed_awkward import AwkwardBackend

    vector.register_awkward()
    return AwkwardBackend(behavior=vector.backends.awkward.behavior)


def behavior() -> Any:
    import vector

    vector.register_awkward()
    return vector.backends.awkward.behavior


# ---- kinematic helpers (recorded ops; identical formulas in the eager reference) -----------------
def delta_phi(a: Any, b: Any) -> Any:
    return (a - b + np.pi) % (2 * np.pi) - np.pi


def delta_r(eta1: Any, phi1: Any, eta2: Any, phi2: Any) -> Any:
    return np.hypot(eta1 - eta2, delta_phi(phi1, phi2))


# ---- per-query collection zips (exactly the columns each query needs) -----------------------------
def muons(g: Any) -> Any:
    return gak.zip(
        {"pt": g.Muon_pt, "eta": g.Muon_eta, "phi": g.Muon_phi,
         "mass": g.Muon_mass, "charge": g.Muon_charge},
        with_name="Momentum4D",
    )


def electrons(g: Any) -> Any:
    return gak.zip(
        {"pt": g.Electron_pt, "eta": g.Electron_eta, "phi": g.Electron_phi,
         "mass": g.Electron_mass, "charge": g.Electron_charge},
        with_name="Momentum4D",
    )


def jets(g: Any, *, btag: bool = False) -> Any:
    fields = {"pt": g.Jet_pt, "eta": g.Jet_eta, "phi": g.Jet_phi, "mass": g.Jet_mass}
    if btag:
        fields["btag"] = g.Jet_btag
    return gak.zip(fields, with_name="Momentum4D")


# ---- the eight queries (each returns staged hist.graphed histograms) ------------------------------
def q1(g: Any) -> Any:
    """MET of all events."""
    return hg.Hist.new.Reg(100, 0, 200, name="met", label=r"$E_{T}^{miss}$ [GeV]").Double().fill(
        met=g.MET_pt
    )


def q2(g: Any) -> Any:
    """pT of all jets (ragged fills flatten)."""
    return hg.Hist.new.Reg(100, 0, 200, name="ptj", label=r"Jet $p_{T}$ [GeV]").Double().fill(
        ptj=g.Jet_pt
    )


def q3(g: Any) -> Any:
    """pT of jets with |eta| < 1."""
    sel = g.Jet_pt[abs(g.Jet_eta) < 1.0]
    return hg.Hist.new.Reg(100, 0, 200, name="ptj", label=r"Jet $p_{T}$ [GeV]").Double().fill(ptj=sel)


def q4(g: Any) -> Any:
    """MET of events with >= 2 jets above 40 GeV."""
    has2jets = gak.sum(g.Jet_pt > 40.0, axis=1) >= 2
    return hg.Hist.new.Reg(100, 0, 200, name="met", label=r"$E_{T}^{miss}$ [GeV]").Double().fill(
        met=g.MET_pt[has2jets]
    )


def q5(g: Any) -> Any:
    """MET of events with an opposite-charge dimuon pair with 60 < m < 120 GeV."""
    mu = muons(g)
    pair = gak.combinations(mu, 2, fields=["mu1", "mu2"])
    mass = (pair.mu1 + pair.mu2).mass
    opposite = pair.mu1.charge != pair.mu2.charge
    good = gak.any((mass > 60.0) & (mass < 120.0) & opposite, axis=1)
    return hg.Hist.new.Reg(100, 0, 200, name="met", label=r"$E_{T}^{miss}$ [GeV]").Double().fill(
        met=g.MET_pt[good]
    )


def q6(g: Any) -> dict[str, Any]:
    """The trijet closest to the top mass: its pT and its max b-tag.

    Jets are re-zipped into cartesian components (x, y, z, t) before summing, matching the
    reference implementation's four-vector arithmetic exactly."""
    p4j = jets(g, btag=True)
    jet = gak.zip(
        {"x": p4j.x, "y": p4j.y, "z": p4j.z, "t": p4j.t, "btag": p4j.btag},
        with_name="Momentum4D",
    )
    tri = gak.combinations(jet, 3, fields=["j1", "j2", "j3"])
    p4 = tri.j1 + tri.j2 + tri.j3
    best = gak.argmin(abs(p4.mass - 172.5), axis=1, keepdims=True)
    best_pt = gak.flatten(p4.pt[best])
    max_btag = gak.flatten(
        np.maximum(tri.j1.btag, np.maximum(tri.j2.btag, tri.j3.btag))[best]
    )
    h_pt = hg.Hist.new.Reg(100, 0, 200, name="pt3j", label=r"Trijet $p_{T}$ [GeV]").Double().fill(
        pt3j=best_pt
    )
    h_btag = hg.Hist.new.Reg(100, 0, 1, name="btag", label="Max jet b-tag score").Double().fill(
        btag=max_btag
    )
    return {"trijetpt": h_pt, "maxbtag": h_btag}


def q7(g: Any) -> Any:
    """Scalar sum of jet pT (jets > 30 GeV, not within dR 0.4 of any lepton > 10 GeV)."""
    jet = jets(g)
    good_jet_mask = jet.pt > 30.0
    leptons = gak.concatenate([muons(g), electrons(g)], axis=1)
    leptons = leptons[leptons.pt > 10.0]
    pair = gak.cartesian([jet, leptons], nested=True)
    dr = delta_r(pair["0"].eta, pair["0"].phi, pair["1"].eta, pair["1"].phi)
    isolated = gak.fill_none(gak.all(dr >= 0.4, axis=2), True)
    sum_pt = gak.sum(jet.pt[good_jet_mask & isolated], axis=1)
    return hg.Hist.new.Reg(100, 0, 200, name="sumjetpt", label=r"Jet $\sum p_{T}$ [GeV]").Double().fill(
        sumjetpt=sum_pt
    )


def q8(g: Any) -> Any:
    """Transverse mass of MET + the leading light lepton outside the best SFOS pair."""
    mu = muons(g)
    el = electrons(g)
    mu = gak.with_field(mu, -13 * mu.charge, "pdgId")
    el = gak.with_field(el, -11 * el.charge, "pdgId")
    lep = gak.concatenate([el, mu], axis=1)

    mask3 = gak.num(lep, axis=1) >= 3
    lep = lep[mask3]
    met_pt = g.MET_pt[mask3]
    met_phi = g.MET_phi[mask3]

    pair = gak.argcombinations(lep, 2, fields=["l1", "l2"])
    sfos = pair[lep[pair.l1].pdgId == -lep[pair.l2].pdgId]
    mass = (lep[sfos.l1] + lep[sfos.l2]).mass
    best = gak.singletons(gak.argmin(abs(mass - 91.2), axis=1))
    best_pair = sfos[best]

    has_pair = gak.num(best_pair, axis=1) > 0
    lep = lep[has_pair]
    met_pt = met_pt[has_pair]
    met_phi = met_phi[has_pair]
    chosen = gak.firsts(best_pair[has_pair])

    idx = gak.local_index(lep, axis=1)
    outside = (idx != chosen.l1) & (idx != chosen.l2)
    others = lep[outside]
    lead = others[gak.argmax(others.pt, axis=1, keepdims=True)]
    l3 = gak.firsts(lead)

    mt = np.sqrt(2.0 * l3.pt * met_pt * (1.0 - np.cos(delta_phi(met_phi, l3.phi))))
    return hg.Hist.new.Reg(100, 0, 200, name="mt", label=r"$\ell$-MET transverse mass [GeV]").Double().fill(
        mt=mt
    )


QUERIES = {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5, "q6": q6, "q7": q7, "q8": q8}


# ---- the runner (compile once; any R7 executor aggregates) ----------------------------------------
def run_query(name: str, where: str, *, steps_per_file: int = 5, executor: Any | None = None) -> dict[str, Any]:
    """Record query ``name`` over ``where`` (a ``path:tree`` string) and aggregate its
    histogram(s). Returns ``{histogram_name: concrete hist.Hist}``."""
    import uproot
    from graphed.write import SequentialRunner

    g = uproot.graphed(where, library="ak", behavior=behavior())
    staged = QUERIES[name](g)
    if not isinstance(staged, dict):
        staged = {name: staged}
    runner = executor if executor is not None else SequentialRunner()
    out = {}
    for label, h in staged.items():
        plan = h.plan(steps_per_file=steps_per_file, backend="adl_graphed:make_backend")
        out[label] = _wrap(runner.run(plan).value)
    return out


def _wrap(value: Any) -> Any:
    import hist as _h

    return _h.Hist(value)
