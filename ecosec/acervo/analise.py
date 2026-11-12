"""Análises do painel: risco por categoria, série temporal, planilha e resumo agregado.

Funções puras sobre pendências já autorizadas e registradas pelo ServicoAcervo:
nada aqui consulta o banco nem decide permissão.

Nível de risco: a criticidade do relatório A3-02 (risco da substância × peso do
motivo × (1 + anos de atraso)) em quatro faixas. Como o atraso cresce com o
tempo, a criticidade de uma pendência não resolvida sobe sozinha: a série
temporal mostra justamente isso, o passivo envelhecendo.
"""
import csv
import hashlib
import io
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field, fields
from datetime import date
from statistics import median

# a régua (faixas, prazo, custo, ação) mora nas regras de negócio: painel e relatórios usam a mesma
from ecosec.acervo import quantidades, regras
from ecosec.acervo.regras import CATEGORIAS, categoria, criticidade
from ecosec.dominio.acervo import Pendencia

BOM = "﻿"                   # o Excel só reconhece UTF-8 com a marca no início


def filtrar(pendencias, hoje: date, ufs=None, categorias=None, atividade: str | None = None) -> list[Pendencia]:
    """Filtros do painel. None = sem restrição naquele critério."""
    return [p for p in pendencias
            if (not ufs or p.uf in ufs) and (not atividade or p.atividade == atividade)
            and (not categorias or categoria(p, hoje) in categorias)]


# ---------------------------------------------------------------- série temporal
def _fim_do_periodo(ano: int, mes: int | None) -> date:
    if mes is None:
        return date(ano, 12, 31)
    proximo = date(ano + (mes == 12), mes % 12 + 1, 1)
    return date.fromordinal(proximo.toordinal() - 1)


def serie_risco(pendencias, inicio: date, fim: date, por_mes: bool = False,
                atividade: str | None = None) -> list[tuple[str, dict[str, int]]]:
    """[(rótulo do período, {categoria: quantidade})]. Em cada período conta as pendências ATIVAS no fim
    dele (ou em `fim`, no último): já identificadas e ainda não encerradas, pela criticidade daquela data."""
    escolhidas = [p for p in pendencias if not atividade or p.atividade == atividade]
    periodos = []
    ano, mes = inicio.year, (inicio.month if por_mes else None)
    while True:
        corte = min(_fim_do_periodo(ano, mes), fim)
        contagem = dict.fromkeys(CATEGORIAS, 0)
        for p in escolhidas:
            if p.ativa(corte):
                contagem[categoria(p, corte)] += 1
        periodos.append((f"{mes:02d}/{ano}" if por_mes else str(ano), contagem))
        if corte >= fim:
            return periodos
        if por_mes:
            ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
        else:
            ano += 1


def _corte_do_ano(ano: int, hoje: date) -> date:
    return min(date(ano, 12, 31), hoje)


def serie_estoque(pendencias, inicio: int, fim: int, hoje: date) -> dict:
    """Série anual por classe: estoque ATIVO no fim de cada ano, entradas, saídas e o
    cadastro acumulado. Agregada: nenhum registro individual sai daqui (serve ao N1)."""
    classes = sorted({p.classe_risco for p in pendencias})
    anos = list(range(inicio, fim + 1))
    ativas = {c: {a: 0 for a in anos} for c in classes}
    entradas = {a: 0 for a in anos}
    saidas = {a: 0 for a in anos}
    acumulado = {a: 0 for a in anos}
    for p in pendencias:
        for a in anos:
            corte = _corte_do_ano(a, hoje)
            if p.ativa(corte):
                ativas[p.classe_risco][a] += 1
            if p.data_identificacao <= corte:
                acumulado[a] += 1
        if p.data_identificacao.year in entradas:
            entradas[p.data_identificacao.year] += 1
        if p.data_encerramento and p.data_encerramento.year in saidas:
            saidas[p.data_encerramento.year] += 1
    return {"anos": anos, "ativas": ativas, "entradas": entradas, "saidas": saidas, "acumulado": acumulado}


# ---------------------------------------------------------------- índice de pressão (N1)
PESOS_PRESSAO = {"volume": 0.30, "severidade": 0.30, "custo": 0.20, "atraso": 0.20}


@dataclass(frozen=True)
class PressaoUF:
    """Totais de uma UF e o Índice de Pressão: posição RELATIVA entre as 27 UFs (0 a 1), não escala física."""
    uf: str
    ativas: int
    criticas: int | None             # None = subcontagem suprimida no N1 (0 < n < k, ou o complemento)
    custo: float | None              # None no N1: sem dado financeiro (o serviço apaga)
    vencidas: int | None             # além do prazo-limite; None = subcontagem suprimida no N1
    indice: float
    posto: int                       # 1 = maior pressão
    suprimida: bool = False          # menos de `supressao_minima` ativas (ou complementar): nenhum número sai


def pesos_pressao(cfg) -> dict[str, float]:
    s = cfg.secao("indice_pressao")
    pesos = {k: float(s[f"peso_{k}"]) for k in PESOS_PRESSAO}
    if abs(sum(pesos.values()) - 1.0) > 1e-6:
        raise ValueError(f"[indice_pressao]: os pesos somam {sum(pesos.values()):.3f}, e devem somar 1.")
    return pesos


def _posto_percentil(valores: dict[str, float]) -> dict[str, float]:
    """0 para a menor UF, 1 para a maior; empates na média dos postos. Robusto a cauda pesada (o custo
    log-normal faria a normalização min-max achatar 26 UFs perto de zero)."""
    ordem = sorted(valores.values())
    n = len(ordem)
    if n < 2:
        return {k: 0.0 for k in valores}
    return {k: (bisect_left(ordem, v) + bisect_right(ordem, v) - 1) / 2 / (n - 1) for k, v in valores.items()}


def indice_pressao(pendencias, ufs, em: date, r: regras.ParametrosRegras | None = None, pesos=None,
                   classe: str | None = None, supressao_minima: int = 0, cubo=None) -> dict[str, PressaoUF]:
    """IP_uf = Σ peso_k · posto_percentil_k(uf), com volume (ativas), severidade (fração CRITICO), custo
    estimado e atraso (fração além do prazo-limite). UF sem ativas entra com zero em tudo.

    Com `cubo` (CuboN1 do mesmo corte), quem some e quais subcontagens viram None vem do cubo, e não de uma
    supressão própria desta vista: a mesma célula (UF, classe) tem o mesmo destino em qualquer filtro."""
    r = r or regras.ParametrosRegras.padrao()
    pesos = pesos or PESOS_PRESSAO
    if abs(sum(pesos.values()) - 1.0) > 1e-6:
        raise ValueError("Os pesos do Índice de Pressão devem somar 1.")
    base = {uf: {"ativas": 0, "criticas": 0, "custo": 0.0, "vencidas": 0} for uf in ufs}
    for p in pendencias:
        if not p.ativa(em) or (classe and p.classe_risco != classe) or p.uf not in base:
            continue
        b = base[p.uf]
        b["ativas"] += 1
        b["criticas"] += categoria(p, em) == "CRITICO"
        b["custo"] += regras.custo_estimado(p, r)
        b["vencidas"] += regras.dias_alem_do_prazo_limite(p, em, r) > 0

    def fracao(uf, k):
        return base[uf][k] / base[uf]["ativas"] if base[uf]["ativas"] else 0.0
    componentes = {
        "volume": _posto_percentil({uf: b["ativas"] for uf, b in base.items()}),
        "severidade": _posto_percentil({uf: fracao(uf, "criticas") for uf in base}),
        "custo": _posto_percentil({uf: b["custo"] for uf, b in base.items()}),
        "atraso": _posto_percentil({uf: fracao(uf, "vencidas") for uf in base}),
    }
    indice = {uf: round(sum(pesos[k] * componentes[k][uf] for k in pesos), 2) if base[uf]["ativas"] else 0.0
              for uf in base}
    posto = {uf: i + 1 for i, uf in enumerate(sorted(indice, key=lambda u: (-indice[u], u)))}
    coluna = classe or TODAS
    if cubo is not None:
        escondidas = {uf for uf in base if (uf, coluna) in cubo.escondidas}
    else:
        escondidas = {c[0] for c in suprimir({(uf,): b["ativas"] for uf, b in base.items()}, supressao_minima,
                                             (lambda c: (),))} if supressao_minima else set()
    resultado = {}
    for uf, b in base.items():
        if uf in escondidas:                 # primária ou complementar: nada que permita deduzir
            resultado[uf] = PressaoUF(uf, 0, 0, 0.0, 0, 0.0, 0, True)
        else:
            criticas = None if cubo is not None and (uf, coluna) in cubo.criticas else b["criticas"]
            vencidas = None if cubo is not None and (uf, coluna) in cubo.alem_do_prazo else b["vencidas"]
            resultado[uf] = PressaoUF(uf, b["ativas"], criticas, round(b["custo"], 2), vencidas,
                                      indice[uf], posto[uf])
    return resultado


