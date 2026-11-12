"""A tela dos painéis temáticos (padrão SINIR+) no N1, no N3 e na UF do N2.

Testes de estrutura com a tela offscreen: quatro painéis no N1 e no N3 (três no N2), ligados ao mesmo EstadoN1;
navegar não perde o filtro nem as escolhas locais; nenhuma dica com fonte, nível ou corte (foi revogada
); um eixo vertical por gráfico, com unidade, sem misturar unidades; None do serviço aparece SUPRIMIDO
(acervo pequeno montado à mão, com supressão de fato), inclusive no estoque por classe e ano; custo
que fecha com o total; encerramento em degraus de 0 a 100% e o ano corrente parcial.
"""
import math
from dataclasses import replace
from datetime import date, timedelta

import pytest

from ecosec.acervo import sinteticos
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel

ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
USUARIOS = {Nivel.N1: ANA_N1, Nivel.N2: BIA_N2, Nivel.N3: CAIO_N3}
AREA, CLASSE_I, RADIOATIVO = sinteticos.AREA, sinteticos.CLASSE_I, sinteticos.RADIOATIVO
HOJE = sinteticos.DATA_BASE


@pytest.fixture
def tela(qt, tmp_path):
    from ecosec.aplicacao import montar
    from ecosec.interface.tela_acervo import TelaAcervo
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    t = TelaAcervo(app)
    t.resize(1500, 950)
    t.show()
    yield t
    t.encerrar()
    t.deleteLater()


def _esperar(ms: int = 60):
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


def _abrir(tela, nivel):
    """O contêiner dos painéis: o panorama no N1 e no N3, os "Painéis da UF" no N2."""
    tela.iniciar(USUARIOS[nivel], nivel)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    if nivel is Nivel.N2:
        pa.mostrar("paineis_uf")
    _esperar(150)
    return pa.paineis_uf if nivel is Nivel.N2 else pa.panorama          # O panorama é só do N1


def _montar_pequeno(tela):
    """Acervo à mão: 30 áreas em SP, 20 classe I no RJ e 2 rejeitos em MG (menos de k=3). No N1 o rejeito some
    em toda vista (e a classe I sai junto, como complementar da linha nacional); a UF MG fica suprimida."""
    repo = tela.app.acervo.repo
    base = {p.classe_risco: p for p in repo.pendencias() if p.ativa(HOJE)}
    atividades = sorted(a.codigo for a in repo.atividades())
    montado, i = [], 0
    for uf, atividade, classe, n in (("SP", atividades[0], AREA, 30), ("RJ", atividades[1], CLASSE_I, 20),
                                     ("MG", atividades[2], RADIOATIVO, 2)):
        for _ in range(n):
            i += 1
            montado.append(replace(base[classe], codigo=f"M{i:04d}", uf=uf, atividade=atividade,
                                   data_encerramento=None, data_identificacao=HOJE - timedelta(days=97 * i % 9000)))
    for anos in (0.5, 1.2, 1.8, 2.5, 3.1, 4.4, 5.0, 6.3, 7.7, 9.0):
        i += 1
        inicio = HOJE - timedelta(days=4000 + 31 * i)
        montado.append(replace(base[AREA], codigo=f"M{i:04d}", uf="SP", atividade=atividades[0],
                               data_identificacao=inicio, data_encerramento=inicio + timedelta(days=round(anos * 365.25))))
    repo._pendencias = montado


# ---------------------------------------------------------------- verificações de estrutura
def _redondo(x: float) -> bool:
    if x <= 0:
        return False
    mantissa = x / 10 ** math.floor(math.log10(x) + 1e-12)
    return any(abs(mantissa - m) < 1e-6 for m in (1, 2, 5))


def _multiplo(valor: float, passo: float, ancora: float = 0.0) -> bool:
    q = (valor - ancora) / passo
    return abs(q - round(q)) < 1e-6


