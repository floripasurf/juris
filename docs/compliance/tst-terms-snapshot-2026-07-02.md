# Snapshot de revisão — fonte TST jurisprudência (backend `pesquisa-textual`)

**Data da revisão:** 2026-07-02 · **Responsável:** Raphael (owner/advogado) ·
**Uso pretendido:** coleta dirigida de inteiro teor de acórdãos-líderes da
espinha (escavação, volume baixo, sequencial) para corpus privado de pesquisa
jurídica. Sem republicação do conteúdo.

## O que foi verificado

### 1. Termos de uso específicos do portal de jurisprudência

**Não localizados.** O portal `jurisprudencia.tst.jus.br` não publica termos de
uso próprios nem página de licenciamento de dados. Não há cláusula pública
proibindo ou autorizando expressamente acesso automatizado.

### 2. robots.txt (verificado ao vivo em 2026-07-02)

| Host | Conteúdo |
| --- | --- |
| `jurisprudencia.tst.jus.br` (SPA) | `User-agent: *` / `Disallow: /` — **desestimula crawling/indexação** |
| `jurisprudencia-backend2.tst.jus.br` (API usada) | sem robots.txt (404) |
| `www.tst.jus.br` | `Allow: /` |

Leitura honesta: o TST não quer o portal de jurisprudência varrido/indexado
por crawlers. O uso do Juris não é crawling de site nem republicação — é
recuperação dirigida de decisões específicas (equivalente à consulta humana),
uma requisição por processo, sequencial. Ainda assim, este sinal foi
**apresentado ao responsável** como fator contrário antes da decisão.

### 3. Política de Privacidade e Proteção de Dados do TST/CSJT

**ATO CONJUNTO TST.CSJT.GP Nº 4, de 12/03/2021** (PPPDP) — lido na íntegra
([PDF oficial](https://www.tst.jus.br/documents/10157/2374827/004+-+de+12-3-2020+-+INSTITUI+A+POLA%CC%83_TICA+DE+PRIVACIDADE+E+PROTEA%CC%83_A%CC%83_O+DE+DADOS+PESSOAIS+NO+A%CC%83_MBITO+DO+TST+E+DO+CSJT.pdf/7190f9da-d9d3-0da6-89ce-aba35091a39c)):

- É política **interna** de tratamento de dados pessoais pelo TST/CSJT; **não
  contém** cláusula sobre raspagem, acesso automatizado, reuso ou
  redistribuição de jurisprudência.
- Invoca LGPD, Marco Civil, LAI (Lei 12.527/2011) e as Resoluções CNJ
  121/2010 e 215/2015 — justamente as normas que tornam os dados processuais
  **públicos** e de consulta livre online.
- Art. 26, IV (por analogia): interações de terceiros não devem causar
  "impacto, dano ou interrupção nos equipamentos" — reforça o dever de coleta
  gentil.

### 4. Moldura legal do uso

- Publicidade dos julgamentos: CF art. 93, IX; acórdãos são documentos
  públicos de consulta livre (Res. CNJ 121/2010).
- LGPD sobre dados pessoais contidos nos acórdãos: tratamento por nós como
  dados tornados manifestamente públicos pelo titular/poder público, com
  finalidade compatível (pesquisa e exercício profissional jurídico);
  obrigações downstream do Juris: corpus local, isolamento por tenant, de-id
  antes de nuvem (ADR-0016), sem republicação.

## Decisão e salvaguardas operacionais

**Aprovado** para coleta dirigida com as salvaguardas já implementadas:

1. Sem bypass de WAF/captcha/login (não existem neste backend; se surgirem, a
   coleta para — regra do projeto).
2. Sequencial, uma requisição por alvo, volume dirigido pela espinha (dezenas
   por execução, não espelhamento em massa).
3. User-Agent identificado.
4. Bloqueio/429/instabilidade do serviço ⇒ interromper, não insistir.
5. Conteúdo fica em corpus privado com proveniência; nunca republicado.
6. Revalidar esta revisão se o TST publicar termos específicos, alterar o
   robots.txt do backend, ou antes de sair do piloto single-tenant.

## Histórico

- 2026-07-02: primeira aprovação (registrada na matriz) e primeira execução:
  20 inteiros teores, 0 falhas.
- 2026-07-02 (mesma data, em seguida): re-revisão solicitada pelo responsável;
  este snapshot produzido com robots.txt + PPPDP lidos na íntegra.
- 2026-07-02: após re-revisão com este material (incluindo o robots.txt do portal), o responsável **manteve a aprovação** nos termos e salvaguardas acima.
