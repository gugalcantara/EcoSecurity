"""Regras de negócio do acervo: o que transforma o cadastro em instrumento de decisão.

Funções puras (sem banco, sem tela), com os parâmetros em config/ecosec.toml
[regras_negocio]. Relatórios e painel usam todas daqui: uma régua só.

1. CRITICIDADE: peso da substância × peso do tipo de ação × (1 + anos de atraso),
   em quatro faixas (BAIXO, MEDIO, ALTO, CRITICO). Sem coleta, sobe sozinha.
2. PRAZO-LIMITE (SLA) por classe: quanto tempo, desde a identificação, a norma
   tolera até a coleta. Estourado = descumprimento, independentemente do prazo
   que o órgão negociou com o responsável.
3. CUSTO ESTIMADO da remediação: por componente e rota de tratamento (acervo/custos.py, [custos]).
4. RESPONSABILIDADE FINANCEIRA: quem paga, o responsável (cobrável), o
   orçamento público (órfãs), investimento em infraestrutura (falta destino) ou
   fiscalização (carga desaparecida, até achar o responsável).
5. AÇÃO RECOMENDADA (escalonamento): do "acompanhar prazo" ao "levar ao
   Ministério Público", conforme faixa, atraso e tipo de ação.
6. Fila do orçamento público: com um orçamento, quais pendências públicas
   resolver primeiro para reduzir mais risco.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

from ecosec.acervo import custos as _custos
from ecosec.acervo.sinteticos import AREA, CLASSE_I, RADIOATIVO
from ecosec.dominio.acervo import Pendencia, grupo_do_motivo

CHAVE_CLASSE = {RADIOATIVO: "rejeito_radioativo", CLASSE_I: "classe_i", AREA: "area_contaminada"}

RISCO_CLASSE = {RADIOATIVO: 3, CLASSE_I: 2, AREA: 1}
PESO_GRUPO = {"Carga em local desconhecido": 3.0, "Depende de recurso público": 2.5,
              "Falta de destino técnico": 2.0, "Cobrável do responsável": 1.0}
ACAO_GRUPO = {"Carga em local desconhecido": "rastrear a carga e autuar quem não deu baixa",
              "Depende de recurso público": "incluir em programa público de remediação",
              "Falta de destino técnico": "abrir capacidade de tratamento ou fila no depósito",
              "Cobrável do responsável": "notificar e cobrar o responsável"}

CATEGORIAS = ("BAIXO", "MEDIO", "ALTO", "CRITICO")
LIMITES = (5.0, 20.0, 60.0)           # limite superior exclusivo de cada faixa; acima do último, CRITICO

COBRAVEL, PUBLICO, INFRAESTRUTURA, FISCALIZACAO = ("COBRAVEL DO RESPONSAVEL", "ORCAMENTO PUBLICO",
                                                   "INVESTIMENTO EM INFRAESTRUTURA", "FISCALIZACAO E RASTREIO")
RESPONSABILIDADE_GRUPO = {"Cobrável do responsável": COBRAVEL, "Depende de recurso público": PUBLICO,
                          "Falta de destino técnico": INFRAESTRUTURA, "Carga em local desconhecido": FISCALIZACAO}

ESCALAR_MP = "ESCALAR AO MINISTERIO PUBLICO"
ACOES = (ESCALAR_MP, "AUTUAR E RASTREAR A CARGA", "PRIORIZAR NO ORCAMENTO PUBLICO", "NOTIFICACAO URGENTE",
         "BUSCAR DESTINO TECNICO", "NOTIFICAR O RESPONSAVEL", "ACOMPANHAR O PRAZO")


@dataclass(frozen=True)
class ParametrosRegras:
    """Sem valores no código: tudo vem de [regras_negocio] (regra do projeto)."""
    sla_dias: dict                    # classe -> dias desde a identificação
    custos: "_custos.ParametrosCustos"  # rotas de tratamento e componentes ([custos])
    escalonamento_mp_dias: int
    orcamento_publico: float

    @classmethod
    def padrao(cls) -> "ParametrosRegras":
        return _padrao()

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosRegras":
        r = cfg.secao("regras_negocio")
        return cls(sla_dias={c: int(r[f"sla_{k}_dias"]) for c, k in CHAVE_CLASSE.items()},
                   custos=_custos.ParametrosCustos.de_configuracao(cfg),
                   escalonamento_mp_dias=int(r["escalonamento_mp_dias"]),
                   orcamento_publico=float(r["orcamento_publico"]))


@lru_cache(maxsize=1)
def _padrao() -> ParametrosRegras:
    from ecosec.configuracao import carregar
    return ParametrosRegras.de_configuracao(carregar())


# ciclo de vida
def ativa(p: Pendencia, em: date) -> bool:
    """Identificada até em e não encerrada até lá. Toda contagem de "pendências"
    usa só as ativas; as encerradas ficam no cadastro como histórico (a curva pode cair)."""
    return p.ativa(em)


def ativas(pendencias, em: date) -> list[Pendencia]:
    return [p for p in pendencias if p.ativa(em)]


# criticidade
def fator_atraso(p: Pendencia, hoje: date) -> float:
    return 1 + p.dias_de_atraso(hoje) / 365


def criticidade(p: Pendencia, hoje: date) -> float:
    return RISCO_CLASSE[p.classe_risco] * PESO_GRUPO[grupo_do_motivo(p.motivo)] * fator_atraso(p, hoje)


def faixa_do_score(valor: float) -> str:
    for nome, limite in zip(CATEGORIAS, LIMITES):
        if valor < limite:
            return nome
    return CATEGORIAS[-1]


def categoria(p: Pendencia, hoje: date) -> str:
    return faixa_do_score(criticidade(p, hoje))


# prazo, custo, responsabilidade
def prazo_limite(p: Pendencia, r: ParametrosRegras) -> date:
    return p.data_identificacao + timedelta(days=r.sla_dias[p.classe_risco])


def dias_alem_do_prazo_limite(p: Pendencia, hoje: date, r: ParametrosRegras) -> int:
    return max(0, (hoje - prazo_limite(p, r)).days)


def custo_estimado(p: Pendencia, r: ParametrosRegras) -> float:
    return _custos.custo(p, r.custos)


def memoria_de_calculo(p: Pendencia, r: ParametrosRegras) -> tuple:
    """Os componentes que somam o custo estimado (para a ficha: "de onde vem esse custo?")."""
    return _custos.decompor(p, r.custos)


def responsabilidade(p: Pendencia) -> str:
    return RESPONSABILIDADE_GRUPO[grupo_do_motivo(p.motivo)]


def acao_recomendada(p: Pendencia, hoje: date, r: ParametrosRegras) -> str:
    """A ação que o caso exige agora: a regra de escalonamento, em ordem de gravidade."""
    faixa, grupo, vencida = categoria(p, hoje), grupo_do_motivo(p.motivo), p.vencida(hoje)
    if grupo == "Carga em local desconhecido":
        return "AUTUAR E RASTREAR A CARGA"
    if grupo == "Cobrável do responsável":
        if faixa == "CRITICO" and p.dias_de_atraso(hoje) > r.escalonamento_mp_dias:
            return ESCALAR_MP                       # cobrança administrativa esgotada: ação civil pública
        if faixa in ("CRITICO", "ALTO") and vencida:
            return "NOTIFICACAO URGENTE"
        return "NOTIFICAR O RESPONSAVEL" if vencida else "ACOMPANHAR O PRAZO"
    if grupo == "Depende de recurso público":
        return "PRIORIZAR NO ORCAMENTO PUBLICO" if faixa in ("CRITICO", "ALTO") else "ACOMPANHAR O PRAZO"
    return "BUSCAR DESTINO TECNICO"


# fila do orçamento público
CRITERIOS = ("MAIOR REDUCAO DE RISCO POR REAL", "MAIOR RISCO PRIMEIRO")


@dataclass(frozen=True)
class Priorizacao:
    selecionadas: tuple                     # (pendência, custo, score), na ordem de execução
    custo_total: float
    score_reduzido: float
    score_publico: float                   # soma dos scores de todas as pendências públicas
    candidatas: int
    orcamento: float

    @property
    def percentual_reduzido(self) -> float:
        return 100 * self.score_reduzido / self.score_publico if self.score_publico else 0.0


def priorizar(pendencias, hoje: date, r: ParametrosRegras, orcamento: float | None = None,
              criterio: str = CRITERIOS[0]) -> Priorizacao:
    """Concorrem pelo orçamento só as que o Estado paga: órfãs/não identificadas (ORCAMENTO
    PUBLICO). Guloso: percorre na ordem do critério e leva tudo o que ainda cabe."""
    orcamento = r.orcamento_publico if orcamento is None else orcamento
    candidatas = [(p, custo_estimado(p, r), criticidade(p, hoje)) for p in pendencias
                  if responsabilidade(p) == PUBLICO and p.ativa(hoje)]
    if criterio == CRITERIOS[0]:
        candidatas.sort(key=lambda c: (-(c[2] / c[1]) if c[1] else float("-inf"), c[0].codigo))
    else:
        candidatas.sort(key=lambda c: (-c[2], c[0].codigo))
    selecionadas, gasto = [], 0.0
    for p, custo, score in candidatas:
        if gasto + custo <= orcamento:
            selecionadas.append((p, custo, score))
            gasto += custo
    return Priorizacao(tuple(selecionadas), round(gasto, 2), sum(e for _, _, e in selecionadas),
                       sum(e for _, _, e in candidatas), len(candidatas), orcamento)


