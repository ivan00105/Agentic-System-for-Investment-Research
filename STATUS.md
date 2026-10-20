# Current implementation

The custom web milestone is implemented in this directory. Start from [README.md](README.md); the four design/research documents are in [docs/planning](docs/planning/implementation_plan.md).

## Working behaviour

- React/TypeScript/Vite workspace with Research, Discovery and History.
- Saved evidence inspector, deterministic financial metrics, qualified claims and a preserved teaching correction.
- FastAPI, SQLite, immutable local snapshots, a single worker, persistent idempotency and refresh-safe run URLs.
- Explicit fresh/frozen/replay modes. Missing configuration or failed inference preserves available results and stops clearly.
- Five-company synthetic examples; narrow SEC annual-facts retrieval and structured interpretation/critic integration behind explicit server configuration.

## Proof

- Production frontend build passed.
- 21 backend tests passed.
- All 8 browser scenarios passed; the final report-fixture adjustment also passed a clean-database rerun of the 3 desktop/discovery/mobile checks.
- Browser accessibility scans passed after contrast fixes. Screenshot and state evidence is recorded in [verification/evidence.json](verification/evidence.json).
- Local links in the relocated planning documents resolve.

## Next acceptance criterion

Configure a real SEC contact identity and an accessible Responses API model. Manually check one annual evidence packet, then run an explicitly budgeted live-provider smoke test. Mock tests do not establish real account access or financial correctness across the universe.

The full five-role coordinator/correction evaluation and price-based forecasting remain research work. Current critic objections remain unresolved for adjudication. The bundled margin correction is synthetic and recorded. Do not present it as a live model result or claim a validated outperformance probability.