# ---------------------------------------------------------------- planilha (registros individuais)
@dataclass(frozen=True)
class LinhaPlanilha:
    CODIGO: str
    SUBSTANCIA: str
    CLASSE_DE_RISCO: str
    QUANTIDADE: float
    UNIDADE: str
    ATIVIDADE: str
    MOTIVO: str
    LOGRADOURO: str
    NUMERO: str
    COMPLEMENTO: str
    BAIRRO: str
    MUNICIPIO: str
    UF: str
    CEP: str
    LATITUDE: float
    LONGITUDE: float
    IDENTIFICACAO: date
    PRAZO_DE_COLETA: date
    ATRASO_DIAS: int
    SITUACAO: str
    ETAPA_ATUAL: str
    ENCERRAMENTO: date | str
    CRITICIDADE: float
    NIVEL_DE_RISCO: str
    PRAZO_LIMITE: date
    DIAS_ALEM_DO_PRAZO_LIMITE: int
    CUSTO_ESTIMADO: float
    RESPONSABILIDADE: str
    ACAO_RECOMENDADA: str


COLUNAS = tuple(f.name for f in fields(LinhaPlanilha))
TITULOS = tuple(nome.replace("_", " ") for nome in COLUNAS)


def linhas(pendencias, hoje: date, r: regras.ParametrosRegras | None = None, atividades: dict | None = None,
           motivos: dict | None = None) -> list[LinhaPlanilha]:
    """Com o catálogo (`atividades`, `motivos`), as colunas ATIVIDADE e MOTIVO saem como "código · nome"."""
    from ecosec.dominio.acervo import rotulo
    r = r or regras.ParametrosRegras.padrao()
    return [LinhaPlanilha(p.codigo, p.substancia, p.classe_risco, p.quantidade, p.unidade,
                          rotulo(p.atividade, atividades or {}), rotulo(p.motivo, motivos or {}),
                          p.logradouro, p.numero, p.complemento or "", p.bairro, p.municipio, p.uf, p.cep,
                          p.latitude, p.longitude, p.data_identificacao, p.prazo_coleta, p.dias_de_atraso(hoje),
                          p.situacao, p.etapa_atual, p.data_encerramento or "",
                          round(criticidade(p, hoje), 2), categoria(p, hoje),
                          regras.prazo_limite(p, r), regras.dias_alem_do_prazo_limite(p, hoje, r),
                          regras.custo_estimado(p, r), regras.responsabilidade(p), regras.acao_recomendada(p, hoje, r))
            for p in pendencias]


# ---------------------------------------------------------------- resumo agregado (todos os níveis)
# "vencida" são dois indicadores com nomes distintos. Fora da previsao = prazo de
# coleta do caso já passou; alem do prazo limite = passou do prazo-limite da norma para a classe (o KPI-03).
FORA_DA_PREVISAO, PERCENTUAL_FORA_DA_PREVISAO = "FORA DA PREVISAO", "PERCENTUAL FORA DA PREVISAO"
ATRASO_FORA_DA_PREVISAO = "ATRASO MEDIO FORA DA PREVISAO (DIAS)"
ALEM_DO_PRAZO, PERCENTUAL_ALEM_DO_PRAZO = "ALEM DO PRAZO LIMITE", "PERCENTUAL ALEM DO PRAZO LIMITE"
CRITICAS = "CRITICAS"
TITULOS_MEDIDAS = ("PENDENCIAS", FORA_DA_PREVISAO, PERCENTUAL_FORA_DA_PREVISAO, CRITICAS, "TONELADAS CLASSE I",
                   "M3 SOLO AREA CONTAMINADA", "M3 REJEITO RADIOATIVO",
                   ATRASO_FORA_DA_PREVISAO, ALEM_DO_PRAZO, PERCENTUAL_ALEM_DO_PRAZO, "CUSTO ESTIMADO")
AGRUPAMENTOS = ("POR UF", "POR REGIAO", "POR ATIVIDADE GERADORA", "POR MOTIVO DA PERMANENCIA", "POR CLASSE DE RISCO",
                "POR NIVEL DE RISCO", "POR ACAO RECOMENDADA", "POR RESPONSABILIDADE FINANCEIRA", "POR UF E ATIVIDADE")
REGIOES = {"NORTE": ("AC", "AM", "AP", "PA", "RO", "RR", "TO"), "NORDESTE": ("AL", "BA", "CE", "MA", "PB", "PE",
                                                                         "PI", "RN", "SE"),
           "CENTRO OESTE": ("DF", "GO", "MS", "MT"), "SUDESTE": ("ES", "MG", "RJ", "SP"), "SUL": ("PR", "RS", "SC")}
REGIAO_DA_UF = {uf: regiao for regiao, ufs in REGIOES.items() for uf in ufs}


COLUNA_DA_CLASSE = dict(zip(quantidades.CLASSES, TITULOS_MEDIDAS[4:7]))   # a ordem de agregar()
# os percentuais são derivados (parte ÷ PENDENCIAS da mesma linha): nunca somados entre linhas


def _chave_do_agrupamento(agrupamento: str, hoje: date, atividades: dict, motivos: dict, r):
    """(títulos do grupo, pendência -> chave do grupo)."""
    chaves = {
        "POR UF": (("UF",), lambda p: (p.uf,)),
        "POR REGIAO": (("REGIAO",), lambda p: (REGIAO_DA_UF.get(p.uf, "OUTRA"),)),
        "POR ACAO RECOMENDADA": (("ACAO RECOMENDADA",), lambda p: (regras.acao_recomendada(p, hoje, r),)),
        "POR RESPONSABILIDADE FINANCEIRA": (("RESPONSABILIDADE",), lambda p: (regras.responsabilidade(p),)),
        "POR ATIVIDADE GERADORA": (("ATIVIDADE", "NOME"),
                                   lambda p: (p.atividade, atividades[p.atividade].nome)),
        "POR MOTIVO DA PERMANENCIA": (("MOTIVO", "NOME"), lambda p: (p.motivo, motivos[p.motivo].nome)),
        "POR CLASSE DE RISCO": (("CLASSE DE RISCO",), lambda p: (p.classe_risco,)),
        "POR NIVEL DE RISCO": (("NIVEL DE RISCO",), lambda p: (categoria(p, hoje),)),
        "POR UF E ATIVIDADE": (("UF", "ATIVIDADE"), lambda p: (p.uf, p.atividade)),
    }
    return chaves[agrupamento]


def contagens_por_classe(pendencias, hoje: date, agrupamento: str, atividades: dict, motivos: dict,
                         r: regras.ParametrosRegras | None = None) -> dict:
    """{grupo: {classe: pendências}}: a contagem da célula (grupo, classe) por trás de cada coluna de quantidade
    do resumo. No N1, a quantidade de uma célula pequena revelaria um caso."""
    r = r or regras.ParametrosRegras.padrao()
    _, chave = _chave_do_agrupamento(agrupamento, hoje, atividades, motivos, r)
    resultado: dict = {}
    for p in pendencias:
        celula = resultado.setdefault(chave(p), {})
        celula[p.classe_risco] = celula.get(p.classe_risco, 0) + 1
    return resultado


def agregar(pendencias, hoje: date, agrupamento: str, atividades: dict, motivos: dict,
            r: regras.ParametrosRegras | None = None):
    """(títulos, linhas) com totais por grupo: nenhum registro individual, nenhuma localização.
    É o que o nível 1 pode ver e extrair (RF-20)."""
    r = r or regras.ParametrosRegras.padrao()
    titulos_grupo, chave = _chave_do_agrupamento(agrupamento, hoje, atividades, motivos, r)
    grupos: dict[tuple, list] = {}
    for p in pendencias:
        grupos.setdefault(chave(p), []).append(p)
    resultado = []
    for grupo, ps in grupos.items():
        fora = [p for p in ps if p.vencida(hoje)]                # fora da previsão (prazo de coleta)
        alem = sum(regras.dias_alem_do_prazo_limite(p, hoje, r) > 0 for p in ps)
        resultado.append(list(grupo) + [
            len(ps), len(fora), round(100 * len(fora) / len(ps), 1),
            sum(categoria(p, hoje) == "CRITICO" for p in ps),
            *(quantidades.total_da_classe(ps, c) for c in quantidades.CLASSES),   # uma coluna por classe e unidade
            round(sum(p.dias_de_atraso(hoje) for p in fora) / len(fora)) if fora else 0,
            alem, round(100 * alem / len(ps), 1),
            round(sum(regras.custo_estimado(p, r) for p in ps), 2)])
    if agrupamento == "POR NIVEL DE RISCO":
        resultado.sort(key=lambda l: CATEGORIAS.index(l[0]))
    elif agrupamento == "POR ACAO RECOMENDADA":
        resultado.sort(key=lambda l: regras.ACOES.index(l[0]))
    else:
        resultado.sort(key=lambda l: (-l[len(titulos_grupo)], l[0]))
    return titulos_grupo + TITULOS_MEDIDAS, resultado


# ---------------------------------------------------------------- KPI-01: tempo até o encerramento
INICIO_OBSERVACAO = date(2006, 1, 1)     # = geracao.series.INICIO_SERIE: antes disso, ninguém sai do cadastro


