# attempts — coffea-benchmarks-graphed-mvp (branch graphed-mvp)

## ADL-1 — the Q1-Q8 port (P1 of the reformulated plan) — 2026-06-11 (freeze-ADL-1)

- **Data**: data/Run2012B_SingleMu_50k.root — a 50k-event skim of the 16 GB benchmark file,
  read over xrootd (root://eospublic.cern.ch//eos/root-eos/benchmark/Run2012B_SingleMu.root via
  a conda env with the XRootD client; uproot's https handler is not served by eospublic) and
  written NanoAOD-style (mktree shared-counter TTree; this uproot fork defaults plain
  recreate-assignment to RNTuple). 3.7 MB, all ADL branches incl. Jet_btag.
- **Reference**: data/reference_counts.json — the ORIGINAL coffea processors run over the skim
  (scripts/make_reference.py, coffea 2026: NanoEventsFactory mode="eager";
  error_missing_event_ids demoted — the skim drops run/lumi/event; awkward-v1 `slot0/1` tuple
  fields patched to "0"/"1"; q8's events.MET.delta_phi(l3) cannot dispatch on a Muon/Electron
  UNION in modern vector — replaced with the identical explicit formula).
- **The port** (adl_graphed.py): per-query gak.zip with with_name="Momentum4D" (no schema
  layer), vector behaviors for kinematics, Δ-quantities as property-safe formulas (vector
  behavior METHODS with arguments are not recordable through the proxy — a known Phase-2 note),
  every query ends in a hist.graphed fill; run_query() aggregates via any R7 executor with the
  backend by import ref ("adl_graphed:make_backend").
- **Acceptance (tests/test_adl_queries.py, 12 tests)**: all NINE histograms (q6 has two) match
  the coffea reference BIT FOR BIT including flow, on the FIRST complete run; partitioning
  invariance (steps 1 vs 7 identical); process-pool aggregation identical (behaviors by import
  ref); recording determinism (byte-identical IR); projection truthfulness (q4's expression
  touches exactly {Jet_pt, MET_pt}; note: an External FILL node is opaque to projection by
  design — project the fill's input expression).
- **Notebook**: graphed-adl-benchmarks.ipynb (31 cells, EXECUTED, 0 errors) — mirrors the
  original coffea notebook: per-query source + plots, plus graphed-awkward exploration cells
  (forms, truthful projection px -> {pt, phi}, graphed_head peeking, compiled-IR stage counts).
- Earlier smoke-test scare recorded: q4 "5708 vs 5712" was h.sum() WITHOUT flow vs a
  flow-inclusive reference — four events with MET >= 200 GeV live in overflow; the acceptance
  comparison is flow-inclusive bin-by-bin. Also: installing coffea replaced the editable uproot
  fork with PyPI uproot (restored with --no-deps; coffea is NOT a CI dependency — the reference
  is committed JSON).

## ADL-1 iteration 1 — same-platform reference (CI q6 finding) — 2026-06-11

- CI (Linux) failed ONLY q6 vs the macOS-generated reference: libm ULP differences flip
  argmin's pick between near-equidistant trijet candidates -> a different candidate's pt ->
  a different bin. Bit-for-bit is a SAME-PLATFORM claim: CI now generates the coffea reference
  on its own platform from the committed skim (coffea installed for that step only); the
  committed JSON remains the macOS snapshot used by the notebook. The process-pool test now
  pins against the sequential run (the sharper claim: the pool changes nothing).
