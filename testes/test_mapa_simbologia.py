"""Simbologia acessível, legenda completa, barra de escala, teclado e painel de camadas.

Critérios de aceite:
- contraste ≥ 3:1 (WCAG 1.4.11, luminância relativa) de cada faixa contra o fundo do mapa, nos mesmos
  matizes; raio estritamente crescente por faixa; anel só no crítico; ponto vazado com o novo tamanho;
- uma entrada por camada visível, com o mesmo símbolo (a cor desenhada na legenda = a do ponto); a
  entrada some quando a camada é desligada; texto na cor de texto;
- a legenda conta só a vista e mostra dentro × fora coerente com contagens;
- barra de escala com erro ≤ 1% contra a haversine em latitudes do RS, do centro e do AM;
  comprimento redondo; muda com o zoom;
- + e − dão zoom; Tab foca um ponto (oeste -> leste); Enter abre a ficha (o mesmo sinal do clique); Esc
  solta; nomes acessíveis; caixas de quintil por teclado;
- reordenar camadas muda o z-value; UFs com liga/desliga; dois nomes para os municípios;
- rampa da densidade fora dos matizes de risco; 1º quintil começa no mínimo real.
"""
import colorsys
from math import asin, cos, radians, sin, sqrt

import pytest

from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel

CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)


def _haversine(lat1, lon1, lat2, lon2, raio=6371.0088):
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * raio * asin(sqrt(a))


def _matiz(cor) -> float:
    from PySide6.QtGui import QColor
    q = QColor(cor)
    return colorsys.rgb_to_hls(q.redF(), q.greenF(), q.blueF())[0] * 360


