"""A régua da criticidade.

(01/11/2026): opção B, só a régua muda e a fórmula do score fica intacta (peso da classe
× peso do motivo × (1 + anos de atraso)). Baixo abaixo de 5, médio de 5 a menos de 20, alto de 20 a menos de 60,
crítico de 60 ou mais. Com a régua de antes (3, 6, 10), 60,5% dos casos ativos eram críticos na data-base.

A distribuição-alvo vale para os casos ativos na data-base (`sinteticos.DATA_BASE`): crítico de 5% a 15%, alto de 20% a
30%, médio de 35% a 50%, baixo de 15% a 25%. Os relatórios que citam o limiar da faixa crítica leem a régua de
`regras.LIMITES`, em vez de "score 10 ou mais" escrito no texto.

O score não muda: o topo de "Casos para agir" (N3) é o mesmo de antes, nos mesmos 20 casos e na mesma ordem
(teste de proteção, verde antes e depois). O hash do acervo também não muda (o gerador não usa `regras.py`): a proteção
é o teste de hash de `test_ficha.py`.
"""
import re
from collections import Counter
from datetime import datetime

import pytest

from ecosec.acervo import regras, sinteticos
from ecosec.acervo.desenho import Tela
from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Usuario
from ecosec.interface.n23_custodia import N_CASOS_PARA_AGIR, casos_por_urgencia
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.servicos.acervo import ServicoAcervo
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
HOJE = sinteticos.DATA_BASE
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
# % dos casos ativos na data-base, por faixa
ALVO = {"CRITICO": (5, 15), "ALTO": (20, 30), "MEDIO": (35, 50), "BAIXO": (15, 25)}
# "Casos para agir" (N3) na data-base: os 20 primeiros com a régua de antes (calculados antes de 01/11/2026)
TOPO_N3 = ("PD-1611", "PD-1791", "PD-0599", "PD-2131", "PD-2363", "PD-0074", "PD-1931", "PD-0308", "PD-1364",
           "PD-1157", "PD-1511", "PD-1253", "PD-0780", "PD-0326", "PD-2213", "PD-2390", "PD-0192", "PD-1783",
           "PD-2309", "PD-2123")


@pytest.fixture(scope="module")
def faixas():
    """% dos casos ativos na data-base em cada faixa."""
    ativas = regras.ativas(sinteticos.gerar()[0], HOJE)
    contagem = Counter(regras.categoria(p, HOJE) for p in ativas)
    return {f: 100 * contagem[f] / len(ativas) for f in regras.CATEGORIAS}


def _confere(faixas, faixa):
    minimo, maximo = ALVO[faixa]
    resumo = ", ".join(f"{f.lower()} {faixas[f]:.1f}%" for f in reversed(regras.CATEGORIAS))
    assert minimo <= faixas[faixa] <= maximo, f"{faixa.lower()} fora de {minimo}% a {maximo}% ({resumo})"


# ================================================================ distribuição das faixas
def test_distribuicao_de_criticos_entre_5_e_15_por_cento(faixas):
    _confere(faixas, "CRITICO")


def test_distribuicao_de_alto_entre_20_e_30_por_cento(faixas):
    _confere(faixas, "ALTO")


def test_distribuicao_de_medio_entre_35_e_50_por_cento(faixas):
    _confere(faixas, "MEDIO")


def test_distribuicao_de_baixo_entre_15_e_25_por_cento(faixas):
    _confere(faixas, "BAIXO")


# ================================================================ os relatórios citam a régua
@pytest.fixture
def acervo():
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), ServicoTrilha(RepositorioTrilhaMemoria()),
                                            b"chave-teste", relogio=lambda: datetime(2026, 10, 25, 10, 0))
    servico.data_referencia = HOJE
    return servico


def _texto(monkeypatch, acervo, codigo, usuario) -> str:
    """Todo o texto desenhado no relatório, numa linha só (o parágrafo quebrado vira uma chamada por trecho)."""
    desenhados = []
    original = Tela.texto

    def escutar(self, x, y, conteudo, *args, **kwargs):
        desenhados.append(str(conteudo))
        return original(self, x, y, conteudo, *args, **kwargs)
    with monkeypatch.context() as m:
        m.setattr(Tela, "texto", escutar)
        acervo.abrir(codigo, usuario, usuario.nivel)
    return re.sub(r"\s+", " ", " ".join(desenhados))


@pytest.mark.parametrize("regua, critico, faixas_do_exemplo", [
    (None, "60", ("média", "crítica")),                   # a régua
    ((5.0, 20.0, 70.0), "70", ("média", "alta")),         # outra régua: o texto acompanha regras.LIMITES
])
def test_relatorios_citam_o_limiar_critico_da_regua(monkeypatch, acervo, regua, critico, faixas_do_exemplo):
    if regua:
        monkeypatch.setattr(regras, "LIMITES", regua)
    a1_01 = _texto(monkeypatch, acervo, "A1-01", ANA_N1)
    a3_01 = _texto(monkeypatch, acervo, "A3-01", CAIO_N3)
    a3_02 = _texto(monkeypatch, acervo, "A3-02", CAIO_N3)
    assert f"dos casos ativos (score {critico} ou mais)" in a1_01               # cartão "Casos de risco crítico"
    assert re.search(rf"de [\d.]+ \(score {critico} ou mais\)", a3_01)          # idem
    assert f"estão na faixa crítica (score {critico} ou mais)." in a3_02          # sumário executivo
    media, alta = faixas_do_exemplo
    assert ("Exemplo: material radioativo (3) sem a quem cobrar (2,5): com 1 ano de atraso (× 2) = 15, faixa "
            f"{media}; com 8 anos (× 9) = 67,5, faixa {alta}.") in a3_02           # nota de método
    if regua is None:                                                             # o glossário, citado no método
        assert "crítico, score de 60 ou mais" in a3_02
    for texto in (a1_01, a3_01, a3_02):
        assert "score 10 ou mais" not in texto


# ================================================================ proteção: o score não muda
def test_top_20_do_n3_continua_ordenado_por_score():
    """A régua muda a faixa, não o score: os 20 primeiros de "Casos para agir" continuam os mesmos, na mesma ordem,
    todos críticos e além do prazo legal, todos de material radioativo (19 públicos e 1 de infraestrutura)."""
    r = regras.ParametrosRegras.padrao()
    topo = casos_por_urgencia(sinteticos.gerar()[0], HOJE, r)[:N_CASOS_PARA_AGIR]
    assert tuple(l.caso.codigo for l in topo) == TOPO_N3
    assert all(l.grupo == 0 and l.faixa == "CRITICO" for l in topo)
    scores = [l.score for l in topo]
    assert scores == sorted(scores, reverse=True)
    assert {l.caso.classe_risco for l in topo} == {sinteticos.RADIOATIVO}
    assert Counter(l.quem_paga for l in topo) == {regras.PUBLICO: 19, regras.INFRAESTRUTURA: 1}
