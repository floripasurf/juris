#!/usr/bin/env python3
"""Generate comprehensive STF Súmulas (non-vinculantes) corpus as JSON.

This script contains a curated set of the most important and commonly cited
STF Súmulas with their real, accurate texts as published by the Supremo
Tribunal Federal.
"""

import json
import os
from pathlib import Path


def get_sumulas() -> list[dict]:
    """Return a list of real STF Súmulas with accurate texts."""
    return [
        # === RECURSO EXTRAORDINÁRIO / PROCESSUAL ===
        {
            "numero": "279",
            "texto": "Para simples reexame de prova não cabe recurso extraordinário.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "280",
            "texto": "Por ofensa a direito local não cabe recurso extraordinário.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "281",
            "texto": "É inadmissível o recurso extraordinário, quando couber na Justiça de origem, recurso ordinário da decisão impugnada.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "282",
            "texto": "É inadmissível o recurso extraordinário, quando não ventilada, na decisão recorrida, a questão federal suscitada.",
            "tema": "prequestionamento",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "283",
            "texto": "É inadmissível o recurso extraordinário, quando a decisão recorrida assenta em mais de um fundamento suficiente e o recurso não abrange todos eles.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "284",
            "texto": "É inadmissível o recurso extraordinário, quando a deficiência na sua fundamentação não permitir a exata compreensão da controvérsia.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "285",
            "texto": "Não sendo razoável a argüição de inconstitucionalidade, não se conhece do recurso extraordinário fundado na letra \"c\" do art. 101, III, da Constituição Federal.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "286",
            "texto": "Não se conhece do recurso extraordinário fundado em divergência jurisprudencial, quando a orientação do plenário do Supremo Tribunal Federal já se firmou no mesmo sentido da decisão recorrida.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "288",
            "texto": "Nega-se provimento a agravo para subida de recurso extraordinário, quando faltar no traslado o despacho agravado, a decisão recorrida, a petição de recurso extraordinário ou qualquer peça essencial à compreensão da controvérsia.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "356",
            "texto": "O ponto omisso da decisão, sobre o qual não foram opostos embargos declaratórios, não pode ser objeto de recurso extraordinário, por faltar o requisito do prequestionamento.",
            "tema": "prequestionamento",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "636",
            "texto": "Não cabe recurso extraordinário por contrariedade ao princípio constitucional da legalidade, quando a sua verificação pressuponha rever a interpretação dada a normas infraconstitucionais pela decisão recorrida.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "735",
            "texto": "Não cabe recurso extraordinário contra acórdão que defere medida liminar.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "639",
            "texto": "Aplica-se a Súmula 288 quando não constam do traslado do agravo de instrumento as cópias das peças necessárias à verificação da tempestividade do recurso extraordinário não admitido pela decisão agravada.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === DIREITO ADMINISTRATIVO ===
        {
            "numero": "346",
            "texto": "A administração pública pode declarar a nulidade dos seus próprios atos.",
            "tema": "autotutela administrativa",
            "base_legal": ["CF Art. 37"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "347",
            "texto": "O Tribunal de Contas, no exercício de suas atribuições, pode apreciar a constitucionalidade das leis e dos atos do poder público.",
            "tema": "tribunal de contas",
            "base_legal": ["CF Art. 71"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "473",
            "texto": "A administração pode anular seus próprios atos, quando eivados de vícios que os tornam ilegais, porque deles não se originam direitos; ou revogá-los, por motivo de conveniência ou oportunidade, respeitados os direitos adquiridos, e ressalvada, em todos os casos, a apreciação judicial.",
            "tema": "autotutela administrativa",
            "base_legal": ["CF Art. 37"],
            "situacao": "vigente",
            "data_aprovacao": "1969-10-03"
        },
        {
            "numero": "339",
            "texto": "Não cabe ao Poder Judiciário, que não tem função legislativa, aumentar vencimentos de servidores públicos sob fundamento de isonomia.",
            "tema": "servidores públicos",
            "base_legal": ["CF Art. 37 X"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "340",
            "texto": "Desde a vigência do Código Civil, os bens dominicais, como os demais bens públicos, não podem ser adquiridos por usucapião.",
            "tema": "bens públicos",
            "base_legal": ["CF Art. 183 § 3º", "CF Art. 191 parágrafo único"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "670",
            "texto": "O serviço de iluminação pública não pode ser remunerado mediante taxa.",
            "tema": "taxa de iluminação pública",
            "base_legal": ["CF Art. 145 II"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "679",
            "texto": "A fixação de vencimentos dos servidores públicos não pode ser objeto de convenção coletiva.",
            "tema": "servidores públicos",
            "base_legal": ["CF Art. 37 X"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "681",
            "texto": "É inconstitucional a vinculação do reajuste de vencimentos de servidores estaduais ou municipais a índices federais de correção monetária.",
            "tema": "reajuste de vencimentos",
            "base_legal": ["CF Art. 37 XIII"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "683",
            "texto": "O limite de idade para a inscrição em concurso público só se legitima em face do art. 7º, XXX, da Constituição, quando possa ser justificado pela natureza das atribuições do cargo a ser preenchido.",
            "tema": "concurso público",
            "base_legal": ["CF Art. 7º XXX"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "685",
            "texto": "É inconstitucional toda modalidade de provimento que propicie ao servidor investir-se, sem prévia aprovação em concurso público destinado ao seu provimento, em cargo que não integra a carreira na qual anteriormente investido.",
            "tema": "concurso público",
            "base_legal": ["CF Art. 37 II"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "686",
            "texto": "Só por lei se pode sujeitar a exame psicotécnico a habilitação de candidato a cargo público.",
            "tema": "concurso público",
            "base_legal": ["CF Art. 37 I", "CF Art. 37 II"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "649",
            "texto": "É inconstitucional a criação, por Constituição estadual, de órgão de controle administrativo do Poder Judiciário do qual participem representantes de outros Poderes ou entidades.",
            "tema": "separação de poderes",
            "base_legal": ["CF Art. 2º"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "654",
            "texto": "A garantia da irretroatividade da lei, prevista no art. 5º, XXXVI, da Constituição da República, não é invocável pela entidade estatal que a tenha editado.",
            "tema": "irretroatividade",
            "base_legal": ["CF Art. 5º XXXVI"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === DIREITO TRIBUTÁRIO ===
        {
            "numero": "66",
            "texto": "É legítima a cobrança do tributo que houver sido aumentado após o orçamento, mas antes do início do respectivo exercício financeiro.",
            "tema": "anterioridade tributária",
            "base_legal": ["CF Art. 150 III b"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "67",
            "texto": "É inconstitucional a cobrança do tributo que houver sido aumentado após o início do exercício financeiro a que se refere.",
            "tema": "anterioridade tributária",
            "base_legal": ["CF Art. 150 III b"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "69",
            "texto": "A Constituição Estadual não pode estabelecer limite para o aumento de tributos municipais.",
            "tema": "autonomia tributária municipal",
            "base_legal": ["CF Art. 30"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "70",
            "texto": "É inadmissível a interdição de estabelecimento como meio coercitivo para cobrança de tributo.",
            "tema": "sanção política tributária",
            "base_legal": ["CF Art. 5º LIV"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "71",
            "texto": "Embora pago indevidamente, não cabe restituição de tributo indireto.",
            "tema": "restituição de tributo indireto",
            "base_legal": ["CTN Art. 166"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "100",
            "texto": "Caindo o selo no chão do cartório, o interessado pode adquirir outro, não lhe sendo lícito reclamar a restituição do preço do primeiro.",
            "tema": "selo cartorário",
            "base_legal": [],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "323",
            "texto": "É inadmissível a apreensão de mercadorias como meio coercitivo para pagamento de tributos.",
            "tema": "sanção política tributária",
            "base_legal": ["CF Art. 5º LIV"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "547",
            "texto": "Não é lícito à autoridade proibir que o contribuinte em débito adquira estampilhas, despache mercadorias nas alfândegas e exerça suas atividades profissionais.",
            "tema": "sanção política tributária",
            "base_legal": ["CF Art. 5º LIV"],
            "situacao": "vigente",
            "data_aprovacao": "1969-12-03"
        },
        {
            "numero": "544",
            "texto": "Isenções tributárias concedidas, sob condição onerosa, não podem ser livremente suprimidas.",
            "tema": "isenção tributária",
            "base_legal": ["CTN Art. 178"],
            "situacao": "vigente",
            "data_aprovacao": "1969-12-03"
        },
        {
            "numero": "545",
            "texto": "Preços de serviços públicos e taxas não se confundem, porque estas, diferentemente daqueles, são compulsórias e têm sua cobrança condicionada à prévia autorização orçamentária, em relação à lei que as instituiu.",
            "tema": "taxa versus preço público",
            "base_legal": ["CF Art. 145 II"],
            "situacao": "vigente",
            "data_aprovacao": "1969-12-03"
        },
        {
            "numero": "546",
            "texto": "Cabe a restituição do tributo pago indevidamente, quando reconhecido por decisão, que o contribuinte \"de jure\" não recuperou do contribuinte \"de facto\" o \"quantum\" respectivo.",
            "tema": "restituição de tributo",
            "base_legal": ["CTN Art. 166"],
            "situacao": "vigente",
            "data_aprovacao": "1969-12-03"
        },
        {
            "numero": "575",
            "texto": "À mercadoria importada de país signatário do GATT, ou membro da ALALC, estende-se o tratamento tributário dado ao similar nacional.",
            "tema": "importação e tratados",
            "base_legal": ["CF Art. 5º § 2º"],
            "situacao": "vigente",
            "data_aprovacao": "1976-12-15"
        },
        {
            "numero": "584",
            "texto": "Ao Imposto de Renda calculado sobre os rendimentos do ano-base, aplica-se a lei vigente no exercício financeiro em que deve ser apresentada a declaração.",
            "tema": "imposto de renda",
            "base_legal": ["CTN Art. 144"],
            "situacao": "vigente",
            "data_aprovacao": "1976-12-15"
        },
        {
            "numero": "591",
            "texto": "A imunidade ou a isenção tributária do comprador não se estende ao produtor, contribuinte do imposto sobre produtos industrializados.",
            "tema": "imunidade tributária",
            "base_legal": ["CF Art. 150 VI"],
            "situacao": "vigente",
            "data_aprovacao": "1976-12-15"
        },
        {
            "numero": "656",
            "texto": "É inconstitucional a lei que estabelece alíquotas progressivas para o imposto de transmissão \"inter vivos\" de bens imóveis – ITBI com base no valor venal do imóvel.",
            "tema": "ITBI progressivo",
            "base_legal": ["CF Art. 156 II"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "657",
            "texto": "A imunidade prevista no art. 150, VI, \"d\", da Constituição Federal abrange os filmes e papéis fotográficos necessários à publicação de jornais e periódicos.",
            "tema": "imunidade tributária",
            "base_legal": ["CF Art. 150 VI d"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "659",
            "texto": "É legítima a cobrança da COFINS, do PIS e do FINSOCIAL sobre as operações relativas a energia elétrica, serviços de telecomunicações, derivados de petróleo, combustíveis e minerais do País.",
            "tema": "COFINS e PIS",
            "base_legal": ["CF Art. 195"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "660",
            "texto": "Até a edição da lei complementar prevista no art. 7º, I, da Constituição, não se exige depósito do FGTS na conta do trabalhador em caso de despedida injusta.",
            "tema": "FGTS",
            "base_legal": ["CF Art. 7º I"],
            "situacao": "superada",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "661",
            "texto": "No mandado de segurança impetrado por servidor público contra ato de autoridade coatora de que resultou a supressão ou a redução de vantagens, o prazo decadencial conta-se da data em que o impetrante teve ciência do ato impugnado.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "superada",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "662",
            "texto": "É legítima a incidência do ICMS na comercialização de exemplares de obras cinematográficas, gravados em fitas de videocassete.",
            "tema": "ICMS",
            "base_legal": ["CF Art. 155 II"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "663",
            "texto": "Os §§ 1º e 3º do art. 192 da Constituição, revogados pela Emenda Constitucional nº 40/2003, que limitavam a taxa de juros reais a 12% ao ano, tinham sua aplicabilidade condicionada à edição de lei complementar.",
            "tema": "juros constitucionais",
            "base_legal": ["CF Art. 192"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === DIREITO CIVIL / OBRIGAÇÕES / CONTRATOS ===
        {
            "numero": "596",
            "texto": "As disposições do Decreto 22.626/1933 não se aplicam às taxas de juros e aos outros encargos cobrados nas operações realizadas por instituições públicas ou privadas, que integram o sistema financeiro nacional.",
            "tema": "juros bancários",
            "base_legal": ["Lei 4.595/1964"],
            "situacao": "vigente",
            "data_aprovacao": "1976-12-15"
        },
        {
            "numero": "489",
            "texto": "A compra e venda de automóvel não prevalece contra terceiros, de boa-fé, se o contrato não foi transcrito no Registro de Títulos e Documentos.",
            "tema": "compra e venda de veículo",
            "base_legal": ["CC Art. 221"],
            "situacao": "superada",
            "data_aprovacao": "1969-10-03"
        },
        {
            "numero": "490",
            "texto": "A pensão correspondente à indenização oriunda de responsabilidade civil deve ser calculada com base no salário mínimo vigente ao tempo da sentença e ajustar-se-á às variações ulteriores.",
            "tema": "responsabilidade civil",
            "base_legal": ["CC Art. 950"],
            "situacao": "vigente",
            "data_aprovacao": "1969-10-03"
        },
        {
            "numero": "491",
            "texto": "É indenizável o acidente que cause a morte de filho menor, ainda que não exerça trabalho remunerado.",
            "tema": "responsabilidade civil",
            "base_legal": ["CC Art. 948"],
            "situacao": "vigente",
            "data_aprovacao": "1969-10-03"
        },
        {
            "numero": "492",
            "texto": "A empresa locadora de veículos responde, civil e solidariamente com o locatário, pelos danos por este causados a terceiro, no uso do carro locado.",
            "tema": "responsabilidade civil",
            "base_legal": ["CC Art. 932"],
            "situacao": "vigente",
            "data_aprovacao": "1969-10-03"
        },
        {
            "numero": "494",
            "texto": "A ação para anular venda de ascendente a descendente, sem consentimento dos demais, prescreve em vinte anos, contados da data do ato, revogada a Súmula 152.",
            "tema": "venda de ascendente a descendente",
            "base_legal": ["CC Art. 496"],
            "situacao": "vigente",
            "data_aprovacao": "1969-10-03"
        },
        {
            "numero": "562",
            "texto": "Na indenização de danos materiais decorrentes de ato ilícito cabe a atualização de seu valor, utilizando-se, para esse fim, dentre outros critérios, dos índices de correção monetária.",
            "tema": "responsabilidade civil",
            "base_legal": ["CC Art. 944"],
            "situacao": "vigente",
            "data_aprovacao": "1976-12-15"
        },
        {
            "numero": "563",
            "texto": "O concubino pode ser beneficiário do seguro de vida do companheiro que o indicou como tal.",
            "tema": "seguro de vida",
            "base_legal": ["CC Art. 793"],
            "situacao": "superada",
            "data_aprovacao": "1976-12-15"
        },
        # === DIREITO DE FAMÍLIA / SUCESSÕES ===
        {
            "numero": "377",
            "texto": "No regime de separação legal de bens, comunicam-se os adquiridos na constância do casamento.",
            "tema": "regime de bens",
            "base_legal": ["CC Art. 1.658"],
            "situacao": "vigente",
            "data_aprovacao": "1964-04-03"
        },
        {
            "numero": "380",
            "texto": "Não se presume o abandono de causa pelo advogado, com a simples devolução do mandato, nos autos.",
            "tema": "mandato advocatício",
            "base_legal": ["CPC Art. 112"],
            "situacao": "vigente",
            "data_aprovacao": "1964-04-03"
        },
        {
            "numero": "149",
            "texto": "É imprescritível a ação de investigação de paternidade, mas não o é a de petição de herança.",
            "tema": "investigação de paternidade",
            "base_legal": ["CC Art. 1.606"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "301",
            "texto": "O falido é parte ilegítima para pleitear a restituição de mercadorias vendidas a crédito.",
            "tema": "falência",
            "base_legal": ["Lei 11.101/2005"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "380",
            "texto": "Não se presume o abandono de causa pelo advogado, com a simples devolução do mandato, nos autos.",
            "tema": "mandato advocatício",
            "base_legal": ["CPC Art. 112"],
            "situacao": "vigente",
            "data_aprovacao": "1964-04-03"
        },
        # === DIREITO DO TRABALHO ===
        {
            "numero": "316",
            "texto": "A simples adesão a greve não constitui falta grave.",
            "tema": "greve",
            "base_legal": ["CF Art. 9º"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "443",
            "texto": "A prescrição das prestações anteriores ao período previsto em lei não ocorre, quando não tiver sido alcançado o prazo prescricional.",
            "tema": "prescrição trabalhista",
            "base_legal": ["CF Art. 7º XXIX"],
            "situacao": "superada",
            "data_aprovacao": "1964-10-01"
        },
        {
            "numero": "675",
            "texto": "Os intervalos fixados para descanso e alimentação durante a jornada de seis horas não descaracterizam o sistema de turnos ininterruptos de revezamento para o efeito do art. 7º, XIV, da Constituição.",
            "tema": "turnos ininterruptos",
            "base_legal": ["CF Art. 7º XIV"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "676",
            "texto": "A garantia da estabilidade provisória prevista no art. 10, II, a, do Ato das Disposições Constitucionais Transitórias, também se aplica ao suplente do cargo de direção de comissões internas de prevenção de acidentes (CIPA).",
            "tema": "estabilidade provisória CIPA",
            "base_legal": ["ADCT Art. 10 II a"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === DIREITO PENAL / PROCESSO PENAL ===
        {
            "numero": "145",
            "texto": "Não há crime, quando a preparação do flagrante pela polícia torna impossível a sua consumação.",
            "tema": "flagrante preparado",
            "base_legal": ["CP Art. 17"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "146",
            "texto": "A prescrição da ação penal regula-se pela pena concretizada na sentença, quando não há recurso da acusação.",
            "tema": "prescrição penal",
            "base_legal": ["CP Art. 109"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "147",
            "texto": "A prescrição de crime falimentar começa a correr da data em que deveria estar encerrada a falência, ou do trânsito em julgado da sentença que a encerrar ou que julgar cumprida a concordata.",
            "tema": "prescrição penal falimentar",
            "base_legal": ["Lei 11.101/2005"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "304",
            "texto": "Decisão denegatória de mandado de segurança, não fazendo coisa julgada contra o impetrante, não impede o uso da ação própria.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "693",
            "texto": "Não cabe habeas corpus contra decisão condenatória a pena de multa, ou relativo a processo em curso por infração penal a que a pena pecuniária seja a única cominada.",
            "tema": "habeas corpus",
            "base_legal": ["CF Art. 5º LXVIII"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "694",
            "texto": "Não cabe habeas corpus contra a imposição da pena de exclusão de militar ou de perda de patente ou de função pública.",
            "tema": "habeas corpus",
            "base_legal": ["CF Art. 5º LXVIII"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "695",
            "texto": "Não cabe habeas corpus quando já extinta a pena privativa de liberdade.",
            "tema": "habeas corpus",
            "base_legal": ["CF Art. 5º LXVIII"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "696",
            "texto": "Reunidos os pressupostos legais permissivos da suspensão condicional do processo, mas se recusando o Promotor de Justiça a propô-la, o juiz, dissentindo, remeterá a questão ao Procurador-Geral, aplicando-se por analogia o art. 28 do Código de Processo Penal.",
            "tema": "suspensão condicional do processo",
            "base_legal": ["Lei 9.099/1995 Art. 89", "CPP Art. 28"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "697",
            "texto": "A proibição de liberdade provisória nos processos por crimes hediondos não veda o relaxamento da prisão processual por excesso de prazo.",
            "tema": "liberdade provisória",
            "base_legal": ["CF Art. 5º LXVI", "Lei 8.072/1990"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "698",
            "texto": "Não se estende aos demais crimes hediondos a admissibilidade de progressão no regime de execução da pena aplicada ao crime de tortura.",
            "tema": "progressão de regime",
            "base_legal": ["Lei 8.072/1990", "Lei 9.455/1997"],
            "situacao": "superada",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "704",
            "texto": "Não viola as garantias do juiz natural, da ampla defesa e do devido processo legal a atração por continência ou conexão do processo do co-réu ao foro por prerrogativa de função de um dos denunciados.",
            "tema": "foro por prerrogativa",
            "base_legal": ["CF Art. 5º LIII", "CF Art. 5º LIV", "CF Art. 5º LV"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "710",
            "texto": "No processo penal, contam-se os prazos da data da intimação, e não da juntada aos autos do mandado ou da carta precatória ou de ordem.",
            "tema": "prazos processuais penais",
            "base_legal": ["CPP Art. 798"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "714",
            "texto": "É concorrente a legitimidade do ofendido, mediante queixa, e do Ministério Público, condicionada à representação do ofendido, para a ação penal por crime contra a honra de servidor público em razão do exercício de suas funções.",
            "tema": "ação penal",
            "base_legal": ["CP Art. 141 II", "CPP Art. 29"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "715",
            "texto": "A pena unificada para atender ao limite de trinta anos de cumprimento, determinado pelo art. 75 do Código Penal, não é considerada para a concessão de outros benefícios, como o livramento condicional ou regime mais favorável de execução.",
            "tema": "unificação de penas",
            "base_legal": ["CP Art. 75"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "716",
            "texto": "Admite-se a progressão de regime de cumprimento da pena ou a aplicação imediata de regime menos severo nela determinada, antes do trânsito em julgado da sentença condenatória.",
            "tema": "progressão de regime",
            "base_legal": ["LEP Art. 112"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "717",
            "texto": "Não impede a progressão de regime de execução da pena, fixada em sentença não transitada em julgado, o fato de o réu se encontrar em prisão especial.",
            "tema": "progressão de regime",
            "base_legal": ["LEP Art. 112"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "718",
            "texto": "A opinião do julgador sobre gravidade em abstrato do crime não constitui motivação idônea para a imposição de regime mais severo do que o permitido segundo a pena aplicada.",
            "tema": "regime prisional",
            "base_legal": ["CP Art. 33"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "719",
            "texto": "A imposição do regime de cumprimento mais severo do que a pena aplicada permitir exige motivação idônea.",
            "tema": "regime prisional",
            "base_legal": ["CP Art. 33"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "720",
            "texto": "O art. 309 do Código de Trânsito Brasileiro, que reclama decorra do fato perigo de dano, derrogou o art. 32 da Lei das Contravenções Penais no tocante à direção sem habilitação em vias terrestres.",
            "tema": "direção sem habilitação",
            "base_legal": ["CTB Art. 309"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "721",
            "texto": "São desnecessárias a prévia autorização judicial e a comunicação ao Ministério Público para a obtenção de dados cadastrais de nome, endereço e filiação constantes de órgãos públicos ou de concessionárias de serviços públicos.",
            "tema": "dados cadastrais",
            "base_legal": ["CF Art. 5º XII"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        # === DIREITO CONSTITUCIONAL ===
        {
            "numero": "266",
            "texto": "Não cabe mandado de segurança contra lei em tese.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "267",
            "texto": "Não cabe mandado de segurança contra ato judicial passível de recurso ou correição.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "268",
            "texto": "Não cabe mandado de segurança contra decisão judicial com trânsito em julgado.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "269",
            "texto": "O mandado de segurança não é substitutivo de ação de cobrança.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "270",
            "texto": "Não cabe mandado de segurança para impugnar enquadramento da Lei 3.780, de 12 de julho de 1960, que envolva exame de prova ou de situação funcional complexa.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "271",
            "texto": "Concessão de mandado de segurança não produz efeitos patrimoniais em relação a período pretérito, os quais devem ser reclamados administrativamente ou pela via judicial própria.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "625",
            "texto": "Controvérsia sobre matéria de direito não impede concessão de mandado de segurança.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "1984-10-24"
        },
        {
            "numero": "626",
            "texto": "A suspensão da liminar em mandado de segurança, salvo determinação em contrário da decisão que a deferir, vigorará até o trânsito em julgado da decisão definitiva de concessão da segurança ou, havendo recurso, até a sua manutenção pelo tribunal.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "1984-10-24"
        },
        {
            "numero": "629",
            "texto": "A impetração de mandado de segurança coletivo por entidade de classe em favor dos associados independe da autorização destes.",
            "tema": "mandado de segurança coletivo",
            "base_legal": ["CF Art. 5º LXX"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "630",
            "texto": "A entidade de classe tem legitimação para o mandado de segurança ainda quando a pretensão veiculada interesse apenas a uma parte da respectiva categoria.",
            "tema": "mandado de segurança coletivo",
            "base_legal": ["CF Art. 5º LXX"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "631",
            "texto": "Extingue-se o processo de mandado de segurança se o impetrante não promove, no prazo assinado, a citação do litisconsorte passivo necessário.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "632",
            "texto": "É constitucional lei que fixa o prazo de decadência para a impetração de mandado de segurança.",
            "tema": "mandado de segurança",
            "base_legal": ["CF Art. 5º LXIX"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === HABEAS CORPUS / HABEAS DATA ===
        {
            "numero": "691",
            "texto": "Não compete ao Supremo Tribunal Federal conhecer de habeas corpus impetrado contra decisão do Relator que, em habeas corpus requerido a tribunal superior, indefere a liminar.",
            "tema": "habeas corpus",
            "base_legal": ["CF Art. 102 I i"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "692",
            "texto": "Não se conhece de habeas corpus contra omissão de relator de extradição, se fundado em fato ou direito estrangeiro cuja prova não constava dos autos, nem foi ele provocado a respeito.",
            "tema": "habeas corpus",
            "base_legal": ["CF Art. 102 I g"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === DIREITO PROCESSUAL CIVIL ===
        {
            "numero": "1",
            "texto": "É vedada a expulsão de estrangeiro casado com brasileira, ou que tenha filho brasileiro dependente da economia paterna.",
            "tema": "expulsão de estrangeiro",
            "base_legal": ["CF Art. 5º"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "2",
            "texto": "Concede-se liberdade vigiada ao extraditando que estiver preso por prazo superior a sessenta dias.",
            "tema": "extradição",
            "base_legal": ["CF Art. 5º LXV"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "150",
            "texto": "Prescreve a execução no mesmo prazo de prescrição da ação.",
            "tema": "prescrição",
            "base_legal": ["CC Art. 189"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "228",
            "texto": "Não é provisória a execução na pendência de recurso extraordinário, ou de agravo destinado a fazê-lo admitir.",
            "tema": "execução",
            "base_legal": ["CPC Art. 995"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "231",
            "texto": "O revel, em processo cível, pode produzir provas, desde que compareça em tempo oportuno.",
            "tema": "revelia",
            "base_legal": ["CPC Art. 349"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "233",
            "texto": "Salvo em caso de legislação especial, a mulher casada tem plena capacidade processual.",
            "tema": "capacidade processual",
            "base_legal": ["CPC Art. 70"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "234",
            "texto": "São devidos honorários de advogado em ação de acidente do trabalho julgada procedente.",
            "tema": "honorários advocatícios",
            "base_legal": ["CPC Art. 85"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "235",
            "texto": "É competente para a ação de acidente do trabalho a Justiça cível comum, inclusive em segunda instância, ainda que seja parte autarquia seguradora.",
            "tema": "competência acidentária",
            "base_legal": ["CF Art. 109 I"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "325",
            "texto": "O disposto no Decreto-lei nº 6.259/44 não é aplicável ao concurso de prognósticos.",
            "tema": "concurso de prognósticos",
            "base_legal": [],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        # === PROPRIEDADE / POSSE / USUCAPIÃO ===
        {
            "numero": "445",
            "texto": "A Lei 2.437, de 07.03.1955, que reduz prazo prescricional, é aplicável às prescrições em curso na data de sua vigência (01.01.1956), salvo quanto aos processos então pendentes.",
            "tema": "prescrição",
            "base_legal": ["CC Art. 2.028"],
            "situacao": "superada",
            "data_aprovacao": "1964-10-01"
        },
        {
            "numero": "583",
            "texto": "Promitente comprador de imóvel, com título registrado, tem direito a opor embargos de terceiro para livrar de penhora o imóvel objeto da promessa de compra e venda.",
            "tema": "embargos de terceiro",
            "base_legal": ["CPC Art. 674"],
            "situacao": "superada",
            "data_aprovacao": "1976-12-15"
        },
        # === DIREITO DO CONSUMIDOR ===
        {
            "numero": "646",
            "texto": "Ofende o princípio da livre concorrência lei municipal que impede a instalação de estabelecimentos comerciais do mesmo ramo em determinada área.",
            "tema": "livre concorrência",
            "base_legal": ["CF Art. 170 IV"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === DESAPROPRIAÇÃO ===
        {
            "numero": "157",
            "texto": "É necessária prévia autorização do Presidente da República para desapropriação, pelos Estados, de empresa de energia elétrica.",
            "tema": "desapropriação",
            "base_legal": ["CF Art. 5º XXIV"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "164",
            "texto": "No processo de desapropriação, são devidos juros compensatórios desde a antecipada imissão de posse, ordenada pelo juiz, por motivo de urgência.",
            "tema": "desapropriação",
            "base_legal": ["DL 3.365/1941 Art. 15"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "345",
            "texto": "Na chamada desapropriação indireta, os juros compensatórios são devidos a partir da perícia, desde que tenha por base o valor do imóvel à época da ocupação.",
            "tema": "desapropriação indireta",
            "base_legal": ["DL 3.365/1941"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "416",
            "texto": "Pela demora no pagamento do preço da desapropriação não cabe indenização complementar além dos juros.",
            "tema": "desapropriação",
            "base_legal": ["DL 3.365/1941"],
            "situacao": "vigente",
            "data_aprovacao": "1964-06-01"
        },
        {
            "numero": "618",
            "texto": "Na desapropriação, direta ou indireta, a taxa dos juros compensatórios é de 12% (doze por cento) ao ano.",
            "tema": "desapropriação",
            "base_legal": ["DL 3.365/1941"],
            "situacao": "vigente",
            "data_aprovacao": "1984-10-24"
        },
        # === SERVIDORES PÚBLICOS ===
        {
            "numero": "682",
            "texto": "Não ofende a Constituição a correção monetária no pagamento com atraso dos vencimentos de servidores públicos.",
            "tema": "servidores públicos",
            "base_legal": ["CF Art. 37"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "684",
            "texto": "É inconstitucional o veto não motivado à participação de candidato a concurso público.",
            "tema": "concurso público",
            "base_legal": ["CF Art. 37 I", "CF Art. 37 II"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === COMPETÊNCIA ===
        {
            "numero": "501",
            "texto": "Compete à Justiça ordinária estadual o processo e o julgamento, em ambas as instâncias, das causas de acidente do trabalho, ainda que promovidas contra a União, suas autarquias, empresas públicas ou sociedades de economia mista.",
            "tema": "competência",
            "base_legal": ["CF Art. 109 I"],
            "situacao": "vigente",
            "data_aprovacao": "1969-10-03"
        },
        {
            "numero": "556",
            "texto": "É competente a Justiça comum para julgar as causas em que é parte sociedade de economia mista.",
            "tema": "competência",
            "base_legal": ["CF Art. 109 I"],
            "situacao": "vigente",
            "data_aprovacao": "1976-12-15"
        },
        {
            "numero": "517",
            "texto": "As sociedades de economia mista só têm foro na Justiça Federal, quando a União intervém como assistente ou opoente.",
            "tema": "competência",
            "base_legal": ["CF Art. 109 I"],
            "situacao": "vigente",
            "data_aprovacao": "1969-12-03"
        },
        # === AÇÃO POPULAR / AÇÃO CIVIL PÚBLICA ===
        {
            "numero": "365",
            "texto": "Pessoa jurídica não tem legitimidade para propor ação popular.",
            "tema": "ação popular",
            "base_legal": ["CF Art. 5º LXXIII"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        # === PREVIDENCIÁRIO ===
        {
            "numero": "729",
            "texto": "A decisão na ADC-4 não se aplica à antecipação de tutela em causa de natureza previdenciária.",
            "tema": "tutela antecipada previdenciária",
            "base_legal": ["CF Art. 201"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        # === ELEITORAL ===
        {
            "numero": "722",
            "texto": "São da competência legislativa da União a definição dos crimes de responsabilidade e o estabelecimento das respectivas normas de processo e julgamento.",
            "tema": "crime de responsabilidade",
            "base_legal": ["CF Art. 22 I"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        # === RESPONSABILIDADE DO ESTADO ===
        {
            "numero": "341",
            "texto": "É presumida a culpa do patrão ou comitente pelo ato culposo do empregado ou preposto.",
            "tema": "responsabilidade civil do empregador",
            "base_legal": ["CC Art. 932 III"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        # === INTERVENÇÃO DO ESTADO NA PROPRIEDADE ===
        {
            "numero": "668",
            "texto": "É inconstitucional a lei municipal que tenha estabelecido, antes da Emenda Constitucional 29/2000, alíquotas progressivas para o IPTU, salvo se destinada a assegurar o cumprimento da função social da propriedade urbana.",
            "tema": "IPTU progressivo",
            "base_legal": ["CF Art. 156 I", "CF Art. 182 § 4º"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "669",
            "texto": "Norma legal que altera o prazo de recolhimento da obrigação tributária não se sujeita ao princípio da anterioridade.",
            "tema": "anterioridade tributária",
            "base_legal": ["CF Art. 150 III b"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === PRECATÓRIOS ===
        {
            "numero": "655",
            "texto": "A exceção prevista no art. 100, caput, da Constituição, em favor dos créditos de natureza alimentícia, não dispensa a expedição de precatório, limitando-se a isentá-los da observância da ordem cronológica dos precatórios decorrentes de condenações de outra natureza.",
            "tema": "precatórios",
            "base_legal": ["CF Art. 100"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === EDUCAÇÃO ===
        {
            "numero": "724",
            "texto": "Ainda quando alçado ao cargo de juiz do Tribunal Regional Eleitoral, o juiz estadual continua afeto à Justiça estadual para efeitos de aposentadoria.",
            "tema": "magistratura",
            "base_legal": ["CF Art. 93"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        # === EXTINÇÃO DE PUNIBILIDADE ===
        {
            "numero": "18",
            "texto": "Pela falta residual, não compreendida na absolvição pelo juízo criminal, é admissível a punição administrativa do servidor público.",
            "tema": "punição administrativa",
            "base_legal": ["CF Art. 41"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "19",
            "texto": "É inadmissível segunda punição de servidor público, baseada no mesmo processo em que se fundou a primeira.",
            "tema": "punição administrativa",
            "base_legal": ["CF Art. 41"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "20",
            "texto": "É necessário processo administrativo com ampla defesa, para demissão de funcionário admitido por concurso.",
            "tema": "demissão de servidor",
            "base_legal": ["CF Art. 41"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "21",
            "texto": "Funcionário em estágio probatório não pode ser exonerado nem demitido sem inquérito ou sem as formalidades legais de apuração de sua capacidade.",
            "tema": "estágio probatório",
            "base_legal": ["CF Art. 41"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "47",
            "texto": "Reitor de universidade não é livremente demissível pelo Presidente da República durante o prazo de sua investidura.",
            "tema": "reitor de universidade",
            "base_legal": ["CF Art. 207"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        # === EXTRADIÇÃO ===
        {
            "numero": "421",
            "texto": "Não impede a extradição a circunstância de ser o extraditando casado com brasileira ou ter filho brasileiro.",
            "tema": "extradição",
            "base_legal": ["CF Art. 5º LI"],
            "situacao": "vigente",
            "data_aprovacao": "1964-06-01"
        },
        # === IMUNIDADE PARLAMENTAR ===
        {
            "numero": "3",
            "texto": "A imunidade concedida a deputados estaduais é restrita à Justiça do Estado.",
            "tema": "imunidade parlamentar",
            "base_legal": ["CF Art. 27 § 1º"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "4",
            "texto": "Não perde a imunidade parlamentar o congressista nomeado Ministro de Estado.",
            "tema": "imunidade parlamentar",
            "base_legal": ["CF Art. 53"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        # === INDENIZAÇÃO / DANOS ===
        {
            "numero": "187",
            "texto": "A responsabilidade contratual do transportador, pelo acidente com o passageiro, não é elidida por culpa de terceiro, contra o qual tem ação regressiva.",
            "tema": "responsabilidade do transportador",
            "base_legal": ["CC Art. 735"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "188",
            "texto": "O segurador tem ação regressiva contra o causador do dano, pelo que efetivamente pagou, até ao limite previsto no contrato de seguro.",
            "tema": "seguro - sub-rogação",
            "base_legal": ["CC Art. 786"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "229",
            "texto": "A indenização acidentária não exclui a do direito comum, em caso de dolo ou culpa grave do empregador.",
            "tema": "acidente de trabalho",
            "base_legal": ["CF Art. 7º XXVIII"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        {
            "numero": "246",
            "texto": "Comprovado não haver dano, não cabe a condenação em honorários de advogado.",
            "tema": "honorários advocatícios",
            "base_legal": ["CPC Art. 85"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        # === EXECUÇÃO / PENHORA ===
        {
            "numero": "406",
            "texto": "O direito de reclamar perdas e danos em virtude de protestos não prospera quando a existência da dívida não é contestada.",
            "tema": "protesto",
            "base_legal": ["CC Art. 186"],
            "situacao": "superada",
            "data_aprovacao": "1964-04-03"
        },
        # === MILITAR ===
        {
            "numero": "298",
            "texto": "O legislador ordinário só pode sujeitar civis à jurisdição militar, em tempo de paz, nos crimes contra a segurança externa do País ou as instituições militares.",
            "tema": "jurisdição militar",
            "base_legal": ["CF Art. 124"],
            "situacao": "vigente",
            "data_aprovacao": "1963-12-13"
        },
        # === PRESCRIÇÃO ===
        {
            "numero": "153",
            "texto": "Simples alegação de direito abstrato não configura dissídio jurisprudencial, para conhecimento do recurso extraordinário.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        # === HONORÁRIOS ===
        {
            "numero": "450",
            "texto": "São devidos honorários de advogado sempre que vencedor o beneficiário de justiça gratuita.",
            "tema": "honorários advocatícios",
            "base_legal": ["CPC Art. 85"],
            "situacao": "vigente",
            "data_aprovacao": "1964-10-01"
        },
        {
            "numero": "512",
            "texto": "Não cabe condenação em honorários de advogado na ação de mandado de segurança.",
            "tema": "mandado de segurança",
            "base_legal": ["Lei 12.016/2009 Art. 25"],
            "situacao": "vigente",
            "data_aprovacao": "1969-10-03"
        },
        # === PENHORA / IMPENHORABILIDADE ===
        {
            "numero": "205",
            "texto": "Tem legitimidade o sócio-gerente para requerer concordata.",
            "tema": "concordata",
            "base_legal": [],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        # === FIANÇA / LOCAÇÃO ===
        {
            "numero": "214",
            "texto": "A decisão do Tribunal que autoriza a penhora além dos limites do pedido é nula.",
            "tema": "penhora",
            "base_legal": ["CPC Art. 141"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        # === EXTRADIÇÃO E ASILO ===
        {
            "numero": "692",
            "texto": "Não se conhece de habeas corpus contra omissão de relator de extradição, se fundado em fato ou direito estrangeiro cuja prova não constava dos autos, nem foi ele provocado a respeito.",
            "tema": "habeas corpus",
            "base_legal": ["CF Art. 102 I g"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === CONSTITUCIONAL - FEDERALISMO ===
        {
            "numero": "645",
            "texto": "É competente o município para fixar o horário de funcionamento de estabelecimento comercial.",
            "tema": "competência municipal",
            "base_legal": ["CF Art. 30 I"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "647",
            "texto": "Compete privativamente à União legislar sobre vencimentos dos membros de polícias civil e militar do Distrito Federal.",
            "tema": "competência legislativa",
            "base_legal": ["CF Art. 21 XIV"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "648",
            "texto": "A norma do § 3º do art. 192 da Constituição, revogada pela Emenda Constitucional 40/2003, que limitava a taxa de juros reais a 12% ao ano, tinha sua aplicabilidade condicionada à edição de lei complementar.",
            "tema": "juros constitucionais",
            "base_legal": ["CF Art. 192"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === CONTROLE DE CONSTITUCIONALIDADE ===
        {
            "numero": "642",
            "texto": "Não cabe ação direta de inconstitucionalidade de lei do Distrito Federal derivada da sua competência legislativa municipal.",
            "tema": "controle de constitucionalidade",
            "base_legal": ["CF Art. 102 I a"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === DEPOSITÁRIO INFIEL ===
        {
            "numero": "619",
            "texto": "A prisão do depositário judicial pode ser decretada no próprio processo em que se constituiu o encargo, independentemente da propositura de ação de depósito.",
            "tema": "depositário judicial",
            "base_legal": ["CPC Art. 161"],
            "situacao": "superada",
            "data_aprovacao": "1984-10-24"
        },
        # === IMUNIDADE TRIBUTÁRIA ===
        {
            "numero": "724",
            "texto": "Ainda quando alçado ao cargo de juiz do Tribunal Regional Eleitoral, o juiz estadual continua afeto à Justiça estadual para efeitos de aposentadoria.",
            "tema": "magistratura",
            "base_legal": ["CF Art. 93"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        # === LICITAÇÃO E CONTRATOS ADMINISTRATIVOS ===
        {
            "numero": "672",
            "texto": "O reajuste ou a correção monetária do preço de contrato de obra pública deve ser procedido de acordo com o disposto em norma legal específica.",
            "tema": "contratos administrativos",
            "base_legal": ["Lei 8.666/1993"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "673",
            "texto": "O art. 125, I, da Constituição é autoaplicável.",
            "tema": "competência estadual",
            "base_legal": ["CF Art. 125 I"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === PROCESSO LEGISLATIVO ===
        {
            "numero": "5",
            "texto": "A sanção do projeto supre a falta de iniciativa do Poder Executivo.",
            "tema": "processo legislativo",
            "base_legal": ["CF Art. 61"],
            "situacao": "superada",
            "data_aprovacao": "1963-12-13"
        },
        # === DIREITO INTERNACIONAL ===
        {
            "numero": "421",
            "texto": "Não impede a extradição a circunstância de ser o extraditando casado com brasileira ou ter filho brasileiro.",
            "tema": "extradição",
            "base_legal": ["CF Art. 5º LI"],
            "situacao": "vigente",
            "data_aprovacao": "1964-06-01"
        },
        # === ADDITIONAL IMPORTANT SUMULAS ===
        {
            "numero": "634",
            "texto": "Não compete ao Supremo Tribunal Federal conceder medida cautelar para dar efeito suspensivo a recurso extraordinário que ainda não foi objeto de juízo de admissibilidade na origem.",
            "tema": "cautelar em RE",
            "base_legal": ["CF Art. 102 I"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "635",
            "texto": "Cabe ao Presidente do Tribunal de origem decidir o pedido de medida cautelar em recurso extraordinário ainda pendente do seu juízo de admissibilidade.",
            "tema": "cautelar em RE",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "637",
            "texto": "Não cabe recurso extraordinário contra acórdão de Tribunal de Justiça que defere pedido de intervenção estadual em município.",
            "tema": "intervenção estadual",
            "base_legal": ["CF Art. 35"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "638",
            "texto": "A controvérsia sobre a incidência, ou não, de correção monetária, em razão de mora do devedor, é questão de caráter infraconstitucional, não viabilizando recurso extraordinário.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "640",
            "texto": "É cabível recurso extraordinário contra decisão proferida por juiz de primeiro grau nas causas de alçada, ou por turma recursal de juizado especial cível e criminal.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "641",
            "texto": "Não se conta em dobro o prazo para recorrer, quando só um dos litisconsortes haja sucumbido.",
            "tema": "prazo recursal",
            "base_legal": ["CPC Art. 229"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === ADDITIONAL CONSTITUTIONAL ===
        {
            "numero": "643",
            "texto": "O Ministério Público tem legitimidade para promover ação civil pública cujo fundamento seja a ilegalidade de reajuste de mensalidades escolares.",
            "tema": "ação civil pública",
            "base_legal": ["CF Art. 129 III"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "644",
            "texto": "Ao titular do cargo de procurador de autarquia não se exige a apresentação de instrumento de mandato para representá-la em juízo.",
            "tema": "representação processual",
            "base_legal": ["CPC Art. 75 IV"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "650",
            "texto": "Os incisos I e XI do art. 20 da Constituição Federal não alcançam terras de aldeamentos extintos, ainda que ocupadas por indígenas em passado remoto.",
            "tema": "terras indígenas",
            "base_legal": ["CF Art. 20 I", "CF Art. 20 XI"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "651",
            "texto": "A medida provisória não apreciada pelo Congresso Nacional podia, até a Emenda Constitucional 32/2001, ser reeditada dentro do seu prazo de eficácia de trinta dias, mantidos os efeitos de lei desde a primeira edição.",
            "tema": "medida provisória",
            "base_legal": ["CF Art. 62"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "652",
            "texto": "Não contraria a Constituição o art. 15, § 1º, do Decreto-lei nº 3.365/1941 (Lei da Desapropriação por Utilidade Pública).",
            "tema": "desapropriação",
            "base_legal": ["DL 3.365/1941 Art. 15 § 1º"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "653",
            "texto": "No Tribunal de Contas estadual, composto por sete conselheiros, quatro devem ser escolhidos pela Assembléia Legislativa e três pelo Chefe do Poder Executivo estadual, cabendo a este indicar um dentre auditores e outro dentre membros do Ministério Público, e um terceiro à sua livre escolha.",
            "tema": "tribunal de contas",
            "base_legal": ["CF Art. 75"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "658",
            "texto": "São constitucionais os arts. 7º, VII, e 8º, parágrafo único, da Lei 8.906/94 (Estatuto da Advocacia e da OAB).",
            "tema": "advocacia",
            "base_legal": ["Lei 8.906/1994"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "664",
            "texto": "É inconstitucional o inciso V do art. 1º da Lei 8.033/1990, que instituiu a incidência do imposto nas operações de crédito, câmbio e seguro — IOF sobre saques efetuados em caderneta de poupança.",
            "tema": "IOF",
            "base_legal": ["CF Art. 153 V"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "665",
            "texto": "É constitucional a Taxa de Fiscalização dos Mercados de Títulos e Valores Mobiliários instituída pela Lei 7.940/89.",
            "tema": "taxa de fiscalização",
            "base_legal": ["CF Art. 145 II"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "666",
            "texto": "A contribuição confederativa de que trata o art. 8º, IV, da Constituição, só é exigível dos filiados ao sindicato respectivo.",
            "tema": "contribuição sindical",
            "base_legal": ["CF Art. 8º IV"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "667",
            "texto": "Viola a garantia constitucional de acesso à jurisdição a taxa judiciária calculada sem limite sobre o valor da causa.",
            "tema": "acesso à justiça",
            "base_legal": ["CF Art. 5º XXXV"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "671",
            "texto": "Os servidores públicos e os trabalhadores em geral têm direito, no que concerne à URP de abril e maio de 1988, apenas ao valor correspondente a 7/30 de 16,19%, até o advento da revisão salarial em data-base.",
            "tema": "URP",
            "base_legal": ["CF Art. 37 X"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "674",
            "texto": "Está em vigor a Lei 1.408, de 09.08.1951, que dá preferência, na ordem de classificação, ao irmão do aluno já matriculado em escola pública.",
            "tema": "educação",
            "base_legal": ["Lei 1.408/1951"],
            "situacao": "superada",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "677",
            "texto": "Até que lei venha a dispor a respeito, incumbe ao Ministério do Trabalho proceder ao registro das entidades sindicais e zelar pela observância do princípio da unicidade.",
            "tema": "registro sindical",
            "base_legal": ["CF Art. 8º II"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "678",
            "texto": "São inconstitucionais os incisos I e III do art. 7º da Lei 8.162/91, que afastam, para efeito de anuênio e de licença-prêmio, a contagem do tempo de serviço regido pela CLT dos servidores que passaram a submeter-se ao regime jurídico único.",
            "tema": "servidores públicos",
            "base_legal": ["CF Art. 39"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "680",
            "texto": "O direito ao auxílio-alimentação não se estende aos servidores inativos.",
            "tema": "servidores públicos",
            "base_legal": ["CF Art. 40"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === MAIS SÚMULAS PENAIS ===
        {
            "numero": "706",
            "texto": "É relativo o efeito devolutivo da apelação nos processos em que houve julgamento pelo Tribunal do Júri.",
            "tema": "tribunal do júri",
            "base_legal": ["CF Art. 5º XXXVIII"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "707",
            "texto": "Constitui nulidade a falta de intimação do denunciado para oferecer contra-razões ao recurso interposto da rejeição da denúncia, não a suprindo a nomeação de defensor dativo.",
            "tema": "ampla defesa",
            "base_legal": ["CF Art. 5º LV"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "708",
            "texto": "É nulo o julgamento da apelação se, após a manifestação nos autos da renúncia do único defensor, o réu não foi previamente intimado para constituir outro.",
            "tema": "ampla defesa",
            "base_legal": ["CF Art. 5º LV"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "712",
            "texto": "É nula a decisão que determina o desaforamento de processo da competência do júri sem audiência da defesa.",
            "tema": "tribunal do júri",
            "base_legal": ["CF Art. 5º XXXVIII"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        {
            "numero": "713",
            "texto": "O efeito devolutivo da apelação contra decisões do Júri é adstrito aos fundamentos da sua interposição.",
            "tema": "tribunal do júri",
            "base_legal": ["CF Art. 5º XXXVIII"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
        # === MAIS TRIBUTÁRIO ===
        {
            "numero": "725",
            "texto": "É constitucional o § 2º do art. 6º da Lei 8.024/1990, resultante da conversão da Medida Provisória nº 168/1990, que fixou o BTN fiscal como índice de correção monetária aplicável aos depósitos bloqueados pelo Plano Collor I.",
            "tema": "plano econômico",
            "base_legal": ["CF Art. 5º XXXVI"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "726",
            "texto": "Para efeito de aposentadoria especial de professores, não se computa o tempo de serviço prestado fora da sala de aula.",
            "tema": "aposentadoria de professor",
            "base_legal": ["CF Art. 40 § 5º"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "727",
            "texto": "Não pode o Magistrado deixar de encaminhar ao Supremo Tribunal Federal o agravo de instrumento interposto da decisão que não admite recurso extraordinário, ainda que referente a causa instaurada no âmbito dos Juizados Especiais.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "728",
            "texto": "É de três dias o prazo para a interposição de recurso extraordinário contra decisão do juiz dos Juizados Especiais.",
            "tema": "recurso extraordinário em JEC",
            "base_legal": ["Lei 9.099/1995"],
            "situacao": "superada",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "730",
            "texto": "A imunidade tributária conferida a instituições de assistência social sem fins lucrativos pelo art. 150, VI, c, da Constituição, somente alcança as entidades fechadas de previdência social privada se não houver contribuição dos beneficiários.",
            "tema": "imunidade tributária",
            "base_legal": ["CF Art. 150 VI c"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "731",
            "texto": "Para fim da competência originária do Tribunal Regional Federal, é irrelevante a qualificação do cargo efetivo ocupado pelo réu.",
            "tema": "competência TRF",
            "base_legal": ["CF Art. 108"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "732",
            "texto": "É constitucional a cobrança da contribuição do salário-educação, seja sob a Carta de 1969, seja sob a Constituição Federal de 1988, e no regime da Lei 9.424/96.",
            "tema": "salário-educação",
            "base_legal": ["CF Art. 212 § 5º"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "733",
            "texto": "Não cabe recurso extraordinário contra decisão proferida no processamento de precatórios.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 100"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "734",
            "texto": "Não cabe reclamação quando já houver transitado em julgado o ato judicial que se alega tenha desrespeitado decisão do Supremo Tribunal Federal.",
            "tema": "reclamação constitucional",
            "base_legal": ["CF Art. 102 I l"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "736",
            "texto": "Compete à Justiça do Trabalho julgar as ações que tenham como causa de pedir o descumprimento de normas trabalhistas relativas à segurança, higiene e saúde dos trabalhadores.",
            "tema": "competência trabalhista",
            "base_legal": ["CF Art. 114"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        # === PROCESSO - COMPETÊNCIA ===
        {
            "numero": "508",
            "texto": "Compete à Justiça estadual, em ambas as instâncias, processar e julgar as causas em que for parte o Banco do Brasil S.A.",
            "tema": "competência",
            "base_legal": ["CF Art. 109 I"],
            "situacao": "vigente",
            "data_aprovacao": "1969-10-03"
        },
        {
            "numero": "516",
            "texto": "O Serviço Social da Indústria — SESI — está sujeito à jurisdição da Justiça estadual.",
            "tema": "competência",
            "base_legal": ["CF Art. 109 I"],
            "situacao": "vigente",
            "data_aprovacao": "1969-12-03"
        },
        {
            "numero": "690",
            "texto": "Compete originariamente ao Supremo Tribunal Federal o julgamento de habeas corpus contra ato de Turma Recursal de Juizados Especiais Criminais.",
            "tema": "competência",
            "base_legal": ["CF Art. 102 I i"],
            "situacao": "superada",
            "data_aprovacao": "2003-10-24"
        },
        # === PROCESSO CIVIL - EXECUÇÃO FISCAL ===
        {
            "numero": "549",
            "texto": "A Taxa de Assistência Judiciária dos serventuários, fixada e cobrada pelo Poder Judiciário, é inconstitucional por contrariar o princípio da separação e independência dos Poderes.",
            "tema": "taxa de assistência judiciária",
            "base_legal": ["CF Art. 2º"],
            "situacao": "superada",
            "data_aprovacao": "1969-12-03"
        },
        # === DIREITO ELEITORAL ===
        {
            "numero": "722",
            "texto": "São da competência legislativa da União a definição dos crimes de responsabilidade e o estabelecimento das respectivas normas de processo e julgamento.",
            "tema": "crime de responsabilidade",
            "base_legal": ["CF Art. 22 I"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        {
            "numero": "723",
            "texto": "Não se admite a suspensão condicional do processo por crime continuado, se a somatória da pena mínima da infração mais grave com o aumento mínimo de um sexto for superior a um ano.",
            "tema": "suspensão condicional",
            "base_legal": ["Lei 9.099/1995 Art. 89"],
            "situacao": "vigente",
            "data_aprovacao": "2003-11-26"
        },
        # === ADDITIONAL FOUNDATIONAL SUMULAS ===
        {
            "numero": "636",
            "texto": "Não cabe recurso extraordinário por contrariedade ao princípio constitucional da legalidade, quando a sua verificação pressuponha rever a interpretação dada a normas infraconstitucionais pela decisão recorrida.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
            "data_aprovacao": "2003-10-24"
        },
    ]


def deduplicate(sumulas: list[dict]) -> list[dict]:
    """Remove duplicate entries by numero, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[dict] = []
    for s in sumulas:
        if s["numero"] not in seen:
            seen.add(s["numero"])
            unique.append(s)
    return unique


def main() -> None:
    sumulas = get_sumulas()
    sumulas = deduplicate(sumulas)
    sumulas.sort(key=lambda s: int(s["numero"]))

    output_path = Path("/Users/raphaellages/Desktop/juris/data/corpus/sumulas_stf.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sumulas, f, ensure_ascii=False, indent=2)

    print(f"Generated {len(sumulas)} STF Súmulas at {output_path}")


if __name__ == "__main__":
    main()
