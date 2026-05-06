# MNI Integration Reference for Brazilian Legal AI

A practical architecture guide for building an AI-driven law-firm system that reads, analyzes, and files in Brazilian courts using the lawyer's own ICP-Brasil credentials.

---

## 1. SOAP Client Structure

### 1.1 Tech stack (Python)

| Concern | Library | Why |
|---|---|---|
| SOAP client | `zeep` | Mature, handles WSDL, namespaces, MTOM. The standard. |
| Certificate auth | `requests-pkcs12` or `python-pkcs11` | A1 vs A3 token handling |
| PDF signing (PAdES) | `pyhanko` or `endesive` | Production-grade, supports ICP-Brasil chain validation |
| XML signing (WS-Security) | `signxml` | For envelope-level signing where required |
| Storage | PostgreSQL + S3-compatible (MinIO/Backblaze B2) | Process metadata in PG, documents as objects |
| Queue | Redis + RQ, or NATS JetStream | For overnight batch + retries |
| Movement codes | CNJ TPU (Tabela Processual Unificada) JSON | Map raw codes to readable categories |

### 1.2 Module layout

```
mni_client/
├── core/
│   ├── soap.py            # cached zeep clients per tribunal endpoint
│   ├── auth.py            # cert vs password strategies
│   ├── tribunais.py       # WSDL registry, per-tribunal quirks
│   ├── tpu.py             # CNJ movement code → semantic category
│   └── retry.py           # exponential backoff + circuit breaker
├── operations/
│   ├── consulta.py        # consultarProcesso
│   ├── intimacoes.py      # consultarAvisosPendentes + consultarTeorComunicacao
│   └── peticionamento.py  # entregarManifestacaoProcessual
├── parsers/
│   ├── processo.py        # XML → ProcessoDomain model
│   ├── movimentos.py      # MovimentoLocal/MovimentoNacional
│   └── documentos.py      # base64 → object storage + extracted text
├── signing/
│   ├── pades.py           # PDF signing via local agent
│   └── envelope.py        # WS-Security envelope signing
├── agents/
│   ├── analyzer.py        # LLM reads new movements, classifies, scores
│   ├── researcher.py      # jurisprudência + doutrina retrieval
│   └── drafter.py         # generates petition draft + recommended action
└── api/
    └── server.py          # internal API for the orchestration layer
```

### 1.3 SOAP client core (zeep)

The MNI WSDL declares `consultarProcesso`, `consultarAvisosPendentes`, `consultarTeorComunicacao`, and `entregarManifestacaoProcessual`. Each tribunal hosts its own endpoint, typically at:

```
https://pje.<tribunal>.jus.br/pje/intercomunicacao?wsdl
```

Cache one zeep `Client` per tribunal in memory — instantiation is expensive (parses the WSDL), reuse is cheap.

```python
# core/soap.py
from functools import lru_cache
from zeep import Client, Settings
from zeep.transports import Transport
from requests import Session
from requests_pkcs12 import Pkcs12Adapter

@lru_cache(maxsize=64)
def mni_client(tribunal_id: str, cert_path: str, cert_password: str) -> Client:
    """Return a cached SOAP client for a given tribunal, authenticated with ICP-Brasil cert."""
    session = Session()
    session.mount(
        "https://",
        Pkcs12Adapter(pkcs12_filename=cert_path, pkcs12_password=cert_password),
    )
    transport = Transport(session=session, timeout=60, operation_timeout=120)
    settings = Settings(strict=False, xml_huge_tree=True)  # MNI XMLs can be huge
    wsdl = TRIBUNAL_WSDLS[tribunal_id]
    return Client(wsdl=wsdl, transport=transport, settings=settings)
```

### 1.4 Authentication patterns

MNI 2.2.2 supports three auth modes — pick per tribunal:

1. **`idConsultante` + `senhaConsultante` in the SOAP body.** Old but still works in many TRTs and TJs. The senha is the user's PJe portal password. Quick to bootstrap.
2. **ICP-Brasil certificate via mTLS.** Mount the certificate on the HTTPS transport (as above). The `senhaConsultante` field can be left empty or echo the CPF.
3. **WS-Security signed envelope.** Some tribunals require the SOAP envelope itself to be XML-signed with the cert. Use `signxml` to sign the `<soap:Body>` plus a `<wsu:Timestamp>`.

For a solo lawyer using a personal e-CPF A3 (USB token), option 2 is simplest. For an A1 (file-based) certificate, the same code works — A1 is just a `.pfx` file you can mount programmatically without user presence.

### 1.5 The consulta call

```python
# operations/consulta.py
def consultar_processo(client, cpf, senha, numero_cnj, com_documentos=False):
    response = client.service.consultarProcesso(
        idConsultante=cpf,
        senhaConsultante=senha,
        numeroProcesso=numero_cnj,
        movimentos=True,
        incluirCabecalho=True,
        incluirDocumentos=com_documentos,  # True = base64 PDFs in response
    )
    return response  # zeep returns a dict-like object matching the XSD
```

The response payload (`response.processo`) contains:

- `dadosBasicos` — capa: numero, classe, assunto, valorCausa, orgaoJulgador, partes
- `movimento[]` — chronological list of movements, each with `dataHora`, `movimentoNacional` (CNJ-coded) or `movimentoLocal` (tribunal-specific text), and optional `complementoNacional`
- `documento[]` — when `incluirDocumentos=True`, full PDFs as base64 with `idDocumento`, `tipoDocumento`, `dataHora`, `descricao`

**Tip:** never store the `senha` plaintext. For multi-tenant SaaS, encrypt at rest with a per-customer KMS key, decrypt in memory only at call time, and rotate when the lawyer changes their portal password.

### 1.6 TPU — making movements semantic

Raw `movimentoNacional` codes are integers from the CNJ Tabela Processual Unificada. Examples:

| Código | Significado | Strategic relevance |
|---|---|---|
| 51 | Audiência designada | High — schedule + prep deadline |
| 60 | Despacho | Medium — read content |
| 132 | Sentença com resolução do mérito | Critical — appeal window opens |
| 193 | Decisão | High — may need recurso |
| 246 | Juntada | Low — usually noise |
| 970 | Trânsito em julgado | Critical — case-closing |

Download the TPU JSON from CNJ once and ship it as a static file in your repo. Map every incoming `movimentoNacional` to a `categoria_semantica` (e.g., `prazo_aberto`, `decisao_recorrivel`, `pauta_marcada`, `noise`). This is what your AI layer uses to decide whether a movement matters at all.

### 1.7 Differential reading (the overnight job)

Don't re-fetch full processes nightly — that's expensive and abusive. The pattern:

1. **Hourly** (or every 30 min): call `consultarAvisosPendentes` per tribunal. Returns intimações not yet marked as ciência.
2. **For each new aviso**: call `consultarTeorComunicacao` to get the full content.
3. **Daily** (overnight): for each active process, call `consultarProcesso` with `movimentos=True` but `incluirDocumentos=False`. Compare last movement timestamp to your stored cursor.
4. **Only if there are new movements**: re-call with `incluirDocumentos=True` filtering by `dataReferencia` to fetch only new PDFs.

This pattern keeps your call volume down ~80–90% versus naive nightly re-fetch, which matters for tribunal rate limits and your own cost.

### 1.8 Retry, backoff, and tribunal stability

Brazilian tribunals go down. A lot. <br>Resolução CNJ 185/2013 explicitly says MNI/external connectivity failures don't count as "indisponibilidade do Processo Eletrônico" — the burden of working around outages is on you. Patterns:

- **Per-tribunal circuit breaker.** If a tribunal returns 5xx for >10 min, open the circuit and queue requests for retry.
- **Exponential backoff with jitter.** 1s, 2s, 5s, 15s, 60s.
- **Distinguish error types.** `TimeoutError`, `Fault` (SOAP-level error), `400` (bad request — don't retry), `401/403` (auth — don't retry, alert), `5xx` (retry).
- **Alert the lawyer when authentication breaks.** PJe portal passwords expire periodically. Detect 401s and ping the user to re-enter.

---

## 2. Certificate-based Signing Flow for Peticionamento

This is the legal moat. Vendors don't sell automated peticionamento well because the architectural problem is real: ICP-Brasil signing requires the lawyer to be in the loop at the moment of signature. You design *for* that requirement, not around it.

### 2.1 The two signing operations

When you file via `entregarManifestacaoProcessual`, two distinct signatures may be required:

1. **PAdES on each PDF document.** The petition itself plus any annexes must be PAdES-B (or PAdES-T) signed. The signature is embedded in the PDF, validated by the tribunal upon receipt.
2. **WS-Security on the SOAP envelope.** Some tribunals require the envelope `<Body>` plus a timestamp to be XML-signed with the same certificate. Most modern PJe instances do not; a few legacy ones do.

PAdES is non-negotiable. WS-Security is per-tribunal — discover empirically.

### 2.2 Architecture: split-trust between cloud and local agent

Your AI runs in the cloud (or on your Mac Mini M4 with OpenClaw). The lawyer's certificate must never leave their machine. The pattern:

```
┌─────────────────────────┐                   ┌───────────────────────┐
│   Cloud Orchestrator    │                   │  Lawyer's machine     │
│                         │                   │                       │
│  1. AI reads case       │                   │  Local Agent (small   │
│  2. Drafts petition     │                   │  Python service +     │
│  3. Renders PDF         │ ─── WebSocket ──> │  system tray UI)      │
│  4. Sends to local      │                   │                       │
│     agent for review    │ <── push notify ─ │  USB token / A3 cert  │
│                         │                   │  always available     │
│  6. Receives signed     │ <── signed PDF ── │                       │
│     PDF                 │                   │  Lawyer reviews PDF,  │
│  7. Submits via MNI     │                   │  clicks "Sign", types │
│  8. Stores receipt      │                   │  PIN once             │
└─────────────────────────┘                   └───────────────────────┘
```

This satisfies multiple constraints simultaneously:

- **Resolução CNJ 615/2025** — supervisão humana efetiva: the lawyer affirmatively reviews and signs.
- **OAB Recommendation Nov/2024** — the lawyer remains responsible for content and verifies it.
- **ICP-Brasil reality** — A3 token can't be remoted; A1 *could* be, but that's bad practice and arguably an OAB ethics issue.
- **LGPD + sigilo profissional** — the cert never leaves the trusted machine.

### 2.3 Local agent skeleton

```python
# local_agent/main.py
from fastapi import FastAPI, WebSocket
from pyhanko.sign import signers, fields
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

app = FastAPI()

@app.websocket("/ws")
async def signing_socket(ws: WebSocket):
    await ws.accept()
    while True:
        msg = await ws.receive_json()
        if msg["type"] == "sign_request":
            pdf_bytes = base64.b64decode(msg["pdf_b64"])
            # show desktop notification: "Petição pronta: <case> <action>"
            # open preview window
            # wait for user to click "Assinar"
            user_approved = await user_consent_dialog(msg["preview_meta"])
            if not user_approved:
                await ws.send_json({"type": "rejected", "request_id": msg["request_id"]})
                continue
            signed_bytes = sign_pades(pdf_bytes, certificate_session)
            await ws.send_json({
                "type": "signed",
                "request_id": msg["request_id"],
                "pdf_b64": base64.b64encode(signed_bytes).decode(),
            })

def sign_pades(pdf_bytes, cert_session):
    """PAdES-B signing using pyhanko, with the user's loaded A3 token via PKCS#11."""
    signer = signers.PdfSigner(
        signers.PdfSignatureMetadata(field_name="AdvogadoSignature"),
        signer=cert_session,
    )
    in_buf = io.BytesIO(pdf_bytes)
    out_buf = io.BytesIO()
    w = IncrementalPdfFileWriter(in_buf)
    signer.sign_pdf(w, output=out_buf)
    return out_buf.getvalue()
```

