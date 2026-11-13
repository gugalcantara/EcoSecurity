"""Agregação por zoom e camada temática de atributos (faixa, classe, fase).

O que se confere:
- zoom 1× com as 1.028 ativas: agregados + pontos soltos desenhados < 25% dos pontos visíveis;
- em todo zoom e com filtro: soma das contagens dos agregados + pontos soltos = pontos visíveis;
- na escala de UF (≥ 3×) nada agregado; recorte e ano refazem os agregados;
- clique e Enter no agregado aproximam; Tab alcança agregados com nome "Agregado de N pendências, pior risco X";
- a legenda continua contando pontos (soma = `contagens["na_vista"]`) e ganha a entrada AGREGADO;
- trocar o atributo troca a legenda e o símbolo (o mesmo objeto Simbolo, e a mesma cor desenhada);
- cores novas com contraste ≥ 3:1 sobre #EEF3EE; classe distinguível pela forma, fase pelo preenchimento;
- N1 sem pontos nem agregados.
"""
from datetime import date
from math import hypot

import pytest

from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel

CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)


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
def mi(tela, qt):
    return _interativo(tela, qt)


def _na_vista_esperado(m):
    vista = m.viewport().rect()
    vt = m.viewportTransform()
    return sum(pt.conta and pt.parentItem().isVisible()
               and pt.deviceTransform(vt).mapRect(pt.boundingRect()).intersects(vista) for pt in m.pontos)


def _no_zoom(m, aumento, lon=-46.6, lat=-23.5):
    from ecosec.interface.mapa_vetorial import projetar
    m.ir_para_brasil()
    if aumento > 1:
        m.aproximar(aumento)
    m.centerOn(projetar(lon, lat))


def _conferir_soma(m):
    """Soma das contagens (agregados + soltos) = pontos visíveis; cada ponto que conta em exatamente um lugar."""
    r = m.resumo_agregacao()
    assert r["soma"] == r["pontos"] == len(m.pontos_visiveis()), r
    membros = [id(pt) for ag in m.agregados for pt in ag.membros]
    assert len(membros) == len(set(membros))                                    # ninguém em dois agregados
    soltos = {id(pt) for pt in m.pontos if pt.conta and pt.isVisible()}
    assert not soltos & set(membros)
    assert soltos | set(membros) == {id(pt) for pt in m.pontos_visiveis()}
    assert all(pt.conta for ag in m.agregados for pt in ag.membros)              # só agrega o que conta
    # Os encerrados ficam fora da contagem por faixa (sem risco atual) e contam à parte
    assert all(ag.n == len(ag.membros) == sum(ag.por_faixa.values()) + ag.encerrados >= 2 for ag in m.agregados)
    return r


def _sem_sobreposicao(m):
    """Agregados e pontos soltos não se encostam (em pixels de tela)."""
    vt = m.viewportTransform()
    itens = [(vt.map(ag.scenePos()), ag.simbolo.raio_externo) for ag in m.agregados]
    soltos = [(vt.map(pt.scenePos()), pt.simbolo.raio_externo) for pt in m.pontos if pt.conta and pt.isVisible()]
    for i, (a, ra) in enumerate(itens):
        for b, rb in itens[i + 1:] + soltos:
            assert hypot(a.x() - b.x(), a.y() - b.y()) >= ra + rb - 1e-6


# algoritmo puro
def test_agrupar_puro_soma_sementes_afastadas_e_determinismo():
    import random

    from ecosec.interface.componentes.agregacao import agrupar
    rng = random.Random(7)
    pontos = [(rng.gauss(0, 60), rng.gauss(0, 40)) for _ in range(800)] + [(500 + i, 500) for i in range(5)]
    grupos = agrupar(pontos, 30.0)
    indices = [i for g in grupos for i in g]
    assert sorted(indices) == list(range(len(pontos)))                            # cada ponto uma vez
    sementes = [pontos[g[0]] for g in grupos]
    for i, a in enumerate(sementes):
        for b in sementes[i + 1:]:
            assert hypot(a[0] - b[0], a[1] - b[1]) > 30.0                         # sementes afastadas
    for g in grupos:
        s = pontos[g[0]]
        assert all(hypot(pontos[j][0] - s[0], pontos[j][1] - s[1]) <= 30.0 for j in g)
    assert agrupar(pontos, 30.0) == grupos                                       # determinístico
    assert agrupar(pontos, 0) == [[i] for i in range(len(pontos))]
    assert agrupar([], 30.0) == []


