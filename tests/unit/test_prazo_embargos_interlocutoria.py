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
