"""Tests for prazo rules — CPC and CLT deadline mapping."""

from __future__ import annotations

from juris.mni.tpu import CategoriaSemantica
from juris.prazo.rules import (
    CLT_RULES,
    CPC_RULES,
    TipoAcao,
    find_applicable_rules,
    shortest_deadline,
)


class TestFindApplicableRules:
    def test_citacao_has_contestacao(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.CITACAO)
        assert any(r.tipo_acao == TipoAcao.CONTESTAR for r in rules)
        assert any(r.dias_uteis == 15 for r in rules)

    def test_sentenca_has_apelacao_and_embargos(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.SENTENCA)
        nomes = {r.nome for r in rules}
        assert "Apelação" in nomes
        assert "Embargos de declaração" in nomes

    def test_embargos_shorter_than_apelacao(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.SENTENCA)
        # Rules are sorted by dias_uteis ascending
        assert rules[0].dias_uteis < rules[-1].dias_uteis

    def test_decisao_has_agravo(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.DECISAO_RECORRIVEL, codigo_tpu=385)
        assert any("agravo" in r.nome.lower() for r in rules)

    def test_specific_code_preferred(self) -> None:
        # Decisão interlocutória (385) should prefer specific agravo rule
        rules = find_applicable_rules(CategoriaSemantica.DECISAO_RECORRIVEL, codigo_tpu=385)
        assert all(r.codigo_tpu == 385 for r in rules)

    def test_generic_when_no_specific(self) -> None:
        # Decisão genérica (193) — no specific rule, gets generic embargos
        rules = find_applicable_rules(CategoriaSemantica.DECISAO_RECORRIVEL, codigo_tpu=193)
        assert len(rules) >= 1
        assert any(r.codigo_tpu is None for r in rules)

    def test_noise_has_no_rules(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.NOISE)
        assert rules == []

    def test_unclassified_has_no_rules(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.UNCLASSIFIED)
        assert rules == []

    def test_cumprimento_has_pagamento(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.CUMPRIMENTO, codigo_tpu=480)
        assert any(r.tipo_acao == TipoAcao.PAGAR for r in rules)

    def test_tutela_has_cumprir(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.TUTELA, codigo_tpu=334)
        assert any(r.tipo_acao == TipoAcao.CUMPRIR for r in rules)

    def test_pericia_laudo_has_manifestar(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.PERICIA, codigo_tpu=472)
        assert any(r.tipo_acao == TipoAcao.MANIFESTAR for r in rules)


class TestShortestDeadline:
    def test_sentenca_shortest_is_embargos(self) -> None:
        rule = shortest_deadline(CategoriaSemantica.SENTENCA)
        assert rule is not None
        assert rule.dias_uteis == 5  # Embargos de declaração

    def test_citacao_shortest(self) -> None:
        rule = shortest_deadline(CategoriaSemantica.CITACAO)
        assert rule is not None
        assert rule.dias_uteis == 15

    def test_noise_no_deadline(self) -> None:
        assert shortest_deadline(CategoriaSemantica.NOISE) is None


class TestCLTRules:
    def test_clt_recurso_is_8_dias(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.SENTENCA, justica="trabalho")
        ro = [r for r in rules if "ordinário" in r.nome.lower()]
        assert len(ro) == 1
        assert ro[0].dias_uteis == 8

    def test_clt_contestacao(self) -> None:
        rules = find_applicable_rules(CategoriaSemantica.CITACAO, justica="trabalho")
        assert any(r.tipo_acao == TipoAcao.CONTESTAR for r in rules)


class TestRulesHaveBaseLegal:
    def test_all_cpc_rules_have_base_legal(self) -> None:
        for rule in CPC_RULES:
            assert rule.base_legal, f"Rule {rule.nome} missing base_legal"

    def test_all_clt_rules_have_base_legal(self) -> None:
        for rule in CLT_RULES:
            assert rule.base_legal, f"Rule {rule.nome} missing base_legal"