@dataclass(frozen=True)
class TempoEncerramento:
    mediana: float | None            # anos; None = a curva não chegou a 50% encerradas
    p90: float | None                # anos até 90% encerradas; None = "não atingido"
    eventos: int                     # encerradas
    censuradas: int                  # ainda ativas na data de corte


def kaplan_meier(observacoes) -> list[tuple[float, float]]:
    """[(t, S(t))] nos tempos de evento. `observacoes` = (tempo, encerrou, idade ao entrar na observação).

    Entrada tardia (truncamento à esquerda): quem foi identificado antes do início da observação só entra
    no conjunto em risco na idade que tinha naquele dia; antes disso, se tivesse saído, nem estaria no
    cadastro. Sem isso, o estoque herdado inflaria o tempo."""
    observacoes = list(observacoes)
    eventos_em: dict = {}
    for t, encerrou, _ in observacoes:
        if encerrou:
            eventos_em[t] = eventos_em.get(t, 0) + 1
    em_risco = _contador_em_risco(observacoes)
    s, curva = 1.0, []
    for t in sorted(eventos_em):
        n = em_risco(t)
        if n:
            s *= 1 - eventos_em[t] / n
            curva.append((t, s))
    return curva


def _contador_em_risco(observacoes):
    """t -> quantas estão em risco em t (entrada < t <= tempo). A entrada nunca passa do tempo de saída, então
    é (entradas antes de t) menos (saídas antes de t)."""
    entradas = sorted(entrada for _, _, entrada in observacoes)
    saidas = sorted(t for t, _, _ in observacoes)
    return lambda t: bisect_left(entradas, t) - bisect_left(saidas, t)


def _primeiro_abaixo(curva, nivel: float) -> float | None:
    return next((round(t, 2) for t, s in curva if s <= nivel + 1e-12), None)


def observacoes_de_encerramento(pendencias, hoje: date, classe: str | None = None,
                                inicio_observacao: date = INICIO_OBSERVACAO) -> list[tuple[float, bool, float]]:
    """(tempo em anos, encerrou, idade ao entrar na observação) de cada pendência identificada até `hoje`."""
    observacoes = []
    for p in pendencias:
        if p.data_identificacao > hoje or (classe and p.classe_risco != classe):
            continue
        encerrou = p.encerrada(hoje)
        fim = p.data_encerramento if encerrou else hoje
        entrada = max(0.0, (inicio_observacao - p.data_identificacao).days / 365.25)
        observacoes.append(((fim - p.data_identificacao).days / 365.25, encerrou, entrada))
    return observacoes


def tempo_ate_encerramento(pendencias, hoje: date, classe: str | None = None,
                           inicio_observacao: date = INICIO_OBSERVACAO) -> TempoEncerramento:
    """KPI-01 por Kaplan-Meier: as ativas entram como censuradas (a mediana só das encerradas sairia menor
    que a idade das que ainda esperam). Mediana e P90 em anos, por classe ou no total."""
    observacoes = observacoes_de_encerramento(pendencias, hoje, classe, inicio_observacao)
    curva = kaplan_meier(observacoes)
    eventos = sum(1 for _, e, _ in observacoes if e)
    return TempoEncerramento(_primeiro_abaixo(curva, 0.5), _primeiro_abaixo(curva, 0.1), eventos,
                             len(observacoes) - eventos)


# ---------------------------------------------------------------- custo por responsável (só N3)
VINCULOS_COBRAVEIS = ("GERADOR_ORIGINAL", "SUCESSOR", "PROPRIETARIO_ATUAL")


@dataclass(frozen=True)
class CustoResponsavel:
    nome: str
    vinculos: tuple                  # papéis em que aparece (gerador, sucessor, proprietário)
    pendencias: int                  # ativas e cobráveis em que é corresponsável
    custo: float                     # soma do custo estimado dessas pendências
    codigos: tuple = ()              # as pendências somadas (para a memória de cálculo)


def custo_por_responsavel(pendencias, responsaveis, hoje: date, r: regras.ParametrosRegras | None = None):
    """Custo do passivo ATIVO e cobrável somado por responsável nomeado, do maior para o menor.

    Responsabilidade solidária (Lei 6.938/1981, art. 14, § 1º; STJ, Súmula 623): a mesma pendência entra na
    soma de cada corresponsável, então a soma da coluna não é o passivo total. Transportador e destinador
    ficam de fora: respondem pela carga (MP-08), não pela remediação. Quem pode ver é decisão da matriz."""
    r = r or regras.ParametrosRegras.padrao()
    cobraveis = {p.codigo: p for p in pendencias
                 if p.ativa(hoje) and regras.grupo_do_motivo(p.motivo) == "Cobrável do responsável"}
    por_nome: dict[str, dict] = {}
    for resp in responsaveis:
        p = cobraveis.get(resp.pendencia_codigo)
        if p is None or resp.vinculo not in VINCULOS_COBRAVEIS:
            continue
        d = por_nome.setdefault(resp.nome, {"vinculos": set(), "codigos": set()})
        d["vinculos"].add(resp.vinculo)
        d["codigos"].add(p.codigo)
    linhas = [CustoResponsavel(nome, tuple(sorted(d["vinculos"])), len(d["codigos"]),
                               round(sum(regras.custo_estimado(cobraveis[c], r) for c in d["codigos"]), 2),
                               tuple(sorted(d["codigos"])))
              for nome, d in por_nome.items()]
    return sorted(linhas, key=lambda l: (-l.custo, l.nome))


# ---------------------------------------------------------------- supressão de célula pequena
SUPRIMIDO = "SUPRIMIDO"


def suprimir(contagens: dict, k: int, marginais=(lambda chave: (),), iniciais=(), travadas=()) -> set:
    """Chaves a esconder num agregado do N1.

    Primária: 0 < n < k. Complementar: se num grupo de margem conhecida (o total da tabela, o total da
    UF, o da região, o da atividade...) sobrou uma só célula escondida, ela sairia por subtração; então a
    menor célula visível do grupo também é escondida. Repete até estabilizar. `marginais` = funções
    chave -> grupo; `iniciais` = chaves já escondidas por outra regra (ex.: a UF inteira).

    A margem também pode ser uma célula do dicionário (a linha "total" no mesmo grupo das suas partes): aí o
    grupo é a equação inteira (total = soma das partes), e o total escondido conta como uma das escondidas.

    `travadas` = chaves cujo destino já foi decidido por outra vista (o cubo do panorama): não são escolhidas
    como complementares enquanto houver outra candidata no grupo. Sem outra, a travada cede (segurança antes
    da coerência entre telas).

    O grupo precisa de complementar se tem uma só escondida (qualquer valor: um zero sozinho também sai, e
    revela a célula ligada a ele) ou uma só escondida não nula (um zero escondido não protege nada: a soma
    das escondidas seria o próprio valor da outra)."""
    escondidas = {c for c, n in contagens.items() if 0 < n < k} | set(iniciais)
    travadas = set(travadas)
    grupos = marginais if isinstance(marginais, _Grupos) else _Grupos.de(contagens, marginais)
    mudou = True
    while mudou:
        mudou = False
        for chaves in grupos.listas:
            ocultas = [c for c in chaves if c in escondidas]
            if len(ocultas) != 1 and sum(contagens[c] > 0 for c in ocultas) != 1:
                continue
            visiveis = sorted((c for c in chaves if c not in escondidas and contagens[c] > 0),
                              key=lambda c: (contagens[c], c))
            livres = [c for c in visiveis if c not in travadas]
            if livres or visiveis:
                escondidas.add((livres or visiveis)[0])
                mudou = True
    return escondidas


@dataclass(frozen=True)
class _Grupos:
    """Os grupos de suprimir já montados (a mesma estrutura serve a várias chamadas sobre as mesmas chaves)."""
    listas: tuple

    @classmethod
    def de(cls, chaves, marginais) -> "_Grupos":
        listas = []
        for margem in marginais:
            grupos: dict = {}
            for c in chaves:
                grupos.setdefault(margem(c), []).append(c)
            listas += [tuple(g) for g in grupos.values() if len(g) > 1]
        return cls(tuple(listas))


def _margens_do_agrupamento(agrupamento: str):
    """Margens que o N1 também vê em outras tabelas do resumo (o total geral está em todas)."""
    total = (lambda c: (),)
    if agrupamento == "POR UF":
        return total + (lambda c: (REGIAO_DA_UF.get(c[0], "OUTRA"),),)        # a região soma as suas UFs
    if agrupamento == "POR UF E ATIVIDADE":
        return (lambda c: (c[0],), lambda c: (c[1],))                         # totais por UF e por atividade
    return total


