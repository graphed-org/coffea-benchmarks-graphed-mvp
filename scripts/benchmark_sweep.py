"""The (query x chunksize x workers) sweep — the graphed analogue of the original __main__.

LOCAL-ONLY for the full 16 GB file (CI runners cannot hold it; CI exercises the harness on the
committed skim instead). Example, mirroring the upstream grid shape:

    python scripts/benchmark_sweep.py \\
        --files /path/to/Run2012B_SingleMu.root \\
        --chunksizes 524288 --workers 1 4 8 \\
        --out results_local.csv
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import benchmark  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="+", required=True, help="ROOT file paths (Events tree)")
    ap.add_argument("--queries", nargs="+", default=sorted(benchmark.adl.QUERIES))
    ap.add_argument("--chunksizes", nargs="+", type=int, default=[2**19])
    ap.add_argument("--workers", nargs="+", type=int, default=[1, 4])
    ap.add_argument("--out", default="results_local.csv")
    args = ap.parse_args()

    files = [f if ":" in os.path.basename(f) else f + ":Events" for f in args.files]
    rows = []
    from graphed_executors.local import ProcessExecutor

    for nworkers in args.workers:
        executor = None
        if nworkers > 1:
            executor = ProcessExecutor(max_workers=nworkers, persistent=True)
        try:
            for chunksize in args.chunksizes:
                for query in args.queries:
                    point = benchmark.run_benchmark(
                        query, files, chunksize=chunksize, executor=executor, workers=nworkers
                    )
                    point.pop("hists")
                    rows.append(point)
                    print(
                        f"{query} chunk={chunksize} workers={nworkers}: "
                        f"{point['walltime']:.2f}s {point['us*core/evt']:.2f} us*core/evt "
                        f"{point['MB/s/core']:.1f} MB/s/core"
                    )
        finally:
            if executor is not None:
                executor.close()

    try:
        import pandas as pd

        df = pd.DataFrame(rows)
        df.to_csv(args.out, index=False)
        print(df.to_string(index=False))
    except ImportError:  # pandas is a local convenience, not a requirement
        import csv

        with open(args.out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
