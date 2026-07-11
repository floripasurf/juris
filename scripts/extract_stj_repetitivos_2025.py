#!/usr/bin/env python3
"""Ingest real STJ Temas Repetitivos fixed in 2025 into the corpus seed.

Source (official, public, no captcha):
  STJ — "STJ julgou 42 temas repetitivos no segundo semestre de 2025" (28/01/2026).
  https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias/2026/
  28012026-STJ-julgou-42-temas-repetitivos-no-segundo-semestre-de-2025--veja-as-teses-fixadas.aspx

These are official fixed theses (teses firmadas), transcribed from the STJ page —
not invented. Some long theses are abbreviated with "[...]" exactly as published/
extracted; flagged via `fonte`/`aviso` for the IA cleanup step (SCHEMA §6) before
production drafting. Merges into data/corpus/temas_repetitivos_stj.json, deduping
by `numero`.
"""

from __future__ import annotations

import json
import os

OUTPUT = os.path.join(os.path.dirname(__file__), "..", "data", "corpus", "temas_repetitivos_stj.json")

_FONTE = "STJ — Temas Repetitivos 2º sem/2025 (transcrição da página oficial; revisar OCR/abreviações)"

# (numero, area, tese verbatim) — extracted from the official STJ page.
_TEMAS: list[tuple[str, str, str]] = [
    ("1178", "direito processual civil", "É vedado o uso de critérios objetivos para o indeferimento imediato da gratuidade judiciária requerida por pessoa natural."),
    ("1201", "direito processual civil", "O agravo interposto contra decisão do tribunal de origem, quando apresentado contra decisão baseada em precedente qualificado oriundo do STJ ou do STF, autoriza a aplicação da multa prevista no artigo 1.021, §4º, do CPC."),
    ("1306", "direito processual civil", "A técnica da fundamentação por referência (per relationem) é permitida desde que o julgador enfrente, ainda que de forma sucinta, as novas questões relevantes para o julgamento do processo."),
    ("1368", "direito civil", "O artigo 406 do Código Civil de 2002 deve ser interpretado no sentido de que é a Selic a taxa de juros de mora aplicável às dívidas de natureza civil."),
    ("1272", "direito público", "O adicional noturno não será devido ao servidor da então carreira de agente federal de execução penal nos períodos de afastamento."),
    ("1308", "direito público", "A vedação de nova admissão de professor substituto temporário não se aplica aos contratos realizados por instituições públicas distintas."),
    ("1326", "direito público", "O prazo prescricional da pretensão de cobrança de complementação de recursos deve ser apurado mês a mês, e não anualmente."),
    ("1342", "direito público", "A remuneração decorrente do contrato de aprendizagem integra a base de cálculo da contribuição previdenciária patronal, da GIIL-RAT e das contribuições a terceiros."),
    ("1346", "direito público", "Não é admissível o recurso especial que discute a transferência da responsabilidade pela manutenção do sistema de iluminação pública."),
    ("1273", "direito público", "O prazo decadencial do artigo 23 da Lei 12.016/2009 não se aplica ao mandado de segurança cuja causa de pedir seja a impugnação de lei ou ato normativo que interfira em obrigações tributárias sucessivas."),
    ("1291", "direito público", "O contribuinte individual não cooperado tem direito ao reconhecimento de tempo de atividade especial exercido após a Lei 9.032/95, desde que comprove a exposição a agentes nocivos."),
    ("1300", "direito público", "Nas ações em que o participante contesta saques em sua conta individualizada do Pasep, o ônus de provar cabe ao participante quanto aos saques sob as formas de crédito em conta e de pagamento por Folha de Pagamento (Pasep-Fopag) [...]"),
    ("1309", "direito público", "Os sucessores do servidor falecido antes da propositura da ação coletiva não são beneficiados pela decisão transitada em julgado que condena ao pagamento de diferenças, salvo se expressamente contemplados."),
    ("1124", "direito público", "Configuração do interesse de agir para a propositura da ação judicial previdenciária: o segurado deve apresentar requerimento administrativo apto, com documentação minimamente suficiente para viabilizar a compreensão e a análise do requerimento."),
    ("1323", "direito público", "A adoção da forma societária de responsabilidade limitada pela sociedade uniprofissional não constitui, por si só, impedimento ao regime de tributação diferenciada do ISS por alíquota fixa."),
    ("1329", "direito público", "No procedimento administrativo para apuração das infrações ao meio ambiente, a intimação por edital para apresentação de alegações finais somente acarretará nulidade dos atos posteriores caso a parte demonstre a existência de efetivo prejuízo para a defesa."),
    ("1350", "direito público", "Não é possível à Fazenda Pública substituir ou emendar a Certidão de Dívida Ativa (CDA) para incluir, complementar ou modificar o fundamento legal do crédito tributário."),
    ("1162", "direito público", "No regime anterior à vigência da MP 871/2019, é possível a flexibilização do critério econômico para a concessão do auxílio-reclusão."),
    ("1224", "direito público", "É possível deduzir, da base de cálculo do IRPF, os valores vertidos a título de contribuições extraordinárias para a entidade fechada de previdência complementar, observando-se o limite de 12%."),
    ("1317", "direito público", "A extinção dos embargos à execução fiscal em face da desistência ou da renúncia do direito manifestada para fins de adesão a programa de recuperação fiscal em que já inserida a verba honorária pela cobrança da dívida pública não enseja nova condenação em honorários advocatícios."),
    ("1319", "direito público", "É possível a dedução dos juros sobre capital próprio (JCP) da base de cálculo do IRPJ e da CSLL, quando apurados em exercício anterior ao da decisão assemblear que autoriza o seu pagamento."),
    ("1251", "direito público", "Reconhecido judicialmente o direito à indenização por danos morais decorrentes de perseguição política sofrida durante a ditadura militar, os juros de mora devem incidir a partir do evento danoso."),
    ("1294", "direito público", "O Decreto 20.910/1932 não dispõe sobre a prescrição intercorrente, não podendo ser utilizado como referência normativa para o seu reconhecimento em processos administrativos estaduais e municipais."),
    ("1304", "direito público", "Não é possível excluir o ICMS, o PIS e a Cofins da base de cálculo do IPI, a partir do conceito de 'valor da operação'."),
    ("1371", "direito público", "A prerrogativa da administração fazendária de promover o procedimento administrativo de arbitramento do valor venal do imóvel transmitido decorre diretamente do CTN, em seu artigo 148."),
    ("1387", "direito público", "O saque integral do principal dá início ao prazo prescricional da pretensão de reparação por falha na prestação do serviço, por saques indevidos, por desfalques, ou por ausência de aplicação dos rendimentos estabelecidos em conta individualizada do Pasep."),
    ("1099", "direito civil", "Prescrição decenal (artigo 205, CC/2002) da pretensão de restituição dos valores pagos a título de comissão de corretagem, quando o pedido de repetição dirigido contra a incorporadora/construtora tiver por fundamento a resolução do contrato em virtude de atraso na entrega do imóvel."),
    ("1137", "direito civil", "Nas execuções cíveis submetidas exclusivamente ao CPC, a adoção judicial de meios executivos atípicos é cabível desde que, cumulativamente, sejam ponderados os princípios da efetividade e da menor onerosidade do executado [...]"),
    ("1173", "direito civil", "O corretor de imóveis, pessoa física ou jurídica, não é, normalmente, responsável por danos causados ao consumidor em razão do descumprimento, pela construtora ou incorporadora, de obrigações relativas ao empreendimento imobiliário."),
    ("1268", "direito civil", "A eficácia preclusiva da coisa julgada impede o ajuizamento de nova ação para pleitear a restituição de quantia paga a título de juros remuneratórios incidentes sobre tarifas bancárias declaradas ilegais ou abusivas em ação anterior."),
    ("1279", "direito civil", "Nas ações de busca e apreensão de bens alienados fiduciariamente, o prazo de cinco dias para pagamento da integralidade da dívida começa a fluir a partir da data da execução da medida liminar."),
    ("1288", "direito civil", "Antes da entrada em vigor da Lei 13.465/2017, nas situações em que já consolidada a propriedade e purgada a mora nos termos do artigo 34 do Decreto-Lei 70/1966 — ato jurídico perfeito —, impõe-se o desfazimento do ato de consolidação."),
    ("1333", "direito penal", "A agravante prevista no artigo 61, II, f, do Código Penal é aplicável às contravenções penais praticadas no contexto de violência doméstica contra a mulher, salvo se houver previsão diversa pela Lei das Contravenções Penais."),
    ("1262", "direito penal", "Na análise das vetoriais da natureza e da quantidade da substância entorpecente, configura-se desproporcional a majoração da pena-base quando a droga apreendida for de ínfima quantidade, independentemente de sua natureza."),
    ("1278", "direito penal", "Em decorrência dos objetivos da execução penal, a leitura pode resultar na remição de pena, com fundamento no artigo 126 da Lei de Execução Penal, desde que observados os requisitos previstos para sua validação."),
    ("1194", "direito penal", "A atenuante genérica da confissão espontânea, prevista no artigo 65, III, d, do Código Penal, é apta a abrandar a pena independentemente de ter sido utilizada na formação do convencimento do julgador."),
    ("1192", "direito penal", "O cometimento de crimes de roubo mediante uma única conduta e sem desígnios autônomos contra o patrimônio de diferentes vítimas, ainda que da mesma família, configura concurso formal de crimes (artigo 70 do Código Penal)."),
    ("1269", "direito penal", "No rito especial que visa apurar a prática de ato infracional, além da audiência de apresentação do adolescente prevista no artigo 184 do ECA, aplica-se subsidiariamente o artigo 400 do Código de Processo Penal."),
    ("1377", "direito penal", "O tipo previsto na primeira parte do caput do artigo 54 da Lei 9.605/1998 possui natureza formal, sendo suficiente a potencialidade de dano à saúde humana para a configuração da conduta delitiva."),
    ("1236", "direito penal", "A remição de pena em razão do estudo a distância (EaD) demanda a prévia integração da instituição ao Projeto Político-Pedagógico (PPP) da unidade ou sistema prisional, não bastando o credenciamento junto ao MEC."),
    ("1347", "direito penal", "A regressão cautelar de regime prisional é medida de caráter provisório e está autorizada pelo poder geral de cautela do juízo da execução, podendo ser aplicada, mediante fundamentação idônea, até a apuração definitiva da falta."),
    ("1195", "direito penal", "O período de doze meses a que se refere o artigo 4º, I, do Decreto 9.246/2017 caracteriza-se pela não ocorrência de falta grave, não se relacionando à data de sua apuração."),
]


def main() -> None:
    with open(OUTPUT, encoding="utf-8") as f:
        existentes = json.load(f)

    by_num = {t.get("numero"): t for t in existentes}
    added = 0
    for numero, area, tese in _TEMAS:
        if numero in by_num:
            continue
        existentes.append(
            {
                "numero": numero,
                "descricao": f"Tema repetitivo STJ {numero} ({area}).",
                "tese": tese,
                "situacao": "transitado",
                "area": area,
                "fonte": _FONTE,
            }
        )
        added += 1

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(existentes, f, ensure_ascii=False, indent=2)

    print(f"Adicionados {added} temas reais; total agora: {len(existentes)}")


if __name__ == "__main__":
    main()
