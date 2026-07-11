"""Tests for the judicial calendar — feriados and dias úteis."""

from __future__ import annotations

from datetime import date

from juris.prazo.calendar import (
    JudicialCalendar,
    _easter,
    feriados_estaduais,
    feriados_nacionais,
    recesso_forense,
)


class TestEaster:
    def test_2026(self) -> None:
        assert _easter(2026) == date(2026, 4, 5)

    def test_2025(self) -> None:
        assert _easter(2025) == date(2025, 4, 20)

    def test_2024(self) -> None:
        assert _easter(2024) == date(2024, 3, 31)


class TestFeriadosNacionais:
    def test_has_13_holidays_after_consciencia_negra_law(self) -> None:
        feriados = feriados_nacionais(2026)
        assert len(feriados) == 13

    def test_has_12_holidays_before_consciencia_negra_law(self) -> None:
        feriados = feriados_nacionais(2023)
        assert len(feriados) == 12

    def test_includes_fixed_dates(self) -> None:
        feriados = feriados_nacionais(2026)
        datas = {f.data for f in feriados}
        assert date(2026, 1, 1) in datas   # Ano novo
        assert date(2026, 4, 21) in datas  # Tiradentes
        assert date(2026, 5, 1) in datas   # Trabalho
        assert date(2026, 9, 7) in datas   # Independência
        assert date(2026, 11, 20) in datas # Consciência Negra
        assert date(2026, 12, 25) in datas # Natal

    def test_consciencia_negra_is_national_since_2024(self) -> None:
        assert date(2023, 11, 20) not in {f.data for f in feriados_nacionais(2023)}
        assert date(2024, 11, 20) in {f.data for f in feriados_nacionais(2024)}
        assert date(2025, 11, 20) in {f.data for f in feriados_nacionais(2025)}

    def test_includes_easter_dependent(self) -> None:
        feriados = feriados_nacionais(2026)
        datas = {f.data for f in feriados}
        # Easter 2026 = April 5
        assert date(2026, 2, 17) in datas  # Carnaval terça (47 days before)
        assert date(2026, 4, 3) in datas   # Sexta-feira Santa


class TestRecessoForense:
    def test_dec_20_to_jan_20(self) -> None:
        recesso = recesso_forense(2025)
        datas = {f.data for f in recesso}
        assert date(2025, 12, 20) in datas
        assert date(2025, 12, 31) in datas
        assert date(2026, 1, 1) in datas
        assert date(2026, 1, 20) in datas
        assert date(2025, 12, 19) not in datas
        assert date(2026, 1, 21) not in datas

    def test_count(self) -> None:
        recesso = recesso_forense(2025)
        assert len(recesso) == 32  # Dec 20-31 (12) + Jan 1-20 (20)


class TestFeriadosEstaduais:
    def test_mg(self) -> None:
        feriados = feriados_estaduais(2026, "mg")
        assert len(feriados) >= 1
        datas = {f.data for f in feriados}
        assert date(2026, 4, 21) in datas  # Data Magna MG

    def test_sp(self) -> None:
        feriados = feriados_estaduais(2026, "sp")
        assert len(feriados) >= 1
        datas = {f.data for f in feriados}
        assert date(2026, 7, 9) in datas

    def test_unknown_uf(self) -> None:
        feriados = feriados_estaduais(2026, "xx")
        assert feriados == []

    def test_rj_keeps_consciencia_negra_before_national_law_only(self) -> None:
        assert date(2023, 11, 20) in {f.data for f in feriados_estaduais(2023, "rj")}
        assert date(2024, 11, 20) not in {f.data for f in feriados_estaduais(2024, "rj")}
        # São Jorge (feriado estadual do RJ) permanece.
        assert date(2024, 4, 23) in {f.data for f in feriados_estaduais(2024, "rj")}

    def test_datas_magnas_estaduais_estatutarias(self) -> None:
        # Amostra de data magna / criação do estado adicionadas na expansão do #8.
        casos = {
            "df": (11, 30),  # Dia do Evangélico
            "pa": (8, 15),  # Adesão do Grão-Pará
            "ms": (10, 11),  # Criação do Estado
            "ce": (3, 25),  # Data Magna do Ceará
            "am": (9, 5),
            "se": (7, 8),
            "ro": (1, 4),
            "to": (10, 5),
        }
        for uf, (mes, dia) in casos.items():
            datas = {f.data for f in feriados_estaduais(2026, uf)}
            assert date(2026, mes, dia) in datas, uf

    def test_estados_sem_data_magna_clara_ficam_no_baseline(self) -> None:
        # ES/MT/GO/RN/SC: sem feriado estadual estatutário claro → direção segura
        # (tratados como dia útil; nunca estende prazo indevidamente).
        for uf in ("es", "mt", "go", "rn", "sc"):
            assert feriados_estaduais(2026, uf) == [], uf