The user-facing UX matters here. Show the lawyer:
- The case number and current state (last movement)
- The AI-generated draft, rendered and scrollable
- A short summary: "Why this petition: [LLM-generated rationale]"
- The cited jurisprudence with links to the source
- A clear "Assinar e Protocolar" button + a "Revisar e ajustar" button + "Cancelar"

### 2.4 Submitting the signed petition via MNI

```python
# operations/peticionamento.py
def entregar_manifestacao(client, cpf, senha, numero_cnj, signed_pdf_bytes, tipo_documento):
    documento = {
        "idDocumentoVinculado": None,
        "tipoDocumento": tipo_documento,  # e.g., "manifestacao", "peticao", from tribunal's vocabulary
        "descricao": "Petição protocolada via sistema integrado",
        "mimetype": "application/pdf",
        "conteudo": base64.b64encode(signed_pdf_bytes).decode(),
        "hash": hashlib.sha256(signed_pdf_bytes).hexdigest(),
        "assinatura": {
            # The PDF is already PAdES-signed — most modern PJe instances accept this
            # without requiring an additional XML signature in this field
            "tipoAssinatura": "ICP-Brasil",
        },
    }
    response = client.service.entregarManifestacaoProcessual(
        idManifestante=cpf,
        senhaManifestante=senha,
        numeroProcesso=numero_cnj,
        documento=[documento],
        dataEnvio=datetime.now().isoformat(),
    )
    # response contains: protocoloRecebimento, mensagem, sucesso
    return response
```

**Critical: capture the recibo.** `protocoloRecebimento` is your proof of filing within the prazo. Store it immutably (S3 + database row + ideally a hash anchored periodically — Bitcoin-style timestamping is overkill but a Liquid-anchored hash log is interesting for audit trail given your DEPIX interest).

### 2.5 Failure modes to handle

| Failure | Cause | Handling |
|---|---|---|
| `Erro de assinatura` | Cert expired, revoked, or chain broken | Re-validate cert at start of each session; alert lawyer |
| `Documento corrompido` | PDF/A flatness issues, fonts not embedded | Use `pyhanko` with PDF/A-2u output |
| `Tipo de documento inválido` | Tribunal-specific document type vocabulary | Maintain per-tribunal type registry |
| `Processo não encontrado` | Wrong tribunal or process moved | Validate via consulta first |
| `Prazo expirado` | Filed past deadline | Pre-flight check against your prazo tracker |
| `Sistema indisponível` | Tribunal down | Retry with backoff; if window closes, hold for protocolo físico fallback (CPC art. 218) |

### 2.6 Mapping to legal/regulatory framework

| Requirement | How this design satisfies it |
|---|---|
| Resolução CNJ 615/2025 — supervisão humana efetiva | Lawyer affirmatively reviews and signs each filing |
| Resolução CNJ 615/2025 — contestabilidade | Full audit log of AI prompts, retrieved sources, draft versions |
| OAB Recommendation Nov/2024 — responsabilidade integral | The lawyer's certificate signs; legal accountability is unambiguous |
| OAB Code of Ethics — sigilo profissional | Certificate stays local; cloud orchestrator only handles data the lawyer authorizes |
| LGPD — base legal | Legitimate interest of the controller (the lawyer/firm) for processing case data |
| Lei 11.419/2006 — peticionamento eletrônico | ICP-Brasil signature satisfies authenticity and integrity requirements |
| MP 2.200-2/2001 — ICP-Brasil | A3 hardware token = the highest assurance level |

---

## 3. Per-Tribunal Coverage Matrix

This is the field map. Verify each line against current state when you implement — tribunal infrastructure changes.

### 3.1 PJe-based tribunals (MNI native)

| Tribunal | MNI version | Stability | Notes |
|---|---|---|---|
| All TRTs (1ª–24ª regiões) | 2.2.2 | Generally good | Trabalhista is the most uniform — best place to start |
| All TRFs (1ª–6ª regiões) | 2.2.2 | Good | Federal — high-value cases, often premium tier |
| TJDF (DF) | 2.2.2 | Good | Reference implementation |
| TJBA, TJMA, TJPI, TJRR, TJAM, TJTO, TJES, TJPB, TJPE, TJSE | 2.2.2 | Variable | Each may have local quirks |
| TJMG (PJe parts) | 2.2.2 | Good | Note: TJMG also has Projudi for older cases |
| TJRJ | 2.2.2 | Good | High volume |
| TJGO | 2.2.2 | Good | |
| CNJ (corregedoria) | 2.2.2 | Reference | |
| TST | 2.2.2 | Good | Superior trabalhista |
| TSE | 2.2.2 | Good | Eleitoral |

### 3.2 eSAJ (Softplan) — the elephant

| Tribunal | MNI? | Approach |
|---|---|---|
| TJSP | ❌ | Largest volume in Brazil. Portal API is partial; full coverage requires authenticated session scraping with the lawyer's certificate. SAJ-ADV (the desktop client) reverse-engineering is one path; a headless browser session is more maintainable. |
| TJAC, TJAL, TJCE, TJMS, TJSC (parts) | ❌ | Same architecture as TJSP; build once, reuse with per-tribunal session config |

**Strategy:** for TJSP, evaluate whether buying coverage from Judit/Escavador for read access is cheaper than building/maintaining your own scraper. For peticionamento on TJSP, the only path is the portal — which means automating the eSAJ peticionamento flow with the lawyer's certificate. This is doable but fragile; expect 1 break per quarter.

### 3.3 eProc

| Tribunal | MNI? | REST API? | Notes |
|---|---|---|---|
| TRF4 | Partial | Yes — own well-documented REST | Use REST. Better than MNI here. |
| TJRS | Partial | Yes | Same |
| TJSC | Partial | Yes | Same |
| TJTO | Partial | Limited | |

eProc tends to be the most modern of the three major systems. The REST APIs are saner than SOAP MNI, and the data model is cleaner. Where eProc REST is available, prefer it.

### 3.4 Projudi (legacy)

| Tribunal | MNI? | Approach |
|---|---|---|
| TJPR (Projudi 1ª/2ª grau) | Limited | Scraping; some operations have JSON endpoints |
| TJBA (Projudi for older cases) | No | Scraping |

Projudi is being phased out in favor of PJe across most jurisdictions. Don't over-invest — cover read-only via scraping, skip peticionamento unless a customer specifically needs it.

### 3.5 Superior courts

| Court | Mechanism | Notes |
|---|---|---|
| STF | Próprio webservice (não MNI) | "Peticionamento eletrônico STF" has its own API. Smaller volume of new petitions but high-stakes — worth implementing carefully. |
| STJ | Próprio webservice | Similar pattern to STF. |
| TST | MNI 2.2.2 | Standard PJe |

### 3.6 Other systems

| System | Tribunals | Approach |
|---|---|---|
| Tucujuris | TJAP | Scraping |
| Themis | Some MPs and small courts | Out of scope unless specific demand |
| SEEU | Execuções penais (national) | Specific webservice; not in DataJud. Needed only for criminal practice. |
| BNMP 3.0 | Mandados de prisão (national) | Read-only; relevant for criminal/compliance |

### 3.7 Ancillary systems (essential complements)

| System | Purpose | Integration |
|---|---|---|
| **DJE (Domicílio Judicial Eletrônico)** | Centralized intimação receipt for all civil cases | Modern API, designed for system integration. **Use this**, not per-tribunal scraping for intimações when possible. |
| **DET (Domicílio Eletrônico Trabalhista)** | Same for trabalhista | Same — modern API |
| **DataJud (CNJ public)** | Cross-tribunal metadata, statistics | REST API; rate-limited but free. Use for jurimetria, adversário lookup, court-level analytics — not for primary case feed. |
| **Diários Oficiais (Eletrônicos)** | Publications | Either CNJ DJEN aggregator or per-tribunal Diários. Vendors (JusBrasil, Escavador) cover this well — buy unless you have a specific reason. |

### 3.8 Coverage strategy summary

A pragmatic build order for a Brazilian legal AI:

1. **Week 1–4:** MNI client for all TRTs + TRFs + your own state TJ's PJe instance. Authenticate with your e-CPF. Read-only.
2. **Week 5–8:** TPU mapping, semantic categorization, AI analyzer reading new movements. Drafter for trabalhista contestações (most uniform vocabulary).
3. **Week 9–12:** Peticionamento via local-agent + PAdES signing. Start with one tribunal, one document type. Expand.
4. **Month 4–6:** DJE/DET integration for intimações firehose. Buy data layer (Judit recommended given MCP support) for cross-tribunal coverage gaps.
5. **Month 6+:** eSAJ scraping if TJSP is in scope. STF/STJ if recursos extraordinários are part of your offer. eProc REST integration.

---

## 4. Practical Considerations

### 4.1 Rate limits and "good citizen" practices

CNJ doesn't publish hard rate limits for MNI per tribunal, but tribunals do throttle. Operating norms:

- ≤ 1 req/sec per tribunal per credenciado for consulta.
- ≤ 10 concurrent connections per tribunal.
- Honor `Retry-After` if returned.
- Use off-peak hours (overnight, weekends) for full reads.
- DataJud public API: 10k requests/day default, request more if needed via formal CNJ ticket.

### 4.2 LGPD posture

You're processing process data containing CPFs, financial data, occasionally health/biometric data. You're a *controller* (not just operator) for your firm's caseload, and a *operator* for SaaS clients. You need:

- Per-firm DPA (contrato de operação)
- DPIA before processing sensitive data through any cloud LLM
- Encryption at rest with rotating keys
- Audit log of every case access
- Right-to-erasure flow even though Lei 11.419 mandates retention

For LLM inference, given your existing Ollama/OpenClaw stack: use local models for any prompt that contains personally identifiable case data. Reserve cloud LLMs (Claude, GPT) for tasks that operate only on de-identified or public data (e.g., jurisprudence search, legal reasoning on anonymized facts).

### 4.3 Audit trail requirements

Every AI-assisted filing should produce an audit record:

