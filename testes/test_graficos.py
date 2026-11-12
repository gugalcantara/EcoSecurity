"""Valores desentrelaçados nos gráficos.

Testes de estrutura sobre os widgets montados offscreen: um eixo vertical por gráfico, eixo de valor com
unidade e passo redondo, nenhuma linha de total sobre as áreas, fluxos e saldo em gráficos separados,
rótulos de evento sem colisão e dentro da área, estoque no recorte da classe, barras na cor da classe,
legenda sem corte e as tabelas do N3 legíveis.
"""
import inspect
import math
import re

import pytest

from ecosec.acervo import analise, sinteticos, vocabulario
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel

ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
CLASSES = (sinteticos.AREA, sinteticos.CLASSE_I, sinteticos.RADIOATIVO)


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


def _abrir(tela, usuario, nivel):
    tela.iniciar(usuario, nivel)
    tela.mostrar_modo("painel")
    _esperar(150)
    return tela.painel_analitico


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
    """Um eixo vertical; todo QValueAxis com passo 1, 2 ou 5 x 10^k, faixa em múltiplos do passo e título."""
    from PySide6.QtCharts import QValueAxis
    from PySide6.QtCore import Qt
    verticais = [e for e in ch.axes() if e.orientation() == Qt.Orientation.Vertical]
    assert len(verticais) <= 1, ch.title()
    for eixo in ch.axes():
        if not isinstance(eixo, QValueAxis):
            continue
        assert eixo.titleText(), (ch.title(), "eixo de valor sem título/unidade")
        assert eixo.tickType() == QValueAxis.TickType.TicksDynamic, ch.title()
        passo, ancora = eixo.tickInterval(), eixo.tickAnchor()
        assert _redondo(passo), (ch.title(), passo)
        if eixo.titleText() == "ano":                            # eixo do tempo: vai do primeiro ao último ano
            assert _multiplo(ancora, passo) or ancora == eixo.min()
            continue
        assert _multiplo(eixo.min(), passo, ancora) and _multiplo(eixo.max(), passo, ancora), (ch.title(), eixo.min(),
                                                                                              eixo.max(), passo)
        assert "%d" not in eixo.labelFormat()                    # nada de %d truncando decimal


def _verificar_rotulos(vista):
    """Números dos eventos: nenhum par se intersecta e todos ficam dentro da plotArea."""
    area = vista.chart().mapRectToScene(vista.chart().plotArea())
    caixas = [r.sceneBoundingRect() for r in vista.rotulos_evento]
    assert caixas, vista.chart().title()
    for i, a in enumerate(caixas):
        assert area.contains(a), (vista.chart().title(), a, area)
        for b in caixas[i + 1:]:
            assert not a.intersects(b), (vista.chart().title(), a, b)


# ================================================================ N1: panorama
# o N1 usa o painel por perguntas (n1_painel.py), com gráficos desenhados à mão (n1_graficos.py). Os três
# testes abaixo conferem as mesmas regras nesses gráficos; o resto está em test_n1.py.
def test_n1_estoque_fluxos_e_marcos(tela):
    pn = _abrir(tela, ANA_N1, Nivel.N1).panorama
    pn.mostrar_secao("resolucao")
    _esperar()
    est, flu = pn.estoque, pn.fluxos
    est.preparar()
    flu.preparar()
    # Só as classes (o total vai no subtítulo), cada uma na sua cor, no mesmo eixo de casos
    assert [s["chave"] for s in est.series] == list(CLASSES)
    assert not any(s["nome"].upper().startswith("ESTOQUE") for s in est.series)
    p = pn.panorama
    assert f"{p.serie['estoque_total'][p.ano]:,}".replace(",", ".") in pn.secoes["resolucao"].cartoes["estoque"].subtitulo.text()
    # Entradas e saídas como duas linhas no mesmo eixo, num gráfico próprio (sem eixo duplo)
    assert [s["chave"] for s in flu.series] == ["entradas", "saidas"]
    # Marcos numerados, todos com dica, sem colisão e dentro do gráfico; a nota lista todos
    assert len(est.rotulos_evento) == len(sinteticos.EVENTOS)
    for i, a in enumerate(est.rotulos_evento):
        assert est.rect().contains(a.toRect())
        for b in est.rotulos_evento[i + 1:]:
            assert not a.intersects(b)
    nota = pn.secoes["resolucao"].cartoes["estoque"].nota.text()
    assert all(f"{n} " in nota for n in range(1, len(sinteticos.EVENTOS) + 1))
    assert sum(1 for d in est.dicas() if re.match(r"\d+\. ", d)) == len(sinteticos.EVENTOS)
    # Dica com o ano e cada classe: o ano do corte marcado
    dica = est._dica(2020)
    assert "2020" in dica and vocabulario.rotulo(sinteticos.AREA) in dica
    assert est.marcado == p.ano
    pn.estado.definir(ano=2012)
    _esperar()
    assert est.marcado == 2012 and flu.marcado == 2012
    pn.estado.definir(ano=pn.panorama.hoje.year)