def suprimir_subcontagem(totais: dict, parte: dict, k: int, marginais=(lambda chave: (),), iniciais=(),
                         travadas=()) -> set:
    """Chaves cuja subcontagem (vencidas, críticas... de um total visível) não sai no N1.
    A parte v e o complemento n − v são duas células da mesma linha, que mostra o total n:
    primária se 0 < v < k ou 0 < n − v < k, e esconder uma esconde a outra. A complementar corre ao longo de
    cada uma das duas colunas pelos grupos de `marginais` (o total da coluna aparece em outra tabela).
    `iniciais` = chaves já escondidas inteiras (entram nas colunas como escondidas); `travadas`, como em suprimir.

    no par: com o total visível e um lado zero, o outro lado é o próprio total, então a célula
    não protege nada; para suprimir ela vale 0 (não é escolhida como complementar e, escondida, não conta). Com o
    total escondido (`iniciais`) o par não a revela, e ela entra com o valor real."""
    lados = ("PARTE", "RESTO")
    celulas = {}
    for c, n in totais.items():
        celulas[(c, "PARTE")], celulas[(c, "RESTO")] = parte.get(c, 0), n - parte.get(c, 0)
    iniciais = set(iniciais)
    outro = {"PARTE": "RESTO", "RESTO": "PARTE"}
    efetivas = {(c, lado): 0 if c not in iniciais and not celulas[(c, outro[lado])] else n
                for (c, lado), n in celulas.items()}
    margens = _Grupos.de(celulas, tuple((lambda c, m=m: (c[1], m(c[0]))) for m in marginais))
    escondidas = {(c, lado) for c in iniciais for lado in lados}
    escondidas |= {(c, lado) for (c, _), n in celulas.items() if 0 < n < k for lado in lados}   # primária: valor real
    travadas = {(c, lado) for c in travadas for lado in lados}
    while True:                              # as duas saem juntas, mesmo quando uma é zero (a tela mostra só v)
        novas = {(c, lado) for c, _ in suprimir(efetivas, k, margens, escondidas, travadas) for lado in lados}
        if novas == escondidas:
            return {c for c, _ in escondidas}
        escondidas = novas


# subcontagens do resumo e as colunas que saem delas: o percentual (com o total visível) e a média revelariam a
# subcontagem escondida, então caem junto com ela
SUBCONTAGENS = {FORA_DA_PREVISAO: (PERCENTUAL_FORA_DA_PREVISAO, ATRASO_FORA_DA_PREVISAO), CRITICAS: (),
                ALEM_DO_PRAZO: (PERCENTUAL_ALEM_DO_PRAZO,)}


def suprimir_tabela(agrupamento: str, titulos, linhas, k: int, por_classe: dict | None = None,
                    iniciais: dict | None = None, total: dict | None = None):
    """(linhas, quantas células escondidas) de uma tabela do resumo do N1.

    Linha: contagem 0 < n < k, ou complementar pelas margens da tabela: todas as medidas viram SUPRIMIDO, e ela
    vai para o fim em ordem de chave (a ordem por contagem entre as escondidas revelaria quem é maior).
    Linha visível: cada subcontagem de SUBCONTAGENS (e as suas derivadas) sai SUPRIMIDO pela regra de
    suprimir_subcontagem; cada coluna de quantidade é a célula (grupo, classe), com a contagem de `por_classe`
    ({grupo: {classe: n}}), e sai SUPRIMIDO se 0 < n < k. Nas duas, a complementar corre ao longo da coluna. O
    custo da linha fica: é soma da linha inteira, que tem pelo menos k pendências.
    `iniciais` = {título da coluna: chaves já escondidas por outra vista} (o cubo do panorama, no por UF).
    `total` = {título da coluna: (valor do total do escopo, escondido no cubo?)}: o total entra como célula da
    equação da tabela (total = soma das linhas), travado. Se o cubo o esconde, a tabela não pode deixá-lo sair
    somando as linhas: precisa de outra escondida na coluna."""
    titulos, iniciais = list(titulos), iniciais or {}
    n_chaves = titulos.index("PENDENCIAS")
    contagens = {tuple(l[:n_chaves]): l[n_chaves] for l in linhas}
    linhas_da_tabela = set(contagens)
    margens = _margens_do_agrupamento(agrupamento)
    total_da_tabela, travadas = ("~TOTAL~",) * n_chaves, set()

    def com_total(valores: dict, coluna: str) -> dict:
        if total is not None:
            valores[total_da_tabela] = total[coluna][0]
        return valores

    def total_escondido(coluna: str) -> set:
        return {total_da_tabela} if total is not None and total[coluna][1] else set()
    if total is not None:
        com_total(contagens, "PENDENCIAS")
        travadas = {total_da_tabela}
    fora = suprimir(contagens, k, margens, set(iniciais.get("PENDENCIAS", ())) | total_escondido("PENDENCIAS"),
                    travadas)
    escondidas = {c for c in fora if c in linhas_da_tabela}
    tapar = {c: set() for c in linhas_da_tabela if c not in escondidas}   # colunas SUPRIMIDO das linhas visíveis
    for coluna, derivadas in SUBCONTAGENS.items():
        i = titulos.index(coluna)
        parte = com_total({tuple(l[:n_chaves]): l[i] for l in linhas}, coluna)
        for c in suprimir_subcontagem(contagens, parte, k, margens,
                                      fora | set(iniciais.get(coluna, ())) | total_escondido(coluna), travadas):
            if c in tapar:
                tapar[c] |= {coluna, *derivadas}
    for classe, coluna in COLUNA_DA_CLASSE.items():
        if por_classe is None:
            break
        n_classe = com_total({c: por_classe.get(c, {}).get(classe, 0) for c in linhas_da_tabela}, coluna)
        for c in suprimir(n_classe, k, margens, fora | set(iniciais.get(coluna, ())) | total_escondido(coluna),
                          travadas):
            if c in tapar:
                tapar[c].add(coluna)
    return _montar_tabela(titulos, linhas, n_chaves, escondidas, tapar)


def _montar_tabela(titulos, linhas, n_chaves: int, escondidas, tapar: dict):
    """(linhas, células escondidas): as visíveis com SUPRIMIDO nas colunas de `tapar`, e as escondidas no fim, em
    ordem de chave (a ordem por contagem entre as escondidas revelaria quem é maior)."""
    visiveis = []
    for l in linhas:
        chave = tuple(l[:n_chaves])
        if chave in tapar:
            visiveis.append([SUPRIMIDO if titulos[j] in tapar[chave] else v for j, v in enumerate(l)])
    tapadas = sorted((list(l[:n_chaves]) + [SUPRIMIDO] * (len(l) - n_chaves) for l in linhas
                      if tuple(l[:n_chaves]) in escondidas), key=lambda l: [str(v) for v in l[:n_chaves]])
    return visiveis + tapadas, len(tapadas) + sum(len(colunas) for colunas in tapar.values())


# ---------------------------------------------------------------- o cubo protegido do N1
TODAS = "TODAS"                          # a coluna do total da linha (todas as classes) no cubo
NACIONAL = "NACIONAL"                    # a linha do total do escopo (cada classe e TODAS) no cubo
# a família de tabelas do resumo ligadas por soma, que o cubo protege junto com as UFs
FAMILIA_UF = ("POR UF", "POR REGIAO", "POR ATIVIDADE GERADORA", "POR UF E ATIVIDADE")


def linha_regiao(regiao: str) -> str:
    return f"REGIAO|{regiao}"


def linha_atividade(atividade: str) -> str:
    return f"ATIVIDADE|{atividade}"


def linha_uf_atividade(uf: str, atividade: str) -> str:
    return f"UF E ATIVIDADE|{uf}|{atividade}"


def _partes_da_linha(linha: str) -> tuple:
    """("N",), ("UF", uf), ("REGIAO", r), ("ATIVIDADE", a) ou ("UF E ATIVIDADE", uf, a)."""
    if linha == NACIONAL:
        return ("N",)
    if "|" not in linha:
        return ("UF", linha)
    return tuple(linha.split("|"))


