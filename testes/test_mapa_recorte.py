"""O mapa recebe um recorte do filtro (/ /).

- `aplicar_recorte(códigos, modo)`: um ponto conta se e somente se estiver ativo no ano do mapa e no recorte;
- as camadas derivadas (dicas das UFs e dos municípios, coroplético municipal) seguem o recorte e o ano;
- a legenda conta só o que cruza a vista (com a transformação do dispositivo, pois os pontos ignoram o
  zoom), é recalculada depois de rolar pelo teclado e mostra "fora do filtro" quando há recorte;
- o `filtrar(faixas, ufs, atividade)` antigo continua dando o mesmo resultado.
"""
from datetime import date

import pytest

from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel

CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
BASE_N3 = 1028                                    # pendências ativas na data de referência (N3: era 1.055)


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


@pytest.fixture
def mapa(tela, qt):
    tela.iniciar(CAIO_N3, Nivel.N3)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    pa.mostrar("mapa")
    qt.processEvents()
    # Este teste conta pontos desenhados (isVisible) na escala país; sem a agregação por zoom, que
    # esconde os pontos dentro dos agregados (a agregação tem os próprios testes)
    pa.mapa.caixa_agrupar.setChecked(False)
    # o padrão do filtro é Todos; estes testes medem o mapa nas ativas
    pa.estado.definir(situacao="ATIVAS")
    return pa.mapa.mapa


def _codigos(m, condicao):
    return frozenset(pt.pendencia.codigo for pt in m.pontos if condicao(pt))


def _visiveis(m):
    """Os pontos visíveis E plenos (no modo esconder, todos os visíveis)."""
    return {pt.pendencia.codigo for pt in m.pontos if pt.isVisible() and not pt.atenuado}


def _hoje(m):
    from ecosec.acervo import sinteticos
    return sinteticos.DATA_BASE


def _na_vista_esperado(m):
    """Pontos que contam cujo retângulo, na transformação do dispositivo, cruza a vista."""
    vista = m.viewport().rect()
    vt = m.viewportTransform()
    return sum(pt.conta and pt.parentItem().isVisible()
               and pt.deviceTransform(vt).mapRect(pt.boundingRect()).intersects(vista) for pt in m.pontos)


def _esperar_legenda(m, limite_ms=4000):
    """Espera o temporizador da legenda disparar (sondando, sem depender de um tempo fixo)."""
    from PySide6.QtTest import QTest
    decorrido = 0
    while m._legenda.isActive() and decorrido < limite_ms:
        QTest.qWait(25)
        decorrido += 25
    assert not m._legenda.isActive(), "a legenda não foi recalculada dentro do limite"


def _total_legenda(m):
    return sum(int(valor) for rotulo, valor in m.linhas_legenda if rotulo.startswith("● "))


def test_codigos_unicos_e_base(mapa):
    assert len({pt.pendencia.codigo for pt in mapa.pontos}) == len(mapa.pontos)
    assert mapa.aplicar_recorte(None) == BASE_N3
    assert len(_visiveis(mapa)) == BASE_N3


def test_recorte_mostra_exatamente_o_conjunto_ativo(mapa):
    hoje = _hoje(mapa)
    recorte = _codigos(mapa, lambda pt: pt.pendencia.uf in ("SP", "MG"))
    n = mapa.aplicar_recorte(recorte)
    esperado = {pt.pendencia.codigo for pt in mapa.pontos
                if pt.pendencia.codigo in recorte and pt.pendencia.ativa(hoje)}
    assert _visiveis(mapa) == esperado and n == len(esperado)
    assert {pt.pendencia.codigo for pt in mapa.pontos_visiveis()} == esperado
    assert mapa.recorte == recorte and mapa.modo_recorte == "esconder"
    assert mapa.aplicar_recorte(None) == BASE_N3 and mapa.recorte is None