```json
{
  "case_number": "0009999-99.2024.8.26.0001",
  "action_id": "uuid-v7",
  "timestamp": "2026-04-29T22:13:00-03:00",
  "trigger": {
    "type": "new_movement",
    "movement_id": 178293,
    "tpu_code": 193,
    "tpu_category": "decisao_recorrivel"
  },
  "ai_chain": [
    {"step": "analysis", "model": "claude-opus-4-7", "prompt_hash": "...", "output_hash": "..."},
    {"step": "research", "model": "local-qwen3", "retrieved_sources": [...]},
    {"step": "draft", "model": "claude-opus-4-7", "prompt_hash": "...", "output_hash": "..."}
  ],
  "human_review": {
    "lawyer_oab": "SP123456",
    "reviewed_at": "2026-04-29T22:31:00-03:00",
    "decision": "approved_with_edits",
    "edit_diff_hash": "..."
  },
  "filing": {
    "method": "MNI:entregarManifestacaoProcessual",
    "tribunal": "trf3",
    "protocolo": "12345/2026",
    "filed_at": "2026-04-29T22:32:14-03:00",
    "signed_pdf_hash": "..."
  }
}
```

Keep this for the case retention period (10 years for most matters, longer for some). This trail is your defense against future challenges to AI-influenced filings under Resolução CNJ 615/2025.

### 4.4 Open-source MNI clients to look at

Several MIT/Apache-licensed Python and Java MNI clients exist on GitHub. Searching `MNI CNJ python` and `intercomunicacao PJe` will surface the main ones. None are production-grade out of the box — treat them as references for the WSDL handling and namespace resolution, then build your own client with proper retry, auth, and error handling.

### 4.5 What you can ship in 90 days, solo

A realistic v1 for your own firm:

- MNI consulta across the PJe instances where you operate, authenticated by your e-CPF
- Nightly differential read; new movements categorized via TPU
- LLM analyzer that flags movements requiring action (deadlines, decisions, hearings)
- Jurisprudence retrieval via DataJud + your own scrapers of STF/STJ/STJ-Pesquisa
- Draft generator for the 3–5 petition types you file most often
- Local agent for review + PAdES signing
- Filing via MNI for those 3–5 types, on your home tribunal first

That's a real product, validates the entire pipeline on your own caseload, gives you a basis to onboard the first 5–10 lawyer-customers from your network, and is feasible in 90 days for a competent solo dev. The data-layer purchase (Judit/Escavador) becomes worth it at customer #10+ when coverage gaps start mattering.

---

## 5. Repertory Architecture

The repertory is what turns the drafter from "an LLM generating plausible-sounding legal text" into "a system that produces grounded, citation-verified, firm-voiced petitions." It's the layer that prevents hallucinated jurisprudência, encodes the firm's writing style, and lets the AI build on the firm's accumulated argumentative work rather than starting from scratch each time.

### 5.1 Three-tier corpus design

The corpus splits into three tiers with very different IP, isolation, and update characteristics:

| Tier | Content | Source | Isolation | Update cadence |
|---|---|---|---|---|
| **Tier 1: Public** | Constitution, codes (CC, CPC, CLT, CTN, CDC), súmulas (STF/STJ vinculantes and não-vinculantes), leading public-domain decisions, CNJ resolutions, OAB ethical code | Built and maintained by you | Shared across all tenants | Weekly (informativos STF/STJ) |
| **Tier 2: Doutrina** | Saraiva, Forense, RT, JusPodivm, periodicals — uploaded as PDFs by the firm | Uploaded by customer | Strict per-tenant | On firm's upload |
| **Tier 3: Petição history** | The firm's own previously-filed petitions | Either uploaded by firm at onboarding or auto-captured from MNI filings going forward | Strict per-tenant | Continuous (auto-capture from your own filing pipeline) |

Tier 1 is your baseline — every customer gets it on day one without uploading anything. Tier 2 is BYO. Tier 3 is the secret sauce: it accumulates automatically as the firm files via your system, and the more they use the product, the better it gets at sounding like them.

### 5.2 Structural extraction

Naive PDF chunking destroys the structure that makes legal text useful. Each tier needs structure-aware extraction.

#### 5.2.1 Jurisprudência

Parse each decision PDF into discrete components:

```
{
  "decision_id": "STJ-REsp-1234567-SP",
  "tribunal": "STJ",
  "classe": "REsp",
  "numero": "1234567",
  "uf": "SP",
  "relator": "Min. Nancy Andrighi",
  "data_julgamento": "2024-03-15",
  "data_publicacao": "2024-03-22",
  "orgao_julgador": "Terceira Turma",
  "tema_repetitivo": null,
  "vinculacao": "persuasivo_forte",  // see hierarchy in 5.3
  "ementa": "...",                    // separate chunk, highest retrieval priority
  "relatorio": "...",
  "voto": [
    {"ministro": "Nancy Andrighi", "tipo": "voto_relator", "texto": "..."},
    {"ministro": "...", "tipo": "voto_vencido", "texto": "..."}
  ],
  "dispositivo": "...",
  "citacoes_internas": ["STJ-REsp-987654-RJ", "STF-RE-456789"],
  "fonte_pdf": "s3://repertory/public/stj/resp-1234567-sp.pdf",
  "fonte_url": "https://stj.jus.br/...",
  "hash": "sha256-..."
}
```

The `ementa` is the single highest-value chunk for retrieval — it's what's actually citable. Index the ementa as its own document with strong weighting. Index the voto and dispositivo separately for argumentative reasoning. Don't mash them together.

For PDFs from STF/STJ, the ementa is reliably marked with formatting cues ("EMENTA:" header, fixed position). A combination of regex + a small LLM extraction pass gets >98% accuracy. For tribunal de segunda instância acórdãos, structure varies; budget for noisier extraction.

#### 5.2.2 Doutrina

Books are organized by article-anchored or thematic chapters. Extract:

```
{
  "doutrina_id": "tartuce-cc-comentado-2024-art206",
  "obra": "Código Civil Comentado",
  "autor": "Flávio Tartuce",
  "edicao": "9ª",
  "ano": 2024,
  "editora": "Forense",
  "isbn": "978-...",
  "anchor_type": "artigo_comentado",
  "artigo_referencia": "CC art. 206, § 3º",
  "capitulo": "Da Prescrição",
  "secao": "Prescrição em três anos",
  "paginas": "234-241",
  "texto": "...",
  "tenant_id": "firm-uuid",
  "fonte_pdf": "s3://tenants/firm-uuid/doutrina/tartuce-cc.pdf",
  "page_number": 234
}
```

The `anchor_type` field is what makes retrieval precise. When the AI is reasoning about CC art. 206, you want commentary specifically anchored to that article, not a random chunk that happens to mention "prescrição." Anchors are mostly: `artigo_comentado`, `tema`, `capitulo`, `verbete` (for legal dictionaries).

PDFs without clear structure (older books, scanned editions) need OCR + LLM-based section detection. Treat this as a one-time per-book ingestion cost — the firm uploads, your pipeline processes overnight, the book becomes searchable next morning.

#### 5.2.3 Petitions (firm's history)

Each filed petition decomposes into roughly the same parts regardless of type:

```
{
  "petition_id": "firm-uuid-pet-2024-12345",
  "tenant_id": "firm-uuid",
  "case_number": "0001234-56.2024.5.02.0001",  // CNJ
  "tipo": "contestacao",                        // inicial, contestacao, replica, recurso, manifestacao, etc.
  "area": "trabalhista",
  "subarea": "verbas_rescisorias",
  "tribunal": "TRT-2",
  "data_filing": "2024-08-15",
  "outcome": "procedente_parcial",              // see 5.8
  "outcome_confidence": 0.95,                   // auto vs. manually confirmed
  "lawyer_oab": "SP123456",
  "sections": {
    "cabecalho": "EXMO. SR. DR. JUIZ DA ___ VARA DO TRABALHO DE ...",
    "preambulo": "FULANO DE TAL, já qualificado nos autos do processo em epígrafe, vem, respeitosamente, perante Vossa Excelência, ...",
    "fatos": "...",
    "preliminares": "...",
    "merito": [
      {"tese": "Inexistência de vínculo empregatício", "argumentacao": "...", "citacoes": [...]},
      {"tese": "Subsidiariamente, descaracterização da rescisão indireta", "argumentacao": "...", "citacoes": [...]}
    ],
    "pedidos": "...",
    "fechamento": "Termos em que, pede deferimento."
  },
  "style_fingerprint": {
    "avg_paragraph_length_words": 87,
    "preferred_citation_format": "tribunal_classe_numero_data",
    "uses_subscript_footnotes": false,
    "section_headers_caps": true,
    "rhetorical_register": "formal_classical"
  },
  "anonymized_text_hash": "sha256-...",
  "raw_pdf": "s3://tenants/firm-uuid/petitions/2024-12345.pdf"
}
```

This is the scaffolding. Each section gets indexed independently — when the AI is drafting a *fatos* section for a new contestação trabalhista, it retrieves *fatos* sections from this firm's prior contestações trabalhistas, not random chunks from the whole petition.

The `outcome` field is the multiplier: a *fatos* section from a winning petition is more valuable as an exemplar than from a losing one. More on this in 5.8.

### 5.3 Hierarchy of authority + hybrid retrieval

#### 5.3.1 Authority hierarchy (encoded as metadata)

Every chunk in the jurisprudência tier carries a `vinculacao` field indicating its binding force:

| Vinculação | Examples | Retrieval weight |
|---|---|---|
| `vinculante_constitucional` | Súmulas vinculantes STF, controle concentrado | Highest |
| `vinculante_repetitivo` | CPC art. 927: IRDR, IAC, RE/RG, REsp repetitivo | Very high |
| `persuasivo_sumula` | Súmulas STF/STJ não-vinculantes | High |
| `persuasivo_forte` | Acórdãos STF/STJ recentes | High |
| `persuasivo_local` | Acórdãos do tribunal onde a causa tramita | Medium-high (case-dependent) |
| `persuasivo_outros` | Acórdãos de outros TJs/TRTs/TRFs | Medium |
| `doutrina_majoritaria` | Doutrina amplamente aceita | Medium |
| `doutrina_minoritaria` | Doutrina de vanguarda ou divergente | Low (flag explicitly) |

The drafter's prompt should instruct: "Lead with the highest-tier source available. If only `persuasivo_local` or below is available for the thesis, surface that limitation to the lawyer instead of overstating."

#### 5.3.2 Hybrid retrieval architecture

Pure dense embeddings miss exact references; pure sparse misses semantic similarity; you need both plus re-ranking.

```
┌────────────────────────────────────────────────────────────┐
│                       Query                                 │
│       "prescrição quinquenal honorários advocatícios"       │
└────────────────────────────────────────────────────────────┘
                          │
       ┌──────────────────┼───────────────────┐
       ▼                  ▼                   ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│ Dense (BGE)  │  │ Sparse (FTS5)│  │ Multi-query      │
│ Qdrant       │  │ SQLite       │  │ generation       │
│              │  │              │  │ (LLM rewrites    │
│ Top-50       │  │ Top-50       │  │ query 5 ways)    │
└──────────────┘  └──────────────┘  └──────────────────┘
       │                  │                   │
       └─────────► RRF ◄──┘◄──────────────────┘
                    │
                    ▼
       Top-100 candidates
                    │
                    ▼
       ┌────────────────────────┐
       │ Metadata filter        │
       │ - tenant_id (always)   │
       │ - vinculacao tier      │
       │ - date range           │
       │ - tribunal (if rel.)   │
       └────────────────────────┘
                    │
                    ▼
       ┌────────────────────────┐
       │ Cross-encoder rerank   │
       │ (BGE-reranker-v2 or    │
       │  Cohere rerank-v3)     │
       └────────────────────────┘
                    │
                    ▼
       Top-5 to top-10 to LLM
```