# critério do país e soma
def test_pais_zoom_1_itens_desenhados_menos_de_25_por_cento(mi):
    m = mi.mapa
    assert m.agregacao and mi.caixa_agrupar.isChecked()                          # ligado por padrão no N3
    m.ir_para_brasil()
    hoje = mi.painel.hoje
    assert len(m.pontos_visiveis()) == sum(pt.pendencia.ativa(hoje) for pt in m.pontos) == 1028
    r = _conferir_soma(m)
    desenhados = sum(pt.isVisible() for pt in m.pontos) + sum(ag.isVisible() for ag in m.agregados)
    assert desenhados == r["desenhados"] < 0.25 * r["pontos"], r
    assert r["agregados"] > 0
    _sem_sobreposicao(m)


@pytest.mark.parametrize("aumento", [1.0, 1.5, 2.0, 2.5, 2.9])
def test_soma_igual_pontos_visiveis_em_varios_zooms(mi, aumento):
    m = mi.mapa
    _no_zoom(m, aumento)
    r = _conferir_soma(m)
    assert r["agregados"] > 0
    _sem_sobreposicao(m)


def test_soma_com_filtro_e_modo_atenuar(mi):
    m = mi.mapa
    m.ir_para_brasil()
    criticos = frozenset(pt.pendencia.codigo for pt in m.pontos if pt.faixa in ("ALTO", "CRITICO"))
    m.aplicar_recorte(criticos)
    r = _conferir_soma(m)
    assert r["pontos"] == sum(pt.pendencia.codigo in criticos and pt.no_ano for pt in m.pontos)
    assert all(pt.faixa in ("ALTO", "CRITICO") for ag in m.agregados for pt in ag.membros)
    # atenuar: os de fora ficam soltos e atenuados (sem agregar, sem contar)
    m.aplicar_recorte(criticos, modo="atenuar")
    _conferir_soma(m)
    atenuados = [pt for pt in m.pontos if pt.atenuado]
    assert atenuados and all(pt.isVisible() and not pt.agrupado for pt in atenuados)
    em_agregados = {id(pt) for ag in m.agregados for pt in ag.membros}
    assert not any(id(pt) in em_agregados for pt in atenuados)
    # o filtro pela barra (estado único) também
    mi.estado.definir(classes=frozenset({"REJEITO RADIOATIVO CNEN"}))
    _conferir_soma(m)
    assert all(pt.pendencia.classe_risco == "REJEITO RADIOATIVO CNEN" for ag in m.agregados for pt in ag.membros)


@pytest.mark.parametrize("aumento", [3.0, 6.0])
def test_escala_de_uf_nada_agregado(mi, aumento):
    m = mi.mapa
    _no_zoom(m, aumento)
    assert not m.agregados and m.raio_agregacao() == 0
    assert all(pt.isVisible() for pt in m.pontos_visiveis())


def _esperar_animacao(m):
    from PySide6.QtCore import QAbstractAnimation
    from PySide6.QtTest import QTest
    for _ in range(80):
        anim = getattr(m, "_animacao_enquadramento", None)
        if anim is None or anim.state() != QAbstractAnimation.State.Running:
            break
        QTest.qWait(25)
    QTest.qWait(30)


def test_aproximar_numa_uf_desagrega(mi, qt):
    from PySide6.QtTest import QTest
    m = mi.mapa
    QTest.qWait(300)
    _esperar_animacao(m)
    m.ir_para_brasil()
    assert m.agregados
    mi.combo_uf.setCurrentText("SP")                                             # filtra e enquadra a UF
    _esperar_animacao(m)
    assert m.aumento >= 3 and m.escala != "PAIS"
    assert not m.agregados and all(pt.isVisible() for pt in m.pontos_visiveis())


