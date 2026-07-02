# Log de compliance de fontes / ToS

Este arquivo registra a liberacao operacional antes de habilitar coleta automatizada
ou ingester HTTP de inteiro teor. Sem linha `Aprovado` para a fonte especifica, o
ingester deve permanecer gated e retornar vazio.

## Regras

- Registrar fonte, URL dos termos, data da revisao, responsavel e decisao.
- Preferir fontes que o escritorio ja possui ou dados oficiais com permissao clara.
- Nao burlar captcha, WAF, login, paywall ou limite tecnico.
- Guardar snapshot/link dos termos quando possivel.
- Revalidar se os termos mudarem ou antes de sair do piloto single-tenant.

## Matriz atual

| Fonte | Uso pretendido | URL/termos revisados | Status | Responsavel | Data | Observacoes |
| --- | --- | --- | --- | --- | --- | --- |
| DataJud CNJ | Movimentos/metadados processuais | `docs/compliance/datajud-terms-snapshot-2026-05-09.md` | Aprovado com restricoes | Juris | 2026-05-09 | Usar dentro dos limites do snapshot; nao substitui inteiro teor. |
| Arquivos do proprio escritorio | Ingestao manual de decisoes/acordaos ja baixados pelo advogado | Contrato/posse do escritorio | Aprovado para piloto | Advogado controlador | `<data>` | Registrar URL/fonte/data/hash no corpus. |
| LexML / dados abertos oficiais | Inteiro teor ou referencia normativa/jurisprudencial quando disponivel | `<preencher>` | Pendente | `<responsavel>` | `<data>` | Liberar por endpoint/fonte especifica. |
| TST jurisprudencia backend `pesquisa-textual` | Coleta automatizada de inteiro teor trabalhista | `docs/compliance/tst-terms-snapshot-2026-07-02.md` (robots.txt + PPPDP Ato Conjunto 4/2021 lidos na integra) | Aprovado | Raphael (owner/advogado) | 2026-07-02 | Aprovado pelo responsavel em sessao de trabalho; coleta sequencial e gentil (executor), sem bypass de WAF/captcha; `JURIS_TST_INTEIRO_TEOR_ENABLED=true` liberado por execucao. |
| Portais de jurisprudencia STF/STJ/TST/TJs | Coleta automatizada de inteiro teor | `<preencher por portal>` | Pendente | `<responsavel>` | `<data>` | Ingesters HTTP permanecem gated ate aprovacao. |

## Historico de decisoes

| Data | Fonte | Decisao | Evidencia | Responsavel |
| --- | --- | --- | --- | --- |
| 2026-07-01 | Base inicial | Criado log para bloquear fonte sem ToS revisado | Este arquivo | Juris |
| 2026-07-02 | TST `pesquisa-textual` | Aprovado para coleta de inteiro teor | Decisao do responsavel (Raphael) registrada nesta matriz | Raphael |
