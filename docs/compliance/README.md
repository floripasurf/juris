# Compliance operacional do piloto

Estes documentos fecham o pacote minimo LGPD/compliance para operar o piloto Juris
sem improviso. Eles sao artefatos operacionais, nao parecer juridico: antes de uso
com escritorio externo, revise com o advogado responsavel, DPO/compliance do
escritorio ou assessoria juridica.

## Artefatos

- `dpa-template-pt.md` - minuta de acordo de tratamento de dados entre o
  escritorio controlador e a Juris operadora/suboperadora durante o piloto.
- `ropa-pilot.md` - registro das atividades de tratamento do piloto.
- `ripd-pilot.md` - avaliacao de impacto simplificada para os fluxos com maior
  risco: MNI, LLM, browser session, corpus, auditoria e backups.
- `datajud-terms-snapshot-2026-05-09.md` - snapshot operacional dos termos DataJud
  usado como referencia do piloto.
- `../../data/tos_compliance_log.md` - matriz de liberacao por fonte/portal antes
  de habilitar coleta de inteiro teor.

## Antes de iniciar um piloto real

1. Preencher o DPA com partes, contatos, duracao, subprocessadores e medidas de
   seguranca.
2. Revisar o ROPA para confirmar que os fluxos usados no piloto estao cobertos.
3. Atualizar o RIPD quando houver novo subprocessador, novo dado sensivel ou mudanca
   no caminho de LLM.
4. Registrar no `data/tos_compliance_log.md` qualquer fonte externa de inteiro teor
   antes de habilitar ingester HTTP ou coleta automatizada.
5. Anexar o DPA/termos do piloto assinados ao registro interno do escritorio.

## Postura padrao

- Dado cru de cliente fica local ou no agente do advogado.
- LLM em nuvem exige de-identificacao completa e DPA/base contratual.
- Fonte de inteiro teor sem liberacao de ToS permanece bloqueada.
- Encerramento do piloto usa `juris tenant erase-data` com certificado de delecao.