**Stack for solo dev:**

| Layer | Tool | Why |
|---|---|---|
| Dense embeddings | BGE-M3 (multilingual, handles PT-BR well) running locally on Mac Mini M4 | Free, fast, no PII leakage |
| Vector DB | Qdrant (self-hosted, Docker) | Strong metadata filtering, per-collection isolation |
| Sparse | SQLite FTS5 | Zero-ops, millions of docs no problem |
| Metadata | PostgreSQL | Joins, filters, outcome correlation |
| Re-ranker | BGE-reranker-v2-m3 (local) for default; Cohere rerank-v3 for top tier | Local for cost/PII, cloud for quality boost on premium plans |
| Multi-query | Local Qwen3 via Ollama | Cheap query rewriting |

Reciprocal Rank Fusion (RRF) for combining dense + sparse + multi-query is well-documented and straightforward to implement (~30 lines of Python).

### 5.4 Citation verification

The single most powerful pattern: **the AI can only cite sources that exist in the repertory.** Hallucinated citations become structurally impossible.

#### 5.4.1 Pre-generation: scoped retrieval

Before the drafter generates anything, the researcher agent retrieves N candidate sources for the thesis being argued and passes them to the drafter as the *only* citable material. The drafter's system prompt:

> You are drafting a section of a Brazilian legal petition. You may ONLY cite sources from the provided `<retrieved_sources>` list, using the exact `decision_id` or `doutrina_id` from each entry. Do not cite anything else. If no source in the list supports a claim, state the claim without citation or omit the claim. Mark each citation in the format `[CITE:decision_id]`.

#### 5.4.2 Post-generation: verification pass

After generation, run every citation through verification:

```python
# verifier.py
import re

CITATION_PATTERN = re.compile(r"\[CITE:([\w\-]+)\]")
CASE_NUMBER_PATTERN = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")

def verify_draft(draft_text: str, repertory) -> tuple[bool, list[str]]:
    failures = []
    
    # Check explicit [CITE:...] markers
    for match in CITATION_PATTERN.finditer(draft_text):
        cite_id = match.group(1)
        if not repertory.exists(cite_id):
            failures.append(f"Cited source not in repertory: {cite_id}")
    
    # Check loose citations (case numbers mentioned without [CITE:])
    for match in CASE_NUMBER_PATTERN.finditer(draft_text):
        case_num = match.group(0)
        if not repertory.case_exists(case_num):
            failures.append(f"Case number cited but not verified: {case_num}")
    
    # Check claimed quotations against source text
    for quote_match in find_quoted_passages(draft_text):
        cite_id = quote_match.attached_citation
        quoted = quote_match.text
        if cite_id and not repertory.text_contains(cite_id, quoted):
            failures.append(f"Quote not found in source {cite_id}: {quoted[:80]}...")
    
    return (len(failures) == 0, failures)
```

If verification fails, return the draft to the drafter with the failure list and instruct it to remove or replace the offending citations. Two strikes = fall back to citation-free draft and flag for the lawyer's manual addition. This loop typically converges in one retry.

This pattern is what most current Brazilian legal AI products *don't* do, and it's why they occasionally embarrass their users with fake citations. Solving it is genuinely defensible product positioning.

### 5.5 Tenant isolation architecture

The IP defensibility of the BYO-doutrina model collapses if isolation is sloppy. Build it right from day one — retrofitting is painful.

#### 5.5.1 Storage isolation

```
s3://repertory-public/
  └── jurisprudence/        # Tier 1, shared
  └── codes/
  └── sumulas/

s3://repertory-tenants/
  └── tenant-{uuid}/
      ├── doutrina/         # Tier 2, BYO
      ├── petitions/        # Tier 3, history
      └── outputs/          # AI-generated drafts, audit logs
```

Per-tenant IAM policies. No cross-tenant access at the storage layer — even your own application credentials should be scoped per-tenant when fulfilling a customer request.

#### 5.5.2 Vector DB isolation

Qdrant supports both metadata filtering on a shared collection and physically separate collections. **Use separate collections per tenant for tiers 2 and 3.** Metadata filtering on a shared collection is faster but exposes you to bugs where a missing filter leaks data across tenants. The performance cost of separate collections is negligible for the volume a single firm produces.

```
qdrant collections:
  - public_jurisprudence       (Tier 1, shared)
  - public_codes_sumulas        (Tier 1, shared)
  - tenant_{uuid}_doutrina     (Tier 2, isolated)
  - tenant_{uuid}_petitions    (Tier 3, isolated)
```

#### 5.5.3 Application-layer enforcement

Every retrieval call carries a `tenant_id`. The retrieval service refuses to query without one. Tier 1 is queried via the shared collections without `tenant_id` constraint; tiers 2 and 3 are queried via tenant-specific collections.

```python
# repertory/retrieval.py
class RepertoryRetriever:
    def query(self, query_text: str, tenant_id: str | None, tiers: list[str]):
        if "tenant_doutrina" in tiers and not tenant_id:
            raise ValueError("Tenant tier requested without tenant_id")
        if "tenant_petitions" in tiers and not tenant_id:
            raise ValueError("Tenant tier requested without tenant_id")
        
        candidates = []
        if "public" in tiers:
            candidates += self._query_public(query_text)
        if "tenant_doutrina" in tiers:
            candidates += self._query_tenant_collection(
                f"tenant_{tenant_id}_doutrina", query_text
            )
        if "tenant_petitions" in tiers:
            candidates += self._query_tenant_collection(
                f"tenant_{tenant_id}_petitions", query_text
            )
        return self._fuse_and_rerank(candidates)
```

Make this the *only* path to retrieval — no direct Qdrant queries elsewhere in the codebase.

#### 5.5.4 Embedding isolation

Don't share embeddings across tenants for tiers 2 and 3. Same text can be embedded twice if two tenants happen to upload the same book — that's fine, the storage cost is minimal and the legal cleanliness is worth it. Tier 1 (public domain) can share embeddings since the content is public.

#### 5.5.5 No cross-tenant aggregation features

Resist the temptation to add features like "most-cited doutrina across the platform" or "top-performing argumentative patterns." Even anonymized aggregation across tenants begins to look like operating a shared corpus and weakens the BYO defense. If you want this kind of feature later, build it as an opt-in research pool with explicit customer consent and a separate ToS clause.

### 5.6 Petition history: style and argument retrieval

The petition history serves two distinct retrieval modes that must not be confused:

#### 5.6.1 Mode A: Style retrieval

When generating any new petition, retrieve 2–3 past petitions of the *same type* (e.g., contestação trabalhista) for use as **style exemplars** in the prompt. The drafter sees concrete examples of how this firm structures, opens, closes, and formats — the rhythm, the verbosity, the rhetorical register, the section conventions.

```python
def retrieve_style_exemplars(tenant_id, petition_type, area, n=3):
    return repertory.query(
        query_text=f"{petition_type} {area}",
        tenant_id=tenant_id,
        tiers=["tenant_petitions"],
        filters={
            "tipo": petition_type,
            "area": area,
            "outcome__in": ["procedente", "procedente_parcial", "acordo_favoravel"],
        },
        order_by="-data_filing",  # recent first
        limit=n,
    )
```

Filter for *favorable outcomes* by default — you want the drafter learning from the firm's wins, not reproducing the structure of petitions that lost. If no favorable outcomes exist for that type yet, fall back to most recent.

#### 5.6.2 Mode B: Argument retrieval

When the drafter needs to argue a specific thesis ("inexistência de vínculo empregatício"), retrieve *sections of past petitions* where this firm argued the same thesis. The match is on the substance of the legal argument, not on the petition type.

```python
def retrieve_argument_precedents(tenant_id, tese: str, n=5):
    return repertory.query(
        query_text=tese,
        tenant_id=tenant_id,
        tiers=["tenant_petitions"],
        section_filter="merito.argumentacao",  # only retrieve the argumentation chunks
        boost_by="outcome_score",  # outcomes weighted: see 5.8
        limit=n,
    )
```

This is gold because:
- Same legal area, same tribunal context
- The lawyer already validated these arguments by filing them
- If outcomes are tracked, winning arguments float to the top
- The firm's signature interpretive moves carry forward

#### 5.6.3 Few-shot prompting integration

Both modes feed into the drafter's prompt as structured exemplars:

```
<style_exemplars>
  <petition outcome="procedente" date="2024-08-15">
    <section name="preambulo">FULANO DE TAL, já qualificado...</section>
    <section name="fatos">[...]</section>
    [...]
  </petition>
  [2 more]
</style_exemplars>

<argument_precedents>
  <argument tese="Inexistência de vínculo empregatício" outcome="procedente">
    <text>[...the argumentation paragraph from the past petition...]</text>
    <citations>[STJ-REsp-..., Tartuce-CLT-art3, ...]</citations>
  </argument>
  [4 more]
</argument_precedents>

<task>
Draft the seção de mérito for a new contestação in the case described in <case_context>.
The thesis to argue is: "Inexistência de vínculo empregatício."

Match the firm's voice and structural conventions shown in <style_exemplars>.
Build on the argumentative patterns shown in <argument_precedents>, but adapt to the
specific facts in <case_context>. Cite only sources in <retrieved_sources>.
</task>
```

Token budget: style exemplars are big. For Tier 1 customers, send full sections. For pricing-sensitive use, send compressed exemplars (preâmbulo + first paragraph of fatos + first thesis paragraph + pedidos closing) which captures most of the style signal at ~20% of the token cost.

#### 5.6.4 Improvement vs. imitation: elevating, not embalming

A real risk of style retrieval is that it ossifies the firm's writing — the AI keeps producing what the firm has always produced, even when the firm should be improving. The petition corpus is an *exemplar* repository, not a *ground-truth* one. Build mechanisms to keep it healthy:

**Recency weighting.** Petitions older than ~24 months get progressively de-weighted. Style and standards evolve; the AI should weight recent voice over voice from 5 years ago. Implement as a decay multiplier:

```python
def recency_weight(petition):
    years_old = (today() - petition.data_filing).days / 365
    return max(0.5, 1.0 - 0.05 * years_old)
```

**Explicit "exemplary" tagging (⭐).** Lawyers can mark specific past petitions as canonical — "this is the kind of work I want the AI to produce." Tagged petitions get a 1.5–2× retrieval boost. Build the tagging into the post-decision flow: after a winning judgment, prompt the lawyer "Mark this as exemplary?" alongside the outcome capture.

**Explicit "deprecated" tagging (🚫).** Conversely, lawyers can mark older petitions as no longer representative — argumentative patterns the firm has moved past, formats no longer used, citations of since-superseded jurisprudence. Deprecated petitions are excluded from retrieval but kept in storage for legal records.

