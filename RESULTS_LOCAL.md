# Local full-file benchmark results (Run2012B_SingleMu.root, 16 GB, 53,446,198 events)

The graphed ADL sweep (`scripts/benchmark_sweep.py`) on the full benchmark file — **local-only**
(CI runners cannot hold the file; CI exercises the same harness on the committed 50k skim).
One machine (macOS, arm64), file on local SSD, chunksize 2^19 (102 chunks/pass), workers
{1, 4, 8} with persistent process pools; every pass touches all 53.4M events. Raw numbers:
`results_local.csv`.

## Walltime per query (all 53.4M events)

| query | bytes read | 1 worker | 4 workers | 8 workers | speedup @4 / @8 |
|---|---|---|---|---|---|
| q1 (MET)              | 0.23 GB | 1.9 s  | 2.0 s  | 1.8 s  | ~1x (driver-bound: tiny) |
| q2 (jet pT)           | 0.75 GB | 5.6 s  | 1.6 s  | 1.1 s  | 3.5x / 5.2x |
| q3 (jet pT, \|eta\|<1)| 1.54 GB | 13.4 s | 3.7 s  | 2.3 s  | 3.7x / 5.8x |
| q4 (MET, >=2 jets)    | 0.98 GB | 7.6 s  | 2.1 s  | 1.4 s  | 3.7x / 5.6x |
| q5 (dimuon mass)      | 1.57 GB | 16.9 s | 4.6 s  | 3.2 s  | 3.7x / 5.3x |
| q6 (trijet)           | 3.52 GB | 181.9 s| 112.9 s| 166.6 s| 1.6x / 1.1x (see note) |
| q7 (jet sum, dR clean)| 4.75 GB | 56.0 s | 15.9 s | 9.7 s  | 3.5x / 5.8x |
| q8 (SFOS + MT)        | 2.14 GB | 26.7 s | 7.5 s  | 4.7 s  | 3.6x / 5.7x |

## Observations

- **Projection shows up directly in the I/O column**: q1 reads 0.23 GB of the 16 GB file
  (MET_pt alone, 4.3 b/evt); q7 reads 4.75 GB (eleven branches, 89 b/evt). The byte counts
  come from uproot's own accounting around the projected reads.
- **Per-event costs (1 worker)** range from 0.036 us*core/evt (q1) to 3.4 (q6); peak read
  throughput ~135 MB/s/core (q2, sequential).
- **Near-linear scaling** for the I/O+compute queries: 3.5-3.7x at 4 workers, 5.2-5.8x at 8.
- **q6 is the exception and worth recording honestly**: 1.6x at 4 workers and a REGRESSION at 8
  (167 s, slower than 4). q6 materializes C(n,3) trijet combinations per chunk — by far the
  largest intermediates of the suite — and eight concurrent workers contend for memory
  bandwidth/allocator on this machine. The right lever is smaller chunks for combinatoric
  queries (less resident intermediate per worker), i.e. the chunksize axis this harness sweeps;
  a per-query chunk policy is an obvious Phase-2 harness refinement.
- Counts were validated bit-for-bit against coffea on the 50k skim (the acceptance suite);
  full-file counts are consistent across worker counts within each query.