# recorte e ano
def test_recorte_e_ano_recalculam_agregados(mi):
    from ecosec.acervo import fase
    m = mi.mapa
    m.ir_para_brasil()
    antes = list(m.agregados)
    sp = frozenset(pt.pendencia.codigo for pt in m.pontos if pt.pendencia.uf == "SP")
    m.aplicar_recorte(sp)
    assert m.agregados and not any(ag in antes for ag in m.agregados)
    assert all(pt.pendencia.uf == "SP" for ag in m.agregados for pt in ag.membros)
    _conferir_soma(m)
    m.aplicar_recorte(None)
    corte = date(2015, 6, 30)
    m.definir_ano(corte)
    r = _conferir_soma(m)
    assert r["pontos"] == sum(pt.pendencia.ativa(corte) for pt in m.pontos)
    assert all(pt.pendencia.ativa(corte) for ag in m.agregados for pt in ag.membros)
    assert all(pt.fase == fase.fase(pt.pendencia, corte) for pt in m.pontos)     # fase no corte, não a de hoje
    m.definir_ano(None, so_ativas=False)                                          # ativas e encerradas
    r = _conferir_soma(m)
    assert r["pontos"] == len(m.pontos)


def test_agrupar_pontos_liga_e_desliga(mi):
    m = mi.mapa
    m.ir_para_brasil()
    assert m.agregados
    mi.caixa_agrupar.setChecked(False)
    assert not m.agregacao and not m.agregados
    assert all(pt.isVisible() for pt in m.pontos_visiveis())
    m._recalcular_legenda()
    assert "AGREGADO" not in dict(m.linhas_legenda)
    mi.caixa_agrupar.setChecked(True)
    assert m.agregacao and m.agregados
    _conferir_soma(m)


def test_n2_ligado_por_padrao(tela, qt):
    mi = _interativo(tela, qt, BIA_N2, Nivel.N2)
    m = mi.mapa
    assert m.agregacao and mi.caixa_agrupar.isVisible() and mi.caixa_agrupar.isChecked()
    m.ir_para_brasil()
    assert m.agregados
    r = _conferir_soma(m)
    assert r["pontos"] == len(m.pontos_visiveis()) and all(pt.pendencia.uf == "SP" for pt in m.pontos)


