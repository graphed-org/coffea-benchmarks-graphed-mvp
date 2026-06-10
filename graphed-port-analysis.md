# Reimplementing the coffea ADL benchmarks on graphed — gap analysis

*(graphed-org/coffea-benchmarks-graphed-mvp, branch `graphed-mvp`, 2026-06-10. The upstream
benchmark: eight ADL queries as coffea processors over Run2012B_SingleMu NanoAOD, each ending in
a `hist` fill, swept over chunk sizes and worker counts.)*

## Where we already stand

All eight ADL queries are ALREADY recorded and executed through graphed — frozen since M7
(`graphed-exec-local/tests/frozen/m7/adl.py`) over a synthetic corpus dataset, with per-chunk
histograms tree-reduced across both executors. Every structural ingredient the queries need
exists and is frozen-tested: `combinations`/`argcombinations` (Q5/Q6/Q8), `cartesian(nested=True)`
+ axis=2 reductions (Q7's ΔR cleaning), boolean AND jagged-integer getitem, `argmin/argmax
(keepdims=)` + `flatten`/`firsts`/`singletons` (best-candidate selection), `local_index`,
`concatenate(axis=1)`, `where`, `with_field`, `sort`/`argsort`, the full ufunc tier, and — since
UPROOT-2 — `behavior=` on `uproot.graphed` with vector behaviors projecting to exactly the
branches a property reads. M22's multi-output compiles cover Q6's two-histogram single pass.

So the port is NOT blocked on the array language. What separates the m7 re-expression from a
faithful benchmark reimplementation:

## P0 — genuine blockers

1. **[P0.1 — DONE 2026-06-10, revised per user direction]** Deferred histogramming is NOT a
   `gak` function: it is its own package, **graphed-histogram** (the dask-histogram analogue —
   fills record as content-addressed External nodes; backends know nothing about histograms;
   partition-wise fill through the compiled IR + native `+` tree-combine), plus **`hist.graphed`**
   in the `hist-graphed-mvp` fork (`Hist`/`NamedHist` with QuickConstruct; `compute()` returns a
   real `hist.Hist`). The benchmark's `Hist.new.Reg(...).Double().fill(...)` lines port nearly
   verbatim: construct via `hist.graphed.Hist`, fill with graphed Arrays, `compute()` per query.
   Root prompt R18 binds the architecture. (graphed M23 seam: `record_external(descriptor=,
   form=)`; graphed-histogram freeze-M23-0; hist fork freeze-HIST-1.)

2. **The dataset + branch-shape witnesses.** Run2012B_SingleMu.root (16 GB; a 50k-event skim
   exists for CI-scale work). The real file is flat-branch NanoAOD (`nJet`, `Jet_pt`, ...):
   collections must be zipped from jagged branches with counts — our uproot behavior tests so
   far zip FLAT branches only. Unwitnessed (likely working, must be pinned over a real NanoAOD
   file): jagged zip + `with_name` + vector behaviors; record+record arithmetic through the
   proxy's `+` (Q5/Q6 four-vector sums — vector supports typetracer, needs the witness);
   jagged-integer-array getitem over an uproot source (Q8's `leptons[pair.l1]`).

## P1 — fidelity and convenience

3. **A NanoAOD collection-zipping helper** (`nJet` + `Jet_*` → one zipped, behavior-named
   collection; MET/HLT singletons). Manual `gak.zip` per collection works today (~20 lines for
   the 4 collections the ADL uses) — a `NanoSchema`-lite convenience belongs in the fork, not
   in graphed (§A.4: the frontend stays domain-free).
4. **Kinematics via behaviors, not hand-rolled formulas.** m7 predates M18 and hand-rolls
   `_pair_mass`/`_delta_r`/`_delta_phi`; the port should use vector's `Momentum4D` (`.mass`,
   `.deltaR`, `.deltaphi`) — NanoAOD gives pt/eta/phi/mass, vector derives Q6's x/y/z/t. Negative
   mass-squared guards: `np.maximum(..., 0)` clamp (the m7 pattern) replaces `np.errstate`.
5. **Benchmark metrics parity.** Upstream reports bytesread / entries / chunks / walltime per
   (query × chunksize × workers). Our `ExecResult` carries n_partitions/n_combines but no I/O
   accounting; `uproot.graphed` partitions are entry-ranged (chunksize ≡ steps_per_file shaping
   needs an entries-per-step option — today steps split per FILE, the benchmark sweeps absolute
   chunk sizes). Needed in the fork harness: a bytes-read probe (uproot reports
   `file.source.num_requested_bytes`) and an entry-target partitioner.

## P2 — harness logistics

6. The sweep driver (queries × chunksizes × cores, pandas table, `results.pkl`) ports directly:
   ProcessExecutor(max_workers=) replaces FuturesExecutor; compile-once-per-query (R7.8) replaces
   the processor re-import; the M22 multi-output compile carries Q6's two histograms in one pass.
   No `/proc/sys/vm/drop_caches` on macOS dev boxes — document.
7. Functional-style rewrites where upstream mutates: `events["leptons"] = ...` →
   `gak.with_field`; `pair[:, 0]` → `gak.firsts`; `ak.singletons(argmin)` → `argmin(keepdims=True)`
   + masked getitem (both m7-proven).

## Suggested order

1. `gak.histogram` (+2D/3D) as a new gated milestone in graphed-awkward (frozen first; monoid
   combine pinned bit-for-bit against `np.histogram`), exec-local regression proving tree
   reduction of histogram outputs. 2. Fork milestone: NanoAOD witnesses (jagged zip + behaviors +
   record arithmetic + jagged-index getitem over a real NanoAOD test file) + the collection
   helper. 3. Port Q1–Q8 as recorded analyses; pin counts bit-for-bit against the coffea
   reference on the 50k skim. 4. Harness + metrics; full-file runs are an operational step, not
   a code one.
