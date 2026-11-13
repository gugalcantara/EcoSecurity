"""Navegação do mapa com as animações ligadas e a vista visível.

O defeito: a animação de enquadramento era criada com DeleteWhenStopped e a referência ficava
guardada na vista; a partir do 2º enquadramento, anterior.state() tocava o objeto C++ já apagado
("Internal C++ object already deleted") e o filtro de UF, o combo de município, a árvore de
custódia e ir_para_ponto paravam de funcionar. Os testes antigos não pegavam porque rodavam sem
animação ou com a vista oculta; aqui a tela é mostrada e cada passo ESPERA a animação terminar
(com folga, sem depender de um tempo fixo).
"""
import sys

import pytest

from ecosec.acervo import vocabulario
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.interface.painel_analitico import TODAS_UFS

BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
LIMITE_MS = 4000                                  # folga larga: a animação dura ~380 ms


@pytest.fixture
def erros(monkeypatch):
    """Exceções levantadas dentro de slots do Qt (o PySide manda para sys.excepthook, não para o teste)."""
    capturados = []
    monkeypatch.setattr(sys, "excepthook", lambda *e: capturados.append(e))
    return capturados


@pytest.fixture
def tela(qt, tmp_path, erros):
    from ecosec.aplicacao import montar
    from ecosec.interface.componentes.animacao import animacoes_ligadas
    from ecosec.interface.tela_acervo import TelaAcervo
    animacoes_ligadas.cache_clear()
    assert animacoes_ligadas(), "o teste exige [interface] animacoes = true no config/ecosec.toml"
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    t = TelaAcervo(app)
    t.resize(1500, 950)
    t.show()
    yield t
    t.encerrar()
    t.deleteLater()
    assert not erros, "exceção dentro de um slot do Qt: " + repr(erros[0][1])


def _abrir_mapa(tela, usuario, nivel):
    from PySide6.QtTest import QTest
    tela.iniciar(usuario, nivel)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    pa.mostrar("mapa")
    QTest.qWait(300)
    m = pa.mapa
    _esperar_fim(m.mapa)
    assert m.mapa.isVisible()
    # Estes testes contam pontos desenhados (isVisible) na escala país; sem a agregação por zoom,
    # que esconde os pontos dentro dos agregados (a agregação tem os próprios testes)
    m.caixa_agrupar.setChecked(False)
    # o padrão do filtro é Todos; estes testes medem o mapa nas ativas
    m.estado.definir(situacao="ATIVAS")
    return m


def _animando(vista) -> bool:
    from PySide6.QtCore import QAbstractAnimation
    anim = getattr(vista, "_animacao_enquadramento", None)
    return anim is not None and anim.state() == QAbstractAnimation.State.Running


def _esperar_fim(vista):
    """Espera o enquadramento em curso terminar (sondando), com teto largo."""
    from PySide6.QtTest import QTest
    decorrido = 0
    while _animando(vista) and decorrido < LIMITE_MS:
        QTest.qWait(25)
        decorrido += 25
    assert not _animando(vista), "a animação não terminou dentro do limite"
    QTest.qWait(30)                               # deixa os temporizadores da legenda rodarem


def _visiveis(m):
    return [pt.pendencia for pt in m.mapa.pontos if pt.isVisible()]


def _ativas(m, uf=None):
    hoje = m.painel.hoje
    return sum(pt.pendencia.ativa(hoje) and (uf is None or pt.pendencia.uf == uf) for pt in m.mapa.pontos)


def _area_visivel(vista):
    return vista.mapToScene(vista.viewport().rect()).boundingRect()


def _clicar_no(arvore, item):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    arvore.scrollToItem(item)
    retangulo = arvore.visualItemRect(item)
    assert retangulo.isValid(), "o nó da árvore não está visível para o clique"
    QTest.mouseClick(arvore.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     retangulo.center())


# (a) combo de UF no N3
def test_n3_combo_uf_filtra_e_enquadra_a_cada_passo(tela, erros):
    m = _abrir_mapa(tela, CAIO_N3, Nivel.N3)
    aumento_anterior = m.mapa.aumento
    for passo in ("SP", TODAS_UFS, "RJ", "MG"):
        uf = None if passo == TODAS_UFS else passo
        m.combo_uf.setCurrentText(passo)
        # o recorte vale na hora, antes mesmo de a animação terminar
        visiveis = _visiveis(m)
        assert len(visiveis) == _ativas(m, uf), passo
        assert uf is None or {p.uf for p in visiveis} == {uf}
        assert m.contagem.text().startswith(vocabulario.casos(len(visiveis))), passo
        if uf:
            assert _animando(m.mapa), "com animações ligadas e a vista visível, o enquadramento é animado"
        _esperar_fim(m.mapa)
        assert len(_visiveis(m)) == _ativas(m, uf), passo
        if uf:
            assert m.mapa.aumento > 3, (passo, m.mapa.aumento)
        else:
            assert m.mapa.aumento == pytest.approx(1.0, abs=0.05)
        assert m.mapa.aumento != pytest.approx(aumento_anterior, rel=0.02), passo
        aumento_anterior = m.mapa.aumento
        assert not erros, (passo, erros[0][1])


