# ROPA - Registro de Atividades de Tratamento do Piloto Juris

> Registro operacional para o piloto. Atualize quando mudar fonte, subprocessador,
> modo de LLM, escopo de protocolo ou politica de retencao.

| Atividade | Finalidade | Dados pessoais | Titulares | Origem | Destino/subprocessador | Retencao | Controles |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Leitura MNI/DataJud | Importar acervo, movimentos, intimacoes e prazos | CNJ, nomes, CPF/CNPJ quando constarem, documentos e movimentos | Clientes, partes, advogados, terceiros processuais | Tribunais/DataJud/MNI | Storage local por tenant; agente local para token | Durante piloto + ate 30 dias apos encerramento | Split-trust, mTLS, tenant storage, audit log |
| Analise e minuta | Gerar estrategia, rascunho, revisao e grounding | Texto processual e dados do caso | Clientes, partes, terceiros | Storage do caso | Ollama local; cloud apenas de-identificado | Artefatos do caso ate encerramento/delecao | De-id fail-closed, citation verifier, review humano |
| Browser session | Usar assinatura Claude.ai/ChatGPT do advogado | Prompt de-identificado e resposta do provedor | Indireto, dados pseudonimizados | Juris agent | Sessao do advogado no provedor | Nao persistido em JS; artefato no caso se salvo | Content script bloqueia PII, token bridge validado |
| Corpus dirigido | Adicionar fontes aceitas pelo advogado | Conteudo de decisoes/fontes, metadados, hash | Partes em decisoes publicas ou documentos do escritorio | Upload/fonte autorizada | `repertory.db` por tenant/publico | Enquanto fonte for valida para o piloto | Proveniencia obrigatoria, ToS log, hash, tenant scope |
| Feedback do piloto | Medir valor e lacunas | CNJ, notas do advogado, utilidade, fonte faltante | Clientes indiretamente via CNJ/caso | Advogado operador | JSONL por tenant/export CSV/JSON/MD | Durante piloto + ate 30 dias | Sanitizacao, tenant scope, sem prompt bruto desnecessario |
| Auditoria e backups | Prova operacional, cadeia de custodia e recuperacao | Metadados de jobs, hashes, caminhos, recibos; eventualmente artefatos se backup completo | Clientes/advogado | Juris runtime | Backup local definido por operador | Conforme politica do controlador | HMAC, SHA-256 por arquivo, criptografia em repouso recomendada |
| Protocolo controlado | Assinar e protocolar documento revisado | PDF/minuta, certificado, recibo e hashes | Cliente, advogado, partes | Juris/advogado | Tribunal/MNI via agente local | Recibos e cadeia de custodia ate delecao | Consentimento explicito, preflight, agente remoto |

## Responsaveis

- Controlador: escritorio/advogado piloto.
- Operador/suboperador: Juris, conforme DPA.
- Dono operacional do registro: `<nome>`.
- Ultima revisao: `<data>`.

## Lacunas controladas

- Fonte externa de inteiro teor so pode ser habilitada apos registro em
  `data/tos_compliance_log.md`.
- Multi-worker exige Redis/proxy para rate limit e sticky/broker para relay.
- Uso de cloud LLM exige DPA/base contratual e de-identificacao completa.
