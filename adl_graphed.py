"""The eight ADL benchmark queries on coffea NanoEvents in graphed mode.

Each query is the original coffea processor's ``process`` body (``coffea-adl-benchmarks.py``) in
the spelling a deferred array needs, as with dask: ``gak`` for ``ak``, ``hist.graphed`` for
``hist``, and ``gak.with_field`` where the original assigns a field. Nothing is read until a
plan runs.
"""

from __future__ import annotations

import warnings
from typing import Any

import graphed_histogram as gh
import hist
import hist.graphed as hg
import numpy as np
from coffea.nanoevents import NanoAODSchema, NanoEventsFactory
from graphed.awkward import gak
from graphed.core.execution import SequentialRunner

NanoAODSchema.warn_missing_crossrefs = False  # the opendata files lack some optional columns
NanoAODSchema.error_missing_event_ids = False  # the committed skim drops run/lumi/event
warnings.filterwarnings("ignore", message="Missing event_ids", category=RuntimeWarning)


def events(files: Any, **uproot_options: Any) -> Any:
    """Deferred NanoEvents over a path, a list of paths, or a ``{path: tree}`` dict."""
    if isinstance(files, str):
        files = [files]
    if not isinstance(files, dict):
        files = dict.fromkeys(files, "Events")
    return NanoEventsFactory.from_root(
        files, schemaclass=NanoAODSchema, mode="graphed", uproot_options=uproot_options
    ).events()


def q1(events):
    """MET of all events."""
    return hg.Hist.new.Reg(100, 0, 200, name="met", label="$E_{T}^{miss}$ [GeV]").Double().fill(events.MET.pt)


def q2(events):
    """pT of all jets."""
    return (
        hg.Hist.new.Reg(100, 0, 200, name="ptj", label="Jet $p_{T}$ [GeV]")
        .Double()
        .fill(gak.flatten(events.Jet.pt))
    )


def q3(events):
    """pT of jets with |eta| < 1."""
    return (
        hg.Hist.new.Reg(100, 0, 200, name="ptj", label="Jet $p_{T}$ [GeV]")
        .Double()
        .fill(gak.flatten(events.Jet[abs(events.Jet.eta) < 1].pt))
    )


def q4(events):
    """MET of events with at least two jets above 40 GeV."""
    has2jets = gak.sum(events.Jet.pt > 40, axis=1) >= 2
    return (
        hg.Hist.new.Reg(100, 0, 200, name="met", label="$E_{T}^{miss}$ [GeV]")
        .Double()
        .fill(events[has2jets].MET.pt)
    )


def q5(events):
    """MET of events with an opposite-charge dimuon pair of mass 60-120 GeV."""
    mupair = gak.combinations(events.Muon, 2, fields=["mu1", "mu2"])
    pairmass = (mupair.mu1 + mupair.mu2).mass
    goodevent = gak.any(
        (pairmass > 60) & (pairmass < 120) & (mupair.mu1.charge == -mupair.mu2.charge),
        axis=1,
    )
    return (
        hg.Hist.new.Reg(100, 0, 200, name="met", label="$E_{T}^{miss}$ [GeV]")
        .Double()
        .fill(events[goodevent].MET.pt)
    )


def q6(events):
    """pT of the trijet closest to the top mass, and the maximum b-tag among its jets."""
    jets = gak.zip(
        {k: getattr(events.Jet, k) for k in ["x", "y", "z", "t", "btag"]},
        with_name="LorentzVector",
    )
    trijet = gak.combinations(jets, 3, fields=["j1", "j2", "j3"])
    trijet = gak.with_field(trijet, trijet.j1 + trijet.j2 + trijet.j3, "p4")
    trijet = gak.flatten(trijet[gak.singletons(gak.argmin(abs(trijet.p4.mass - 172.5), axis=1))])
    max_btag = np.maximum(trijet.j1.btag, np.maximum(trijet.j2.btag, trijet.j3.btag))
    return {
        "trijetpt": hg.Hist.new.Reg(100, 0, 200, name="pt3j", label="Trijet $p_{T}$ [GeV]")
        .Double()
        .fill(trijet.p4.pt),
        "maxbtag": hg.Hist.new.Reg(100, 0, 1, name="btag", label="Max jet b-tag score")
        .Double()
        .fill(max_btag),
    }


