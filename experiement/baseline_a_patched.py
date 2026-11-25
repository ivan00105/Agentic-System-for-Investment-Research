"""Rerun Baseline A with one documented fix to the legacy pipeline (monkeypatch only, repo untouched):
retrieve_packet required inline-XBRL dei tags (ix:nonnumeric), which exist only in filings from mid-2019.
For pre-iXBRL filings the issuer is already verified by the filing index (CIK and accession regex), so the
dei identity/form/period checks are skipped when the document has no ix tags. Everything else is unchanged."""
import inspect, sys, textwrap
from research_assistant import filings, research
src = inspect.getsource(filings.retrieve_packet)
old = '    identity = {n.attrs.get("name"): n.text() for n in doc.root.nodes("ix:nonnumeric")}\n'
assert old in src
lines = src.split("\n")
start = next(i for i, l in enumerate(lines) if l.startswith('    identity = {'))
end = next(i for i, l in enumerate(lines) if l.startswith('    documents = ['))
block = lines[start + 1:end]
new = lines[:start + 1] + ["    if identity:"] + ["    " + l if l else l for l in block] + lines[end:]
code = "\n".join(new).replace("def retrieve_packet", "def retrieve_packet_patched")
ns = dict(vars(filings)); exec(code, ns)
research.retrieve_packet = ns["retrieve_packet_patched"]
sys.path.insert(0, "eval")
import run_eval
sys.exit(run_eval.main(sys.argv[1:]))
