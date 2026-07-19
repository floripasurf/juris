"""Tests for CPC art. 1.026 embargos de declaração interruption of interlocutórias.

Escopo ESTREITO (revisão jurídica externa): apenas a interlocutória agravável
(TPU 385, art. 1.015 CPC) reabre o agravo após o julgamento dos embargos.
Qualquer outra decisão recorrível (DECISAO_RECORRIVEL sem TPU 385) com ED
detectados vai para revisão manual — nunca fabricar recurso. Acórdão/RE/REsp
sem categoria própria no CategoriaSemantica ficam fora do escopo.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from juris.agents.analyzer import AnalysisResult
from juris.mni.tpu import CategoriaSemantica, Urgencia
from juris.prazo.engine import compute_prazos
from juris.prazo.rules import TipoAcao


def _movement(
    movimento_id: str,
    categoria: CategoriaSemantica,
    codigo_tpu: int,
    descricao: str,
    data: date,
    *,
    requer_acao: bool = True,
) -> AnalysisResult:
    return AnalysisResult(
        movimento_id=movimento_id,
        codigo_tpu=codigo_tpu,
        descricao=descricao,
        data_hora=datetime(data.year, data.month, data.day, 12, 0, tzinfo=UTC),
        categoria=categoria,
        urgencia=Urgencia.CRITICA,
        requer_acao=requer_acao,
        recomendacao="Test",
        confianca=0.95,
        metodo="rule",
    )


class TestAgravoInterrompidoPorEmbargos:
    def test_agravo_suprimido_com_embargos_pendentes_vai_para_revisao_manual(self) -> None:
        # (a) interlocutória TPU 385 + ED pendente → agravo suprimido +
        # prazo_interrompido_embargos_pendentes (nenhum agravo fabricado
        # enquanto o ED não é julgado).
        analyses = [
            _movement(
                "dec", CategoriaSemantica.DECISAO_RECORRIVEL, 385, "Decisão interlocutória publicada", date(2026, 1, 5)
            ),
            _movement("ed", CategoriaSemantica.RECURSO, 199, "Embargos de declaração opostos", date(2026, 1, 9)),
        ]

        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 1, 20))

        assert all(p.rule.nome != "Agravo de instrumento" for p in report.prazos)
        assert any(
            r.motivo == "prazo_interrompido_embargos_pendentes" and r.movimento_id == "dec"
            for r in report.revisao_manual
        )

    def test_agravo_reabre_apos_julgamento_de_embargos_de_declaracao(self) -> None:
        # (b) + julgamento do ED publicado → reabertura-agravo-ed, 15 dias
        # úteis contados da intimação do julgamento dos embargos.
        analyses = [
            _movement(
                "dec", CategoriaSemantica.DECISAO_RECORRIVEL, 385, "Decisão interlocutória publicada", date(2026, 1, 5)
            ),
            _movement("ed", CategoriaSemantica.RECURSO, 199, "Embargos de declaração opostos", date(2026, 1, 9)),
            _movement(
                "ed-julgado",
                CategoriaSemantica.RECURSO,
                464,
                "Embargos de declaração não providos",
                date(2026, 2, 10),
            ),
        ]

        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 2, 11))

        reopened = [p for p in report.prazos if p.movimento_id == "dec:reabertura-agravo-ed"]
        assert len(reopened) == 1
        assert reopened[0].data_inicio == date(2026, 2, 10)
        assert reopened[0].dias_uteis_total == 15
        assert reopened[0].rule.tipo_acao == TipoAcao.RECORRER
        assert reopened[0].rule.base_legal == "Art. 1.015 c/c Art. 1.026 CPC"
        # O agravo original (a partir da data da decisão) não deve continuar
        # aparecendo como se estivesse correndo/vencido.
        assert all(
            not (p.rule.nome == "Agravo de instrumento" and p.data_inicio == date(2026, 1, 5))
            for p in report.prazos
        )

    def test_agravo_reaberto_admite_dobro_para_fazenda(self) -> None:
        # A regra reaberta do agravo deve passar pelo mesmo caminho de dobra
        # (Task 8) que a apelação reaberta — não é prazo próprio.
        analyses = [
            _movement(
                "dec", CategoriaSemantica.DECISAO_RECORRIVEL, 385, "Decisão interlocutória publicada", date(2026, 1, 5)
            ),
            _movement("ed", CategoriaSemantica.RECURSO, 199, "Embargos de declaração opostos", date(2026, 1, 9)),
            _movement(
                "ed-julgado",
                CategoriaSemantica.RECURSO,
                464,
                "Embargos de declaração não providos",
                date(2026, 2, 10),
            ),
        ]

        report = compute_prazos(
            "123", "tjmg", analyses, today=date(2026, 2, 11), parte_representada="fazenda"
        )

        reopened = [p for p in report.prazos if p.movimento_id == "dec:reabertura-agravo-ed"]
        assert len(reopened) == 1
        assert reopened[0].dias_uteis_total == 30
        assert "art. 183" in reopened[0].rule.base_legal.lower()


class TestDecisaoSemAgravoVaiParaRevisaoManual:
    def test_ed_sobre_decisao_nao_agravavel_vai_para_revisao_manual_sem_fabricar_recurso(self) -> None:
        # (c) interlocutória sem TPU 385 (ex.: TPU 193 "Decisão") + ED
        # detectados → revisão manual ed_sobre_decisao_recurso_incerto; nenhum
        # prazo de recurso é fabricado nesse cenário (nem pendente, nem
        # julgado o ED).
        analyses = [
            _movement("dec", CategoriaSemantica.DECISAO_RECORRIVEL, 193, "Decisão publicada", date(2026, 1, 5)),
            _movement("ed", CategoriaSemantica.RECURSO, 199, "Embargos de declaração opostos", date(2026, 1, 9)),
            _movement(
                "ed-julgado",
                CategoriaSemantica.RECURSO,
                464,
                "Embargos de declaração não providos",
                date(2026, 2, 10),
            ),
        ]

        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 2, 11))

        assert report.prazos == []
        assert any(
            r.motivo == "ed_sobre_decisao_recurso_incerto" and r.movimento_id == "dec"
            for r in report.revisao_manual
        )


class TestPareamentoEdDecisao:
    def test_ed_apos_decisao_b_nao_interrompe_decisao_a(self) -> None:
        # (d) pareamento: duas interlocutórias A e B (ambas TPU 385); o ED só
        # é oposto depois de B. A não pode ser considerada interrompida —
        # a janela de A vai até a publicação de B.
        analyses = [
            _movement(
                "dec-a",
                CategoriaSemantica.DECISAO_RECORRIVEL,
                385,
                "Decisão interlocutória A publicada",
                date(2026, 1, 5),
            ),
            _movement(
                "dec-b",
                CategoriaSemantica.DECISAO_RECORRIVEL,
                385,
                "Decisão interlocutória B publicada",
                date(2026, 1, 20),
            ),
            _movement(
                "ed-b",
                CategoriaSemantica.RECURSO,
                199,
                "Embargos de declaração opostos contra decisão B",
                date(2026, 1, 22),
            ),
        ]

        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 1, 25))

        agravo_a = [p for p in report.prazos if p.movimento_id == "dec-a"]
        assert len(agravo_a) == 1
        assert agravo_a[0].rule.nome == "Agravo de instrumento"
        assert agravo_a[0].data_inicio == date(2026, 1, 5)

        # B, por outro lado, está corretamente suprimida aguardando seu
        # próprio ED.
        assert all(p.movimento_id != "dec-b" for p in report.prazos)
        assert any(
            r.motivo == "prazo_interrompido_embargos_pendentes" and r.movimento_id == "dec-b"
            for r in report.revisao_manual
        )


class TestPareamentoCrossCategoria:
    def test_ed_apos_interlocutoria_seguida_de_sentenca_interrompe_so_a_sentenca(self) -> None:
        # (f) pareamento cross-categoria: interlocutória TPU 385 (05/01) →
        # sentença (10/01) → único ED (15/01) → julgamento do ED publicado
        # (20/02). O ED só pode pertencer a UMA decisão — a mais próxima e
        # anterior a ele (a sentença). Bug corrigido: a janela antiga só
        # olhava para a próxima decisão da MESMA categoria, então um único ED
        # marcava as duas como interrompidas (e, julgado, fabricava dois
        # recursos reabertos para o mesmo ED).
        analyses = [
            _movement(
                "dec",
                CategoriaSemantica.DECISAO_RECORRIVEL,
                385,
                "Decisão interlocutória publicada",
                date(2026, 1, 5),
            ),
            _movement("sent", CategoriaSemantica.SENTENCA, 132, "Sentença publicada", date(2026, 1, 10)),
            _movement("ed", CategoriaSemantica.RECURSO, 199, "Embargos de declaração opostos", date(2026, 1, 15)),
            _movement(
                "ed-julgado",
                CategoriaSemantica.RECURSO,
                464,
                "Embargos de declaração não providos",
                date(2026, 2, 20),
            ),
        ]

        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 2, 21))

        reopened = [
            p for p in report.prazos if p.movimento_id in {"sent:reabertura-apelacao-ed", "dec:reabertura-agravo-ed"}
        ]
        assert len(reopened) == 1
        assert reopened[0].movimento_id == "sent:reabertura-apelacao-ed"
        assert reopened[0].data_inicio == date(2026, 2, 20)

        # A interlocutória NÃO foi suprimida/reaberta pelo ED da sentença — o
        # agravo dela segue o fluxo normal (vencido/aberto conforme as datas).
        agravo_normal = [p for p in report.prazos if p.movimento_id == "dec"]
        assert len(agravo_normal) == 1
        assert agravo_normal[0].rule.nome == "Agravo de instrumento"
        assert not any(r.movimento_id == "dec" for r in report.revisao_manual)

    def test_ed_apos_sentenca_seguida_de_interlocutoria_interrompe_so_o_agravo(self) -> None:
        # Espelho de (f): sentença primeiro, depois interlocutória, ED só
        # após a interlocutória → só o agravo reabre; a sentença segue o
        # fluxo normal (Apelação + Embargos de declaração, sem interrupção).
        analyses = [
            _movement("sent", CategoriaSemantica.SENTENCA, 132, "Sentença publicada", date(2026, 1, 5)),
            _movement(
                "dec",
                CategoriaSemantica.DECISAO_RECORRIVEL,
                385,
                "Decisão interlocutória publicada",
                date(2026, 1, 10),
            ),
            _movement("ed", CategoriaSemantica.RECURSO, 199, "Embargos de declaração opostos", date(2026, 1, 15)),
            _movement(
                "ed-julgado",
                CategoriaSemantica.RECURSO,
                464,
                "Embargos de declaração não providos",
                date(2026, 2, 20),
            ),
        ]

        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 2, 21))

        reopened = [
            p for p in report.prazos if p.movimento_id in {"sent:reabertura-apelacao-ed", "dec:reabertura-agravo-ed"}
        ]
        assert len(reopened) == 1
        assert reopened[0].movimento_id == "dec:reabertura-agravo-ed"
        assert reopened[0].data_inicio == date(2026, 2, 20)

        # A sentença NÃO foi suprimida/reaberta pelo ED da interlocutória — a
        # apelação segue o fluxo normal.
        apelacao_normal = [p for p in report.prazos if p.movimento_id == "sent" and p.rule.nome == "Apelação"]
        assert len(apelacao_normal) == 1
        assert not any(r.movimento_id == "sent" for r in report.revisao_manual)


class TestRegressaoSentenca:
    def test_apelacao_reabre_apos_embargos_continua_intacta(self) -> None:
        # (e) regressão: o cenário de sentença (Task existente) não pode ser
        # afetado pela generalização do pareamento para DECISAO_RECORRIVEL.
        analyses = [
            _movement("sent", CategoriaSemantica.SENTENCA, 132, "Sentença publicada", date(2026, 1, 5)),
            _movement("ed", CategoriaSemantica.RECURSO, 199, "Embargos de declaração opostos", date(2026, 1, 9)),
            _movement(
                "ed-julgado",
                CategoriaSemantica.RECURSO,
                464,
                "Embargos de declaração não providos",
                date(2026, 2, 10),
            ),
        ]

        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 2, 11))

        reopened = [p for p in report.prazos if "reaberta após embargos" in p.rule.nome]
        assert len(reopened) == 1
        assert reopened[0].data_inicio == date(2026, 2, 10)
        assert reopened[0].dias_uteis_total == 15
        assert reopened[0].status != "vencido"


class TestJulgamentoAmbiguoEntreDecisoes:
    """Achado P1 nº 6 (revisão 18/07): a resolução do ED não pode vazar para
    fora da janela da decisão (a janela antiga buscava a resolução em
    ``after_decision`` inteiro), e mesmo restrita à janela um julgamento não
    é atribuído sozinho a uma decisão se outra decisão do processo também
    tiver ED pendente naquele momento — regra de ouro: na dúvida, revisão
    manual; nunca dois recursos reabertos pelo mesmo julgamento.
    """

    def test_julgamento_apos_ed_b_nao_reabre_dois_recursos(self) -> None:
        # Cenário do achado: decisão A -> ED-A; decisão B -> ED-B; um único
        # julgamento é publicado DEPOIS da interposição do ED-B (portanto já
        # fora da janela de A, que termina na publicação de B). A janela nova
        # já impede que esse julgamento seja escolhido para A; ele só cai
        # dentro da janela (sem fim) de B. Mas quando B tentaria usá-lo, A
        # ainda tem um ED interposto antes dele e nunca resolvido dentro da
        # SUA própria janela — ambíguo o bastante para B não reabrir sozinho.
        # Resultado observado: NENHUM recurso é reaberto; A fica no motivo
        # pré-existente ("embargos pendentes") e B vai para o motivo novo
        # ("ed_julgamento_ambiguo"). Nunca dois recursos reabertos pelo mesmo
        # julgamento.
        analyses = [
            _movement(
                "dec-a",
                CategoriaSemantica.DECISAO_RECORRIVEL,
                385,
                "Decisão interlocutória A publicada",
                date(2026, 1, 5),
            ),
            _movement(
                "ed-a",
                CategoriaSemantica.RECURSO,
                199,
                "Embargos de declaração opostos contra decisão A",
                date(2026, 1, 9),
            ),
            _movement(
                "dec-b",
                CategoriaSemantica.DECISAO_RECORRIVEL,
                385,
                "Decisão interlocutória B publicada",
                date(2026, 1, 20),
            ),
            _movement(
                "ed-b",
                CategoriaSemantica.RECURSO,
                199,
                "Embargos de declaração opostos contra decisão B",
                date(2026, 1, 25),
            ),
            _movement(
                "ed-julgado",
                CategoriaSemantica.RECURSO,
                464,
                "Embargos de declaração não providos",
                date(2026, 2, 10),
            ),
        ]

        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 2, 11))

        # Regra de ouro: nunca dois recursos reabertos pelo mesmo julgamento
        # (e, aqui, nem sequer um é fabricado sem pareamento seguro).
        reabertos = {"dec-a:reabertura-agravo-ed", "dec-b:reabertura-agravo-ed"}
        assert all(p.movimento_id not in reabertos for p in report.prazos)

        # A: nenhum julgamento caiu dentro da sua própria janela (que termina
        # em dec-b) -> segue "pendente", como já era antes desta correção.
        assert any(
            r.motivo == "prazo_interrompido_embargos_pendentes" and r.movimento_id == "dec-a"
            for r in report.revisao_manual
        )
        # B: o julgamento caiu dentro da sua janela, mas A também tinha ED
        # pendente naquele momento -> ambíguo, não reabre sozinho.
        assert any(
            r.motivo == "ed_julgamento_ambiguo" and r.movimento_id == "dec-b" for r in report.revisao_manual
        )

    def test_dois_eds_julgados_em_ordem_cada_decisao_reabre_com_seu_julgamento(self) -> None:
        # Pareamento inequívoco: o julgamento do ED-A ocorre ANTES de decisão
        # B sequer existir (dentro da janela de A, sem nenhuma outra decisão
        # com ED pendente naquele momento), e o julgamento do ED-B ocorre
        # depois, quando o ED-A já está resolvido — nenhuma ambiguidade em
        # nenhum dos dois momentos. Cada decisão reabre com o SEU julgamento.
        analyses = [
            _movement(
                "dec-a",
                CategoriaSemantica.DECISAO_RECORRIVEL,
                385,
                "Decisão interlocutória A publicada",
                date(2026, 1, 5),
            ),
            _movement(
                "ed-a",
                CategoriaSemantica.RECURSO,
                199,
                "Embargos de declaração opostos contra decisão A",
                date(2026, 1, 9),
            ),
            _movement(
                "ed-a-julgado",
                CategoriaSemantica.RECURSO,
                464,
                "Embargos de declaração da decisão A não providos",
                date(2026, 1, 15),
            ),
            _movement(
                "dec-b",
                CategoriaSemantica.DECISAO_RECORRIVEL,
                385,
                "Decisão interlocutória B publicada",
                date(2026, 1, 20),
            ),
            _movement(
                "ed-b",
                CategoriaSemantica.RECURSO,
                199,
                "Embargos de declaração opostos contra decisão B",
                date(2026, 1, 25),
            ),
            _movement(
                "ed-b-julgado",
                CategoriaSemantica.RECURSO,
                464,
                "Embargos de declaração da decisão B não providos",
                date(2026, 2, 10),
            ),
        ]

        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 2, 11))

        reopened_a = [p for p in report.prazos if p.movimento_id == "dec-a:reabertura-agravo-ed"]
        reopened_b = [p for p in report.prazos if p.movimento_id == "dec-b:reabertura-agravo-ed"]
        assert len(reopened_a) == 1
        assert reopened_a[0].data_inicio == date(2026, 1, 15)
        assert len(reopened_b) == 1
        assert reopened_b[0].data_inicio == date(2026, 2, 10)
        assert not any(r.motivo == "ed_julgamento_ambiguo" for r in report.revisao_manual)
