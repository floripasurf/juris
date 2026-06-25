# Design — portar os 9 módulos do "Auditor Estratégico" para o EstrategiaAgent

**Data:** 2026-06-25 · **Status:** desenho (pré-implementação)

**Fonte:** metodologia adaptada de `pizaniadv/auditor-estrategico-juridico`
(SKILL.md, **CC BY 4.0** — uso permitido com atribuição). Não copiamos o texto da
skill; portamos a **arquitetura dos 9 módulos** para o `EstrategiaAgent`
(`src/juris/agents/estrategia.py`, Estágio 2 do filtro ADR-0017).

---

## 1. Tese do port

O auditor é, em essência, **o nosso Estágio 2 expandido**: auditar fatos, provas,
teses, riscos e vetores estratégicos *antes* de redigir, com **protocolo
antialucinatório** (= nosso princípio "não inventar jurisprudência") e
**separação estratégico×redacional** (Relatório Interno vs Dossiê). Três dos nove
módulos **já existem** no juris; o port é majoritariamente **fiação + 6 módulos novos**.

Dois produtos do auditor mapeiam exatamente no que já temos:
- **Relatório Estratégico Interno** → o `EstrategiaResult` enriquecido (uso interno, auditado).
- **Dossiê de Redação** → a linha escolhida + citações verificadas que já entregamos ao `drafter` (commit 3831b44). É o subconjunto **auditado e redacional**, sem o vocabulário estratégico interno.

---

## 2. Mapa: módulo → componente juris

| Módulo do auditor | Encaixe no juris | Natureza |
|---|---|---|
| **A. Classificação de elementos** (fato / prova / inferência / lacuna / risco) | **novo** `ClassificacaoCaso` — pré-passo que estrutura o caso | LLM estrutura → dataclass |
| **B. Matriz probatória** (alegação ↔ prova/lacuna) | **novo** `MatrizProbatoria` — cada alegação mapeada a prova existente/faltante | LLM preenche; alimenta o score (linha sem lastro probatório enfraquece) |
| **C. Hierarquização argumentativa** (principal / subsidiária / eventual) | **JÁ EXISTE**: `escolhida` + `alternativas` viram a hierarquia; cada `LinhaArgumentativa` ganha `ordem` | LLM gera *como* hierarquia; **penal inverte** (principais = nulidades/atipicidade) |
| **D. Análise institucional do adversário** | **REUSO**: `defesa_analyzer` / contraponto já modela o adversário | reuso → alimenta `riscos` + resiliência no score |
| **E. Argumento consequencialista** (reduzir o custo decisório do julgador) | **novo** componente: cada linha ganha `fundamento_consequencialista` + peso no score | LLM gera; score "reduz custo decisório?" |
| **F. Controle jurisprudencial em tripla camada** | **JÁ EXISTE**: (1) existe? = `MarkerCitationVerifier`; (2) autoridade = `nivel_hierarquico`; (3) vigência+relevância = escore composto (Estágio 1) | **DETERMINÍSTICO** |
| **G. Calibração de confiança** (firmeza do tom ∝ solidez) | `score` → rótulo `confianca` + **diretiva de tom** passada ao drafter | **DETERMINÍSTICO** (deriva do score) |
| **H. Consolidação multi-instância** (1º grau → câmara → superior) | dimensão topológica: `nivel_hierarquico` + *fit-ao-decisor* (escavação, futuro) | det. + dado futuro |
| **I. Riscos recursais e deontológicos** | `LinhaArgumentativa.riscos` + **veto deontológico** (CED/EOAB) | LLM enumera + guardrail determinístico |

**Resumo:** F, C (parcial) e D já existem; G e a base de I (grounding) também. Novos: A, B, E, H + o veto deontológico de I.

---

## 3. Arquitetura evoluída do EstrategiaAgent

De um único `propor()` para um **pipeline de auditoria** que produz o Relatório
Interno e o handoff do Dossiê:

```
propor(contexto, precedentes, *, modo="completo"|"abreviado")
  1. de-identificar o contexto (core/deid.py) antes de qualquer LLM de nuvem   [LGPD / ADR-0016]
  2. A — classificar elementos        → ClassificacaoCaso        (LLM)
  3. B — matriz probatória            → MatrizProbatoria         (LLM)
  4. C — gerar linhas hierarquizadas  → list[LinhaArgumentativa] (LLM, judge-panel)
  5. D — análise do adversário        → reusar defesa_analyzer   (reuso)
  6. E — framing consequencialista    → por linha                (LLM)
  7. F — controle jurisprudencial     → verificar + escore composto (DETERMINÍSTICO)
  8. I — riscos + veto deontológico   → por linha                (LLM + guardrail)
  9. G — calibrar confiança           → score → confianca        (DETERMINÍSTICO)
  10. H — consolidação multi-instância→ por linha                (det. + escavação futura)
  → selecionar_linha (determinístico) → EstrategiaResult (Relatório) + Dossiê
```