def test_recorte_cruza_com_o_ano(mapa):
    corte = date(2015, 12, 31)
    recorte = _codigos(mapa, lambda pt: pt.faixa in ("ALTO", "CRITICO"))
    mapa.definir_ano(corte)
    n = mapa.aplicar_recorte(recorte)
    esperado = {pt.pendencia.codigo for pt in mapa.pontos
                if pt.pendencia.codigo in recorte and pt.pendencia.ativa(corte)}
    assert _visiveis(mapa) == esperado and n == len(esperado)
    # a ordem não importa: trocar o ano mantém o recorte
    mapa.definir_ano(_hoje(mapa))
    assert _visiveis(mapa) == {pt.pendencia.codigo for pt in mapa.pontos
                               if pt.pendencia.codigo in recorte and pt.pendencia.ativa(_hoje(mapa))}


def test_sinal_e_contagens_dentro_fora(mapa):
    recebidos = []
    mapa.recorte_mudou.connect(lambda dentro, fora: recebidos.append((dentro, fora)))
    recorte = _codigos(mapa, lambda pt: pt.faixa == "CRITICO")
    n = mapa.aplicar_recorte(recorte)
    c = mapa.contagens
    assert recebidos[-1] == (c["dentro"], c["fora"]) and c["dentro"] == n
    assert c["dentro"] + c["fora"] == c["total"] == BASE_N3
    corte = date(2012, 12, 31)
    mapa.definir_ano(corte)                                  # o ano também muda as contagens
    ativos = sum(pt.pendencia.ativa(corte) for pt in mapa.pontos)
    assert sum(recebidos[-1]) == ativos == mapa.contagens["total"]


def test_modo_atenuar(mapa, qt):
    from PySide6.QtCore import Qt
    hoje = _hoje(mapa)
    recorte = _codigos(mapa, lambda pt: pt.faixa == "BAIXO")
    n = mapa.aplicar_recorte(recorte, modo="atenuar")
    dentro = {pt.pendencia.codigo for pt in mapa.pontos if pt.pendencia.codigo in recorte and pt.pendencia.ativa(hoje)}
    assert n == len(dentro) == len(mapa.pontos_visiveis())
    fora = [pt for pt in mapa.pontos if pt.pendencia.ativa(hoje) and pt.pendencia.codigo not in recorte]
    assert fora and all(pt.isVisible() and pt.opacity() < 0.3 for pt in fora)
    assert all(pt.acceptedMouseButtons() == Qt.MouseButton.NoButton and not pt.toolTip() for pt in fora)
    assert all(pt.zValue() < min(p.zValue() for p in mapa.pontos_visiveis()) for pt in fora)   # por baixo
    inativos = [pt for pt in mapa.pontos if not pt.pendencia.ativa(hoje)]
    assert inativos and not any(pt.isVisible() for pt in inativos)
    mapa._recalcular_legenda()
    assert _total_legenda(mapa) == _na_vista_esperado(mapa) == mapa.contagens["na_vista"]
    assert mapa.contagens["dentro"] == n and mapa.contagens["fora"] == len(fora)
    assert mapa.dica_uf("SP").startswith(f"SP: {sum(pt.pendencia.uf == 'SP' for pt in mapa.pontos_visiveis())} ")
    mapa.aplicar_recorte(None)                                # volta ao normal: opacidade plena e clicável
    assert all(pt.opacity() == 1.0 and pt.acceptedMouseButtons() != Qt.MouseButton.NoButton for pt in fora)
    with pytest.raises(ValueError):
        mapa.aplicar_recorte(None, modo="apagar")


