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

## ADL-1 iteration 2 — q6 coordinate-system fidelity (the second CI finding) — 2026-06-11

- With a SAME-PLATFORM reference, q6 still differed on Linux (and only there): the port summed
  four-vectors in pt/eta/phi/mass coordinates while upstream deliberately zips CARTESIAN
  x/y/z/t components first. Different conversion order -> ULP-level differences -> flipped
  argmin picks between near-equidistant trijet candidates (macOS agreement was luck of the
  rounding). q6 now mirrors upstream exactly: re-zip {x, y, z, t, btag} (vector-derived — modern
  coffea's LorentzVector methods ARE vector's) before combining. Lesson for the record:
  bit-for-bit ports must mirror the reference's COORDINATE SYSTEM and operation order, not just
  its mathematics.

## ADL-1 iteration 3 — the parallel tier + the speedup demo — 2026-06-11

- USER: parallel processing with ProcessExecutor everywhere; approximate agreement acceptable
  for parallel (the exact bit-for-bit pins stay on the SequentialRunner tier); the notebook's
  primary plots from a >=2-core ProcessExecutor, showing the speedup.
- tests: every query through ProcessExecutor(max_workers=2) with np.allclose vs the reference
  (8 new tests; 20 total green).
- FINDING en route: a fresh import-heavy pool per run() made the eight queries 3x SLOWER
  parallel than sequential on the 50k skim — fixed upstream in graphed-exec-local with the
  opt-in persistent=True pool (frozen-tested there; 0f4d44a/7c2286b).
- notebook: ONE ProcessExecutor(max_workers=4, persistent=True) drives every query plot;
  the speedup section times all eight queries sequential vs pool on the skim AND on an 8x
  replicated dataset, with a bar chart — executed outputs: 2.43x (50k) and 2.94x (400k).

## ADL-2 — the P2 benchmark harness — 2026-06-11 (freeze-ADL-2)

- USER: continue with P2; the full 16 GB runs are LOCAL-ONLY (CI runners cannot hold the file).
- graphed-histogram gained plan(partitions=) (its M23 iteration 4; an assertion-less edit
  initially pushed the test without the implementation — caught and fixed in 50aea1a; lesson:
  assert every replace anchor).
- benchmark.py: entry-target partitioning from uproot metadata entry counts (the sweep varies
  ABSOLUTE chunk sizes); _BenchFill measures bytes around the PROJECTED branch reads via
  uproot's file.source.num_requested_bytes (q1 reads 0.73 MB of the 3.7 MB skim — MET only —
  vs q5's 5.1 MB: the projection is visible in the I/O numbers); one compiled graph per query
  (q6's two histograms ride one multi-output compile, a single pass); run_benchmark reports the
  upstream metric set (entries, chunks, bytesread, walltime, us*core/evt, b/evt, MB/s/core).
- scripts/benchmark_sweep.py mirrors the upstream __main__ grid driver (persistent pools for
  parallel points; pandas optional with a csv fallback).
- tests/test_benchmark_harness.py (5, CI-safe on the skim): exact tiling; metric sanity +
  reference agreement; PROJECTION SHRINKS BYTES (q1 < q7/3); q6 single-pass two-histogram;
  a parallel point through a persistent pool.