@dataclass(frozen=True)
class CuboN1:
    """O cubo protegido de um corte: linhas = cada UF, a linha NACIONAL e, para o resumo, cada região, cada
    atividade e cada par (UF, atividade); colunas = cada classe e TODAS. Protegido uma vez com todas as equações
    que alguma vista do N1 mostra, e lido por todas: panorama (todas as classes ou uma classe), resumo (por UF,
    POR REGIAO, POR ATIVIDADE, POR UF E ATIVIDADE e POR CLASSE DE RISCO) e painéis por UF, por classe e de custo.
    A mesma célula tem o mesmo destino em qualquer filtro e em qualquer tabela. Antes, cada vista suprimia só a
    sua fatia: a primária da visão "todas" saía por subtração na visão da classe, e uma UF escondida
    podia sair somando as suas linhas de UF e atividade (risco)."""
    ativas: dict                         # (linha, classe ou TODAS) -> pendências ativas no corte
    escondidas: frozenset                # células cujo número não sai (a UF some na vista daquela coluna)
    criticas: frozenset                  # células cuja subcontagem de críticas não sai
    alem_do_prazo: frozenset             # células cuja subcontagem além do prazo-limite (KPI-03) não sai
    fora_da_previsao: frozenset = frozenset()   # células cuja subcontagem fora da previsão (KPI-03b) não sai
    subcontagens: dict = field(default_factory=dict)   # CRITICAS / ALEM_DO_PRAZO / FORA_DA_PREVISAO -> {célula: n}

    def suprimidas(self, subcontagem: str) -> frozenset:
        return {CRITICAS: self.criticas, ALEM_DO_PRAZO: self.alem_do_prazo,
                FORA_DA_PREVISAO: self.fora_da_previsao}[subcontagem]

    def contagem(self, linha: str, coluna: str):
        """Ativas da célula, ou None se o cubo a esconde."""
        return None if (linha, coluna) in self.escondidas else self.ativas.get((linha, coluna), 0)

    def subcontagem(self, subcontagem: str, linha: str, coluna: str):
        """A subcontagem da célula, ou None se ela (ou a célula inteira) não sai."""
        if (linha, coluna) in self.escondidas or (linha, coluna) in self.suprimidas(subcontagem):
            return None
        return self.subcontagens.get(subcontagem, {}).get((linha, coluna), 0)

    def iniciais_do_resumo(self) -> dict:
        """O destino das UFs no resumo POR UF (mesmo corte): {título da coluna: chaves (uf,) escondidas}."""
        def da_coluna(conjunto, coluna):
            return {(uf,) for uf, c in conjunto if c == coluna and _partes_da_linha(uf)[0] == "UF"}
        iniciais = {"PENDENCIAS": da_coluna(self.escondidas, TODAS)}
        iniciais.update({nome: da_coluna(self.suprimidas(nome), TODAS) for nome in SUBCONTAGENS})
        iniciais.update({titulo: da_coluna(self.escondidas, classe) for classe, titulo in COLUNA_DA_CLASSE.items()})
        return iniciais

    def iniciais_por_classe(self) -> dict:
        """O mesmo destino no resumo POR CLASSE DE RISCO: a linha NACIONAL do cubo, chaves (classe,)."""
        def da_linha(conjunto):
            return {(c,) for linha, c in conjunto if linha == NACIONAL and c != TODAS}
        iniciais = {"PENDENCIAS": da_linha(self.escondidas)}
        iniciais.update({nome: da_linha(self.suprimidas(nome)) for nome in SUBCONTAGENS})
        return iniciais


def _margens_do_cubo():
    """As equações que alguma vista do N1 mostra, uma função por tipo (célula fora da equação: grupo dela só).
    Em toda linha: as classes somam TODAS. Em cada coluna: a UF soma as suas linhas de UF e atividade; a atividade
    soma a sua coluna de UF e atividade; a região soma as suas UFs e também as suas linhas de UF e atividade; e
    NACIONAL soma as UFs, as regiões, as atividades e as linhas de UF e atividade (cada tabela fecha com o total)."""
    def so(c):
        return ("S",) + c

    def linha(c):
        return ("L", c[0])

    def uf_e_linhas(c):
        p = _partes_da_linha(c[0])
        return ("U", p[1], c[1]) if p[0] in ("UF", "UF E ATIVIDADE") else so(c)

    def atividade_e_linhas(c):
        p = _partes_da_linha(c[0])
        return ("A", p[1], c[1]) if p[0] == "ATIVIDADE" else ("A", p[2], c[1]) if p[0] == "UF E ATIVIDADE" \
            else so(c)

    def regiao_e(tipo):
        def margem(c):
            p = _partes_da_linha(c[0])
            if p[0] == "REGIAO":
                return ("R", tipo, p[1], c[1])
            return ("R", tipo, REGIAO_DA_UF.get(p[1], "OUTRA"), c[1]) if p[0] == tipo else so(c)
        return margem

    def nacional_e(tipo):
        return lambda c: ("N", tipo, c[1]) if _partes_da_linha(c[0])[0] in ("N", tipo) else so(c)
    return (linha, uf_e_linhas, atividade_e_linhas, regiao_e("UF"), regiao_e("UF E ATIVIDADE")) + tuple(
        nacional_e(t) for t in ("UF", "REGIAO", "ATIVIDADE", "UF E ATIVIDADE"))


_MEMO_CUBO: dict = {}


def proteger_cubo(pendencias, ufs, em: date, k: int, r: regras.ParametrosRegras | None = None) -> CuboN1:
    """O cubo do corte `em` (ver _proteger_cubo). Memorizado: o mesmo acervo, escopo, corte, k e parâmetros dão o
    mesmo cubo, e o painel pede o mesmo corte várias vezes (panorama, resumo, painéis, cartões)."""
    r = r or regras.ParametrosRegras.padrao()
    pendencias = tuple(pendencias)
    chave = (hash(pendencias), tuple(sorted(ufs)), em, k, id(r))
    achado = _MEMO_CUBO.get(chave)
    if achado is not None and achado[1] is r and achado[0] == pendencias:
        return achado[2]
    cubo = _proteger_cubo(pendencias, ufs, em, k, r)
    if len(_MEMO_CUBO) >= 128:
        _MEMO_CUBO.clear()
    _MEMO_CUBO[chave] = (pendencias, r, cubo)
    return cubo


def _proteger_cubo(pendencias, ufs, em: date, k: int, r: regras.ParametrosRegras) -> CuboN1:
    """O cubo do corte `em`. Com k = 0 (N2 e N3: o k não se aplica) nada é escondido.

    Número: primária 0 < n < k; complementar pelas equações de _margens_do_cubo, até estabilizar (a margem é
    uma célula do mesmo grupo, então uma UF escondida com todas as suas linhas de UF e atividade visíveis leva uma
    delas junto). A UF escondida na coluna TODAS esconde todas as suas células, zeros inclusive: na vista de uma
    classe ela some, e não mostra 0 nem o número. O total geral (NACIONAL, TODAS) está em toda tela (estoque),
    então fica travado. Subcontagens (críticas, além do prazo-limite, fora da previsão): suprimir_subcontagem,
    com as mesmas equações e com as células escondidas já fora."""
    colunas = tuple(quantidades.CLASSES) + (TODAS,)
    ufs = set(ufs)
    ativas = {(uf, c): 0 for uf in ufs | {NACIONAL} for c in colunas}
    subs = {nome: dict.fromkeys(ativas, 0) for nome in SUBCONTAGENS}
    for p in pendencias:
        if p.uf not in ufs or not p.ativa(em):
            continue
        marcas = {CRITICAS: categoria(p, em) == "CRITICO", FORA_DA_PREVISAO: p.vencida(em),
                  ALEM_DO_PRAZO: regras.dias_alem_do_prazo_limite(p, em, r) > 0}
        linhas = (p.uf, NACIONAL, linha_regiao(REGIAO_DA_UF.get(p.uf, "OUTRA")), linha_atividade(p.atividade),
                  linha_uf_atividade(p.uf, p.atividade))
        for linha in linhas:
            for chave in ((linha, p.classe_risco), (linha, TODAS)):
                ativas[chave] = ativas.get(chave, 0) + 1
                for nome, marca in marcas.items():
                    subs[nome][chave] = subs[nome].get(chave, 0) + marca
    for linha in {l for l, _ in ativas}:     # a linha nova nasce com zero nas classes que ela não tem
        for c in colunas:
            ativas.setdefault((linha, c), 0)
            for nome in SUBCONTAGENS:
                subs[nome].setdefault((linha, c), 0)
    if not k:
        return CuboN1(ativas, frozenset(), frozenset(), frozenset(), frozenset(), subs)
    margens, escondidas, travadas = _margens_do_cubo(), set(), {(NACIONAL, TODAS)}
    grupos = _Grupos.de(ativas, margens)
    while True:
        fechadas = escondidas | {(uf, c) for uf, coluna in escondidas if coluna == TODAS and uf in ufs
                                 for c in colunas}
        novas = suprimir(ativas, k, grupos, fechadas, travadas)
        if novas == escondidas:
            break
        escondidas = novas
    sub = {nome: frozenset(suprimir_subcontagem(ativas, subs[nome], k, margens, escondidas, travadas))
           for nome in SUBCONTAGENS}
    return CuboN1(ativas, frozenset(escondidas), sub[CRITICAS], sub[ALEM_DO_PRAZO], sub[FORA_DA_PREVISAO], subs)


# ---------------------------------------------------------------- o resumo do N1 inteiro, coerente
def _linha_do_cubo(agrupamento: str, chave: tuple) -> str:
    if agrupamento == "POR UF":
        return chave[0]
    if agrupamento == "POR REGIAO":
        return linha_regiao(chave[0])
    if agrupamento == "POR ATIVIDADE GERADORA":
        return linha_atividade(chave[0])
    return linha_uf_atividade(chave[0], chave[1])


