# Pilot runbook — closing Sprints 4 & 5 (the human-gated steps)

Everything in Sprints 4 and 5 is **built and tested in code**. Their `Pronto quando`
conditions are, by definition, *outcomes of running real cases* — which need two things
an AI cannot provide: the lawyer's **ICP-Brasil A3 e-CPF** (a hardware token) and an
**LLM backend** (Ollama or a Claude key). This runbook is the exact sequence to produce
those outcomes. Follow it and the machinery does the rest.

## Prerequisites (once)

```bash
uv sync
# LLM: either local (no PII leaves the machine) …
ollama serve && ollama pull qwen3:8b          # local, recommended for real case data
# … or cloud, de-identified (ADR-0016 gate is automatic):
export ANTHROPIC_API_KEY=sk-...               # only if using --cloud
# Plug in the A3 token; set the agent credentials on THIS machine (split-trust):
export JURIS_AGENT_CPF=... JURIS_AGENT_SENHA=... JURIS_AGENT_PIN=...
uv run juris pilot preflight                   # readiness gate before real runs
```

## Sprint 4 — instrumented pilot (5–10 real cases)

`Pronto quando: existir relatório de piloto com evidência e backlog priorizado.`

For each real case (repeat 5–10×):

1. **Read the case** via MNI (real, with the A3 token):
   ```bash
   uv run juris consulta <numero_cnj> --tribunal tjmg
   ```
2. **Run the pipeline** (analyze → strategy → draft → review):
   ```bash
   uv run juris demo <numero_cnj> contestacao --source mni    # add --cloud to use Claude
   ```
   Open the console (`uv run juris serve` → http://127.0.0.1:8000) to read the draft,
   the strategy panel, the review flags and the citations.
3. **Register feedback** (console → "Piloto instrumentado", or `POST /api/pilot-feedback`)
   with the objective, measurable fields:
   - `time_saved_minutes` — vs drafting from scratch;
   - `citations_accepted` / `citations_rejected` — the reviewer already marks grounded
     vs spurious; record the lawyer's accept/reject;
   - `corpus_usable` + `missing_source` — what inteiro-teor was missing (feeds the moat);
   - `perceived_utility` (1–5).
4. **Generate the report** once the cases are in:
   ```bash
   uv run juris pilot summary                       # headline metrics
   uv run juris pilot report -o piloto.md           # evidence + prioritized backlog
   ```
   `piloto.md` **is** the Sprint 4 deliverable: time saved, citation acceptance rate,
   average utility, and the prioritized corpus-gap backlog → informs the price/scope call.

## Sprint 5 — prove the moat (second run improves)

`Pronto quando: segunda execução melhora resultado em casos do piloto.`

The gaps to fill come straight from Sprint 4's backlog (`missing_source`). Pick a
**ToS-cleared inteiro-teor source** — this is a legal/business decision, not code:

- **Simplest & unambiguous:** decisions the firm already holds (their own downloads /
  received acórdãos) — clearly licensed, public-domain official acts (Lei 9.610/98 art. 8).
- **Open government data:** LexML (lexml.gov.br) / the courts' open-data endpoints —
  clear the specific ToS in `data/tos_compliance_log.md` before enabling any fetch. The
  portal ingesters stay **gated** until that sign-off (`jurisprudencia_portais.py`).

Then:

1. **Ingest with provenance** (mandatory URL/fonte/data/hash/tipo enforced):
   console → "Fila de corpus" → aceitar fonte → `POST /api/corpus/reingest`.
2. **Check coverage:** console → "Cobertura do corpus dirigido" (`/api/corpus/coverage`)
   — área/tribunal/tema.
3. **Re-run the same pilot cases** and compare grounding with the harness:
   ```python
   from juris.benchmark.corpus_improvement import RetrievalCase, measure_grounding, compare_runs
   # cases = the pilot queries + the source_ids they SHOULD ground on
   before = measure_grounding(cases, service)   # first run (pre-ingest snapshot)
   after  = measure_grounding(cases, service)   # after ingesting the missing sources
   print(compare_runs(before, after))           # improved: True, newly_grounded: [...]
   ```
   `improved: True` on the pilot cases is the Sprint 5 done-when. The mechanism is already
   proven deterministically in `tests/unit/test_corpus_improvement.py`; this applies it to
   the real pilot cases.

## Why this can't be scripted end-to-end here

Running the cases needs the physical A3 token and an LLM; choosing the corpus source is a
ToS/commercial decision. Fabricating pilot feedback or legal text to satisfy the gate
would defeat the entire purpose (evidence must be real). So the code is done; these steps
are yours.