`modo="abreviado"` roda só **A, B, F, G** (como o regime abreviado do auditor:
consultas pontuais, validação rápida de tese).

### Estruturas de dados (evolução)

```python
@dataclass(frozen=True)
class ElementoCaso:        # Módulo A
    texto: str
    tipo: Literal["fato", "prova", "inferencia", "lacuna", "risco"]

@dataclass(frozen=True)
class ItemMatriz:          # Módulo B
    alegacao: str
    provas: list[str]      # ids/descrições de provas existentes
    lacunas: list[str]     # provas faltantes

@dataclass(frozen=True)
class LinhaArgumentativa:  # já existe — ACRÉSCIMOS
    tese: str
    fundamentos: list[str]
    citacoes: list[str]
    riscos: list[str]                 # Módulo I
    score: float
    # novos:
    ordem: Literal["principal", "subsidiaria", "eventual"]  # Módulo C
    fundamento_consequencialista: str | None = None         # Módulo E
    confianca: Literal["alta", "media", "baixa"] = "media"  # Módulo G
    consolidacao_multiinstancia: str | None = None          # Módulo H

@dataclass(frozen=True)
class EstrategiaResult:    # já existe — vira o "Relatório Estratégico Interno"
    escolhida: LinhaArgumentativa
    alternativas: list[LinhaArgumentativa]
    # novos:
    classificacao: list[ElementoCaso]      # A
    matriz_probatoria: list[ItemMatriz]    # B
    analise_adversario: str | None         # D
    avisos_deontologicos: list[str]        # I (veto)
    revisao_humana_obrigatoria: bool       # auditor §6.14 / §5
```

---

## 4. Fronteira determinístico × LLM (ADR-0017)

| Determinístico (auditável, sem LLM) | LLM (propõe, depois verificado) |
|---|---|
| **F** — verificação de citação + escore composto (vigência/nível/grounding) | **A** classificação, **B** matriz, **C** geração de linhas, **E** consequencialista |
| **G** — confiança derivada do score | **I** enumeração de riscos |
| `selecionar_linha` (ranking) | **D** análise do adversário (via defesa_analyzer) |
| veto deontológico de **I** (regras CED/EOAB) | |

Regra mantida: tudo de que **citação ou prazo** depende é determinístico; o LLM só
gera, sempre ancorado e verificado. O `score_linha` já penaliza citação alucinada
(grounding) — é o Módulo F operando hoje.

---

## 5. Salvaguardas (já alinhadas)

- **Antialucinação** (regra nº1 do auditor) = nosso princípio 7 + o grounding do `score_linha` + `MarkerCitationVerifier`. **Verificação humana obrigatória** das citações: marcar no Relatório (`revisao_humana_obrigatoria`).
- **Separação Relatório×Dossiê**: o Relatório (estratégico, interno) nunca entra na peça; só a linha verificada + citações (Dossiê) vão ao drafter — já é assim (a nota estratégica/contraponto é interna).
- **LGPD** (auditor §3.B): de-identificar (core/deid.py) antes de LLM de nuvem; minimizar dado sensível. Casa com o ADR-0016.
- **Veto deontológico**: o guardrail de I recusa condutas vedadas pelo CED/EOAB (captação, quebra de sigilo) — guardrail determinístico, não sugestão de LLM.

---

## 6. Plano de port (incremental, TDD)

1. **F + G + C-rotulagem** (o que já existe): rotular `escolhida`/`alternativas` como hierarquia (`ordem`) e derivar `confianca` do score. Determinístico, testável já. *(menor esforço, valor imediato)*
2. **Módulo I (riscos + veto deontológico)**: enumerar riscos por linha (LLM) + guardrail determinístico de condutas vedadas.
3. **Módulos A + B** (classificação + matriz probatória): pré-passos LLM estruturados → enriquecem o Relatório e o score (lacuna probatória penaliza).
4. **Módulo E** (consequencialista) + **D** (wire do `defesa_analyzer` no agente).
5. **Módulo H** (consolidação multi-instância) — depende da escavação/fit-decisor (futuro).
6. **Regimes** `completo`/`abreviado` + de-id no início do `propor`.

> Cada passo é um increment TDD isolado; o `EstrategiaResult` cresce de forma
> retrocompatível (campos novos com default). O drafter já consome a linha
> escolhida — passa a consumir também a `confianca` (diretiva de tom) e os avisos.