def proteger_resumo(tabelas: dict, pendencias, hoje: date, atividades: dict, motivos: dict, k: int,
                    r: regras.ParametrosRegras | None = None, cubo: "CuboN1 | None" = None):
    """({agrupamento: (títulos, linhas)}, células escondidas): o resumo do N1 inteiro com k e complementar.

    Garantia hierárquica: as quatro tabelas de FAMILIA_UF saem do mesmo cubo protegido (proteger_cubo, corte
    `hoje`), que tem as UFs, as regiões, as atividades e os pares (UF, atividade) como linhas e protege as
    equações que ligam umas às outras. Nenhuma célula escondida em por UF sai somando as linhas visíveis de por UF
    e atividade, nem por UF a partir de por regiao, nem por atividade a partir da sua coluna; vale para a contagem,
    para cada subcontagem (parte e complemento) e para cada quantidade por classe (a célula da classe). E o mapa
    lê o mesmo cubo: a UF tem o mesmo destino no panorama e no resumo.

    Por classe de risco segue a linha NACIONAL do cubo. As outras tabelas (motivo, nível, ação, responsabilidade)
    só se ligam pelo total e seguem suprimir_tabela, com o total do cubo como célula: quando o cubo o esconde (uma
    subcontagem nacional concentrada numa linha só), nenhuma delas o revela somando as linhas."""
    r, pendencias = r or regras.ParametrosRegras.padrao(), list(pendencias)
    if cubo is None:
        cubo = proteger_cubo(pendencias, REGIAO_DA_UF, hoje, k, r)
    saida, escondidas_total = dict(tabelas), 0
    da_classe = cubo.iniciais_por_classe()
    geral = (NACIONAL, TODAS)
    total = {"PENDENCIAS": (cubo.ativas.get(geral, 0), geral in cubo.escondidas)}
    total.update({nome: (cubo.subcontagens.get(nome, {}).get(geral, 0), geral in cubo.suprimidas(nome))
                  for nome in SUBCONTAGENS})
    total.update({titulo: (cubo.ativas.get((NACIONAL, classe), 0), (NACIONAL, classe) in cubo.escondidas)
                  for classe, titulo in COLUNA_DA_CLASSE.items()})
    for g, (titulos, linhas) in tabelas.items():
        if g in FAMILIA_UF:
            continue
        por_classe = contagens_por_classe(pendencias, hoje, g, atividades, motivos, r)
        linhas, n = suprimir_tabela(g, titulos, linhas, k, por_classe,
                                    da_classe if g == "POR CLASSE DE RISCO" else None, total)
        saida[g], escondidas_total = (titulos, linhas), escondidas_total + n
    for g in FAMILIA_UF:
        if g not in tabelas:
            continue
        titulos, linhas = tabelas[g]
        n_chaves = list(titulos).index("PENDENCIAS")
        escondidas, tapar = set(), {}
        for l in linhas:
            chave = tuple(l[:n_chaves])
            linha = _linha_do_cubo(g, chave)
            if (linha, TODAS) in cubo.escondidas:
                escondidas.add(chave)
                continue
            tapar[chave] = set()
            for nome, derivadas in SUBCONTAGENS.items():
                if (linha, TODAS) in cubo.suprimidas(nome):
                    tapar[chave] |= {nome, *derivadas}
            tapar[chave] |= {titulo for classe, titulo in COLUNA_DA_CLASSE.items()
                             if (linha, classe) in cubo.escondidas}
        linhas, n = _montar_tabela(titulos, linhas, n_chaves, escondidas, tapar)
        saida[g], escondidas_total = (titulos, linhas), escondidas_total + n
    return saida, escondidas_total


# ---------------------------------------------------------------- painéis temáticos do N1
def suprimir_grade(contagens: dict, k: int, iniciais=(), travadas=()) -> set:
    """Tabela de n dimensões com as margens como células (TODAS em qualquer posição da chave). Em cada eixo, a
    margem e as suas partes formam um grupo (uma equação): ninguém sai por subtração ao longo de eixo nenhum,
    nem cruzando duas vistas da mesma grade (ex.: custo por classe e por rota, que somam o mesmo total)."""
    dims = len(next(iter(contagens), ()))
    margens = tuple((lambda c, i=i: c[:i] + ("*",) + c[i + 1:]) for i in range(dims))
    return suprimir(contagens, k, margens, iniciais, travadas)


def _travadas_pelo_cubo(cubo: "CuboN1 | None", chave_da_classe) -> tuple[set, set]:
    """(iniciais, travadas) das células de uma grade que repetem a linha NACIONAL do cubo: o total de cada
    classe e o geral têm o mesmo destino do panorama. `chave_da_classe(classe ou TODAS)` dá a chave na grade."""
    colunas = tuple(quantidades.CLASSES) + (TODAS,)
    travadas = {chave_da_classe(c) for c in colunas}
    if cubo is None:
        return set(), travadas
    return {chave_da_classe(c) for c in colunas if cubo.contagem(NACIONAL, c) is None}, travadas


# KPI-04: envelhecimento do estoque
FAIXAS_IDADE = (("<1", 0, 1), ("1-3", 1, 3), ("3-5", 3, 5), ("5-10", 5, 10), ("10-20", 10, 20),
                ("≥20", 20, float("inf")))
ROTULOS_FAIXAS = tuple(f for f, _, _ in FAIXAS_IDADE)


def idade(p: Pendencia, em: date) -> float:
    """Anos desde a identificação."""
    return (em - p.data_identificacao).days / 365.25


def faixa_de_idade(anos: float) -> str:
    return next(f for f, de, ate in FAIXAS_IDADE if de <= anos < ate)


@dataclass(frozen=True)
class Envelhecimento:
    """KPI-04 num corte: ativas por (classe ou TODAS, faixa de idade ou TODAS) e a idade mediana."""
    contagens: dict                      # (classe ou TODAS, faixa ou TODAS) -> ativas
    medianas: dict                       # classe ou TODAS -> idade mediana em anos (1 casa); None sem ativas


def envelhecimento(pendencias, em: date) -> Envelhecimento:
    colunas = tuple(quantidades.CLASSES) + (TODAS,)
    contagens = {(c, f): 0 for c in colunas for f in ROTULOS_FAIXAS + (TODAS,)}
    idades = {c: [] for c in colunas}
    for p in pendencias:
        if not p.ativa(em):
            continue
        anos = idade(p, em)
        for c in (p.classe_risco, TODAS):
            idades.setdefault(c, []).append(anos)
            for f in (faixa_de_idade(anos), TODAS):
                contagens[(c, f)] = contagens.get((c, f), 0) + 1
    return Envelhecimento(contagens, {c: round(median(v), 1) if v else None for c, v in idades.items()})


def proteger_envelhecimento(env: Envelhecimento, k: int, cubo: "CuboN1 | None" = None) -> set:
    """Células escondidas da grade classe × faixa (com as margens): o total de cada classe e o geral seguem o
    cubo (travados); a complementar cai nas faixas."""
    if not k:
        return set()
    iniciais, travadas = _travadas_pelo_cubo(cubo, lambda c: (c, TODAS))
    return suprimir_grade(env.contagens, k, iniciais, travadas)


# KPI-05: custo do passivo ativo por classe, rota e categoria EEA
@dataclass(frozen=True)
class CustoDoPassivo:
    """KPI-05 num corte, em R$ da data-base de [custos]. Chave (classe ou TODAS, rota ou TODAS, categoria ou
    TODAS); `contagens` = pendências que contribuem para a célula (a categoria só conta quem tem componente
    nela), que é o n do k. Responsabilidade: chave (classe ou TODAS, responsabilidade ou TODAS)."""
    contagens: dict
    valores: dict                        # mesma chave -> R$
    n_responsabilidade: dict             # (classe ou TODAS, responsabilidade ou TODAS) -> pendências
    responsabilidade: dict               # mesma chave -> R$


def custo_do_passivo(pendencias, em: date, r: regras.ParametrosRegras | None = None) -> CustoDoPassivo:
    from ecosec.acervo import custos
    r = r or regras.ParametrosRegras.padrao()
    contagens, valores, n_resp, v_resp = {}, {}, {}, {}
    for p in pendencias:
        if not p.ativa(em):
            continue
        rota, total = custos.rota_de(p, r.custos).nome, regras.custo_estimado(p, r)
        partes = custos.por_categoria(p, r.custos)
        for c in (p.classe_risco, TODAS):
            for ro in (rota, TODAS):
                for cat, valor in ((TODAS, total), *partes.items()):
                    if cat != TODAS and not valor:
                        continue
                    contagens[(c, ro, cat)] = contagens.get((c, ro, cat), 0) + 1
                    valores[(c, ro, cat)] = valores.get((c, ro, cat), 0.0) + valor
            for resp in (regras.responsabilidade(p), TODAS):
                n_resp[(c, resp)] = n_resp.get((c, resp), 0) + 1
                v_resp[(c, resp)] = v_resp.get((c, resp), 0.0) + total
    return CustoDoPassivo(contagens, {c: round(v, 2) for c, v in valores.items()}, n_resp,
                          {c: round(v, 2) for c, v in v_resp.items()})


def proteger_custo(custo: CustoDoPassivo, k: int, cubo: "CuboN1 | None" = None) -> tuple[set, set]:
    """(escondidas da grade classe × rota × categoria, escondidas da grade classe × responsabilidade).

    As duas grades protegem as margens como células: a mesma conta por classe e por rota fecha com o mesmo total
    (e cada rota com as suas classes), então nenhuma vista do painel deduz outra. O total de cada classe e o geral
    seguem o cubo (travados). Na responsabilidade, o total de cada grupo segue o resumo por responsabilidade
    FINANCEIRA (k e complementar pelo total, o mesmo destino) e também fica travado."""
    if not k:
        return set(), set()
    iniciais, travadas = _travadas_pelo_cubo(cubo, lambda c: (c, TODAS, TODAS))
    grade = suprimir_grade(custo.contagens, k, iniciais, travadas)
    ini_r, trav_r = _travadas_pelo_cubo(cubo, lambda c: (c, TODAS))
    grupos = {resp: n for (c, resp), n in custo.n_responsabilidade.items() if c == TODAS and resp != TODAS}
    do_resumo = suprimir({(g,): n for g, n in grupos.items()}, k)
    ini_r |= {(TODAS, g) for (g,) in do_resumo}
    trav_r |= {(TODAS, g) for g in grupos}
    return grade, suprimir_grade(custo.n_responsabilidade, k, ini_r, trav_r)


