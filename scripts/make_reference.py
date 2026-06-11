"""Run the ORIGINAL coffea ADL processors over the 50k skim and save their histogram counts.

The saved JSON is the acceptance reference for the graphed port (bit-for-bit per bin, including
flow). Run locally with coffea installed; CI compares against the committed JSON."""

from __future__ import annotations

import json
import os
import sys

import numpy as np
from coffea import nanoevents
from coffea.nanoevents import NanoEventsFactory

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIM = os.path.join(HERE, "data", "Run2012B_SingleMu_50k.root")
OUT = os.path.join(HERE, "data", "reference_counts.json")

nanoevents.NanoAODSchema.warn_missing_crossrefs = False
nanoevents.NanoAODSchema.error_missing_event_ids = False  # the skim drops run/lumi/event deliberately
sys.path.insert(0, HERE)

# import the original processors from the benchmark script (hyphenated filename). The script
# predates coffea 2026 (processor.NanoAODSchema moved); neutralize its legacy module-level lines
# and stop before the __main__ harness — the PROCESSOR CLASSES are what we need, verbatim.
src = open(os.path.join(HERE, "coffea-adl-benchmarks.py")).read()
src = src.replace("processor.NanoAODSchema.warn_missing_crossrefs = False", "pass")
src = src.replace("mupair.slot0", 'mupair["0"]').replace("mupair.slot1", 'mupair["1"]')  # awkward v1 tuple-field names
src = src.replace(
    "np.cos(events.MET.delta_phi(l3))",
    "np.cos((events.MET.phi - l3.phi + np.pi) % (2 * np.pi) - np.pi)",
)  # modern vector cannot dispatch delta_phi on a Muon/Electron UNION; identical formula
src = src.replace("import psutil", "")
src = src.replace("proc = psutil.Process()", "")
src = src.split('if __name__ == "__main__":')[0]
import types
mod = types.ModuleType("coffea_adl")
exec(compile(src, "coffea-adl-benchmarks.py", "exec"), mod.__dict__)

events = NanoEventsFactory.from_root(
    {SKIM: "Events"}, schemaclass=nanoevents.NanoAODSchema, mode="eager"
).events()
print("events:", len(events))

reference: dict[str, dict[str, list[float]]] = {}
for name, proc_cls in [
    ("q1", mod.Q1Processor), ("q2", mod.Q2Processor), ("q3", mod.Q3Processor),
    ("q4", mod.Q4Processor), ("q5", mod.Q5Processor), ("q6", mod.Q6Processor),
    ("q7", mod.Q7Processor), ("q8", mod.Q8Processor),
]:
    out = proc_cls().process(events)
    hists = out if isinstance(out, dict) else {name: out}
    reference[name] = {
        label: [float(x) for x in np.asarray(h.values(flow=True))]
        for label, h in hists.items()
    }
    print(name, {label: round(sum(v), 1) for label, v in reference[name].items()})

with open(OUT, "w") as f:
    json.dump(reference, f, indent=1)
print("wrote", OUT)