def _verificar_chart(ch):
    """Um eixo vertical; todo QValueAxis com título (unidade), passo 1, 2 ou 5 x 10^k e faixa redonda."""
    from PySide6.QtCharts import QValueAxis
    from PySide6.QtCore import Qt
    verticais = [e for e in ch.axes() if e.orientation() == Qt.Orientation.Vertical]
    assert len(verticais) == 1, ch.title()
    for eixo in ch.axes():
        if not isinstance(eixo, QValueAxis):
            continue
        assert eixo.titleText(), (ch.title(), "eixo de valor sem título/unidade")
        assert eixo.tickType() == QValueAxis.TickType.TicksDynamic, ch.title()
        passo, ancora = eixo.tickInterval(), eixo.tickAnchor()
        assert _redondo(passo), (ch.title(), passo)
        if eixo.titleText() == "ano":
            continue
        assert _multiplo(eixo.min(), passo, ancora) and _multiplo(eixo.max(), passo, ancora), ch.title()
        assert "%d" not in eixo.labelFormat()


def _charts(painel):
    """Os QChart dos gráficos do painel (o mapa não é QChartView)."""
    from PySide6.QtCharts import QChartView
    return [g.chart() for g in painel.graficos() if isinstance(g, QChartView)]


def _rotulos_sem_colisao(grafico):
    """Rótulos desenhados na cena: dentro do gráfico e sem se sobrepor."""
    cena = grafico.chart().mapRectToScene(grafico.chart().rect())
    caixas = [r.sceneBoundingRect() for r in grafico.rotulos]
    for i, a in enumerate(caixas):
        assert cena.contains(a), (grafico.chart().title(), grafico.rotulos[i].text())
        for b in caixas[i + 1:]:
            assert not a.intersects(b), (grafico.chart().title(), a, b)


def _textos(widget) -> list[str]:
    from PySide6.QtWidgets import QLabel
    return [l.text() for l in widget.findChildren(QLabel) if l.isVisibleTo(widget)]


# Os testes dos "Painéis da UF" do N2 (n23_paineis_uf.PaineisUF) estão em testes/test_analitico.py.


# ================================================================ segurança: None é SUPRIMIDO
# Do N1: test_n1.py::test_none_do_servico_aparece_suprimido_e_nunca_zero e ::test_estoque_e_fluxos_do_n1_seguem_o_cubo.


def test_estoque_com_k_tem_o_destino_do_cubo_de_cada_ano(tela):
    """A série do panorama no N1 lê, em cada ano, a linha NACIONAL do cubo daquele corte. A classe
    escondida na série é a mesma que as barras do panorama daquele ano escondem; o N3 vê tudo."""
    _montar_pequeno(tela)
    acervo = tela.app.acervo
    n1, n3 = acervo.panorama(ANA_N1, 1), acervo.panorama(CAIO_N3, 3)
    reais = {c: {a: sum(p.classe_risco == c and p.ativa(min(date(a, 12, 31), HOJE)) for p in acervo.repo.pendencias())
                 for a in n1.serie["anos"]} for c in n1.serie["ativas"]}
    assert n3.serie["ativas"] == reais                                           # N3 sem k
    escondidas = 0
    for a in n1.serie["anos"]:
        do_ano = acervo.panorama(ANA_N1, 1, a)
        for c, serie in n1.serie["ativas"].items():
            if serie[a] is None:
                escondidas += 1
                assert do_ano.totais_classe.get(c) is None, (a, c)                  # o mesmo destino do cubo
            else:
                assert serie[a] == reais[c][a] and not 0 < serie[a] < 3, (a, c)
                assert do_ano.totais_classe.get(c, 0) == serie[a], (a, c)
        assert n1.serie["estoque_total"][a] == sum(reais[c][a] for c in reais)      # o total do ano, travado
    assert escondidas


# O custo e o encerramento do N2 (n23_paineis_uf.PaineisUF) estão em testes/test_analitico.py.