def q7(events):
    """Scalar sum of the pT of jets above 30 GeV not within dR 0.4 of a lepton above 10 GeV."""
    cleanjets = events.Jet[
        gak.all(events.Jet.metric_table(events.Muon[events.Muon.pt > 10]) >= 0.4, axis=2)
        & gak.all(events.Jet.metric_table(events.Electron[events.Electron.pt > 10]) >= 0.4, axis=2)
        & (events.Jet.pt > 30)
    ]
    return (
        hg.Hist.new.Reg(100, 0, 200, name="sumjetpt", label=r"Jet $\sum p_{T}$ [GeV]")
        .Double()
        .fill(gak.sum(cleanjets.pt, axis=1))
    )


def q8(events):
    """Transverse mass of MET and the leading lepton outside the SFOS pair closest to the Z."""

    # Leptons as one record type (concatenating Electron with Muon makes a union, which is slow
    # and has no delta_phi) kept beside MET: a field assigned onto `events` makes every read
    # also fetch other collections' counters.
    def lepton(collection, pdg):
        fields = {k: getattr(collection, k) for k in ["pt", "eta", "phi", "mass", "charge"]}
        return gak.zip({**fields, "pdgId": pdg * collection.charge}, with_name="PtEtaPhiMCandidate")

    leptons = gak.concatenate([lepton(events.Electron, -11), lepton(events.Muon, -13)], axis=1)
    has3 = gak.num(leptons) >= 3
    leptons, met = leptons[has3], events.MET[has3]

    pair = gak.argcombinations(leptons, 2, fields=["l1", "l2"])
    pair = pair[(leptons[pair.l1].pdgId == -leptons[pair.l2].pdgId)]
    pair = pair[gak.singletons(gak.argmin(abs((leptons[pair.l1] + leptons[pair.l2]).mass - 91.2), axis=1))]
    haspair = gak.num(pair) > 0
    leptons, met, pair = leptons[haspair], met[haspair], pair[haspair][:, 0]

    l3 = gak.local_index(leptons)
    l3 = l3[(l3 != pair.l1) & (l3 != pair.l2)]
    l3 = l3[gak.argmax(leptons[l3].pt, axis=1, keepdims=True)]
    l3 = leptons[l3][:, 0]

    mt = np.sqrt(2 * l3.pt * met.pt * (1 - np.cos(met.delta_phi(l3))))
    return (
        hg.Hist.new.Reg(100, 0, 200, name="mt", label=r"$\ell$-MET transverse mass [GeV]").Double().fill(mt)
    )


QUERIES = {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5, "q6": q6, "q7": q7, "q8": q8}


def query_plan(
    names: Any, files: Any, *, steps_per_file: int = 1, partitions: Any = None, **uproot_options: Any
) -> Any:
    """ONE plan for every histogram of the named queries (a name or a list): one pass over the data."""
    ev = events(files, **uproot_options)
    staged = {}
    for name in [names] if isinstance(names, str) else names:
        out = QUERIES[name](ev)
        staged.update(out if isinstance(out, dict) else {name: out})
    return gh.plan(staged, steps_per_file=steps_per_file, partitions=partitions)


def run_query(name: str, files: Any, *, steps_per_file: int = 1, executor: Any = None) -> dict[str, Any]:
    """Run query ``name`` and return ``{histogram label: hist.Hist}``."""
    runner = executor if executor is not None else SequentialRunner()
    value = runner.run(query_plan(name, files, steps_per_file=steps_per_file)).value
    return {label: hist.Hist(h) for label, h in value.items()}