def test_n1_estoque_segue_a_classe(tela):
    """Com a classe X, a série é só de X e o último ponto = panorama.totais_classe[X]."""
    pn = _abrir(tela, ANA_N1, Nivel.N1).panorama
    for classe in CLASSES:
        pn.estado.definir(classe=classe)
        _esperar()
        p = pn.panorama
        ultimo = p.serie["anos"][-1]
        assert set(p.serie["ativas"]) == {classe}
        assert [s["chave"] for s in pn.estoque.series] == [classe]
        assert pn.estoque.series[0]["pontos"][-1] == (ultimo, p.totais_classe[classe])
        # o "de T" da contagem continua o estoque de todas as classes
        assert pn.barra.contagem.text().endswith(f"(de {p.serie['estoque_total'][ultimo]:,})".replace(",", "."))
    pn.estado.definir(classe=None)


def test_n1_barras_cor_da_classe_dica_e_suprimido(tela):
    from PySide6.QtGui import QColor

    from ecosec.interface import n1_graficos as g
    pn = _abrir(tela, ANA_N1, Nivel.N1).panorama
    pn.mostrar_secao("onde")
    _esperar()
    r = pn.regioes
    r.preparar()
    assert r.unidade == "casos ativos"
    for linha in r.linhas:                                                   # Cada segmento na cor da classe
        assert [(nome, QColor(cor).name()) for nome, _, cor, _ in linha["segmentos"]] == [
            (vocabulario.rotulo(c), QColor(g.cor_classe(c)).name()) for c in CLASSES]
        for c in CLASSES:                                                    # Dica com classe, n e %
            dica = linha["dicas"][vocabulario.rotulo(c)]
            assert vocabulario.rotulo(c) in dica and "%" in dica
    # UF suprimida não desenha 0; mostra Suprimido
    pn.estado.definir(classe=sinteticos.RADIOATIVO)
    _esperar()
    uf = next(u for u, item in pn.panorama.pressao.items() if item.suprimida)
    pn.ranking.preparar()
    linha = next(l for l in pn.ranking.linhas if l["chave"] == uf)
    assert linha["valor"] is None and linha["fim"] == ""
    assert "Suprimido" in pn.ranking.textos() and "Suprimido" in linha["dica"]
    assert "0" not in [t for t in pn.ranking.textos() if t == "0"]
    pn.estado.definir(classe=None)


def test_n1_legenda_de_quintis(tela):
    from ecosec.interface.componentes.legenda_quantis import COR_SEM_ATIVAS, COR_SUPRIMIDA
    import unicodedata
    pn = _abrir(tela, ANA_N1, Nivel.N1).panorama
    pn.mostrar_secao("onde")                      # A legenda fica em "Onde estão os casos?"
    _esperar()
    leg = pn.legenda

    def sem_acento(texto):                        # "% ALÉM" também (antes só Í, Ê e Ã apareciam)
        return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    for indice in range(pn.combo_indicador.count()):
        pn.combo_indicador.setCurrentIndex(indice)
        _esperar(30)
        assert "(" in leg.titulo.text() and sem_acento(pn.combo_indicador.currentText().upper())[:6] in sem_acento(
            leg.titulo.text().upper())
        for caixa in leg.caixas + [leg.suprimida, leg.sem_ativas]:                 # nada cortado
            assert caixa.fontMetrics().horizontalAdvance(caixa.text()) <= caixa.contentsRect().width(), caixa.text()
        # O 1º quintil começa no mínimo real ("a a b"), não em "≤ b" (que sugeria começar em 0)
        assert not leg.caixas[0].text().startswith("≤") and leg.intervalos[0][0] is not None
        assert leg.intervalos[0][0] <= leg.intervalos[0][1]
        anterior = leg.intervalos[0][1]
        for baixo, alto in leg.intervalos[1:]:                                       # sem sobreposição
            if baixo is None:
                continue
            assert baixo > anterior
            anterior = alto
        assert all("UF" in c.toolTip() for c in leg.caixas)
    assert leg.suprimida.text() == "SUPRIMIDA" and leg.suprimida.isVisibleTo(leg)
    assert leg.sem_ativas.text() == "SEM ATIVAS"
    assert COR_SUPRIMIDA in leg.suprimida.styleSheet() and COR_SEM_ATIVAS in leg.sem_ativas.styleSheet()