**Best-practices overlay.** The drafter prompt includes both firm-specific exemplars *and* a small set of general legal-writing best practices (clear structure, modern Brazilian legal Portuguese conventions, readability). When firm style and best practices conflict, the drafter surfaces the choice rather than silently picking. Example: if the firm historically uses ALLCAPS section headers but modern conventions prefer mixed case, the drafter notes the divergence and lets the lawyer choose.

**Outcome-driven evolution.** Over time, correlation between exemplar choice and outcome becomes signal. Which arguments produced wins, which produced losses. After ~50 cases of data, the system can surface adjustments — "Your contestações trabalhistas leading with thesis A win 78%; with thesis B, 31%. Consider thesis A in similar matters." This is where Tier 3 stops being just style memory and becomes genuine institutional learning.

**Quality lifting from the public corpus.** When a past firm petition cites only TJ-level jurisprudence on a thesis where STJ binding precedent now exists, the drafter's research step surfaces the higher-tier authority and the new draft cites both — adopting the firm's voice while elevating the legal substance. The petition history is the floor of quality; the public repertory is the ceiling.

#### 5.6.5 What the customer sees: the petition library

Customers don't interact with Qdrant or embeddings — they see a folder. The UX should mirror how a paralegal organizes case files in a serious firm:

```
[Workspace: Escritório Silva & Associados]
├── 📁 Repertório (firm's library)
│   ├── 📁 Doutrina
│   │   ├── 📂 Direito Civil
│   │   │   ├── 📄 Tartuce - Manual de Direito Civil (17ª ed.)
│   │   │   ├── 📄 Gonçalves - Direito Civil Brasileiro
│   │   │   └── ➕ [adicionar livro]
│   │   ├── 📂 Direito do Trabalho
│   │   ├── 📂 Direito Tributário
│   │   └── ...
│   └── 📁 Petições protocoladas
│       ├── 📂 Trabalhista
│       │   ├── 📂 Contestações
│       │   │   ├── ⭐ Caso 0001234... (procedente, exemplar)
│       │   │   ├── ✓  Caso 0005678... (procedente parcial)
│       │   │   ├── 🚫 Caso 0009012... (improcedente, depreciada)
│       │   │   └── ...
│       │   ├── 📂 Recursos Ordinários
│       │   ├── 📂 Agravos de Petição
│       │   └── ...
│       ├── 📂 Cível
│       └── 📂 Tributário
└── 📁 Casos (active matters)
```

Clicking any petition opens the full original (not the anonymized version — the lawyer sees their own work in full) plus a sidebar showing:

- Outcome and trânsito em julgado date
- How many times this petition has been used as an AI exemplar
- Correlation between its use and outcomes of the petitions it influenced
- Tagging controls: ⭐ exemplar / ✓ representative / 🚫 deprecated / 📌 archive only

Side benefit beyond style: a fully searchable archive of the firm's own work. Most Brazilian firms desperately need this and rarely have it — petitions live scattered across email, drives, and PJe portals, and finding "the contestação we wrote 3 years ago for the case similar to this one" is a daily friction. Selling the AI gets much easier when the customer is already getting daily value from this archive function alone.

#### 5.6.6 Onboarding flow for petition history

Tier 3 starts empty. The fastest path to value is bulk-loading the firm's recent work at onboarding:

**Step 1 — Discovery.** Ask the firm: "Where does your past work live?" Common answers and the path for each:

| Source | Approach |
|---|---|
| Gestão jurídica software (Astrea, Projuris, ADVBOX, Esaj escritório) | API export or batch CSV/PDF export |
| PJe procurador panel | Bulk-fetch via MNI consulta over the firm's caseload using the lawyer's certificate; download manifestações per case |
| Cloud drive folder (Dropbox, Drive, OneDrive) | Bulk PDF upload via drag-drop |
| Old laptop or local server | Sync agent + bulk upload |
| eSAJ / TJSP (no MNI) | Authenticated session + per-case download with the lawyer's certificate |

The MNI path is particularly nice when the firm has been filing electronically for years — you can recover their entire historical output from the courts themselves, no need to find it in their internal systems.

**Step 2 — Bulk ingestion.** The customer points your system at the source. Overnight pipeline: PDF parsing, structural extraction (per 5.2.3), anonymization (per 5.7), outcome backfill from MNI consulta, indexing into Tier 3. Customer wakes up to a populated repertory.

**Step 3 — First-week curation.** After ingestion, the system surfaces the top 20–30 petitions for the lawyer to review and tag (⭐ exemplar / ✓ representative / 🚫 deprecated). This 30-minute exercise dramatically improves output quality and gives the customer confidence in what the AI will produce. Frame it as "training your AI assistant on your style" — which is literally what it is.

**Step 4 — Continuous capture.** Every petition filed through the system is auto-captured into Tier 3 with full structural fidelity (the system already knows the section structure, since it generated the draft). Outcomes backflow automatically as cases progress through the TPU pipeline. No further customer effort required.

The compounding curve: typically by day 60–90 of regular use, the firm has 50–200 firm-specific exemplars per common petition type, and drafts become indistinguishable from the lawyer's own writing. After 6 months, the system has enough outcome data to start nudging the firm toward winning patterns. After 12 months, switching costs for the customer are real — the AI knows their voice, their preferred arguments, their tribunal-specific tactics, and which judges respond to what. This is the moat. A competitor's generic-petition-writer can't catch up without the same accumulation period.

### 5.7 PII handling in petition history

Old petitions contain client names, CPFs, salary figures, witness statements, medical details. Even within a single tenant, you don't want PII bleeding across cases — Case A's client name shouldn't appear in retrieval results for Case B unless legally relevant.

#### 5.7.1 Anonymization at ingest

When a petition is added to the repertory (either auto-captured at filing time or uploaded at onboarding), run an anonymization pass:

```python
def anonymize_for_repertory(petition_text: str, case_metadata) -> str:
    # Replace named parties with role tokens
    text = replace_party_names(petition_text, case_metadata.parties)
    # Mask CPFs, CNPJs, RGs
    text = mask_documents(text)
    # Mask specific monetary values (replace with magnitude bucket)
    text = bucket_monetary_values(text)
    # Optionally: mask witness names, addresses
    text = mask_personal_identifiers(text)
    return text
```

The anonymized version goes into the embeddings and into LLM prompt context. The original signed PDF stays in object storage with normal access controls — you don't lose anything, you just don't surface raw PII through the retrieval layer.

This matters more when the drafter uses cloud LLMs (Claude, GPT). For purely local inference (your Ollama stack), the PII never leaves the firm's perimeter anyway, but anonymization is still good hygiene for cross-case retrieval cleanliness.

#### 5.7.2 Hybrid inference routing

For petition drafting, run the high-context steps (prompt with full retrieved context) on local models when possible, and reserve cloud LLMs for tasks where the input is already de-identified (legal reasoning on anonymized facts, jurisprudence summarization, public-corpus questions). Your existing OpenClaw + Ollama stack is well-suited for this.

### 5.8 Outcome tracking

A petition's outcome multiplies its value as an exemplar. Two paths to capturing it:

#### 5.8.1 Manual

When a case closes, the lawyer marks: `procedente` / `procedente_parcial` / `improcedente` / `acordo` / `desistencia` / `extinto_sem_merito`. UI-driven, accurate, but requires lawyer effort. Most firms won't do this consistently.

#### 5.8.2 Automatic from TPU + sentence parsing

Detect outcomes from movements in the case file:

| TPU code | Movement | Outcome inference |
|---|---|---|
| 132 | Sentença com resolução do mérito | Trigger sentence parsing |
| 1042 | Procedência | `procedente` (high confidence) |
| 1043 | Improcedência | `improcedente` (high confidence) |
| 1041 | Procedência parcial | `procedente_parcial` |
| 1051 | Homologação de acordo | `acordo` |
| 1054 | Desistência | `desistencia` |
| 970 | Trânsito em julgado | Lock outcome |

When the trigger fires, fetch the sentence document and run an LLM extractor that identifies which side prevailed and on which pedidos. Mark `outcome_confidence` based on whether you have just the TPU code (medium), the parsed sentence (high), or manual lawyer confirmation (very high).

#### 5.8.3 Outcome-weighted retrieval

Define `outcome_score`:

```python
OUTCOME_SCORES = {
    "procedente": 1.0,
    "procedente_parcial": 0.7,
    "acordo_favoravel": 0.6,
    "desistencia": 0.3,
    "improcedente": 0.1,
    "unknown": 0.5,
}
```

Multiply this into the retrieval ranking. The drafter sees winning arguments first; losing arguments are still retrievable but de-prioritized.

#### 5.8.4 Provenance and feedback loop

Every drafter output that uses petition-history exemplars records the provenance: which exemplars influenced this draft. When the new petition is filed and eventually has its own outcome, you can correlate: did exemplars-from-winners produce winners? This becomes a feedback loop for ranking weights over time. Don't over-engineer this in v1, but instrument the data so you have it later.

### 5.9 Putting it together: the drafter agent's flow

Concretely, when a new movement triggers a draft:

```
Trigger: TPU code 193 (decisão recorrível) on case 0001234-56.2024.5.02.0001
                          │
                          ▼
[1] Analyzer agent
    Reads the decision document, classifies:
    - "Decisão denegou medida liminar."
    - Recommended action: "Agravo de instrumento"
    - Deadline: 15 dias úteis
                          │
                          ▼
[2] Researcher agent
    Generates retrieval queries:
    - "agravo de instrumento contra denegação de liminar"
    - "requisitos da tutela de urgência CPC art. 300"
    - "[case-specific thesis]"
    Retrieves from:
    - public/jurisprudence (vinculante + persuasivo_forte first)
    - tenant/doutrina (CPC commentaries on tutela de urgência)
    - tenant/petitions (past agravos this firm filed, weighted by outcome)
                          │
                          ▼
[3] Drafter agent
    Inputs:
    - <case_context>: capa, partes, decisão impugnada, fatos relevantes
    - <retrieved_sources>: 8 jurisprudence + 3 doutrina passages
    - <style_exemplars>: 3 past agravos from this firm (favorable outcomes)
    - <argument_precedents>: 5 thesis-matched passages from past petitions
    - <constraints>: cite only from retrieved_sources, follow style_exemplars
    Output: full draft of agravo de instrumento with [CITE:...] markers
                          │
                          ▼
[4] Verifier
    - Every [CITE:...] resolves to a source in retrieved_sources
    - Every quoted passage exists in the cited source
    - Every case number cited is in the public corpus
    - If failures: return to drafter with failure list (max 2 retries)
                          │
                          ▼
[5] Local agent (lawyer's machine)
    Renders draft as PDF preview
    Shows: AI rationale, citations, deadline, exemplars used
    Lawyer reviews, edits if needed, clicks "Assinar e Protocolar"
                          │
                          ▼
[6] Signing + filing (Section 2)
                          │
                          ▼
[7] Audit trail + petition-history capture
    The filed petition is automatically ingested back into Tier 3.
    Eventually, when the agravo is decided, outcome backflows to update its exemplar weight.
```

The whole loop is roughly 30 seconds of compute (excluding lawyer review time) on your Mac Mini M4 with local inference, or 5–10 seconds with cloud LLMs.

### 5.10 v1 ingestion targets