def _distancia_matiz(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


@pytest.fixture
def tela(qt, tmp_path):
    from ecosec.aplicacao import montar
    from ecosec.interface.tela_acervo import TelaAcervo
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    t = TelaAcervo(app)
    t.resize(1400, 900)
    t.show()
    yield t
    t.encerrar()
    t.deleteLater()


def _interativo(tela, qt, usuario=CAIO_N3, nivel=Nivel.N3):
    tela.iniciar(usuario, nivel)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    pa.mostrar("mapa")
    # o padrão do filtro é Todos; estes testes medem o mapa nas ativas
    pa.estado.definir(situacao="ATIVAS")
    qt.processEvents()
    return pa.mapa


@pytest.fixture
def mapa(tela, qt):
    return _interativo(tela, qt).mapa


def _na_vista_esperado(m):
    vista = m.viewport().rect()
    vt = m.viewportTransform()
    return sum(pt.conta and pt.parentItem().isVisible()
               and pt.deviceTransform(vt).mapRect(pt.boundingRect()).intersects(vista) for pt in m.pontos)


def _aproximar_em(m, lon, lat, aumento_minimo):
    from ecosec.interface.mapa_vetorial import projetar
    m.ir_para_brasil()
    while m.aumento < aumento_minimo:
        m.aproximar(1.5)
    m.centerOn(projetar(lon, lat))


# simbologia acessível
def test_contraste_de_cada_faixa_contra_o_fundo_e_mesmo_matiz(mapa):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QGraphicsPathItem

    from ecosec.interface.componentes import simbologia as sb
    contorno = next(i for i in mapa.cena.items() if i.zValue() == 0 and i.parentItem() is None
                    and isinstance(i, QGraphicsPathItem))
    assert contorno.brush().color().name().upper() == sb.FUNDO_MAPA.upper()      # o fundo real dos pontos
    antes = {f: sb.contraste(c, sb.FUNDO_MAPA) for f, c in sb.COR_IDENTIDADE.items()}
    assert sum(v < 3 for v in antes.values()) == 3                                  # as três faixas sem contraste suficiente
    for faixa in sb.FAIXAS:
        cor = sb.COR_FAIXA[faixa]
        assert sb.contraste(cor, sb.FUNDO_MAPA) >= 3.0, (faixa, cor)
        assert _distancia_matiz(_matiz(cor), _matiz(sb.COR_IDENTIDADE[faixa])) <= 3     # mesmo tom
        assert sb.luminancia(cor) <= sb.luminancia(sb.COR_IDENTIDADE[faixa]) + 1e-9    # só escurece
    # luminância WCAG conferida contra valores de referência
    assert sb.luminancia("#FFFFFF") == pytest.approx(1.0) and sb.luminancia("#000000") == pytest.approx(0.0)
    assert sb.contraste("#FFFFFF", "#000000") == pytest.approx(21.0)
    assert sb.contraste(sb.COR_TEXTO, "#FFFFFF") >= 4.5                              # texto da legenda
    # cada ponto do mapa usa a cor da sua faixa
    for pt in mapa.pontos[:200]:
        assert QColor(pt.cor).name().upper() == sb.COR_FAIXA[pt.faixa].upper()


def sb_rotulo(tematica, categoria):
    from ecosec.interface.componentes import simbologia as sb
    return sb.rotulo_categoria(tematica, categoria)


def test_raio_crescente_por_faixa_anel_so_no_critico_e_vazado(mapa):
    from ecosec.interface.componentes import simbologia as sb
    raios = [sb.RAIO_FAIXA[f] for f in sb.FAIXAS]
    assert all(a < b for a, b in zip(raios, raios[1:]))
    assert [sb.ANEL_FAIXA[f] for f in sb.FAIXAS] == [False, False, False, True]
    por_faixa = {f: next(pt for pt in mapa.pontos if pt.faixa == f) for f in sb.FAIXAS}
    largura = [por_faixa[f].boundingRect().width() for f in sb.FAIXAS]
    assert all(a < b for a, b in zip(largura, largura[1:]))                           # o desenho cresce também
    assert [por_faixa[f].anel for f in sb.FAIXAS] == [False, False, False, True]
    # vazado (encerrados): sem faixa atual, contorno cinza de tamanho único e sem anel
    for faixa, pt in por_faixa.items():
        pt.definir_vazado(True)
        assert pt.vazado and pt.simbolo.vazado and pt.raio == sb.RAIO_FAIXA["MEDIO"] and not pt.anel
        assert pt.cor == sb.COR_ENCERRADO and sb.contraste(sb.COR_ENCERRADO, sb.FUNDO_MAPA) >= 3.0
        pt.definir_vazado(False)
        assert not pt.simbolo.vazado


def test_ponto_desenhado_na_cor_da_faixa_e_vazado_sem_preenchimento(qt):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter

    from ecosec.interface.componentes import simbologia as sb
    for faixa in sb.FAIXAS:
        for vazado in (False, True):
            imagem = QImage(40, 40, QImage.Format.Format_ARGB32)
            imagem.fill(QColor(sb.FUNDO_MAPA))
            painter = QPainter(imagem)
            sb.desenhar_ponto(painter, sb.simbolo_faixa(faixa, vazado=vazado), QPointF(20, 20))
            painter.end()
            centro = imagem.pixelColor(20, 20).name().upper()
            assert centro == (sb.FUNDO_MAPA.upper() if vazado else sb.COR_FAIXA[faixa].upper()), (faixa, vazado)
            borda = imagem.pixelColor(20 + int(sb.simbolo_faixa(faixa, vazado=vazado).raio), 20)
            assert borda.name().upper() != sb.FUNDO_MAPA.upper()                       # o contorno existe


# legenda dinâmica completa
def test_legenda_uma_entrada_por_camada_visivel_com_o_mesmo_simbolo(tela, qt):
    from ecosec.interface.componentes import simbologia as sb
    mi = _interativo(tela, qt)
    m = mi.mapa
    mi.caixas_n3["densidade"].setChecked(True)
    mi.caixas_n3["municipios"].setChecked(True)
    alvo = next(pt for pt in m.pontos_visiveis() if pt.pendencia.uf == "SP")
    _aproximar_em(m, alvo.pendencia.longitude, alvo.pendencia.latitude, 7)          # limites aparecem
    m._recalcular_legenda()
    desenhadas = {c for c in m.camadas if m.camada_desenhada(c)}
    assert desenhadas == {"ufs", "municipios", "limites", "densidade", "pendencias", "custodias"}
    camadas_na_legenda = [e.camada for e in m.entradas_legenda if e.camada]
    assert set(camadas_na_legenda) == desenhadas
    # na ordem de desenho (a de cima primeiro), uma seção contígua por camada
    secoes = [c for i, c in enumerate(camadas_na_legenda) if i == 0 or camadas_na_legenda[i - 1] != c]
    assert secoes == [c for c in m.ordem_camadas if c in desenhadas]
    # o mesmo símbolo: cor, raio e anel do ponto da faixa
    faixas = [e for e in m.entradas_legenda if e.chave.startswith("● ")]
    assert faixas
    for e in faixas:
        faixa = e.chave[2:]
        ponto = next(pt for pt in m.pontos if pt.faixa == faixa)
        assert e.simbolo == ponto.simbolo == sb.simbolo_faixa(faixa)
    # densidade com rampa, coroplético com rampa e faixa de valores, ocupação explicada
    por_chave = {e.chave: e for e in m.entradas_legenda}
    assert por_chave["▒ DENSIDADE"].simbolo.forma == "rampa"
    assert por_chave["PENDÊNCIAS POR MUNICÍPIO"].simbolo.forma == "rampa" and " a " in por_chave[
        "PENDÊNCIAS POR MUNICÍPIO"].valor
    assert por_chave["OCUPAÇÃO"].simbolo.cores == sb.COR_OCUPACAO and "70" in por_chave["OCUPAÇÃO"].valor
    # a cor desenhada na legenda é a do ponto (amostra no centro do símbolo)
    imagem = m.legenda.grab().toImage()
    for e in faixas:
        i = m.entradas_legenda.index(e)
        p = m.legenda.ponto_do_simbolo(i)
        cor = imagem.pixelColor(int(p.x() * imagem.devicePixelRatio()), int(p.y() * imagem.devicePixelRatio()))
        assert cor.name().upper() == sb.COR_FAIXA[e.chave[2:]].upper(), e.chave
    assert m.legenda.accessibleName() and "Casos na vista" in m.legenda.accessibleDescription()
    # desligar a camada tira a entrada
    for chave in ("densidade", "ufs", "custodias", "limites", "municipios"):
        mi.caixas_n3[chave].setChecked(False)
        m._recalcular_legenda()
        assert chave not in {e.camada for e in m.entradas_legenda}, chave
    mi.caixas_n3["pendencias"].setChecked(False)
    m._recalcular_legenda()
    assert not any(e.chave.startswith("● ") for e in m.entradas_legenda)


def test_legenda_limites_so_quando_desenhados_e_encerradas(tela, qt):
    m = _interativo(tela, qt).mapa
    m.ir_para_brasil()
    m._recalcular_legenda()
    assert "limites" not in {e.camada for e in m.entradas_legenda}          # ligada, mas longe demais
    m.definir_ano(None, so_ativas=False)
    m._recalcular_legenda()
    linhas = dict(m.linhas_legenda)
    assert int(linhas["○ ENCERRADAS"]) == sum(pt.vazado and pt.conta for pt in m.pontos) > 0


# a vista certa, dentro × fora
def test_legenda_conta_so_a_vista_e_dentro_fora_coerente(mapa):
    alvo = next(pt for pt in mapa.pontos_visiveis() if pt.pendencia.uf == "SP")
    _aproximar_em(mapa, alvo.pendencia.longitude, alvo.pendencia.latitude, 40)
    mapa._recalcular_legenda()
    soma = sum(int(v) for r, v in mapa.linhas_legenda if r.startswith("● "))
    assert 0 < soma == _na_vista_esperado(mapa) < len(mapa.pontos_visiveis())
    assert int(dict(mapa.linhas_legenda)["PENDÊNCIAS NA VISTA"]) == soma == mapa.contagens["na_vista"]
    recorte = frozenset(pt.pendencia.codigo for pt in mapa.pontos if pt.faixa in ("ALTO", "CRITICO"))
    mapa.aplicar_recorte(recorte)
    mapa._recalcular_legenda()
    linhas, c = dict(mapa.linhas_legenda), mapa.contagens
    assert int(linhas["DENTRO DO FILTRO"]) == c["dentro"] and int(linhas["FORA DO FILTRO"]) == c["fora"]
    assert c["dentro"] + c["fora"] == c["total"]
    assert sum(int(v) for r, v in mapa.linhas_legenda if r.startswith("● ")) == _na_vista_esperado(mapa)
    assert all(r[2:] in ("ALTO", "CRITICO") for r, _ in mapa.linhas_legenda if r.startswith("● "))
    mapa.aplicar_recorte(recorte, modo="atenuar")
    mapa._recalcular_legenda()
    fora = next(e for e in mapa.entradas_legenda if e.chave == "FORA DO FILTRO")
    assert fora.simbolo is not None and fora.simbolo.atenuado and "atenuado" in fora.rotulo


# barra de escala
def test_distancia_redonda():
    from ecosec.interface.mapa_vetorial import distancia_redonda
    assert [distancia_redonda(v) for v in (1, 1.9, 3, 7.5, 37, 99, 120, 0.3, 4999)] == \
        [1, 1, 2, 5, 20, 50, 100, 0.2, 2000]


@pytest.mark.parametrize("lugar, lon, lat", [("RS", -51.2, -30.0), ("centro", -47.9, -15.8), ("AM", -60.0, -3.1)])
def test_barra_de_escala_erro_ate_1_por_cento_contra_haversine(mapa, lugar, lon, lat):
    from PySide6.QtCore import QPointF

    from ecosec.interface.mapa_vetorial import COS_LAT, KM_POR_GRAU, desprojetar, km_por_pixel
    for aumento in (4, 15):
        _aproximar_em(mapa, lon, lat, aumento)
        km, px, lat_centro = mapa.barra_escala()
        assert abs(lat_centro - lat) < 0.5, (lugar, lat_centro)
        mantissa = km / 10 ** int(f"{km:e}".split("e")[1])
        assert round(mantissa, 9) in (1, 2, 5) and 40 <= px <= 140
        escala = mapa.transform().m11()
        centro = mapa.mapToScene(mapa.viewport().rect().center())
        a = desprojetar(QPointF(centro.x() - px / 2 / escala, centro.y()))
        b = desprojetar(QPointF(centro.x() + px / 2 / escala, centro.y()))
        real = _haversine(a[1], a[0], b[1], b[0])
        assert abs(km - real) / real <= 0.01, (lugar, aumento, km, real)
    # com um cosseno fixo de 15°, no RS o erro passaria de 10%
    if lugar == "RS":
        fixo = KM_POR_GRAU * COS_LAT / (100.0 * COS_LAT)
        certo = km_por_pixel(1.0, lat)
        assert abs(fixo - certo) / certo > 0.10


def test_barra_de_escala_muda_com_zoom_e_rolagem(mapa):
    alvo = next(pt for pt in mapa.pontos_visiveis() if pt.pendencia.uf == "RS")
    _aproximar_em(mapa, alvo.pendencia.longitude, alvo.pendencia.latitude, 4)
    km1, px1, lat1 = mapa.barra_escala()
    mapa.aproximar(2.0)
    km2, px2, _ = mapa.barra_escala()
    assert (km2, px2) != (km1, px1) and km2 / px2 < km1 / px1                         # mais perto: menos km/px
    mapa.verticalScrollBar().setValue(mapa.verticalScrollBar().value() - 400)        # rola para o norte
    _, _, lat3 = mapa.barra_escala()
    assert lat3 > lat1
    imagem = mapa.grab().toImage()                                                    # desenhada sobre o mapa
    assert not imagem.isNull()


# teclado e acessibilidade
def test_mais_e_menos_dao_zoom(mapa, qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    mapa.ir_para_brasil()
    z0 = mapa.aumento
    QTest.keyClick(mapa, Qt.Key.Key_Plus)
    assert mapa.aumento == pytest.approx(z0 * 1.6)
    QTest.keyClick(mapa, Qt.Key.Key_Minus)
    assert mapa.aumento == pytest.approx(z0)
    QTest.keyClick(mapa, Qt.Key.Key_Equal)                                          # "+" sem Shift
    assert mapa.aumento == pytest.approx(z0 * 1.6)
    QTest.keyClick(mapa, Qt.Key.Key_Plus, Qt.KeyboardModifier.KeypadModifier)       # teclado numérico
    assert mapa.aumento == pytest.approx(z0 * 1.6 ** 2)
    QTest.keyClick(mapa, Qt.Key.Key_Minus, Qt.KeyboardModifier.KeypadModifier)
    assert mapa.aumento == pytest.approx(z0 * 1.6)


def test_tab_foca_pontos_enter_abre_a_ficha_esc_solta(tela, qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    mi = _interativo(tela, qt)
    m = mi.mapa
    assert m.accessibleName() and m.accessibleDescription()
    alvo = next(pt for pt in m.pontos_visiveis() if pt.pendencia.uf == "SP")
    _aproximar_em(m, alvo.pendencia.longitude, alvo.pendencia.latitude, 30)
    lista = m.pontos_focaveis()
    assert 1 < len(lista) < len(m.pontos_visiveis())
    xs = [pt.pos().x() for pt in lista]
    assert xs == sorted(xs)                                                          # oeste para leste
    m.setFocus()
    QTest.keyClick(m, Qt.Key.Key_Tab)
    primeiro = m.ponto_em_foco
    assert primeiro is lista[0] and primeiro.focado and primeiro.conta
    rotulo = sb_rotulo("faixa", primeiro.faixa).lower()                       # Vocabulário
    assert primeiro.nome_acessivel.startswith(f"Caso {primeiro.pendencia.codigo}, risco {rotulo}, UF ")
    assert primeiro.nome_acessivel in m.accessibleDescription()
    QTest.keyClick(m, Qt.Key.Key_Tab)
    assert m.ponto_em_foco is lista[1] and not primeiro.focado
    QTest.keyClick(m, Qt.Key.Key_Backtab)
    assert m.ponto_em_foco is primeiro
    # Enter: o mesmo sinal do clique, e a ficha abre pelo mesmo caminho
    recebidas = []
    m.pendencia_escolhida.connect(recebidas.append)
    QTest.keyClick(m, Qt.Key.Key_Return)
    QTest.qWait(400)
    assert recebidas == [primeiro.pendencia]
    assert mi.ficha.aberto and mi.ficha_titulo.text().startswith(primeiro.pendencia.codigo)
    # clique num ponto que está por cima no seu lugar: o mesmo sinal, com a pendência dele
    clicavel = next(pt for pt in lista if m.itemAt(m.mapFromScene(pt.scenePos())) is pt)
    QTest.mouseClick(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     m.mapFromScene(clicavel.scenePos()))
    assert recebidas[-1] is clicavel.pendencia and len(recebidas) == 2
    # Esc solta o foco; a descrição volta às instruções
    QTest.keyClick(m, Qt.Key.Key_Escape)
    assert m.ponto_em_foco is None and not primeiro.focado and "Tab" in m.accessibleDescription()
    # sem armadilha: depois do último ponto, o Tab sai do mapa
    for _ in range(len(lista)):
        assert m.focar_proximo(True)
    assert not m.focar_proximo(True) and m.ponto_em_foco is None


def test_foco_solto_quando_o_ponto_sai_do_filtro(mapa, qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    mapa.ir_para_brasil()
    QTest.keyClick(mapa, Qt.Key.Key_Tab)
    focado = mapa.ponto_em_foco
    assert focado is not None
    mapa.aplicar_recorte(frozenset(pt.pendencia.codigo for pt in mapa.pontos if pt is not focado))
    assert mapa.ponto_em_foco is None and not focado.focado
    mapa.aplicar_recorte(None)


def test_caixas_de_quintil_acessiveis_por_teclado(qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from ecosec.interface.componentes.legenda_quantis import LegendaQuantis
    leg = LegendaQuantis()
    leg.show()
    leg.definir([2.0, 4.0, 6.0, 8.0, 10.0], titulo="ÍNDICE (0 a 1)", inferiores=[1.0, 3.0, 5.0, 7.0, 9.0],
                contagens=[5, 5, 6, 5, 6])
    assert leg.caixas[0].text() == "1,00 a 2,00" and leg.intervalos[0] == (1.0, 2.0)
    passou, escolhido = [], []
    leg.passou.connect(passou.append)
    leg.escolhido.connect(escolhido.append)
    caixa = leg.caixas[2]
    assert caixa.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert caixa.accessibleName() == "Quintil 3: 5,00 a 6,00, 6 UFs" and caixa.accessibleDescription()
    caixa.setFocus(Qt.FocusReason.TabFocusReason)
    qt.processEvents()
    assert passou and passou[-1] == 2 and "#0063B1" in caixa.styleSheet()              # foco visível
    QTest.keyClick(caixa, Qt.Key.Key_Space)
    assert escolhido == [2] and leg.ativo == 2
    QTest.keyClick(caixa, Qt.Key.Key_Return)
    assert escolhido == [2, -1] and leg.ativo == -1
    leg.caixas[3].setFocus(Qt.FocusReason.TabFocusReason)
    qt.processEvents()
    assert passou[-1] == 3
    leg.close()


def test_n1_coropletico_sem_pontos_sem_legenda_de_pontos_com_nome(tela, qt):
    tela.iniciar(ANA_N1, Nivel.N1)
    tela.mostrar_modo("painel")
    qt.processEvents()
    pn = tela.painel_analitico.panorama
    pn.mostrar_secao("onde")                      # O coroplético do N1 fica em "Onde estão os casos?"
    qt.processEvents()
    m = pn.mapa
    assert not m.pontos and not m.legenda.isVisible() and not m.entradas_legenda
    assert m.accessibleName() == "Mapa coroplético por UF"
    assert not m.focar_proximo(True)                                                 # nada a focar no N1


# painel de camadas
def test_reordenar_camadas_muda_o_z_value(tela, qt):
    from ecosec.interface.mapa_vetorial import NOME_CAMADA
    mi = _interativo(tela, qt)
    m, painel = mi.mapa, mi.painel_camadas
    assert m.camadas["custodias"].zValue() > m.camadas["pendencias"].zValue()
    assert painel.ordem()[:2] == ["custodias", "pendencias"]
    painel.linhas["pendencias"].subir.click()
    assert m.camadas["pendencias"].zValue() > m.camadas["custodias"].zValue()
    assert m.ordem_camadas[0] == "pendencias" and painel.ordem()[:2] == ["pendencias", "custodias"]
    lay = painel._layout
    assert [lay.itemAt(i).widget().chave for i in range(lay.count())] == painel.ordem()     # a lista acompanha
    assert not painel.linhas["pendencias"].subir.isEnabled()
    painel.linhas["ufs"].subir.click()                                               # UF sobe acima do coroplético
    ordem = m.ordem_camadas
    assert ordem.index("ufs") < ordem.index("municipios")
    assert m.camadas["ufs"].zValue() > m.camadas["municipios"].zValue()
    m._recalcular_legenda()                                                          # a legenda segue a ordem
    secoes = list(dict.fromkeys(e.camada for e in m.entradas_legenda if e.camada))
    assert secoes == [c for c in m.ordem_camadas if c in secoes]
    # UFs também ligam e desligam
    mi.caixas_n3["ufs"].setChecked(False)
    assert not m.camada_visivel("ufs") and not m.camadas["ufs"].isVisible()
    mi.caixas_n3["ufs"].setChecked(True)
    assert m.camada_visivel("ufs")
    # dois nomes sem ambiguidade; símbolo ao lado de cada nome
    nomes = {c: painel.caixas[c].text() for c in painel.caixas}
    assert nomes["municipios"] == NOME_CAMADA["municipios"] == "Coroplético municipal"
    assert nomes["limites"] == "Limites municipais" and "Municípios" not in nomes.values()
    for linha in painel.linhas.values():
        assert not linha.icone.pixmap().isNull() and linha.subir.accessibleName()
    # recarregar volta à ordem padrão (o mapa é remontado) e o painel acompanha
    mi.carregar(mi.painel)
    assert m.camadas["custodias"].zValue() > m.camadas["pendencias"].zValue()
    assert painel.ordem()[:2] == ["custodias", "pendencias"]


def test_n2_painel_horizontal_com_ufs_limites_e_coropletico(tela, qt):
    mi = _interativo(tela, qt, BIA_N2, Nivel.N2)
    assert mi.linha_camadas.isVisibleTo(mi) and not mi.coluna_n3.isVisibleTo(mi)
    assert set(mi.caixas_n2) == {"pendencias", "densidade", "municipios", "limites", "ufs"}
    assert mi.caixas_n2["ufs"].isChecked() and mi.caixas_n2["limites"].isChecked()
    assert not mi.caixas_n2["municipios"].isChecked()
    mi.mapa._recalcular_legenda()
    assert "custodias" not in {e.camada for e in mi.mapa.entradas_legenda}            # o N2 não tem custódias
    mi.linha_camadas.linhas["densidade"].subir.click()
    assert mi.mapa.camadas["densidade"].zValue() > mi.mapa.camadas["pendencias"].zValue()


# rampa da densidade
def test_rampa_da_densidade_nao_colide_com_a_de_risco(mapa, qt):
    from PySide6.QtTest import QTest

    from ecosec.interface.componentes import simbologia as sb
    from ecosec.interface.componentes.legenda_quantis import RAMPA
    risco = [_matiz(c) for c in (*sb.COR_IDENTIDADE.values(), *RAMPA)]
    for cor in sb.RAMPA_DENSIDADE:
        assert min(_distancia_matiz(_matiz(cor), h) for h in risco) >= 60, cor
    mapa.definir_camada_visivel("densidade", True)
    QTest.qWait(50)
    item = mapa._densidade_item
    assert item is not None
    imagem = item.pixmap().toImage()
    cores = {imagem.pixelColor(x, y).rgb() for x in range(0, imagem.width(), 7) for y in range(0, imagem.height(), 7)
             if imagem.pixelColor(x, y).alpha() > 60}
    assert cores
    from PySide6.QtGui import QColor
    for rgb in list(cores)[:200]:
        c = QColor(rgb)
        assert c.blue() >= c.red(), c.name()                                          # azul, não laranja