# (b) enquadramentos seguidos direto na vista
def test_tres_enquadramentos_seguidos_via_ir_para_uf(tela):
    m = _abrir_mapa(tela, CAIO_N3, Nivel.N3)
    for uf in ("SP", "MG", "BA"):
        m.mapa.ir_para_uf(uf)                     # antes do conserto, o 2º levantava RuntimeError aqui
        assert _animando(m.mapa)
        _esperar_fim(m.mapa)
        assert m.mapa.aumento > 3, (uf, m.mapa.aumento)
        assert _area_visivel(m.mapa).contains(m.mapa.ufs[uf].boundingRect().center()), uf
    # interromper no meio também não pode quebrar: um novo destino vence o anterior
    m.mapa.ir_para_uf("RJ")
    m.mapa.ir_para_uf("SP")
    _esperar_fim(m.mapa)
    assert _area_visivel(m.mapa).contains(m.mapa.ufs["SP"].boundingRect().center())
    # e o recuo ao país inteiro cancela um enquadramento em curso (não é desfeito pelo quadro seguinte)
    m.mapa.ir_para_uf("MG")
    m.mapa.ir_para_brasil()
    _esperar_fim(m.mapa)
    assert m.mapa.aumento == pytest.approx(1.0, abs=0.05)


# (c) árvore de custódia e ir_para_ponto
def test_foco_pela_arvore_e_ir_para_ponto_depois_de_um_zoom(tela):
    from ecosec.interface.arvore_custodia import PAPEL
    from ecosec.interface.mapa_vetorial import projetar
    m = _abrir_mapa(tela, CAIO_N3, Nivel.N3)
    m.combo_uf.setCurrentText("SP")               # zoom anterior (o 1º enquadramento)
    _esperar_fim(m.mapa)
    arvore = m.arvore
    raizes = [arvore.topLevelItem(i) for i in range(arvore.topLevelItemCount())]
    # nó de UF (IN SITU) -> ir_para_uf
    in_situ = next(r for r in raizes if r.data(0, PAPEL)[0] == "IN_SITU")
    in_situ.setExpanded(True)
    no_uf = in_situ.child(0)
    uf = no_uf.data(0, PAPEL)[1]
    _clicar_no(arvore, no_uf)
    assert _animando(m.mapa)
    _esperar_fim(m.mapa)
    assert _area_visivel(m.mapa).contains(m.mapa.ufs[uf].boundingRect().center())
    # nó de pendência -> ficha aberta e ponto enquadrado
    no_uf.setExpanded(True)
    no_p = no_uf.child(0)
    p = no_p.data(0, PAPEL)[1]
    _clicar_no(arvore, no_p)
    assert m.ficha_titulo.text().startswith(p.codigo)
    _esperar_fim(m.mapa)
    assert m.ficha.aberto
    assert _area_visivel(m.mapa).contains(projetar(p.longitude, p.latitude))
    assert m.mapa.aumento > 20, m.mapa.aumento
    # custódia -> enquadramento mais aberto (400) em torno dela
    in_situ.setExpanded(False)
    no_c = next(r for r in raizes if r.data(0, PAPEL)[0] == "CUSTODIA")
    c = no_c.data(0, PAPEL)[1]
    _clicar_no(arvore, no_c)
    _esperar_fim(m.mapa)
    assert _area_visivel(m.mapa).contains(projetar(c.longitude, c.latitude))
    # ir_para_ponto direto, em seguida, para outra pendência
    outra = next(pt.pendencia for pt in m.mapa.pontos if pt.pendencia.uf != p.uf)
    m.mapa.ir_para_ponto(outra.longitude, outra.latitude)
    assert _animando(m.mapa)
    _esperar_fim(m.mapa)
    assert _area_visivel(m.mapa).contains(projetar(outra.longitude, outra.latitude))
    assert _area_visivel(m.mapa).width() < 400


# (d) N2 navegando por município
def test_n2_municipio_duas_vezes_seguidas(tela):
    m = _abrir_mapa(tela, BIA_N2, Nivel.N2)
    ativas_sp = _ativas(m, "SP")
    assert len(_visiveis(m)) == ativas_sp and {p.uf for p in _visiveis(m)} == {"SP"}
    aumento_uf = m.mapa.aumento
    nomes = [m.combo_municipio.itemText(i) for i in range(1, m.combo_municipio.count())]
    escolhidos = [n for n in nomes if ("SP", n) in m.mapa.municipios][:2]
    assert len(escolhidos) == 2 and m.combo_municipio.isEnabled()
    for nome in escolhidos:
        m.combo_municipio.setCurrentText(nome)
        assert _animando(m.mapa), nome
        _esperar_fim(m.mapa)
        regiao = m.mapa.municipios[("SP", nome)]
        assert _area_visivel(m.mapa).contains(regiao.boundingRect().center()), nome
        assert m.mapa.aumento > aumento_uf, (nome, m.mapa.aumento, aumento_uf)
        # O município enquadra e recorta (o Filtro usa o par (UF, município))
        assert {(p.uf, p.municipio) for p in _visiveis(m)} <= {("SP", nome)}, nome
        assert len(_visiveis(m)) == sum(pt.pendencia.ativa(m.painel.hoje) and pt.pendencia.municipio == nome
                                        and pt.pendencia.uf == "SP" for pt in m.mapa.pontos), nome
    # de volta a todos os municípios: a vista volta à UF
    m.combo_municipio.setCurrentIndex(0)
    _esperar_fim(m.mapa)
    assert _area_visivel(m.mapa).contains(m.mapa.ufs["SP"].boundingRect().center())
    assert len(_visiveis(m)) == ativas_sp