For the 90-day solo build, the realistic ingestion plan:

**Tier 1 (build once, ship to all tenants):**
- Constitution, CPC, CC, CLT, CTN, CDC, CP, CPP — straight from planalto.gov.br
- All STF Súmulas Vinculantes (~58)
- All STF Súmulas (~736)
- All STJ Súmulas (~660)
- TST Súmulas + Orientações Jurisprudenciais
- Top ~500 leading STF/STJ decisions per major area (auto-rank by citation count from DataJud)
- CNJ resolutions (esp. 615/2025), OAB ethical code

That's ~3,000–4,000 documents. One developer-week of focused ingestion + structural extraction + indexing.

**Tier 2 (per-tenant, customer uploads):**
- Self-service upload UI: drag PDF → background ingestion → searchable in ~5 minutes per book
- Support a "starter pack" UX: customer can also paste references to books they own, and your system pre-indexes the public metadata (table of contents, author, edition) so they can refer to these in conversations even before uploading the PDF — useful for "did you mean Tartuce or Gonçalves?" disambiguation

**Tier 3 (per-tenant, auto-captured + onboarding upload):**
- At onboarding: customer can bulk-upload their last 2–3 years of filed petitions as PDFs. Your pipeline anonymizes, structurally extracts, and indexes overnight.
- Going forward: every petition filed *through* your system is auto-captured into Tier 3 with full structural fidelity (the AI knows exactly what sections it generated, no parsing needed).
- Outcome is tracked automatically from the case's TPU stream once the system is monitoring it.

The compounding effect kicks in fast: within 60 days of a firm using the product daily, Tier 3 typically has 50–200 high-quality firm-specific exemplars per common petition type, and the drafts start sounding genuinely indistinguishable from the lawyer's own writing.

---

## 6. V1 Critical Features

Beyond the core MNI integration, repertory, and drafter pipeline, three features must ship in v1 because each one independently widens the addressable market and differentiates the product.

### 6.1 The Prazo Engine

Brazilian processual deadlines are a genuine minefield. Lawyers lose mandates and face OAB ethics issues over miscounted deadlines. There is no good open-source Brazilian prazo engine, every legal-tech product handles deadlines fuzzily, and a correct engine becomes a standalone selling point — you can lead the conversation with "we count your prazos correctly with explainable logic" before the AI features even land.

**This must be deterministic, not LLM-based.** A prazo calculator that hallucinates is malpractice waiting to happen. The LLM may *describe* a calculation in plain language, but the math runs through a rules engine with full auditability.

#### 6.1.1 The legal framework

The CPC (Lei 13.105/2015) reformed prazo counting in 2016 and the rules cascade from there:

| Rule | Source | Implication |
|---|---|---|
| Atos processuais contam-se em dias úteis | CPC art. 219 | Default for most prazos: weekends and feriados excluded |
| Atos materiais contam-se em dias corridos | CPC art. 219, parágrafo único | Prescrição, decadência: dias corridos |
| Prazo começa a correr no primeiro dia útil seguinte ao da intimação | CPC art. 224 | The intimação date is "dia zero" |
| Suspensão durante recesso forense (20/dez a 20/jan) | Lei 5.010/66, CPC art. 220 | All processual prazos suspended in this window |
| Suspensão por força maior, calamidade, indisponibilidade do sistema | CPC art. 221, Resolução CNJ 185/2013 | Per-tribunal portarias declare these |
| Prazo em dobro para Defensoria, MP, Fazenda Pública, litisconsortes com diferentes procuradores | CPC arts. 180, 183, 186, 229 | Multiplier on the base prazo |
| Feriados forenses estaduais e municipais | Per-tribunal calendars | Vary by tribunal location |
| Trabalhista: prazos em dias úteis (após Lei 13.467/17) | CLT art. 775 | Trabalhista alignment with CPC |
| Eleitoral: prazos em dias corridos | Lei 9.504/97 | Different from civil/trabalhista |
| Penal: regras próprias (CPP) | CPP art. 798+ | Different from civil; some material |

**The interrupção vs. suspensão distinction:**
- **Suspensão** pauses the prazo; when it resumes, the remaining days continue from where they stopped.
- **Interrupção** restarts the prazo from zero.

Mixing these is a classic source of error. The engine must track each prazo's state explicitly.

#### 6.1.2 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Prazo Engine                              │
│                                                              │
│  ┌─────────────────┐    ┌──────────────────┐                │
│  │ Movement →      │    │ Calendar Service │                │
│  │ Prazo type map  │    │ - Feriados nac   │                │
│  │ (TPU code →     │◄──►│ - Feriados est   │                │
│  │  prazo_type)    │    │ - Recesso        │                │
│  └────────┬────────┘    │ - Suspensões     │                │
│           │             │ - Por tribunal   │                │
│           ▼             └──────────────────┘                │
│  ┌─────────────────────────────────────┐                    │
│  │ Rules Engine                         │                    │
│  │ - Base duration (5/10/15/30 dias)    │                    │
│  │ - Counting mode (úteis/corridos)     │                    │
│  │ - Multipliers (dobro)                │                    │
│  │ - Suspensão windows                  │                    │
│  │ - Interrupção triggers               │                    │
│  └────────┬────────────────────────────┘                    │
│           ▼                                                  │
│  ┌─────────────────────────────────────┐                    │
│  │ Calculator                           │                    │
│  │ - Computes deadline date             │                    │
│  │ - Generates step-by-step explanation │                    │
│  │ - Produces alert schedule            │                    │
│  └────────┬────────────────────────────┘                    │
└───────────┼──────────────────────────────────────────────────┘
            ▼
       PrazoResult: { deadline, explanation, alerts }
```

#### 6.1.3 Data model

```python
@dataclass
class PrazoRule:
    """Static rules indexed by TPU code or movement type."""
    tpu_code: int                   # CNJ TPU codigo
    prazo_type: str                 # 'contestacao', 'replica', 'recurso_apelacao', etc.
    base_dias: int                  # 15, 30, etc.
    counting_mode: str              # 'uteis' | 'corridos'
    legal_basis: str                # 'CPC art. 335', 'CLT art. 847', etc.
    can_double: bool                # Is "prazo em dobro" applicable?
    triggers_on: str                # 'intimacao' | 'publicacao' | 'juntada'

@dataclass
class CalendarEvent:
    """Non-counting days."""
    date: date
    type: str                       # 'feriado_nacional', 'feriado_estadual',
                                    # 'feriado_forense', 'recesso', 'suspensao'
    tribunal: Optional[str]         # None for nacional, set for tribunal-specific
    portaria: Optional[str]         # Reference to the act declaring it
    description: str

@dataclass
class Prazo:
    """An individual prazo instance for a case."""
    id: str
    case_number: str
    movement_id: str                # The triggering movement
    prazo_type: str
    legal_basis: str
    
    triggered_at: datetime          # When the trigger occurred (intimação, publicação)
    starts_at: date                 # First counting day (dia 1, primeiro dia útil seguinte)
    deadline: date                  # Final day to act
    
    base_dias: int
    counting_mode: str              # 'uteis' | 'corridos'
    multiplier: float               # 1.0 default, 2.0 for prazo em dobro
    
    suspensions: list[CalendarEvent]  # Suspensions that affected this prazo
    
    explanation: str                # Step-by-step prose explanation for the lawyer
    status: str                     # 'aberto' | 'cumprido' | 'expirado' | 'suspenso'
    alerts_scheduled: list[date]    # When to ping the lawyer
```

#### 6.1.4 The calculation algorithm

```python
def calculate_prazo(rule: PrazoRule, trigger_date: date, case_context: CaseContext, calendar: Calendar) -> Prazo:
    # 1. Determine "dia zero": intimação/publicação/juntada date
    #    Per CPC art. 224, prazo starts on the first dia útil after dia zero
    starts_at = next_dia_util(trigger_date, calendar, case_context.tribunal)
    
    # 2. Determine multiplier
    multiplier = 1.0
    if rule.can_double and case_context.party_type in DOUBLE_PRAZO_PARTIES:
        multiplier = 2.0
    if case_context.has_litisconsortes_diff_procuradores and rule.can_double:
        multiplier = 2.0  # CPC art. 229
    
    total_days = int(rule.base_dias * multiplier)
    
    # 3. Count days
    if rule.counting_mode == 'uteis':
        deadline = count_dias_uteis(starts_at, total_days, calendar, case_context.tribunal)
    else:
        deadline = count_dias_corridos(starts_at, total_days, calendar, case_context.tribunal)
    
    # 4. Apply any active suspensões that intersect the prazo window
    #    (recesso forense, indisponibilidade declarada, etc.)
    suspensions = calendar.suspensions_in_window(starts_at, deadline, case_context.tribunal)
    if suspensions:
        deadline = extend_for_suspensions(deadline, suspensions, calendar, case_context.tribunal, rule.counting_mode)
    
    # 5. Build explanation
    explanation = build_explanation(rule, trigger_date, starts_at, total_days, multiplier, suspensions, deadline)
    
    # 6. Schedule alerts
    alerts = schedule_alerts(deadline, urgency=rule.urgency)
    
    return Prazo(...)


def count_dias_uteis(start: date, n: int, calendar: Calendar, tribunal: str) -> date:
    """Count n dias úteis forward, skipping weekends and non-counting calendar events."""
    current = start
    counted = 0
    while counted < n:
        if calendar.is_dia_util(current, tribunal):
            counted += 1
            if counted == n:
                return current
        current += timedelta(days=1)
    return current