# fluxos anuais e KPI-02
@dataclass(frozen=True)
class FluxosAnuais:
    """Entradas, saídas e estoque em 1º de janeiro por (classe ou TODAS, ano), com o k do N1 aplicado uma vez
    para o painel inteiro: o mesmo par (classe, ano) tem o mesmo destino no gráfico de saldo do panorama e no
    KPI-02. Em cada ano, o total e as classes formam uma equação (complementar pelo ano)."""
    entradas: dict                       # (classe ou TODAS, ano) -> n
    saidas: dict
    estoque_inicial: dict                # (classe ou TODAS, ano) -> ativas em 1º de janeiro
    fluxos_escondidos: frozenset         # (classe ou TODAS, ano): entradas e saídas saem None
    estoque_escondido: frozenset


def proteger_fluxos(pendencias, anos, k: int) -> FluxosAnuais:
    colunas = tuple(quantidades.CLASSES) + (TODAS,)
    anos = list(anos)
    entradas = {(c, a): 0 for c in colunas for a in anos}
    saidas, estoque = dict(entradas), dict(entradas)
    for p in pendencias:
        ativa_em = [a for a in anos if p.ativa(date(a, 1, 1))]
        for c in (p.classe_risco, TODAS):
            if (c, p.data_identificacao.year) in entradas:
                entradas[(c, p.data_identificacao.year)] += 1
            if p.data_encerramento and (c, p.data_encerramento.year) in saidas:
                saidas[(c, p.data_encerramento.year)] += 1
            for a in ativa_em:
                estoque[(c, a)] += 1
    if not k:
        return FluxosAnuais(entradas, saidas, estoque, frozenset(), frozenset())
    por_ano = (lambda c: c[1],)
    escondidos: set = set()
    while True:                              # o par do ano sai junto: o saldo se deduz do estoque
        novos = suprimir(entradas, k, por_ano, escondidos) | suprimir(saidas, k, por_ano, escondidos)
        if novos == escondidos:
            break
        escondidos = novos
    return FluxosAnuais(entradas, saidas, estoque, frozenset(escondidos),
                        frozenset(suprimir(estoque, k, por_ano)))


@dataclass(frozen=True)
class TaxaAnual:
    """KPI-02 de um ano: saídas no ano ÷ ativas em 1º de janeiro. None = suprimido."""
    ano: int
    saidas: int | None
    ativas_1_jan: int | None
    percentual: float | None             # 0 a 100, uma casa
    parcial: bool                        # ano corrente: sem anualização


def taxa_anual_encerramento(fluxos: FluxosAnuais, anos, hoje: date, classe: str | None = None) -> list[TaxaAnual]:
    coluna, linhas = classe or TODAS, []
    for a in anos:
        s = None if (coluna, a) in fluxos.fluxos_escondidos else fluxos.saidas.get((coluna, a), 0)
        n = None if (coluna, a) in fluxos.estoque_escondido else fluxos.estoque_inicial.get((coluna, a), 0)
        pct = round(100 * s / n, 1) if s is not None and n else None
        linhas.append(TaxaAnual(a, s, n, pct, a == hoje.year))
    return linhas


# KPI-01 em tábua de vida (N1) ou curva exata (N2, N3)
@dataclass(frozen=True)
class IntervaloVida:
    """Um degrau da tábua de vida: (inicio, fim] em anos desde a identificação."""
    inicio: float
    fim: float
    em_risco: int                        # o menor conjunto em risco no intervalo (no início e em cada evento)
    eventos: int                         # encerramentos no intervalo (>= k no N1)
    sobrevivencia: float                 # S(fim), do Kaplan-Meier com entrada tardia


@dataclass(frozen=True)
class CurvaEncerramento:
    """KPI-01 de uma classe (ou TODAS): pontos (t, S(t)) a partir de (0, 1). No N1, só as fronteiras da tábua de
    vida anual (degraus com >= k eventos e >= k em risco); no N2 e no N3, a curva exata do Kaplan-Meier."""
    classe: str
    pontos: tuple
    intervalos: tuple                    # IntervaloVida (tábua); vazio na curva exata
    mediana: float | None                # anos; None = "não atingido"
    p90: float | None                    # anos até 90% encerradas; None = "não atingido"
    exata: bool
    eventos: int | None = None           # só na curva exata
    censuradas: int | None = None


def _sobrevivencia_em(curva, t: float) -> float:
    i = bisect_right([x for x, _ in curva], t + 1e-12)
    return curva[i - 1][1] if i else 1.0