# clique, Enter, Tab e dica
def test_clique_no_agregado_aproxima(mi, qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    m = mi.mapa
    QTest.qWait(300)
    _esperar_animacao(m)
    m.ir_para_brasil()
    z0 = m.aumento
    ag = max((a for a in m.agregados if m.itemAt(m.mapFromScene(a.scenePos())) is a), key=lambda a: a.n)
    centro = ag.retangulo_membros().center()
    QTest.mouseClick(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     m.mapFromScene(ag.scenePos()))
    QTest.qWait(50)
    _esperar_animacao(m)
    assert m.aumento >= 2 * z0 - 1e-6
    assert m.mapToScene(m.viewport().rect()).boundingRect().contains(centro)
    assert ag not in m.agregados                                                 # refeitos no novo zoom


def test_tab_alcanca_agregado_nome_acessivel_dica_e_enter_aproxima(mi, qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from ecosec.interface.mapa_vetorial import _Agregado, _Ponto
    m = mi.mapa
    _no_zoom(m, 1.5)
    lista = m.pontos_focaveis()
    assert any(isinstance(i, _Agregado) for i in lista)
    assert all(isinstance(i, (_Agregado, _Ponto)) for i in lista)
    assert all(not isinstance(i, _Ponto) or (i.conta and i.isVisible()) for i in lista)
    xs = [i.pos().x() for i in lista]
    assert xs == sorted(xs)                                                      # oeste para leste
    m.setFocus()
    for _ in range(len(lista)):
        QTest.keyClick(m, Qt.Key.Key_Tab)
        if isinstance(m.ponto_em_foco, _Agregado):
            break
    ag = m.ponto_em_foco
    assert isinstance(ag, _Agregado) and ag.focado
    from ecosec.interface.componentes import simbologia as sb
    if ag.por_faixa:                                       # Rótulos do vocabulário, "casos"
        assert ag.nome_acessivel == f"Agrupamento de {ag.n} casos, pior risco {sb.rotulo_categoria('faixa', ag.pior).lower()}"
    assert ag.nome_acessivel in m.accessibleDescription() and "Enter aproxima" in m.accessibleDescription()
    from ecosec.interface.componentes.simbologia import FAIXAS
    ativos = [pt.faixa for pt in ag.membros if not pt.vazado]
    assert ag.pior == (max(ativos, key=FAIXAS.index) if ativos else sb.ENCERRADO)
    dica = ag.toolTip()
    for faixa, n in ag.por_faixa.items():
        assert f"{sb.rotulo_categoria('faixa', faixa)}: {n}" in dica
    assert f"{ag.n} casos" in dica and "Enter" in dica
    z0 = m.aumento
    QTest.keyClick(m, Qt.Key.Key_Return)
    _esperar_animacao(m)
    assert m.aumento >= 2 * z0 - 1e-6 and m.ponto_em_foco is None
    assert ag not in m.agregados


# legenda
def test_legenda_conta_pontos_e_tem_entrada_agregado(mi):
    from ecosec.interface.componentes import simbologia as sb
    m = mi.mapa
    for aumento in (1.0, 2.0):
        _no_zoom(m, aumento)
        m._recalcular_legenda()
        linhas = dict(m.linhas_legenda)
        soma = sum(int(v) for r, v in m.linhas_legenda if r.startswith("● "))
        assert soma == int(linhas["PENDÊNCIAS NA VISTA"]) == m.contagens["na_vista"] == _na_vista_esperado(m)
        vista = m.viewport().rect()
        vt = m.viewportTransform()
        na_vista = sum(ag.deviceTransform(vt).mapRect(ag.boundingRect()).intersects(vista) for ag in m.agregados)
        assert linhas["AGREGADO"] == f"{na_vista} na vista" and na_vista > 0
        entrada = next(e for e in m.entradas_legenda if e.chave == "AGREGADO")
        assert entrada.simbolo == sb.simbolo_agregado_legenda("faixa") and entrada.camada == "pendencias"
        assert soma > na_vista                                                   # conta pendências, não agregados


# temática
def test_trocar_atributo_troca_legenda_e_simbolo(mi, qt):
    from ecosec.acervo import fase
    from ecosec.interface.componentes import simbologia as sb
    m = mi.mapa
    pixmap_faixa = mi.painel_camadas.linhas["pendencias"].icone.pixmap().toImage()
    for indice, tematica, prefixo in ((1, "classe", "CLASSE:"), (2, "fase", "FASE:")):
        mi.combo_simbologia.setCurrentIndex(indice)
        assert m.tematica == tematica
        _no_zoom(m, 8.0)
        m._recalcular_legenda()
        entradas = [e for e in m.entradas_legenda if e.chave.startswith(prefixo)]
        assert entradas and not any(e.chave.startswith("● ") for e in m.entradas_legenda)
        assert sum(int(e.valor) for e in entradas) == m.contagens["na_vista"] == _na_vista_esperado(m)
        titulo = next(e for e in m.entradas_legenda if e.chave == "PENDÊNCIAS NA VISTA")
        assert sb.NOME_TEMATICA[tematica].lower() in titulo.rotulo                # "por classe"
        imagem = m.legenda.grab().toImage()
        for e in entradas:
            categoria = e.chave[len(prefixo):]
            ponto = next(pt for pt in m.pontos if pt.categoria == categoria)
            assert e.simbolo == ponto.simbolo == sb.simbolo_categoria(tematica, categoria, vazado=ponto.vazado)
            assert e.rotulo == sb.rotulo_categoria(tematica, categoria)
            if not e.simbolo.vazado and e.simbolo.preenchimento == 1.0:          # a cor desenhada é a do ponto
                p = m.legenda.ponto_do_simbolo(m.entradas_legenda.index(e))
                r = imagem.devicePixelRatio()
                cor = imagem.pixelColor(int(p.x() * r), int(p.y() * r)).name().upper()
                assert cor == sb.cor_categoria(tematica, categoria).upper(), (tematica, categoria)
        # agregados com o anel da temática; o ícone do painel de camadas acompanha
        _no_zoom(m, 1.0)
        assert m.agregados
        cores = set(sb.cor_categoria(tematica, c) for c in sb.categorias(tematica))
        assert all(set(ag.simbolo.cores) <= cores and not ag.simbolo.anel for ag in m.agregados)
        assert mi.painel_camadas.linhas["pendencias"].icone.pixmap().toImage() != pixmap_faixa
        # Tab e dica continuam (nome com a categoria)
        _no_zoom(m, 30.0)
        assert m.focar_proximo(True)
        foco = m.ponto_em_foco
        risco = "encerrado" if foco.vazado else f"risco {sb.rotulo_categoria('faixa', foco.faixa).lower()}"
        assert foco.nome_acessivel.startswith(f"Caso {foco.pendencia.codigo}, {risco}")
        rotulo = (sb.rotulo_categoria("classe", foco.pendencia.classe_risco) if tematica == "classe"
                  else sb.rotulo_categoria("fase", foco.fase).lower())
        assert rotulo in foco.nome_acessivel and rotulo in foco.toolTip()
        m.soltar_foco()
    mi.combo_simbologia.setCurrentIndex(0)
    assert m.tematica == "faixa" and all(pt.simbolo == sb.simbolo_faixa(pt.faixa, pt.vazado) for pt in m.pontos)
    with pytest.raises(ValueError):
        m.definir_tematica("cor")


def test_tematica_fase_com_encerradas_e_legenda_por_fase(mi):
    from ecosec.acervo import fase
    m = mi.mapa
    mi.estado.definir(situacao="TODAS")
    mi.combo_simbologia.setCurrentIndex(2)
    m.ir_para_brasil()
    m._recalcular_legenda()
    linhas = dict(m.linhas_legenda)
    assert "○ ENCERRADAS" not in linhas                                         # a ENCERRADA já é uma fase
    for f in fase.FASES:
        assert int(linhas[f"FASE:{f}"]) == sum(pt.conta and pt.fase == f for pt in m.pontos)
    assert all((pt.fase == fase.ENCERRADA) == pt.vazado for pt in m.pontos if pt.conta)
    assert all(pt.simbolo.vazado == (pt.fase == fase.ENCERRADA) for pt in m.pontos)
    _conferir_soma(m)


def test_cores_novas_contraste_formas_e_preenchimentos(qt):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter

    from ecosec.acervo import fase
    from ecosec.interface.componentes import simbologia as sb
    for tematica in ("classe", "fase"):
        for c in sb.categorias(tematica):
            assert sb.contraste(sb.cor_categoria(tematica, c), sb.FUNDO_MAPA) >= 3.0, (tematica, c)
    assert sb.contraste(sb.COR_TEXTO, sb.COR_FUNDO_AGREGADO) >= 4.5             # contagem do agregado
    assert len({sb.MARCA_CLASSE[c] for c in sb.CLASSES}) == 3                    # classe: forma além da cor
    assert len({sb.PREENCHIMENTO_FASE[f] for f in fase.FASES}) == 4              # fase: preenchimento
    # as três formas de classe com a mesma área desenhada na cor da classe (± 15%; tolerância de antisserrilhado)
    def perto(a, b):
        return sum(abs(x - y) for x, y in zip(a.getRgb()[:3], b.getRgb()[:3])) < 60

    areas = {}
    for c in sb.CLASSES:
        imagem = QImage(40, 40, QImage.Format.Format_ARGB32)
        imagem.fill(QColor(sb.FUNDO_MAPA))
        painter = QPainter(imagem)
        sb.desenhar_ponto(painter, sb.simbolo_categoria("classe", c), QPointF(20, 20))
        painter.end()
        cor = QColor(sb.COR_CLASSE[c])
        areas[c] = sum(perto(imagem.pixelColor(x, y), cor) for x in range(40) for y in range(40))
    assert max(areas.values()) <= 1.15 * min(areas.values()), areas
    # setores: toda categoria presente com pelo menos 20°, soma 360
    angulos = sb.setores([500, 1, 2])
    assert sum(angulos) == pytest.approx(360) and min(angulos) >= sb.SETOR_MINIMO_GRAUS
    ag = sb.simbolo_agregado({"CRITICO": 3, "BAIXO": 9})
    assert ag.anel and ag.cores == (sb.COR_FAIXA["CRITICO"], sb.COR_FAIXA["BAIXO"]) and ag.texto == "12"
    assert sb.raio_agregado(2) < sb.raio_agregado(100) <= 15.0
    from ecosec.interface.mapa_vetorial import RAIO_AGREGACAO_PX
    maior = sb.Simbolo("agregado", raio=15.0, anel=True).raio_externo
    assert 2 * maior <= RAIO_AGREGACAO_PX                                       # sementes afastadas: sem sobreposição


def test_n1_sem_pontos_nem_agregados(tela, qt):
    tela.iniciar(ANA_N1, Nivel.N1)
    tela.mostrar_modo("painel")
    qt.processEvents()
    pn = tela.painel_analitico.panorama
    pn.mostrar_secao("onde")                      # O coroplético do N1 fica em "Onde estão os casos?"
    qt.processEvents()
    m = pn.mapa
    m.ir_para_brasil()
    assert not m.pontos and not m.agregados and m.raio_agregacao() == 0
    from ecosec.interface.mapa_vetorial import _Agregado, _Ponto
    assert not any(isinstance(i, (_Agregado, _Ponto)) for i in m.cena.items())
    assert not m.focar_proximo(True)