```

#### 6.1.5 The explanation field

This is what makes the engine trustworthy. Every calculated prazo carries a human-readable explanation:

> **Prazo: Contestação**
>
> Caso 0001234-56.2024.5.02.0001 — Justiça do Trabalho, TRT-2 (São Paulo)
>
> - **Trigger:** Citação válida em 15/04/2026 (terça-feira)
> - **Base legal:** CLT art. 847 — 5 dias úteis para apresentação de defesa em audiência una; em rito sumaríssimo, prazo coincide com a audiência
> - **Início da contagem:** 16/04/2026 (primeiro dia útil seguinte à citação, conforme CPC art. 224)
> - **Modo de contagem:** dias úteis (CLT art. 775, redação dada pela Lei 13.467/17)
> - **Duração base:** 5 dias úteis
> - **Multiplicador:** 1.0 (parte privada, sem litisconsortes com procuradores diferentes)
> - **Suspensões aplicáveis:** nenhuma no período
> - **Feriados no período:** Tiradentes (21/04/2026, terça-feira) — não contado
> - **Cálculo:** 16/04 (dia 1) → 17/04 (dia 2) → 20/04 segunda (dia 3) → 22/04 quarta (dia 4) → 23/04 quinta (dia 5)
> - **Prazo final: 23/04/2026 (quinta-feira)**
>
> **Alertas programados:** 21/04 (D-2), 22/04 (D-1), 23/04 manhã (dia do prazo)

This explanation is generated by templated assembly, not by LLM. It's deterministic, auditable, and the lawyer can verify each step. If the engine is wrong, it's wrong in a traceable way that you can fix; an LLM-generated calculation is wrong opaquely.

#### 6.1.6 Calendar service

The calendar is the operational soft-spot — it must be kept current and tribunal-specific. Design:

- **National feriados:** static table, rarely changes
- **Estadual feriados:** per-state table, ~5-10 per state, mostly stable
- **Municipal feriados:** matters because the tribunal location determines applicability; per-comarca table
- **Recesso forense:** 20/dez–20/jan nationally per Lei 5.010/66
- **Suspensões por portaria:** dynamic. Tribunals publish portarias declaring indisponibilidade or suspensão (system outage, security incident, calamidade). These must be ingested as they're published.

For suspensões por portaria, build an ingestion job that monitors each tribunal's site (or use the CNJ's consolidated portaria feed where available) and parses the declarations into calendar events. This is exactly the kind of work that vendors like Alerte already do for monitoring purposes — worth checking if you can buy the calendar data feed rather than build the scraper farm.

**Critical:** the calendar service is shared infrastructure across all tenants. There's no per-tenant data here — the feriados in São Paulo are the same for every São Paulo lawyer. Cache aggressively, refresh daily.

#### 6.1.7 Integration with the analyzer agent

Every new movement in the overnight pipeline goes through the analyzer, which:

1. Maps the TPU code to a `prazo_type` (or determines no prazo opens)
2. If a prazo opens, calls the prazo engine
3. The resulting `Prazo` object joins the case timeline with full explanation
4. Alert schedule is registered with the notification system
5. The drafter can be triggered ahead of the deadline if a draft is appropriate

The lawyer never has to count manually, but always has the full reasoning available if they want to audit.

#### 6.1.8 Why this is a moat by itself

Most legal tech in Brazil treats prazo as a calendar entry. The hard part — correct computation with explainable logic across 100+ prazo types and dozens of edge cases — is consistently done badly or not at all. Customers will tell you they have a system, and when you show them an explainable engine that catches the trabalhista vs. cível dia-úteis distinction, the prazo em dobro for litisconsortes, and the 2024 portaria that suspended TRT-15 for three days, they'll switch.

Lead with this in sales. The AI features close the deal; the prazo engine opens the door.

### 6.2 Second-Opinion Mode

The drafter generates petitions, the lawyer reviews. But many sophisticated lawyers — especially senior partners — will reject "AI writes for me, I edit." They'll happily adopt "I write, AI critiques against the firm's standards and the public corpus." Same architecture, different framing, dramatically wider acceptable user base.

#### 6.2.1 The flow

```
Lawyer pastes/uploads draft → 
  Researcher retrieves relevant jurisprudência + doutrina + similar prior firm petitions →
    Reviewer agent runs structured critique →
      Output: critique with severity levels and citations
```

This is the existing retrieval stack with a different prompt template at the end. No new infrastructure.

#### 6.2.2 The reviewer agent prompt

The critique is structured into categories with explicit severity:

```python
CRITIQUE_CATEGORIES = [
    "missing_arguments",          # Theses the firm typically raises but this draft doesn't
    "missing_citations",          # Authority that supports the draft's claims but isn't cited
    "weak_citations",             # Cited authority that's been superseded or distinguished
    "unaddressed_counterargs",    # Likely opposing arguments not preempted
    "factual_gaps",               # Claims without supporting facts or evidence references
    "structural_issues",          # Section ordering, missing required parts (CPC art. 319)
    "style_drift",                # Departures from this firm's typical voice
    "ethics_flags",               # Language risks (desrespeito, má-fé, inadequate evidence)
    "procedural_errors",          # Wrong tribunal, wrong rito, wrong remedy
]

SEVERITIES = ["critical", "important", "suggestion", "nitpick"]
```

The reviewer's output:

```json
{
  "summary": "Draft is structurally sound. Three important findings: missing recent STJ precedent on thesis A, untreated counterargument about prescrição, and one citation that has been distinguished by Tema 1234.",
  "findings": [
    {
      "category": "missing_citations",
      "severity": "important",
      "location": "section: fundamentos, paragraph 3",
      "issue": "Argument about responsabilidade objetiva is asserted without authority. STJ Tema 985 (REsp 1.737.412/SE) is directly on point and binding on the lower courts.",
      "suggested_action": "Add citation to STJ Tema 985 with the binding effect language.",
      "supporting_source": "stj-tema-985"
    },
    {
      "category": "weak_citations",
      "severity": "critical",
      "location": "section: fundamentos, paragraph 7",
      "issue": "Cited STJ REsp 1.234.567 (2014) on prescrição has been distinguished by Tema 1234 of STJ (2023) for cases involving public administration, which is the case here.",
      "suggested_action": "Replace citation with STJ Tema 1234 or address the distinguishing.",
      "supporting_source": "stj-tema-1234"
    },
    ...
  ]
}
```

#### 6.2.3 UI presentation

The lawyer sees the original draft with annotations, critique-mode style:

- 🔴 Critical findings inline with the affected paragraph
- 🟠 Important findings in a sidebar
- 🟡 Suggestions in a "consider" section
- ⚪ Nitpicks collapsed by default

Each finding has a one-click "show me the source" that opens the cited authority alongside, and a "rewrite this paragraph addressing the finding" button that hands the paragraph + finding to the drafter for a localized revision.

#### 6.2.4 Why this widens the market

The drafter market is "lawyers willing to let AI write." The reviewer market is "lawyers writing legal briefs" — which is essentially every lawyer. Many partners who reject ghostwriting AI will eagerly adopt review AI, especially when the output cites real authority and flags real risks. Adoption pattern: lawyer tries reviewer mode, finds value, gradually trusts the system enough to try drafter mode for routine work.

This is also a strong onboarding wedge: "Bring us your last petition, we'll review it for free as a demo." The output speaks for itself — "we found three important issues including a citation that's been superseded" is a much more compelling pitch than "try our drafter."

### 6.3 The Contradictory-Jurisprudence Flag

This is the intellectual-honesty differentiator. Most legal AI products retrieve only authority that *supports* the user's position, producing drafts that are blind-sided when opposing counsel cites the obvious counter-decision. A draft that anticipates and addresses opposing arguments is materially better preparation, and the lawyer chooses whether to address them preemptively in the filing or hold them for the réplica.

#### 6.3.1 Architecture: the "opposing counsel" retrieval pass

Every drafter run also triggers a parallel retrieval with inverted polarity:

```python
def draft_with_contraponto(case_context, thesis):
    # Standard retrieval — supporting authority for the firm's thesis
    supporting = researcher.retrieve(thesis, polarity="supporting")
    
    # Adversarial retrieval — strongest authority for the opposing thesis
    opposing_thesis = invert_thesis(thesis)  # LLM call: state the opposite legal proposition
    opposing = researcher.retrieve(opposing_thesis, polarity="supporting")
    
    # Filter opposing to "credible" — must be hierarchically strong
    # No point flagging a TJ-RJ decision against the firm; flag STJ/STF only
    opposing_credible = [o for o in opposing if o.autoridade_tier <= 4]
    
    # Drafter receives both
    draft = drafter.generate(
        case_context=case_context,
        thesis=thesis,
        supporting_sources=supporting,
        opposing_sources=opposing_credible,
        instruction="Draft the petition in the firm's voice. Address the strongest opposing arguments preemptively in a 'Da antecipação aos argumentos contrários' subsection, OR mark them for the lawyer's strategic review with a [[CONTRAPONTO]] flag if you judge they're better held for the réplica."
    )
    
    return draft
```

#### 6.3.2 The "invert_thesis" step

A small but careful LLM call that produces the opposite legal proposition:

- Input: "A prescrição quinquenal do art. 206, § 5º, I do CC se aplica a esta cobrança"
- Output: "A prescrição decenal do art. 205 do CC se aplica a esta cobrança"

Or:

- Input: "Vínculo empregatício caracterizado pelos arts. 2º e 3º da CLT"
- Output: "Inexistência de vínculo empregatício; relação de natureza autônoma"

The opposing thesis must be the strongest credible counter-argument, not just a negation. This is genuinely useful prompt engineering — feed it good few-shot examples for legal counter-thesis generation.

#### 6.3.3 Output presentation

In the draft, opposing arguments appear in two possible forms:

**Inline preemption** — when the AI judges the counter-argument should be addressed in this filing:

> "(...) cumpre antecipar o argumento contrário, frequentemente suscitado pela parte adversa em casos análogos, no sentido de que [contraponto]. Tal tese, contudo, não se sustenta porque [resposta], conforme entendimento consolidado em [CITE:stj-tema-1234]."

**Strategic flag** — when the AI judges the counter-argument should be reserved for the réplica:

> "[[CONTRAPONTO ESTRATÉGICO — não incluído no draft]]
> Adversário provavelmente sustentará: [contra-tese] com fundamento em [CITE:stj-acordao-xyz, de autoria do Min. ABC, Terceira Turma, 2024]. 
> Sugestão de tratamento: aguardar réplica para responder; resposta consistiria em [análise]."

The lawyer chooses per case whether to address preemptively or hold. The flag is in the draft for the lawyer's eyes only — it's stripped before filing.

#### 6.3.4 The "contraponto previsto" subsection in the petition

For preemptive addressing, a dedicated section structure helps. Most Brazilian petition templates don't formally include a "counter-argument anticipation" section, but it fits cleanly into the fundamentação:

```
DOS FUNDAMENTOS JURÍDICOS

I. Da tese principal: [main argument]
II. Do amparo legal e jurisprudencial: [supporting authority]
III. Da antecipação aos possíveis argumentos contrários: [contraponto + resposta]
   a) [counter-argument 1] - resposta
   b) [counter-argument 2] - resposta