# ================================================================ N3: evolução, priorização, responsáveis
def test_n3_priorizacao_e_custo_por_responsavel(tela):
    from PySide6.QtCore import Qt
    pa = _abrir(tela, CAIO_N3, Nivel.N3)
    # (R$) nos títulos, acumulado fixo pela ordem
    pa.mostrar("orcamento")
    _esperar(100)
    m = pa.orcamento.modelo
    assert "CUSTO (R$)" in m.titulos and "ACUMULADO NA FILA (R$)" in m.titulos
    assert not pa.orcamento.tabela.isSortingEnabled()
    custo, acumulado = m.titulos.index("CUSTO (R$)"), m.titulos.index("ACUMULADO NA FILA (R$)")
    soma = 0.0
    for linha in m.todas:
        soma += linha[custo]
        assert linha[acumulado] == pytest.approx(soma, abs=0.05)
        assert isinstance(linha[custo], float) and isinstance(linha[acumulado], float)    # um formato só
    textos = {m.data(m.index(0, c), Qt.ItemDataRole.DisplayRole) for c in (custo, acumulado)}
    assert all(re.fullmatch(r"[\d.]+,\d{2}", t) for t in textos)
    # Todas as colunas à vista a 1500 px, com a memória legível
    pa.mostrar("responsaveis")
    _esperar(200)
    r = pa.responsaveis
    assert r.modelo.titulos[-1] == "CUSTO ATIVO COBRAVEL (R$)"
    cabecalho = r.tabela.horizontalHeader()
    largura = r.tabela.viewport().width()
    for c in range(r.modelo.columnCount()):
        assert cabecalho.sectionViewportPosition(c) >= 0
        assert cabecalho.sectionViewportPosition(c) + cabecalho.sectionSize(c) <= largura + 1, r.modelo.titulos[c]
        titulo = vocabulario.titulo_coluna(r.modelo.titulos[c])         # O título de exibição
        assert cabecalho.fontMetrics().horizontalAdvance(titulo) <= cabecalho.sectionSize(c), titulo
    assert r.memoria.width() >= 440


# ================================================================ componentes


def test_estoque_sem_opcao_de_acumulado_e_eixos_redondos(qt):
    from PySide6.QtCharts import QValueAxis

    from ecosec.interface.componentes.grafico_estoque import GraficoEstoque, eixo_redondo, passo_redondo
    assert "mostrar_acumulado" not in inspect.signature(GraficoEstoque.mostrar).parameters
    assert [passo_redondo(x) for x in (0.7, 3, 31.1, 150, 260, 1000)] == [1, 5, 50, 200, 500, 1000]
    eixo = QValueAxis()
    eixo_redondo(eixo, 0, 6.9, intervalos=5)
    assert (eixo.min(), eixo.max(), eixo.tickInterval(), eixo.labelFormat()) == (0, 8, 2, "%.0f")
    eixo_redondo(eixo, -147, 120, simetrico=True)
    assert eixo.min() == -eixo.max() and _multiplo(0, eixo.tickInterval())
    ps = sinteticos.gerar()[0]
    serie = analise.serie_estoque(ps, 2006, 2026, sinteticos.DATA_BASE)
    g = GraficoEstoque()
    g.resize(600, 900)                                           # estreito: os números dos eventos se empilham
    g.show()
    for modo in ("ESTOQUE ATIVO POR CLASSE", "SALDO ANUAL (ENTRADAS - SAIDAS)", "POR CLASSE (SMALL MULTIPLES)"):
        g.mostrar(serie, sinteticos.EVENTOS, ano=2022, modo=modo)
        _esperar()
        for vista in g.vistas_visiveis():
            _verificar_chart(vista.chart())
            _verificar_rotulos(vista)
    g.close()
