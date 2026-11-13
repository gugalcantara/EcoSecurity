"""Custo de remediação por componente.

    custo(p) = Σ fixos(rota) + q(p) · Σ variáveis(rota) + monitoramento_anual(rota) · anos(rota)

A rota sai da substância ([custos.rota_por_substancia]: PCBs vão à incineração, inorgânicos à
estabilização, fase livre ao bombeamento, NORM ao armazém de NORM); sem regra, vale a rota padrão da
classe. Todo valor tem fonte: enquanto não há fonte primária, é "PARAMETRO" (parâmetro de simulação),
e a tela mostra isso na memória de cálculo.

CATEGORIA (padrão EEA): todo componente cai numa de quatro categorias, pela tabela
[custos.categoria_componente]: diagnóstico = INVESTIGACAO; obra ou contenção no local = REMEDIACAO; transporte,
tratamento e destino fora do local = DISPOSICAO; acompanhamento depois da intervenção = MONITORAMENTO. Um
componente sem categoria é recusado na carga, como uma rota sem fonte.

Regra de transição: as variáveis da rota PADRÃO de cada classe somam o custo unitário antigo (R$ 2.800/t,
R$ 180.000/m³ e, para a área, que é medida em m³ de solo, R$ 1.200/t × densidade documentada em
[custos] densidade_solo_t_por_m3). O que muda o total é o volume coerente, os fixos e o
monitoramento, todos visíveis na memória de cálculo.
"""
from dataclasses import dataclass, field

from ecosec.acervo.sinteticos import METROS_CUBICOS
from ecosec.dominio.acervo import Pendencia

CATEGORIAS_EEA = ("INVESTIGACAO", "REMEDIACAO", "MONITORAMENTO", "DISPOSICAO")
MONITORAMENTO = "MONITORAMENTO"          # nome do componente anual que decompor() acrescenta


@dataclass(frozen=True)
class Rota:
    nome: str
    fixos: tuple                     # ((componente, R$ por pendência), ...)
    variaveis: tuple                 # ((componente, R$ por unidade), ...)
    monitoramento_anual: float       # R$ por ano
    anos_monitoramento: float
    fonte: str

    @property
    def unitario(self) -> float:
        return sum(v for _, v in self.variaveis)


@dataclass(frozen=True)
class Componente:
    nome: str
    quantidade: float                # 1 (fixo), q (variável) ou anos (monitoramento)
    unidade: str                     # "pendência", "t", "m³", "anos"
    unitario: float
    valor: float
    fonte: str
    categoria: str = ""              # uma de CATEGORIAS_EEA ([custos.categoria_componente])


@dataclass(frozen=True)
class ParametrosCustos:
    rotas: dict                      # nome -> Rota
    rota_padrao: dict                # classe -> nome da rota
    rota_por_substancia: dict        # substância -> nome da rota
    data_base: str                   # "2026-10": mês a que os valores se referem
    densidade_solo: float            # t/m³: só documenta a conversão da referência antiga da área (R$/t -> R$/m³)
    categoria_componente: dict = field(default_factory=dict)   # componente -> categoria EEA

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosCustos":
        c = cfg.secao("custos")
        rotas = {}
        for nome, r in c["rotas"].items():
            if not str(r.get("fonte", "")).strip():
                raise ValueError(f"[custos.rotas.\"{nome}\"] sem fonte: use \"PARAMETRO\" enquanto não houver uma.")
            rotas[nome] = Rota(nome, tuple((n, float(v)) for n, v in r.get("fixos", [])),
                               tuple((n, float(v)) for n, v in r["variaveis"]),
                               float(r.get("monitoramento_anual", 0.0)), float(r.get("anos_monitoramento", 0.0)),
                               str(r["fonte"]))
        padrao, por_substancia = dict(c["rota_padrao"]), dict(c.get("rota_por_substancia", {}))
        faltando = [n for n in list(padrao.values()) + list(por_substancia.values()) if n not in rotas]
        if faltando:
            raise ValueError(f"Rota sem definição em [custos.rotas]: {', '.join(sorted(set(faltando)))}")
        categorias = {str(n): str(v) for n, v in dict(c.get("categoria_componente", {})).items()}
        invalidas = sorted(n for n, v in categorias.items() if v not in CATEGORIAS_EEA)
        if invalidas:
            raise ValueError(f"[custos.categoria_componente]: categoria fora de {', '.join(CATEGORIAS_EEA)} em "
                             f"{', '.join(invalidas)}")
        sem_categoria = sorted(componentes_das_rotas(rotas) - set(categorias))
        if sem_categoria:
            raise ValueError(f"Componente sem categoria em [custos.categoria_componente]: {', '.join(sem_categoria)}")
        return cls(rotas, padrao, por_substancia, str(c["data_base_valores"]), float(c["densidade_solo_t_por_m3"]),
                   categorias)


def componentes_das_rotas(rotas: dict) -> set:
    """Todo nome de componente que decompor() pode devolver (o monitoramento entra se alguma rota o tem)."""
    nomes = {n for r in rotas.values() for n, _ in r.fixos + r.variaveis}
    if any(r.monitoramento_anual and r.anos_monitoramento for r in rotas.values()):
        nomes.add(MONITORAMENTO)
    return nomes


def rota_de(p: Pendencia, c: ParametrosCustos) -> Rota:
    return c.rotas[c.rota_por_substancia.get(p.substancia) or c.rota_padrao[p.classe_risco]]


def decompor(p: Pendencia, c: ParametrosCustos) -> tuple[Componente, ...]:
    """A memória de cálculo: um componente por linha, na ordem fixos -> variáveis -> monitoramento."""
    rota = rota_de(p, c)
    unidade = "m³" if p.unidade == METROS_CUBICOS else "t"
    cat = c.categoria_componente.get
    linhas = [Componente(nome, 1, "pendência", valor, round(valor, 2), rota.fonte, cat(nome, ""))
              for nome, valor in rota.fixos]
    linhas += [Componente(nome, p.quantidade, unidade, valor, round(p.quantidade * valor, 2), rota.fonte,
                          cat(nome, "")) for nome, valor in rota.variaveis]
    if rota.monitoramento_anual and rota.anos_monitoramento:
        linhas.append(Componente(MONITORAMENTO, rota.anos_monitoramento, "anos", rota.monitoramento_anual,
                                 round(rota.anos_monitoramento * rota.monitoramento_anual, 2), rota.fonte,
                                 cat(MONITORAMENTO, "")))
    return tuple(linhas)


def por_categoria(p: Pendencia, c: ParametrosCustos) -> dict[str, float]:
    """{categoria EEA: R$} da pendência, nas quatro categorias (0 onde não há componente). A soma é o custo."""
    soma = dict.fromkeys(CATEGORIAS_EEA, 0.0)
    for x in decompor(p, c):
        soma[x.categoria] += x.valor
    return {k: round(v, 2) for k, v in soma.items()}


def custo(p: Pendencia, c: ParametrosCustos) -> float:
    return round(sum(x.valor for x in decompor(p, c)), 2)