def tabua_de_vida(observacoes, k: int, largura: float = 1.0, fronteiras=None) -> list[IntervaloVida]:
    """Tábua de vida em intervalos de `largura` anos, sobre o Kaplan-Meier com entrada tardia. Junta intervalos
    seguidos até somar k eventos; para onde o conjunto em risco fica abaixo de k (os eventos que sobrarem no
    fim entram no último degrau). Com `fronteiras` (lista crescente a partir de 0), usa só esses cortes: é como
    a curva TODAS herda os cortes comuns das classes."""
    observacoes = list(observacoes)
    if not observacoes:
        return []
    curva = kaplan_meier(observacoes)
    em_risco = _contador_em_risco(observacoes)
    entradas = sorted(e for _, _, e in observacoes)
    saidas = sorted(t for t, _, _ in observacoes)
    eventos = sorted(t for t, e, _ in observacoes if e)
    fim_dos_dados = max(saidas)
    if fronteiras is None:
        fronteiras = [i * largura for i in range(int(fim_dos_dados // largura) + 2)]
    intervalos, aberto, d_aberto, n_aberto, fim = [], fronteiras[0], 0, None, fronteiras[0]
    for a, b in zip(fronteiras, fronteiras[1:]):
        no_inicio = bisect_right(entradas, a) - bisect_right(saidas, a)
        tempos = eventos[bisect_right(eventos, a):bisect_right(eventos, b)]
        n = min([no_inicio] + [em_risco(t) for t in set(tempos)])
        if n < k or a >= fim_dos_dados:
            break
        d_aberto += len(tempos)
        n_aberto = n if n_aberto is None else min(n_aberto, n)
        fim = b
        if d_aberto >= max(k, 1):
            intervalos.append(IntervaloVida(aberto, b, n_aberto, d_aberto, _sobrevivencia_em(curva, b)))
            aberto, d_aberto, n_aberto = b, 0, None
    if d_aberto and intervalos:                  # sobra com menos de k eventos: entra no último degrau
        u = intervalos[-1]
        intervalos[-1] = IntervaloVida(u.inicio, fim, min(u.em_risco, n_aberto), u.eventos + d_aberto,
                                       _sobrevivencia_em(curva, fim))
    return intervalos


def quantil_da_tabua(intervalos, nivel: float) -> float | None:
    """Primeiro t com S(t) <= nivel, interpolado dentro do degrau (uma casa); None = não atingido."""
    s_antes = 1.0
    for iv in intervalos:
        if iv.sobrevivencia <= nivel + 1e-12:
            if s_antes - iv.sobrevivencia < 1e-12:
                return round(iv.inicio, 1)
            return round(iv.inicio + (iv.fim - iv.inicio) * (s_antes - nivel) / (s_antes - iv.sobrevivencia), 1)
        s_antes = iv.sobrevivencia
    return None


def _curva_da_tabua(classe: str, observacoes, k: int, fronteiras=None) -> CurvaEncerramento:
    intervalos = tabua_de_vida(observacoes, k, fronteiras=fronteiras)
    pontos = ((0.0, 1.0),) + tuple((iv.fim, iv.sobrevivencia) for iv in intervalos)
    return CurvaEncerramento(classe, pontos if intervalos else (), tuple(intervalos),
                             quantil_da_tabua(intervalos, 0.5), quantil_da_tabua(intervalos, 0.1), False)


def curvas_de_encerramento(pendencias, hoje: date, k: int, classe: str | None = None,
                           inicio_observacao: date = INICIO_OBSERVACAO) -> dict:
    """{classe ou TODAS: CurvaEncerramento}. Com `classe`, só ela; sem, as classes presentes e TODAS. k = 0:
    curva exata (N2, N3).

    No N1, a curva TODAS usa só os cortes comuns às tábuas das classes e para no fim da mais curta: cada degrau
    dela é a união de degraus inteiros de todas as classes, então os eventos do total nunca revelam, por
    diferença, os de uma classe num intervalo que a tábua da classe juntou."""
    pendencias = list(pendencias)
    presentes = [c for c in quantidades.CLASSES if any(p.classe_risco == c for p in pendencias)]
    pedidas = [classe] if classe else presentes + [TODAS]
    precisa = set(pedidas) | (set(presentes) if TODAS in pedidas and k else set())
    obs = {c: observacoes_de_encerramento(pendencias, hoje, None if c == TODAS else c, inicio_observacao)
           for c in precisa}
    curvas = {}
    if not k:
        for c in pedidas:
            exata = tempo_ate_encerramento(pendencias, hoje, None if c == TODAS else c, inicio_observacao)
            curva = kaplan_meier(obs[c])
            curvas[c] = CurvaEncerramento(c, (((0.0, 1.0),) + tuple(curva)) if obs[c] else (), (), exata.mediana,
                                          exata.p90, True, exata.eventos, exata.censuradas)
        return curvas
    tabuas = {c: _curva_da_tabua(c, obs[c], k) for c in precisa if c != TODAS}
    curvas.update({c: tabuas[c] for c in pedidas if c != TODAS})
    if TODAS in pedidas:
        curvas[TODAS] = CurvaEncerramento(TODAS, (), (), None, None, False)
        degraus = [tabuas[c].intervalos for c in presentes]
        if degraus and all(degraus):
            fim = min(d[-1].fim for d in degraus)
            comuns = set.intersection(*({0.0} | {iv.fim for iv in d} for d in degraus))
            fronteiras = sorted(b for b in comuns if b <= fim + 1e-9)
            if len(fronteiras) > 1:
                curvas[TODAS] = _curva_da_tabua(TODAS, obs[TODAS], k, fronteiras)
    return curvas


# ---------------------------------------------------------------- arquivos
def _valor(v):
    return v.isoformat() if isinstance(v, date) else v


def tabela_csv(titulos, dados) -> bytes:
    """CSV separado por ";" (o Excel em português abre direto), UTF-8 com BOM."""
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(titulos)
    for linha in dados:
        escritor.writerow([_valor(v) for v in linha])
    return (BOM + saida.getvalue()).encode("utf-8")


def tabela_xlsx(titulos, dados, rastreio: dict[str, str], aba_dados: str = "PASSIVOS") -> bytes:
    """XLSX com a aba de dados e a aba RASTREIO (quem exportou, quando, com que filtros)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    livro = Workbook()
    aba = livro.active
    aba.title = aba_dados
    aba.append(list(titulos))
    for celula in aba[1]:
        celula.font = Font(bold=True)
    for linha in dados:
        aba.append(list(linha))
    aba.freeze_panes = "B2"
    aba.auto_filter.ref = aba.dimensions
    info = livro.create_sheet("RASTREIO")
    for chave, valor in rastreio.items():
        info.append([chave, valor])
    livro.properties.creator = rastreio.get("EXPORTADO POR", "ECOSECURITY")
    saida = io.BytesIO()
    livro.save(saida)
    return saida.getvalue()


def para_csv(dados: list[LinhaPlanilha]) -> bytes:
    return tabela_csv(TITULOS, ([getattr(l, c) for c in COLUNAS] for l in dados))


def sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


# ---------------------------------------------------------------- painel do N1
def pesos_sem_custo(pesos=None) -> dict[str, float]:
    """Pesos do Índice de pressão do N1: o componente de custo sai e os outros são
    renormalizados para somar 1, na mesma proporção (0,30; 0,30; 0,20 -> 0,375; 0,375; 0,25). O N2 e o N3
    continuam com os pesos completos de [indice_pressao]."""
    pesos = {k: float(v) for k, v in (pesos or PESOS_PRESSAO).items() if k != "custo"}
    soma = sum(pesos.values())
    if soma <= 0:
        raise ValueError("Sem o custo, os pesos do Índice de pressão não somam nada.")
    return {k: round(v / soma, 6) for k, v in pesos.items()}


def contagens_motivo_classe(pendencias, em: date) -> dict:
    """Ativas no corte por (motivo ou TODAS, classe ou TODAS): a grade "por que continuam abertos" do N1, com
    as margens como células (o total do motivo, o total da classe e o geral)."""
    colunas = tuple(quantidades.CLASSES) + (TODAS,)
    contagens: dict = {(TODAS, c): 0 for c in colunas}
    for p in pendencias:
        if not p.ativa(em):
            continue
        for m in (p.motivo, TODAS):
            for c in (p.classe_risco, TODAS):
                contagens[(m, c)] = contagens.get((m, c), 0) + 1
    for m in {m for m, _ in contagens}:              # o motivo nasce com zero nas classes que não tem
        for c in colunas:
            contagens.setdefault((m, c), 0)
    return contagens


def _equacoes_da_grade(chaves) -> list[tuple]:
    """As equações de uma grade de duas dimensões com as margens como células (TODAS em qualquer posição): cada
    linha soma a sua margem e cada coluna também. Cada equação é (margem, partes)."""
    chaves = set(chaves)
    linhas = {l for l, _ in chaves}
    colunas = {c for _, c in chaves}
    equacoes = []
    for l in linhas:
        partes = tuple(sorted((l, c) for c in colunas if c != TODAS and (l, c) in chaves))
        if (l, TODAS) in chaves and partes:
            equacoes.append(((l, TODAS), partes))
    for c in colunas:
        partes = tuple(sorted((l, c) for l in linhas if l != TODAS and (l, c) in chaves))
        if (TODAS, c) in chaves and partes:
            equacoes.append(((TODAS, c), partes))
    return equacoes


def _posto(linhas: list[list]) -> int:
    """Posto exato (frações) de uma matriz pequena."""
    from fractions import Fraction
    m = [[Fraction(x) for x in l] for l in linhas]
    posto, colunas = 0, len(m[0]) if m else 0
    for j in range(colunas):
        pivo = next((i for i in range(posto, len(m)) if m[i][j] != 0), None)
        if pivo is None:
            continue
        m[posto], m[pivo] = m[pivo], m[posto]
        for i in range(len(m)):
            if i != posto and m[i][j] != 0:
                fator = m[i][j] / m[posto][j]
                m[i] = [a - fator * b for a, b in zip(m[i], m[posto])]
        posto += 1
    return posto


def celulas_recompostas(contagens: dict, escondidas, equacoes=None) -> set:
    """Células escondidas que as equações publicadas determinam (álgebra linear exata). Incógnitas: as escondidas
    não nulas; um zero escondido conta como conhecido (um zero escondido não protege nada).
    `equacoes`: [(margem, partes)]; padrão, as de uma grade de duas dimensões com margens (_equacoes_da_grade).
    Vazio = nenhuma célula escondida sai por soma ou subtração de outras visíveis."""
    escondidas = {c for c in escondidas if c in contagens}
    incognitas = sorted((c for c in escondidas if contagens[c]), key=str)
    if not incognitas:
        return set()
    indice = {c: i for i, c in enumerate(incognitas)}
    equacoes = _equacoes_da_grade(contagens) if equacoes is None else equacoes
    matriz = []
    for margem, partes in equacoes:
        linha = [0] * len(incognitas)
        for c, sinal in ((margem, -1), *((p, 1) for p in partes)):
            if c in indice:
                linha[indice[c]] += sinal
        if any(linha):
            matriz.append(linha)
    if not matriz:
        return set()
    base = _posto(matriz)
    recompostas = set()
    for c, i in indice.items():
        unitario = [0] * len(incognitas)
        unitario[i] = 1
        if _posto(matriz + [unitario]) == base:      # o vetor da célula está no espaço das equações
            recompostas.add(c)
    return recompostas


def proteger_grade_n1(contagens: dict, k: int, conhecidas=(), iniciais=()) -> set:
    """Células escondidas de uma grade nova do N1 (duas dimensões, margens como células), coerente com o que outra
    vista já publica: `conhecidas` = células que outra vista do N1 mostra (não adianta escondê-las: contam como
    sabidas); `iniciais` = células que outra vista esconde (escondidas aqui também).

    Primeiro suprimir_grade (primária 0 < n < k e complementar pelas equações, com as conhecidas travadas). Depois
    a prova algébrica (celulas_recompostas): enquanto alguma escondida sair das equações, esconde mais uma, a menor
    visível não nula e não conhecida da linha ou da coluna dela. Sem candidata, esconde a grade inteira (o padrão
    mais conservador). Com k = 0 (N2 e N3), nada."""
    if not k:
        return set()
    conhecidas = {c for c in conhecidas if c in contagens}
    escondidas = (suprimir_grade(contagens, k, set(iniciais), conhecidas) | set(iniciais)) - conhecidas
    for _ in range(len(contagens) + 1):
        recompostas = celulas_recompostas(contagens, escondidas)
        if not recompostas:
            return escondidas
        alvo = min(recompostas, key=str)
        livres = [c for c in contagens if c not in escondidas and c not in conhecidas and contagens[c] > 0]
        vizinhas = [c for c in livres if c[0] == alvo[0] or c[1] == alvo[1]]
        if not (vizinhas or livres):
            break
        escondidas.add(min(vizinhas or livres, key=lambda c: (contagens[c], str(c))))
    return set(contagens) - conhecidas
