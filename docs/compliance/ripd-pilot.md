# RIPD - Avaliacao de Impacto do Piloto Juris

> Avaliacao simplificada para piloto controlado. Nao substitui RIPD formal quando
> o controlador entender que ha alto risco residual ou escala de producao.

## 1. Escopo

Sistema de apoio juridico para escritorio piloto, com leitura de processos,
analise assistiva por IA, busca em corpus, geracao de rascunhos, revisao, auditoria
e protocolo controlado.

Fora do escopo: atendimento direto a cliente final, decisao automatizada sem
advogado, treinamento de modelo com dados do cliente, scraping de portal sem ToS
liberado.

## 2. Fluxos de maior risco

| Fluxo | Risco principal | Controles existentes | Risco residual |
| --- | --- | --- | --- |
| MNI com A3 | Exposicao de CPF/senha/PIN/token | Agente local, split-trust, token nao enviado ao servidor, mTLS com verificacao de host | Medio se operador configurar agente incorretamente |
| LLM externo | Vazamento de PII ou uso para treinamento | De-id fail-closed, NER, content script com backstop de PII, DPA/termos do provedor | Medio, depende de subprocessador e configuracao de treino |
| Browser session | Processo local indevido dirigir sessao do advogado | Bridge loopback, token validado no native host, sender validation, prompt nao persistido em JS | Baixo/medio se token ausente |
| Corpus de inteiro teor | Ingestao sem direito/ToS ou dados excessivos | Proveniencia obrigatoria, hash, ToS log, ingesters gated | Medio enquanto fonte viva nao for liberada |
| Auditoria/backups | Retencao excessiva ou perda de prova | HMAC, SHA-256, runbook de backup/restore, delecao por tenant | Medio se backup externo nao for criptografado |
| Protocolo | Protocolo duplicado ou sem revisao | Dry-run, preflight, consentimento explicito, pending recovery manual | Medio ate retry automatico ter salvaguarda anti-duplicata |

## 3. Necessidade e proporcionalidade

- Necessario: dados processuais sao indispensaveis para calcular prazos, gerar
  rascunhos e verificar fundamentacao.
- Minimizacao: modo local preferencial para PII crua; cloud apenas de-identificado;
  fontes de corpus exigem proveniencia.
- Transparencia: termos do piloto, audit trail e feedback estruturado.
- Retencao: ate 30 dias apos encerramento salvo base legal/contratual.

## 4. Medidas obrigatorias antes do piloto real

1. Assinar termos do piloto e DPA preenchido.
2. Rodar `juris pilot preflight --live` no ambiente do advogado.
3. Confirmar `JURIS_REQUIRE_TENANTS=1` em ambiente exposto/reverso proxy.
4. Definir `JURIS_AUDIT_HMAC_KEY` em producao.
5. Configurar backup criptografado ou documentar decisao de nao reter backup.
6. Registrar qualquer fonte de inteiro teor em `data/tos_compliance_log.md`.
7. Desligar treinamento/historico no provedor de browser session quando usado.

## 5. Sinais de parada

Interromper uso real e voltar para modo demo/local se ocorrer:

- de-id incompleto antes de LLM externo;
- agente remoto sem token/bridge health;
- fonte de inteiro teor sem liberacao de ToS;
- erro de prazo nao revisado;
- tentativa de protocolo sem consentimento explicito;
- incidente de seguranca ou suspeita de acesso cross-tenant.

## 6. Aprovacao

| Papel | Nome | Data | Decisao |
| --- | --- | --- | --- |
| Advogado responsavel |  |  |  |
| DPO/compliance do escritorio |  |  |  |
| Responsavel tecnico Juris |  |  |  |