def test_dica_de_sp_e_coropletico_seguem_o_recorte(mapa):
    antes_dica, antes_municipal = mapa.dica_uf("SP"), mapa.contagem_municipal
    mapa.definir_camada_visivel("municipios", True)
    cores_antes = {k: r.brush().color().rgba() for k, r in mapa.municipios.items()}
    recorte = _codigos(mapa, lambda pt: pt.faixa == "CRITICO")
    mapa.aplicar_recorte(recorte)
    em_sp = [pt for pt in mapa.pontos_visiveis() if pt.pendencia.uf == "SP"]
    assert em_sp and mapa.dica_uf("SP") == f"SP: {len(em_sp)} casos, {len(em_sp)} críticos"
    assert mapa.dica_uf("SP") != antes_dica
    municipal = mapa.contagem_municipal
    assert municipal != antes_municipal and sum(municipal.values()) == len(mapa.pontos_visiveis())
    chave = (em_sp[0].pendencia.uf, em_sp[0].pendencia.municipio)
    if chave in mapa.municipios:
        from ecosec.acervo import vocabulario
        assert mapa.municipios[chave].toolTip().endswith(f": {vocabulario.casos(municipal[chave])}")
    cores = {k: r.brush().color().rgba() for k, r in mapa.municipios.items()}
    assert cores != cores_antes                                # o coroplético foi repintado
    corte = date(2012, 12, 31)                                 # e segue o ano
    mapa.definir_ano(corte)
    em_sp = [pt for pt in mapa.pontos if pt.pendencia.uf == "SP" and pt.faixa == "CRITICO"
             and pt.pendencia.ativa(corte)]
    assert mapa.dica_uf("SP").startswith(f"SP: {len(em_sp)} casos")
    mapa.definir_camada_visivel("municipios", False)


def test_legenda_conta_so_a_vista_em_zoom_municipal_e_apos_seta(mapa, qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from ecosec.interface.mapa_vetorial import projetar
    alvo = next(pt for pt in mapa.pontos_visiveis() if pt.pendencia.uf == "SP")
    mapa.centerOn(projetar(alvo.pendencia.longitude, alvo.pendencia.latitude))
    while mapa.escala != "MUNICIPIO":
        mapa.aproximar(2.0)
    mapa.centerOn(projetar(alvo.pendencia.longitude, alvo.pendencia.latitude))
    mapa._recalcular_legenda()
    esperado = _na_vista_esperado(mapa)
    assert 0 < esperado < len(mapa.pontos_visiveis())
    assert _total_legenda(mapa) == esperado == mapa.contagens["na_vista"]
    barra = mapa.horizontalScrollBar()
    antes = barra.value()
    mapa._legenda.stop()
    for _ in range(25):
        QTest.keyClick(mapa, Qt.Key.Key_Right)
    assert barra.value() != antes                              # a seta rolou a vista ...
    assert mapa._legenda.isActive()                            # ... e agendou a legenda
    _esperar_legenda(mapa)
    assert _total_legenda(mapa) == _na_vista_esperado(mapa) == mapa.contagens["na_vista"]
    # "fora do filtro" aparece com o recorte, e dentro + fora == total
    assert not any(r == "FORA DO FILTRO" for r, _ in mapa.linhas_legenda)
    mapa.aplicar_recorte(_codigos(mapa, lambda pt: pt.faixa == "CRITICO"))
    mapa._recalcular_legenda()
    linhas = dict(mapa.linhas_legenda)
    c = mapa.contagens
    assert int(linhas["FORA DO FILTRO"]) == c["fora"] > 0 and c["dentro"] + c["fora"] == c["total"]
    assert _total_legenda(mapa) == _na_vista_esperado(mapa)


def test_filtrar_antigo_da_o_mesmo_resultado(mapa):
    hoje = _hoje(mapa)
    atividade = mapa.pontos[0].pendencia.atividade
    casos = [(None, None, None), (("CRITICO",), None, None), (None, {"SP"}, None), (None, None, atividade),
             (("ALTO", "CRITICO"), {"SP", "MG"}, atividade)]
    for faixas, ufs, ativ in casos:
        n = mapa.filtrar(faixas, ufs, ativ)
        esperado = {pt.pendencia.codigo for pt in mapa.pontos if pt.pendencia.ativa(hoje)
                    and (not faixas or pt.faixa in faixas) and (not ufs or pt.pendencia.uf in ufs)
                    and (not ativ or pt.pendencia.atividade == ativ)}
        assert _visiveis(mapa) == esperado and n == len(esperado), (faixas, ufs, ativ)
    assert mapa.filtrar() == BASE_N3 and mapa.recorte is None
