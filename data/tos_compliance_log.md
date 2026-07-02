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
| TST jurisprudencia backend `pesquisa-textual` | Coleta automatizada de inteiro teor trabalhista | `<preencher snapshot ToS TST>` | Pendente | `<responsavel>` | `<data>` | Implementacao tecnica pronta; manter `JURIS_TST_INTEIRO_TEOR_ENABLED=false` ate aprovacao. |
| Portais de jurisprudencia STF/STJ/TST/TJs | Coleta automatizada de inteiro teor | `<preencher por portal>` | Pendente | `<responsavel>` | `<data>` | Ingesters HTTP permanecem gated ate aprovacao. |

## Historico de decisoes

| Data | Fonte | Decisao | Evidencia | Responsavel |
| --- | --- | --- | --- | --- |
| 2026-07-01 | Base inicial | Criado log para bloquear fonte sem ToS revisado | Este arquivo | Juris |