IV. Conclusão dos fundamentos
```

This is an intellectually-honest petition structure that signals to the judge "we've thought about this thoroughly." It's also the kind of thing that distinguishes a senior associate's work from a junior's, and it's the differentiator that makes your AI feel like the former rather than the latter.

#### 6.3.5 Why this matters for positioning

Most current Brazilian legal AI products will write a confident, one-sided petition that doesn't anticipate what's coming. When the lawyer files it and gets a contestação citing the obvious STJ decision the AI didn't mention, they lose trust in the tool. Your tool says, before they file: "the opposing side will likely cite this decision; here's how to address it." That's the difference between an AI that writes legal text and an AI that thinks about cases.

Combined with the citation verification (5.4), the contradictory-jurisprudence flag makes a strong product story: every citation in our drafts exists, every superseded decision is flagged, every likely opposing argument is anticipated. No competitor in Brazil does all three. This is your defensible differentiation.

---

## 7. Roadmap: Phase 2 and Beyond

The features below are deliberately deferred — each is valuable, but v1 ships without them. They're listed roughly in priority order for phase 2 sequencing.

### 7.1 Phase 2 (target: 6–9 months post-launch)

#### 7.1.1 Case timeline as primary UI

A per-case timeline that interleaves court movements, AI analyses, drafted petitions, lawyer decisions, deadlines, and related research — replacing the flat-list view that all current legal software defaults to. The lawyer scrolls through a case and understands its entire history at a glance: what happened, what the AI thought about it, what was decided, what's pending, what comes next.

**Why phase 2:** the underlying data is already captured by v1's analyzer and audit log; this is a UI layer on top of existing infrastructure. The reason it's deferred is that v1 needs to ship with a simpler list-and-detail view first to validate the core loop. Once the loop is working, the timeline view becomes the moment of "this is genuinely better than what I had before."

**Bonus:** the timeline view doubles as the audit trail rendered for humans, satisfying Resolução CNJ 615/2025 contestabilidade requirements in a UX-first way. It's also the answer to "how does a partner taking over a case mid-stream understand it quickly" — currently a real pain point in firms with high case turnover.

#### 7.1.2 WhatsApp thin client

Lawyers in Brazil live in WhatsApp. A thin WhatsApp interface for high-frequency interactions:

- Deadline alerts ("D-3 days for contestação on case X — draft ready for review")
- Urgent movement notifications ("Decisão denegou liminar — agravo recommended within 15 dias")
- Quick consultations ("What's the prazo for resposta in case X?")
- Yes/no decision prompts ("Should I generate the agravo? Y/N")
- Status checks ("Status of case X")
- Client communication automation: status updates to clients about their cases ("Sua audiência foi marcada para 15/06") with templated, lawyer-approved messages

**Critical:** WhatsApp is for lightweight interactions only. Drafting and signing stay on the desktop UX where the certificate and review workflow live. WhatsApp is for the moments when the lawyer is in a meeting, a hearing, or a courtroom and needs to answer a question or trigger an action without opening their laptop.

**Why phase 2:** ties to your existing WhatsApp work on Lança/Chamei — you have the integration knowledge. But WhatsApp Business API has its own compliance and rate-limit considerations that need careful handling, and the daily UX should mature in v1 before adding WhatsApp as the side channel.

#### 7.1.3 Document understanding for incoming evidence

The AI reads decisions well because they have predictable structure. But cases also generate evidence (medical reports, financial records, technical opinions) and opposing filings that the lawyer needs to digest. A document-understanding pipeline that:

- Ingests these documents
- Summarizes them
- Identifies key claims
- Flags inconsistencies and vulnerabilities
- Cross-references against the case's existing facts

This is what tools like Harvey AI emphasize for the U.S. market; Brazilian competitors don't generally do it well. The technical lift is moderate — extending the existing PDF parsing and structural extraction to non-judicial documents.

**Why phase 2:** v1 focuses on output (generating petitions). Phase 2 expands input intelligence (digesting what the case throws at the firm).

### 7.2 Phase 3 (target: 12–18 months post-launch)

#### 7.2.1 Adversário intelligence

Profile the opposing party using public sources. Their case history, default rates, settlement patterns, which arguments tend to succeed against them, who their typical lawyers are, their active processes. DataJud has the metadata; Judit/Escavador sells this as a feature. For a corporate defendant being sued, knowing they settle 80% of similar claims and how much they typically pay changes the strategy fundamentally.

**Why phase 3:** moderate complexity, meaningful token cost for the analytical layer, and requires either substantial DataJud query volume or a paid data-layer subscription. Better introduced after v1 has paying customers funding the data layer.

**Architectural note:** capturing insights from the opposing lawyer or firm in similar processes — their argumentative patterns, defense strategies, frequent citations, success rates — is genuinely game-changing intelligence. Implement as periodic profile builds (per opposing OAB number, per opposing firm CNPJ) cached to keep token costs manageable, refreshed on a slow cadence (monthly).

#### 7.2.2 Tribunal and judge intelligence

Aggregated jurimetria from DataJud and the firm's own experience: which judges grant tutela antecipada freely, which câmaras of TJSP reverse first-instance decisions on certain themes at predictable rates, which ministros at STJ have well-known positions on particular issues. Frame as descriptive context for the lawyer's strategy, never as a recommendation about merit — Resolução CNJ 615/2025 is most nervous about anything resembling decision prediction.

**Implementation pattern:** for each case, fetch the assigned juiz and orgão julgador, look up their jurimetric profile (cached), surface as "context" in the case timeline and as input to the drafter (e.g., "this juíza tends to require more documentary evidence at the inicial stage; consider front-loading").

**Why phase 3:** politically sensitive given current CNJ regulatory mood; better introduced after the product has established credibility through other features.

#### 7.2.3 Research mode (separate from drafting)

Sometimes the lawyer doesn't want a draft — they want to understand the law on a question. "What's the current STJ position on prescrição em ações de improbidade administrativa post-Lei 14.230/21?" The system already has the components (researcher agent + repertory) to answer this directly with citations, in conversation.

**Why phase 3:** low technical lift, but commits product surface area to a different use case. v1 should establish identity as "the AI that drafts and files" before adding "the AI that researches" — otherwise the positioning gets muddled. Once v1 is established, research mode becomes a high-frequency entry point that pulls in lawyers who aren't ready for drafting.

#### 7.2.4 What-if / strategy scenarios

When the firm is deciding whether to take a case or how to structure the inicial, run multiple drafts under different theoretical strategies and compare projected outcomes (using the tribunal/judge intelligence from 7.2.2). 

> "Filing for X with thesis A: estimated 60% favorable, R$ Y expected.
> Thesis B: 35% favorable but R$ 3Y expected.
> Settle at current offer: R$ 0.8Y certain."

This is decision-support, not legal opinion (which only the lawyer renders), but it's the kind of structured comparison currently done informally if at all. For sophisticated litigation firms this is genuinely valuable.

**Why phase 3:** depends on tribunal/judge intelligence being mature, depends on having enough customer outcome data to calibrate probability estimates.

#### 7.2.5 Honorários and case-economics intelligence

Brazilian law firms struggle with pricing because most cases involve some mix of fixed fees, success fees, and honorários sucumbenciais. With case-history data, the system can project case economics: typical timeline for this case type in this tribunal, typical outcome distributions, typical sucumbência amounts when the firm wins, typical costs incurred. A small economics layer on top of case data lets you give partners weekly views like "your active cases have R$ X expected revenue at completion, weighted by win probability and timeline."

**Why phase 3:** firm-management territory rather than legal-practice territory. Most legal AIs don't touch it, but partners would pay for it separately. Best introduced after v1 has established the lawyer-facing product so the partner-facing product can build on the same data.

### 7.3 Phase 3+ (long-term roadmap)

#### 7.3.1 Doutrina publisher partnerships

Long-term, securing corpus licenses from one or two major publishers (Forense, RT/Thomson Reuters, JusPodivm, Saraiva) — even limited ones — would be a step-change in product quality for customers without extensive personal libraries. Hard sales motion, but a Brazilian legal AI startup actually has more credibility for this than foreign players. The clean model is: license a corpus that's exposed only through your platform, with usage tracking back to the publisher, and customers without their own libraries get access through their subscription.

**Why long-term:** publishers move slowly and are protective of their corpora. Pursue once the product has commercial traction (~1000+ paying lawyers) so the publisher sees a revenue opportunity rather than a risk.

### 7.4 Phasing summary

| Feature | Phase | Reason |
|---|---|---|
| Prazo engine | **V1** | Universal need, hard to do right, wide differentiation, opens sales |
| Second-opinion mode | **V1** | Widens addressable market beyond drafter-acceptors |
| Contradictory-jurisprudence flag | **V1** | Intellectual-honesty differentiator; signals product seriousness |
| Case timeline UI | Phase 2 | UI on top of existing data; v1 ships with simpler view first |
| WhatsApp thin client | Phase 2 | Distribution wedge once core UX is stable |
| Document understanding | Phase 2 | Expands input intelligence after output (drafter) is mature |
| Adversário intelligence | Phase 3 | Token cost + data-layer dependency; needs paying customers |
| Tribunal/judge intelligence | Phase 3 | Regulatory sensitivity; introduce after credibility established |
| Research mode | Phase 3 | Low lift, but positioning matters; let v1 establish identity first |
| What-if scenarios | Phase 3 | Depends on judge intelligence + outcome data |
| Honorários intelligence | Phase 3 | Firm-management surface, after lawyer-facing product matures |
| Doutrina publisher partnerships | Long-term | Requires commercial traction to interest publishers |
| Ethics/má-fé compliance check | **V1.5** | Cheap to add, reduces user-side risk; fold into citation_verifier or as a sibling agent |

#### 7.4.1 The ethics/má-fé compliance check (V1.5)

A small dedicated agent that runs before any filing and flags:

- Language that could be construed as desrespeitoso (CPC art. 78)
- Allegations not supported by the evidence in the case file (potential litigância de má-fé, CPC arts. 79–81)
- OAB ethical issues with how the case is framed
- Citations that are the typical signature of AI hallucination patterns (round numbers in case IDs, implausible ministros for the date, etc.)
- Inconsistencies between the petition's claimed facts and the case's actual documents

**Implementation:** small classifier model + rules engine, ~100 lines of Python plus prompt. Cheap to run, catches issues that create real problems for the lawyer down the line. Fold it into the citation_verifier as an additional check, or run as a sibling agent immediately before the lawyer's review.

**Why V1.5 rather than V1:** it's optional polish for the v1 launch, but worth adding within the first few months once the core flow is validated. The cost of *not* having it is real (lawyers have already been fined for AI-induced má-fé citations in Brazilian courts) but it's a defense rather than an offense.

---

## Appendix: Quick-reference SOAP envelope examples

### A.1 consultarProcesso request

```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:int="http://www.cnj.jus.br/intercomunicacao-2.2.2">
  <soap:Body>
    <int:consultarProcesso>
      <int:idConsultante>12345678901</int:idConsultante>
      <int:senhaConsultante>...</int:senhaConsultante>
      <int:numeroProcesso>0009999-99.2024.8.26.0001</int:numeroProcesso>
      <int:movimentos>true</int:movimentos>
      <int:incluirCabecalho>true</int:incluirCabecalho>
      <int:incluirDocumentos>false</int:incluirDocumentos>
    </int:consultarProcesso>
  </soap:Body>
</soap:Envelope>
```

### A.2 entregarManifestacaoProcessual request (skeleton)

```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:int="http://www.cnj.jus.br/intercomunicacao-2.2.2"
               xmlns:tip="http://www.cnj.jus.br/tipos-servicos-intercomunicacao-2.2.2">
  <soap:Body>
    <int:entregarManifestacaoProcessual>
      <int:idManifestante>12345678901</int:idManifestante>
      <int:senhaManifestante>...</int:senhaManifestante>
      <int:numeroProcesso>0009999-99.2024.8.26.0001</int:numeroProcesso>
      <int:dataEnvio>2026-04-29T22:32:14-03:00</int:dataEnvio>
      <int:documento>
        <tip:tipoDocumento>manifestacao</tip:tipoDocumento>
        <tip:descricao>Manifestação - resposta ao despacho</tip:descricao>
        <tip:mimetype>application/pdf</tip:mimetype>
        <tip:conteudo><!-- base64 of PAdES-signed PDF --></tip:conteudo>
        <tip:hash>sha256-hex...</tip:hash>
      </int:documento>
    </int:entregarManifestacaoProcessual>
  </soap:Body>
</soap:Envelope>
```

The exact element names vary slightly by MNI version — always derive from the live WSDL of the target tribunal, not from copy-pasted docs.
