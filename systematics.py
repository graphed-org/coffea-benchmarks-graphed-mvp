"""Self-contained correctionlib payloads for the notebook's Q6 systematics demo.

These two :class:`correctionlib.schemav2.CorrectionSet`\\ s stand in for the real POG JSONs a
production analysis would read from ``jsonPOG-integration`` — hand-built so the notebook is
reproducible on a clean machine with no external download, but shaped and evaluated **exactly** like
the real ones:

* **JES** — ``JES_Total`` mirrors ``Summer19UL16_V7_MC_Total_AK4PFchs``: a 2-D ``(JetEta, JetPt)``
  multibinning returning a *fractional* uncertainty ``delta``; the analysis shifts the whole jet
  four-vector (and MET) by ``pt -> pt * (1 +/- delta)``. Signed ``JetEta`` (the real Total source is
  eta-signed).
* **b-tag** — ``deepJet_shape`` mirrors the DeepJet *shape-calibration* method
  (``btagging.json.gz``): ``evaluate(systematic, flavor, abseta, pt, discriminant)`` returns a
  per-jet scale factor; the per-event weight is the product over the event's jets. Systematics are
  the POG's ``central`` and the ``up/down`` heavy-/light-flavour components. ``abseta`` (unsigned),
  as in the real file.

Two demo-only simplifications, called out honestly:

1. The 50k skim carries no ``Jet_hadronFlavour`` (MC truth), so hadron flavour is PROXIED from the
   b-tag discriminant (``Jet_btag > 0.7 -> b``); a real analysis reads the truth branch.
2. The shape method is norm-preserving: production renormalises the per-jet SFs so each systematic
   keeps the nominal yield. That second pass is omitted here so the up/down universes show a visible
   yield band — the point being demonstrated.

Magnitudes are deliberately realistic (JES ~1-6%, b-tag components ~2-8%) so the variations read as a
plausible band rather than a toy wiggle.
"""

from __future__ import annotations

import correctionlib.schemav2 as cs


def _centers(edges: list[float]) -> list[float]:
    return [(edges[i] + edges[i + 1]) / 2 for i in range(len(edges) - 1)]


def _dump(cset: cs.CorrectionSet) -> bytes:
    try:
        return cset.json().encode()  # correctionlib/pydantic v1
    except Exception:
        return cset.model_dump_json().encode()  # pydantic v2


def jes_correctionset() -> bytes:
    """``JES_Total.evaluate(JetEta, JetPt) -> fractional uncertainty`` (Summer19UL16_V7 shape)."""
    eta = [-5.0, -3.0, -2.5, -1.3, 0.0, 1.3, 2.5, 3.0, 5.0]
    pt = [15, 25, 40, 70, 120, 250, 1000]

    def delta(e: float, p: float) -> float:
        # grows toward the forward region and at low pT, like the real Total source
        return 0.012 + 0.035 * min(abs(e) / 2.5, 2.0) + 0.02 * (30.0 / max(p, 30.0))

    content = [round(delta(e, p), 5) for e in _centers(eta) for p in _centers(pt)]
    corr = cs.Correction(
        name="JES_Total",
        version=1,
        inputs=[cs.Variable(name="JetEta", type="real"), cs.Variable(name="JetPt", type="real")],
        output=cs.Variable(name="delta", type="real"),
        data=cs.MultiBinning(
            nodetype="multibinning",
            inputs=["JetEta", "JetPt"],
            edges=[eta, pt],
            content=content,
            flow="clamp",
        ),
    )
    return _dump(cs.CorrectionSet(schema_version=2, corrections=[corr]))


def btag_correctionset() -> bytes:
    """``deepJet_shape.evaluate(systematic, flavor, abseta, pt, discriminant) -> per-jet SF``."""
    flavours = [0, 4, 5]  # udsg, c, b
    abseta = [0.0, 0.8, 1.6, 2.5]
    pt = [20, 40, 70, 150, 1000]
    disc = [0.0, 0.5, 1.0]

    def base(flavour: int, a: float, x: float) -> float:
        return 0.98 + 0.02 * x - 0.01 * min(a, 2.5) + (0.02 if flavour == 5 else 0.0)

    def sf(flavour: int, a: float, x: float, systematic: str) -> float:
        v = base(flavour, a, x)
        if systematic == "up_hf" and flavour == 5:
            v *= 1.05
        if systematic == "down_hf" and flavour == 5:
            v *= 0.95
        if systematic == "up_lf" and flavour == 0:
            v *= 1.08
        if systematic == "down_lf" and flavour == 0:
            v *= 0.92
        return v

    def binning(systematic: str, flavour: int) -> cs.MultiBinning:
        content = [
            round(sf(flavour, a, x, systematic), 5)
            for a in _centers(abseta)
            for _p in _centers(pt)
            for x in _centers(disc)
        ]
        return cs.MultiBinning(
            nodetype="multibinning",
            inputs=["abseta", "pt", "discriminant"],
            edges=[abseta, pt, disc],
            content=content,
            flow="clamp",
        )

    systematics = ["central", "up_hf", "down_hf", "up_lf", "down_lf"]
    data = cs.Category(
        nodetype="category",
        input="systematic",
        content=[
            cs.CategoryItem(
                key=s,
                value=cs.Category(
                    nodetype="category",
                    input="flavor",
                    content=[cs.CategoryItem(key=f, value=binning(s, f)) for f in flavours],
                ),
            )
            for s in systematics
        ],
    )
    corr = cs.Correction(
        name="deepJet_shape",
        version=1,
        inputs=[
            cs.Variable(name="systematic", type="string"),
            cs.Variable(name="flavor", type="int"),
            cs.Variable(name="abseta", type="real"),
            cs.Variable(name="pt", type="real"),
            cs.Variable(name="discriminant", type="real"),
        ],
        output=cs.Variable(name="weight", type="real"),
        data=data,
    )
    return _dump(cs.CorrectionSet(schema_version=2, corrections=[corr]))
