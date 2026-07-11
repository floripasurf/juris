"""Brazilian judicial calendar — feriados, recessos, and dias úteis calculation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum


class TipoFeriado(StrEnum):
    """Type of holiday."""

    NACIONAL = "nacional"
    ESTADUAL = "estadual"
    MUNICIPAL = "municipal"
    FORENSE = "forense"  # Recesso forense, suspensão de prazos


@dataclass(frozen=True, slots=True)
class Feriado:
    """A single holiday entry."""

    data: date
    nome: str
    tipo: TipoFeriado


def _easter(year: int) -> date:
    """Compute Easter Sunday for a given year (Anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def feriados_nacionais(year: int) -> list[Feriado]:
    """Return all Brazilian national holidays for a given year."""
    pascoa = _easter(year)
    carnaval = pascoa - timedelta(days=47)  # Terça de carnaval
    sexta_santa = pascoa - timedelta(days=2)
    corpus_christi = pascoa + timedelta(days=60)

    feriados = [
        Feriado(date(year, 1, 1), "Confraternização Universal", TipoFeriado.NACIONAL),
        Feriado(carnaval - timedelta(days=1), "Carnaval (segunda)", TipoFeriado.NACIONAL),
        Feriado(carnaval, "Carnaval (terça)", TipoFeriado.NACIONAL),
        Feriado(sexta_santa, "Sexta-feira Santa", TipoFeriado.NACIONAL),
        Feriado(date(year, 4, 21), "Tiradentes", TipoFeriado.NACIONAL),
        Feriado(date(year, 5, 1), "Dia do Trabalho", TipoFeriado.NACIONAL),
        Feriado(corpus_christi, "Corpus Christi", TipoFeriado.NACIONAL),
        Feriado(date(year, 9, 7), "Independência do Brasil", TipoFeriado.NACIONAL),
        Feriado(date(year, 10, 12), "Nossa Sra. Aparecida", TipoFeriado.NACIONAL),
        Feriado(date(year, 11, 2), "Finados", TipoFeriado.NACIONAL),
        Feriado(date(year, 11, 15), "Proclamação da República", TipoFeriado.NACIONAL),
        Feriado(date(year, 12, 25), "Natal", TipoFeriado.NACIONAL),
    ]
    if year >= 2024:
        # Lei 14.759/2023: 20 de novembro passou a ser feriado nacional.
        feriados.append(Feriado(date(year, 11, 20), "Dia da Consciência Negra", TipoFeriado.NACIONAL))
    return feriados


def recesso_forense(year: int) -> list[Feriado]:
    """Return recesso forense dates (Dec 20 to Jan 20).

    Art. 220 CPC: Suspensão de prazos de 20/dez a 20/jan.
    """
    dates = []
    # Dec 20 to Dec 31 of current year
    for day in range(20, 32):
        dates.append(
            Feriado(
                date(year, 12, day),
                "Recesso forense",
                TipoFeriado.FORENSE,
            )
        )
    # Jan 1 to Jan 20 of next year
    for day in range(1, 21):
        dates.append(
            Feriado(
                date(year + 1, 1, day),
                "Recesso forense",
                TipoFeriado.FORENSE,
            )
        )
    return dates


# Feriados estaduais estatutários (data magna / criação do estado).
#
# Cobertura deliberadamente conservadora: só entram feriados estaduais com base
# legal firme. A direção do erro é assimétrica — um feriado indevido ESTENDE o
# prazo e pode causar perda de prazo; omitir um feriado real apenas encurta o
# prazo (falso alarme de urgência). Por isso:
#   * feriados MUNICIPAIS/de comarca NÃO entram aqui (variam por localidade);
#   * "ponto facultativo" (ex.: N. Sra. da Penha no ES) NÃO é feriado e fica de fora;
#   * estados sem data magna estadual estatutária clara (ES, GO, MT, RN, SC)
#     usam o baseline federal — o motor os trata como dia útil (direção segura).
# 20/11 (Consciência Negra) é feriado NACIONAL desde 2024 (Lei 14.759/2023) e é
# deduplicado abaixo para não contar em dobro com a entrada estadual histórica.
_FERIADOS_ESTADUAIS: dict[str, list[tuple[int, int, str]]] = {
    "ac": [(6, 15, "Aniversário do Acre")],
    "al": [(9, 16, "Emancipação Política de Alagoas")],
    "am": [(9, 5, "Elevação do Amazonas à categoria de província")],
    "ap": [(9, 13, "Criação do Território Federal do Amapá")],
    "ba": [(7, 2, "Independência da Bahia")],
    "ce": [(3, 25, "Data Magna do Ceará")],
    "df": [(11, 30, "Dia do Evangélico")],
    "ma": [(7, 28, "Adesão do Maranhão à Independência")],
    "mg": [(4, 21, "Data Magna de Minas Gerais")],
    "ms": [(10, 11, "Criação do Estado de Mato Grosso do Sul")],
    "pa": [(8, 15, "Adesão do Grão-Pará à Independência")],
    "pb": [(8, 5, "Fundação do Estado da Paraíba")],
    "pe": [(3, 6, "Revolução Pernambucana")],
    "pi": [(10, 19, "Dia do Piauí")],
    "pr": [(12, 19, "Emancipação do Paraná")],
    "rj": [(4, 23, "São Jorge"), (11, 20, "Dia da Consciência Negra")],
    "ro": [(1, 4, "Criação do Estado de Rondônia")],
    "rr": [(10, 5, "Criação do Estado de Roraima")],
    "rs": [(9, 20, "Revolução Farroupilha")],
    "se": [(7, 8, "Emancipação Política de Sergipe")],
    "sp": [(7, 9, "Revolução Constitucionalista")],
    "to": [(10, 5, "Criação do Estado do Tocantins")],
}


def feriados_estaduais(year: int, uf: str) -> list[Feriado]:
    """Return state-level holidays for a given UF.

    Municipal/comarca holidays are out of scope. Entries são estatutárias; ver o
    comentário de ``_FERIADOS_ESTADUAIS`` para a política de cobertura e a nota
    sobre estados sem data magna clara.
    """
    uf_lower = uf.lower()
    entries = _FERIADOS_ESTADUAIS.get(uf_lower, [])
    return [
        Feriado(date(year, month, day), nome, TipoFeriado.ESTADUAL)
        for month, day, nome in entries
        # 20/11 virou feriado nacional em 2024; não contar em dobro no plano estadual.
        if not (year >= 2024 and (month, day) == (11, 20))
    ]


@dataclass(slots=True)
class JudicialCalendar:
    """Calendar for computing dias úteis in Brazilian judicial proceedings.

    Combines national holidays, state holidays, recesso forense, and
    optional custom suspensions (e.g., tribunal-specific).
    """

    uf: str = "mg"
    include_recesso: bool = True
    custom_suspensions: list[Feriado] = field(default_factory=list)
    _holiday_cache: dict[int, set[date]] = field(default_factory=dict, repr=False)

    def _build_year_cache(self, year: int) -> set[date]:
        """Build the set of non-working dates for a given year."""
        if year in self._holiday_cache:
            return self._holiday_cache[year]

        dates: set[date] = set()

        # National holidays
        for f in feriados_nacionais(year):
            dates.add(f.data)

        # State holidays
        for f in feriados_estaduais(year, self.uf):
            dates.add(f.data)

        # Recesso forense (spans two years)
        if self.include_recesso:
            # Recesso starting in previous year affects Jan of this year
            for f in recesso_forense(year - 1):
                if f.data.year == year:
                    dates.add(f.data)
            # Recesso starting in this year affects Dec of this year
            for f in recesso_forense(year):
                if f.data.year == year:
                    dates.add(f.data)

        # Custom suspensions
        for f in self.custom_suspensions:
            if f.data.year == year:
                dates.add(f.data)

        self._holiday_cache[year] = dates
        return dates

    def is_dia_util(self, d: date) -> bool:
        """Check if a date is a dia útil (business day for judicial purposes)."""
        # Weekends
        if d.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        holidays = self._build_year_cache(d.year)
        return d not in holidays

    def add_dias_uteis(self, start: date, dias: int) -> date:
        """Add N dias úteis to a start date.

        Per CPC Art. 219: prazos em dias úteis.
        The start date itself is NOT counted (Art. 224 §1º CPC).
        """
        if dias <= 0:
            return start

        current = start
        counted = 0
        while counted < dias:
            current += timedelta(days=1)
            if self.is_dia_util(current):
                counted += 1
        return current

    def subtract_dias_uteis(self, end: date, dias: int) -> date:
        """Subtract N dias úteis from an end date (for alert scheduling)."""
        if dias <= 0:
            return end

        current = end
        counted = 0
        while counted < dias:
            current -= timedelta(days=1)
            if self.is_dia_util(current):
                counted += 1
        return current

    def dias_uteis_between(self, start: date, end: date) -> int:
        """Count dias úteis between two dates (exclusive of start, inclusive of end)."""
        if end <= start:
            return 0
        count = 0
        current = start
        while current < end:
            current += timedelta(days=1)
            if self.is_dia_util(current):
                count += 1
        return count

    def next_dia_util(self, d: date) -> date:
        """Return the next dia útil on or after the given date."""
        current = d
        while not self.is_dia_util(current):
            current += timedelta(days=1)
        return current

    def all_feriados(self, year: int) -> list[Feriado]:
        """Return all holidays for a given year (for display/export)."""
        result = feriados_nacionais(year)
        result.extend(feriados_estaduais(year, self.uf))
        if self.include_recesso:
            for f in recesso_forense(year - 1):
                if f.data.year == year:
                    result.append(f)
            for f in recesso_forense(year):
                if f.data.year == year:
                    result.append(f)
        result.extend(f for f in self.custom_suspensions if f.data.year == year)
        return sorted(result, key=lambda f: f.data)
