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
    def test_has_12_holidays(self) -> None:
        feriados = feriados_nacionais(2026)
        assert len(feriados) == 12

    def test_includes_fixed_dates(self) -> None:
        feriados = feriados_nacionais(2026)
        datas = {f.data for f in feriados}
        assert date(2026, 1, 1) in datas   # Ano novo
        assert date(2026, 4, 21) in datas  # Tiradentes
        assert date(2026, 5, 1) in datas   # Trabalho
        assert date(2026, 9, 7) in datas   # Independência
        assert date(2026, 12, 25) in datas # Natal

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