class TestJudicialCalendar:
    def test_weekend_not_dia_util(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        # 2026-04-25 is Saturday
        assert not cal.is_dia_util(date(2026, 4, 25))
        # 2026-04-26 is Sunday
        assert not cal.is_dia_util(date(2026, 4, 26))

    def test_weekday_is_dia_util(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        # 2026-04-27 is Monday (not a holiday)
        assert cal.is_dia_util(date(2026, 4, 27))

    def test_feriado_not_dia_util(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        assert not cal.is_dia_util(date(2026, 12, 25))  # Natal

    def test_consciencia_negra_nacional_not_dia_util(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        assert not cal.is_dia_util(date(2026, 11, 20))
        assert cal.add_dias_uteis(date(2026, 11, 19), 1) == date(2026, 11, 23)

    def test_recesso_not_dia_util(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=True)
        assert not cal.is_dia_util(date(2026, 12, 25))
        assert not cal.is_dia_util(date(2026, 12, 22))  # Tuesday in recesso
        assert not cal.is_dia_util(date(2026, 1, 5))     # Jan 5 (from prev year recesso)

    def test_add_dias_uteis_simple(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        # 2026-04-20 is Monday. Add 5 dias úteis → Friday 2026-04-27
        # Apr 21 is Tiradentes (holiday), so skip it
        result = cal.add_dias_uteis(date(2026, 4, 20), 5)
        assert result == date(2026, 4, 28)  # Tue: 22, Wed:23, Thu:24, Fri:27(Mon is 27), Tue:28

    def test_add_dias_uteis_skips_weekend(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        # 2026-04-24 is Friday. Add 1 dia útil → Monday 2026-04-27
        result = cal.add_dias_uteis(date(2026, 4, 24), 1)
        assert result == date(2026, 4, 27)

    def test_add_zero_dias(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        result = cal.add_dias_uteis(date(2026, 4, 20), 0)
        assert result == date(2026, 4, 20)

    def test_dias_uteis_between(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        # Mon Apr 20 to Fri Apr 24 = 4 dias úteis (21 is holiday)
        count = cal.dias_uteis_between(date(2026, 4, 20), date(2026, 4, 24))
        assert count == 3  # 22, 23, 24 (21 is Tiradentes)

    def test_dias_uteis_between_same_day(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        assert cal.dias_uteis_between(date(2026, 4, 20), date(2026, 4, 20)) == 0

    def test_next_dia_util_on_weekday(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        assert cal.next_dia_util(date(2026, 4, 22)) == date(2026, 4, 22)  # Wed

    def test_next_dia_util_on_weekend(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        assert cal.next_dia_util(date(2026, 4, 25)) == date(2026, 4, 27)  # Sat→Mon

    def test_next_dia_util_on_holiday(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        # Apr 21 is Tiradentes (Tuesday in 2026)
        assert cal.next_dia_util(date(2026, 4, 21)) == date(2026, 4, 22)

    def test_subtract_dias_uteis(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        # From Monday Apr 27, subtract 1 → Friday Apr 24
        result = cal.subtract_dias_uteis(date(2026, 4, 27), 1)
        assert result == date(2026, 4, 24)

    def test_all_feriados(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=True)
        feriados = cal.all_feriados(2026)
        assert len(feriados) >= 20  # National + state + recesso
