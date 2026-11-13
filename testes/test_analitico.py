"""Analítico do N2 e do N3.

- Planilha analítica: filtros em grupos com rótulo de campo, um único "Limpar filtros" (o da barra), município na
  planilha, sincronismo com o mapa (filtro único; padrão Todos) e sem a coluna redundante;
  os detalhes do caso numa gaveta sobre a grade (Enter ou duplo clique; "Abrir no mapa" leva ao mapa);
- N3: Priorização, Custo por responsável e Resumo agregado com totais que fecham (sem base nem corte);
- legenda do mapa com a situação Todos: os encerrados fora das faixas de risco;
- navegação do mapa: arrasto a partir de qualquer lugar, clique ao soltar, zoom que para no limite, folga
  para arrastar no país inteiro, botão "UF" no N2 (a UF do diretor) e "Brasil" no N3; a faixa de listas sem
  sobreposição em 1500×950 e quebrando em 2 linhas em 1366×768; em 1366×768, o mapa inteiro à vista e a coluna
  de camadas do N3 com rolagem;
- nenhum "escore", "KPI-0" ou "pendência" visível nas abas do analítico.

A ficha ("Dados técnicos" do mapa) tem o canônico em test_n23.py; os Painéis da UF (N2), em
test_paineis_uf.py.
"""
import re

import pytest

from ecosec.acervo import analise, formatos, regras, sinteticos, vocabulario
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel

ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
USUARIOS = {Nivel.N1: ANA_N1, Nivel.N2: BIA_N2, Nivel.N3: CAIO_N3}
ORIGEM = re.compile(r"[Ff]onte|corte \d|Base:|PARAMETRO|simula")       # a tela não diz mais


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


def _abrir(tela, qt, nivel, aba=None):
    tela.iniciar(USUARIOS[nivel], nivel)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    if aba:
        pa.mostrar(aba)
    qt.processEvents()
    return pa


def _escolhas(pa):
    hoje = pa.painel.hoje
    ps = [pt.pendencia for pt in pa.mapa.mapa.pontos]
    return {c: next(p for p in ps if p.classe_risco == c and p.ativa(hoje)) for c in sinteticos.UNIDADE_DA_CLASSE}


def _textos_visiveis(raiz) -> list[str]:
    """Texto que a pessoa lê: rótulos, botões, itens de combo e cabeçalhos de tabela (sem a aba Glossário)."""
    from PySide6.QtCore import QAbstractListModel, Qt
    from PySide6.QtWidgets import QAbstractButton, QAbstractItemView, QComboBox, QLabel

    from ecosec.interface.glossario import PainelGlossario
    glossarios = raiz.findChildren(PainelGlossario) + ([raiz] if isinstance(raiz, PainelGlossario) else [])

    def fora(w):
        return not any(g.isAncestorOf(w) for g in glossarios)
    textos = [w.text() for w in raiz.findChildren(QLabel) if fora(w)]
    textos += [w.text() for w in raiz.findChildren(QAbstractButton) if fora(w)]
    for w in raiz.findChildren(QComboBox):
        if fora(w):
            textos += [w.itemText(i) for i in range(w.count())]
    for v in raiz.findChildren(QAbstractItemView):
        m = v.model()
        if m is not None and fora(v):
            colunas = 1 if isinstance(m, QAbstractListModel) else m.columnCount()   # lista: columnCount é privado
            textos += [str(m.headerData(j, Qt.Orientation.Horizontal)) for j in range(colunas)]
            textos += [str(m.data(m.index(i, j))) for i in range(min(3, m.rowCount())) for j in range(colunas)]
    return textos


# 1. planilha: filtros em grupos, um só "Limpar"
@pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
def test_um_unico_limpar_filtros_e_grupos_rotulados(tela, qt, nivel):
    from ecosec.interface.fluent import PushButton
    from ecosec.interface.painel_analitico import PlanilhaAnalitica
    pa = _abrir(tela, qt, nivel, "planilha")
    limpar = [b for b in pa.findChildren(PushButton) if b.text() == "Limpar filtros" and b.isVisibleTo(pa)]
    assert limpar == [pa.barra.botao_limpar] and not hasattr(pa.planilha, "botao_limpar")
    pl = pa.planilha
    # Três grupos (eram quatro), não regressão. Busca e situação saem dos grupos para a
    # linha de topo (recorte geral, vale também para o mapa); etapa vai para "O quê" e ação fica em "Por quê".
    assert tuple(pl.grupos) == PlanilhaAnalitica.GRUPOS == ("Onde", "O quê", "Por quê")
    membros = {"Onde": (pl.combo_uf, pl.combo_municipio),
               "O quê": (pl.combo_classe, pl.combo_risco, pl.combo_atividade, pl.combo_etapa),
               "Por quê": (pl.combo_motivo, pl.combo_acao)}
    for grupo, widgets in membros.items():
        caixa = pl.grupos[grupo]
        assert caixa.titulo.text() == grupo and all(caixa.isAncestorOf(w) for w in widgets), grupo
        assert all(w.accessibleName() for w in widgets)                              # rótulo do campo
    topo = (pl.busca, pl.combo_situacao)
    assert not any(caixa.isAncestorOf(w) for caixa in pl.grupos.values() for w in topo)
    assert all(w.accessibleName() for w in topo)
    rotulos = {w.accessibleName() for ws in (*membros.values(), topo) for w in ws}
    assert {"Situação do caso", "UF", "Município", "Classe", "Faixa de risco", "Atividade de origem",
            "Motivo da permanência", "Ação recomendada", "Etapa atual"} <= rotulos
    assert pl.combo_situacao.currentText() == "Todos"                               # padrão Todos


def test_planilha_e_mapa_seguem_o_mesmo_filtro_inclusive_o_municipio(tela, qt):
    pa = _abrir(tela, qt, Nivel.N3, "planilha")
    pl, m = pa.planilha, pa.mapa
    assert not pl.combo_municipio.isEnabled()                                       # sem UF, sem lista
    pl.combo_uf.setCurrentText("SP")
    qt.processEvents()
    assert m.combo_uf.currentText() == "SP" and pl.combo_municipio.isEnabled()
    municipio = pl.combo_municipio.itemText(1)
    pl.combo_municipio.setCurrentText(municipio)
    qt.processEvents()
    assert pa.estado.filtro.municipios == {("SP", municipio)}
    assert m.combo_municipio.currentText() == municipio                             # o mapa acompanha
    assert {l.MUNICIPIO for l in pl.modelo.todas} == {municipio}
    assert {pt.pendencia.municipio for pt in m.mapa.pontos if pt.conta} == {municipio}
    m.combo_classe.setCurrentText(vocabulario.rotulo(sinteticos.AREA, "classe"))
    qt.processEvents()
    assert pl.combo_classe.currentText() == vocabulario.rotulo(sinteticos.AREA, "classe")
    assert {l.CLASSE_DE_RISCO for l in pl.modelo.todas} <= {sinteticos.AREA}
    assert any(c.rotulo == f"Município: {municipio}/SP" for c in pa.barra.chips)
    pa.barra.botao_limpar.click()
    qt.processEvents()
    assert pl.combo_municipio.currentIndex() == 0 and pl.combo_uf.currentIndex() == 0
    assert len(pl.modelo.todas) == len(pa.painel.pendencias)


def test_colunas_da_planilha_sem_redundancia_e_com_rotulos(tela, qt):
    from PySide6.QtCore import Qt

    from ecosec.interface.painel_analitico import TITULOS_PLANILHA
    pa = _abrir(tela, qt, Nivel.N2, "planilha")
    modelo = pa.planilha.modelo
    assert "UNIDADE" not in modelo.titulos and modelo.titulos == TITULOS_PLANILHA
    # Só as 9 colunas de decisão, não regressão. Score, substância, quantidade, datas,
    # atraso, andamento, atividade, quem paga, custo, endereço e coordenadas ficam na ficha e na exportação.
    cabecalhos = [modelo.headerData(j, Qt.Orientation.Horizontal) for j in range(modelo.columnCount())]
    assert cabecalhos == ["Código", "Faixa de risco", "Classe", "UF", "Município", "Etapa atual",
                          "Dias além do prazo legal", "Ação recomendada", "Motivo da permanência"]
    assert not {"Unidade", "Score de risco", "Endereço", "Coordenadas", "Atraso (dias)", "Atividade de origem",
                "Custo estimado"} & set(cabecalhos)
    assert all(c == vocabulario.titulo_coluna(t) for c, t in zip(cabecalhos, modelo.titulos))
    # a cor da faixa vai num símbolo; o texto fica na cor de texto
    i = modelo.titulos.index("NIVEL DE RISCO")
    indice = modelo.index(0, i)
    assert modelo.data(indice, Qt.ItemDataRole.DecorationRole) is not None
    assert modelo.data(indice, Qt.ItemDataRole.ForegroundRole) is None


def test_faixa_mostra_o_score_na_dica_e_ordena_pelo_score(tela, qt):
    """O score não aparece na grade (só na dica da faixa, como em "Casos para agir"); ordenar pela
    faixa ordena pelo score, a ordem do risco (o código da faixa em ordem alfabética não é)."""
    from PySide6.QtCore import Qt
    pa = _abrir(tela, qt, Nivel.N3, "planilha")
    modelo = pa.planilha.modelo
    i = modelo.titulos.index("NIVEL DE RISCO")
    modelo.sort(i, Qt.SortOrder.DescendingOrder)
    scores = [l.CRITICIDADE for l in modelo.todas]
    assert scores == sorted(scores, reverse=True) and modelo.ultima_ordem == (i, Qt.SortOrder.DescendingOrder)
    for k, linha in enumerate(modelo._visiveis()[:5]):
        assert modelo.data(modelo.index(k, i), Qt.ItemDataRole.ToolTipRole) == (
            f"{vocabulario.rotulo(linha.NIVEL_DE_RISCO, 'faixa')} · score de risco "
            f"{formatos.numero(linha.CRITICIDADE, 2)}")
    modelo.sort(i, Qt.SortOrder.AscendingOrder)
    assert [l.CRITICIDADE for l in modelo.todas] == sorted(scores)


def test_exportacao_da_planilha_continua_com_as_29_colunas_cruas(tela, qt, tmp_path):
    """A grade mostra 9 colunas; o arquivo exportado continua com as 29 de analise.TITULOS."""
    from openpyxl import load_workbook

    from ecosec.interface.painel_analitico import TITULOS_PLANILHA
    pa = _abrir(tela, qt, Nivel.N2, "planilha")
    pl, servico = pa.planilha, tela.app.acervo
    codigos = [l.CODIGO for l in pl.modelo.todas[:5]]
    servico.exportar_planilha(pa.painel, BIA_N2, codigos, tmp_path / "p.xlsx", verificado_em=servico.relogio())
    cabecalho = next(load_workbook(tmp_path / "p.xlsx")["PASSIVOS"].iter_rows(max_row=1, values_only=True))
    assert len(analise.TITULOS) == 29 and tuple(cabecalho) == analise.TITULOS
    assert len(TITULOS_PLANILHA) == 9 and set(TITULOS_PLANILHA) < set(analise.TITULOS)


@pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
def test_as_9_colunas_cabem_e_o_motivo_fica_com_a_sobra(tela, qt, nivel):
    """Em 1500 px as 9 colunas cabem sem rolagem; a última (motivo) fica com a sobra, com um mínimo, e o
    texto inteiro na dica. Código e faixa sempre à vista."""
    from PySide6.QtCore import Qt

    from ecosec.interface.painel_analitico import MINIMO_MOTIVO
    pa = _abrir(tela, qt, nivel, "planilha")
    pl = pa.planilha
    cabecalho, largura = pl.tabela.horizontalHeader(), pl.tabela.viewport().width()
    j = pl.modelo.titulos.index("MOTIVO")
    assert j == cabecalho.count() - 1 and not any(cabecalho.isSectionHidden(k) for k in range(cabecalho.count()))
    assert cabecalho.sectionViewportPosition(j) + cabecalho.sectionSize(j) == largura          # até a borda
    assert cabecalho.sectionSize(j) >= MINIMO_MOTIVO and pl.tabela.horizontalScrollBar().maximum() == 0
    longo = next(l for l in pl.modelo._visiveis() if len(l.MOTIVO) > 24)
    k = pl.modelo._visiveis().index(longo)
    assert pl.modelo.data(pl.modelo.index(k, j), Qt.ItemDataRole.ToolTipRole) == longo.MOTIVO


def test_indicador_de_mais_colunas_a_direita(tela, qt):
    """Com a janela estreita a grade rola; uma faixa na borda direita avisa que há mais colunas e some no
    fim da rolagem (a barra do Fluent só aparece com o mouse em cima)."""
    pa = _abrir(tela, qt, Nivel.N2, "planilha")
    pl = pa.planilha
    assert pl.indicador_direita.isHidden()                                          # 1500 px: tudo cabe
    tela.resize(900, 950)
    qt.processEvents()
    barra = pl.tabela.horizontalScrollBar()
    assert barra.maximum() > 0 and not pl.indicador_direita.isHidden()
    vp = pl.tabela.viewport().geometry()
    assert pl.indicador_direita.geometry().right() == vp.right() and pl.indicador_direita.accessibleName()
    barra.setValue(barra.maximum())
    qt.processEvents()
    assert pl.indicador_direita.isHidden()
    barra.setValue(0)
    tela.resize(1500, 950)
    qt.processEvents()
    assert pl.indicador_direita.isHidden()


@pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
def test_aviso_de_exportacao_ao_lado_do_por_que(tela, qt, nivel):
    """O aviso de exportação ocupa o espaço livre à direita do grupo "Por quê" (sem linha própria)."""
    from PySide6.QtCore import QPoint
    pa = _abrir(tela, qt, nivel, "planilha")
    pl = pa.planilha
    grupo, aviso = pl.grupos["Por quê"], pl.aviso
    g, a = grupo.mapTo(pl, QPoint(0, 0)), aviso.mapTo(pl, QPoint(0, 0))
    assert aviso.text() and a.x() > g.x() + grupo.width()                             # à direita do grupo
    assert g.y() <= a.y() and a.y() + aviso.height() <= g.y() + grupo.height()       # na mesma faixa
    assert pl.tabela.mapTo(pl, QPoint(0, 0)).y() >= g.y() + grupo.height()           # a tabela logo abaixo


# detalhes do caso na gaveta
def _linha_com_rodovia(pl):
    """A primeira linha da página com endereço em rodovia ("RODOVIA SP 330 KM 83")."""
    linhas = pl.modelo._visiveis()
    k = next(i for i, l in enumerate(linhas) if l.LOGRADOURO.startswith("RODOVIA"))
    return k, linhas[k]


def _enter_na_linha(pl, qt, k):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    pl.tabela.setFocus()
    pl.tabela.selectRow(k)
    QTest.keyClick(pl.tabela, Qt.Key.Key_Return)
    qt.processEvents()


@pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
def test_enter_na_linha_abre_a_gaveta_com_o_caso(tela, qt, nivel):
    """Linha selecionada + Enter abre "Detalhes do caso" na própria planilha, com a ficha do caso. No N3
    (sem exportação) é o acesso aos campos que ficaram fora da grade."""
    pa = _abrir(tela, qt, nivel, "planilha")
    pl = pa.planilha
    assert not pl.gaveta.aberto
    k, linha = _linha_com_rodovia(pl)
    _enter_na_linha(pl, qt, k)
    assert pa.abas.currentRouteKey() == "planilha" and pl.gaveta.aberto and pl.gaveta.isVisible()
    assert pl.gaveta.titulo.text() == "Detalhes do caso"
    assert pl.ficha_tecnica.titulo.text().startswith(linha.CODIGO) and not pa.mapa.ficha.aberto


def test_duplo_clique_na_planilha_abre_a_gaveta_sem_sair_da_aba(tela, qt):
    """(muda): o duplo clique na linha abre os detalhes na própria
    planilha; o mapa fica no botão "Abrir no mapa" da gaveta."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    pa = _abrir(tela, qt, Nivel.N2, "planilha")
    pl = pa.planilha
    linha = pl.modelo._visiveis()[3]
    centro = pl.tabela.visualRect(pl.modelo.index(3, 4)).center()
    for clique in (QTest.mouseClick, QTest.mouseDClick):          # a sequência real: clique e, em seguida, o duplo
        clique(pl.tabela.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centro)
    qt.processEvents()
    assert pa.abas.currentRouteKey() == "planilha" and pl.gaveta.aberto and not pa.mapa.ficha.aberto
    assert pl.ficha_tecnica.titulo.text().startswith(linha.CODIGO)


def test_gaveta_mostra_o_endereco_completo_com_rodovia_e_km(tela, qt):
    """O endereço inteiro, como no acervo ("RODOVIA SP 330 KM 83, S/N - BAIRRO - CEP 00000-000"), sem separar
    rodovia e km."""
    pa = _abrir(tela, qt, Nivel.N2, "planilha")
    pl = pa.planilha
    k, linha = _linha_com_rodovia(pl)
    _enter_na_linha(pl, qt, k)
    p = next(p for p in pa.painel.pendencias if p.codigo == linha.CODIGO)
    local = dict(pl.ficha_tecnica.blocos["local"].linhas)
    assert local["Endereço"] == p.endereco
    assert re.match(r"RODOVIA [A-Z]{2} \d{3} KM \d+, S/N - ", local["Endereço"])
    assert f"CEP {linha.CEP[:5]}-{linha.CEP[5:]}" in local["Endereço"] and linha.BAIRRO in local["Endereço"]


def test_gaveta_mostra_o_local_primeiro_e_o_endereco_sem_rolar(tela, qt):
    """Na gaveta o bloco Local vem antes de Situação e prazos, e a linha do endereço fica
    inteira à vista sem rolar; a ficha do mapa mantém a ordem dela (contexto diferente)."""
    from PySide6.QtCore import QAbstractAnimation, QPoint
    from PySide6.QtTest import QTest
    pa = _abrir(tela, qt, Nivel.N3, "planilha")
    pl = pa.planilha
    k, linha = _linha_com_rodovia(pl)
    _enter_na_linha(pl, qt, k)
    for _ in range(80):                                                # a animação de entrada termina
        if pl.gaveta._anim.state() != QAbstractAnimation.State.Running:
            break
        QTest.qWait(25)

    def ordem(ft):
        return [c for c in sorted(ft.blocos, key=lambda c: ft.layout().indexOf(ft.blocos[c]))]
    assert ordem(pl.ficha_tecnica)[:2] == ["local", "situacao"]
    assert ordem(pa.mapa.ficha_tecnica)[:2] == ["situacao", "local"]
    from PySide6.QtWidgets import QLabel
    local = pl.ficha_tecnica.blocos["local"]
    endereco = next(w for w in local.findChildren(QLabel)
                    if w.isVisibleTo(local) and w.text().startswith(linha.LOGRADOURO))
    assert local.linhas[1][0] == "Endereço"
    vista = pl.ficha_tecnica.parentWidget()                            # o viewport da rolagem
    assert vista.parentWidget().verticalScrollBar().value() == 0
    assert endereco.mapTo(vista, QPoint(0, endereco.height())).y() <= vista.height()


def test_com_a_gaveta_aberta_o_clique_em_outra_linha_troca_o_caso(tela, qt):
    """Fechada, o clique só seleciona; aberta, o clique (e a seta) em outra linha troca o caso, como num painel
    lateral. O foco fica na grade."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    pa = _abrir(tela, qt, Nivel.N2, "planilha")
    pl = pa.planilha
    linhas = pl.modelo._visiveis()

    def clicar(i):
        centro = pl.tabela.visualRect(pl.modelo.index(i, 1)).center()
        QTest.mouseClick(pl.tabela.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centro)
        qt.processEvents()
    clicar(2)
    assert not pl.gaveta.aberto
    _enter_na_linha(pl, qt, 0)
    assert pl.gaveta.aberto and pl.ficha_tecnica.titulo.text().startswith(linhas[0].CODIGO)
    clicar(5)
    assert pl.gaveta.aberto and pl.ficha_tecnica.titulo.text().startswith(linhas[5].CODIGO)
    assert pl._p_atual.codigo == linhas[5].CODIGO and pl.tabela.hasFocus()
    QTest.keyClick(pl.tabela, Qt.Key.Key_Down)
    qt.processEvents()
    assert pl.ficha_tecnica.titulo.text().startswith(linhas[6].CODIGO)


def test_gaveta_cobre_os_campos_que_sairam_da_grade(tela, qt):
    """O que tirou da grade (substância, score, quantidade, datas, quem paga, custo, endereço e
    coordenadas) está na gaveta, com os rótulos do vocabulário e não com os títulos crus da exportação."""
    from ecosec.acervo import ficha
    pa = _abrir(tela, qt, Nivel.N3, "planilha")
    pl = pa.planilha
    k, linha = _linha_com_rodovia(pl)
    _enter_na_linha(pl, qt, k)
    p = next(p for p in pa.painel.pendencias if p.codigo == linha.CODIGO)
    ft = pl.ficha_tecnica
    b = {chave: dict(bloco.linhas) for chave, bloco in ft.blocos.items()}
    assert vocabulario.frase(p.substancia) in ft.titulo.text() and "Score de risco" in ft.score.text()
    assert b["situacao"][vocabulario.rotulo("IDENTIFICACAO", "campo")] == f"{linha.IDENTIFICACAO:%d/%m/%Y}"
    assert b["situacao"][vocabulario.rotulo("PRAZO_COLETA", "prazo")].startswith(f"{linha.PRAZO_DE_COLETA:%d/%m/%Y}")
    assert b["situacao"][vocabulario.rotulo("PRAZO_LIMITE", "prazo")].startswith(f"{linha.PRAZO_LIMITE:%d/%m/%Y}")
    assert b["situacao"][vocabulario.titulo_coluna("RESPONSABILIDADE")] == vocabulario.rotulo(
        linha.RESPONSABILIDADE, "responsabilidade")
    assert b["contaminacao"][vocabulario.rotulo("QUANTIDADE", "campo")].startswith(formatos.numero(linha.QUANTIDADE, 2))
    assert b["local"]["Coordenadas"] == f"{formatos.numero(linha.LATITUDE, 5)}; {formatos.numero(linha.LONGITUDE, 5)}"
    assert b["custo"]["Total"] == f"R$ {formatos.numero(ficha.atributos(p, pa.painel.regras.custos).memoria.total, 0)}"
    texto = ft.texto()
    assert not [t for t in ("LOGRADOURO", "CUSTO ESTIMADO", "PRAZO DE COLETA", "DIAS ALEM") if t in texto]


def test_abrir_no_mapa_a_partir_da_gaveta(tela, qt):
    """"Abrir no mapa", no cabeçalho da gaveta (ao lado do ✕, acima da ficha), leva ao mapa com a ficha do
    mesmo caso (o caminho que o duplo clique fazia)."""
    from PySide6.QtCore import QPoint
    pa = _abrir(tela, qt, Nivel.N2, "planilha")
    pl = pa.planilha
    k, linha = _linha_com_rodovia(pl)
    _enter_na_linha(pl, qt, k)
    botao, fechar = pl.botao_abrir_no_mapa, pl.gaveta.botao_fechar
    assert botao.text() == "Abrir no mapa"
    b, f = botao.mapTo(pl.gaveta, QPoint(0, 0)), fechar.mapTo(pl.gaveta, QPoint(0, 0))
    assert b.x() + botao.width() <= f.x() and b.y() < f.y() + fechar.height() and f.y() < b.y() + botao.height()
    assert b.y() + botao.height() <= pl.ficha_tecnica.mapTo(pl.gaveta, QPoint(0, 0)).y()
    botao.click()
    qt.processEvents()
    assert pa.abas.currentRouteKey() == "mapa" and pa.mapa.ficha.aberto
    assert pa.mapa._p_atual.codigo == linha.CODIGO


def test_gaveta_fica_sobre_a_grade_sem_mudar_as_colunas_e_fecha_com_esc(tela, qt):
    """A gaveta é sobreposta, não é coluna: a grade mantém a largura e as 9 colunas, a gaveta ocupa a altura
    da tabela (os filtros ficam à vista) e deixa à esquerda o código e a faixa; Esc fecha."""
    from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
    from PySide6.QtTest import QTest
    pa = _abrir(tela, qt, Nivel.N3, "planilha")
    pl = pa.planilha
    cabecalho = pl.tabela.horizontalHeader()
    antes = (pl.tabela.viewport().width(), [cabecalho.sectionSize(j) for j in range(cabecalho.count())])
    _enter_na_linha(pl, qt, 0)
    for _ in range(80):                                                # a animação de entrada termina
        if pl.gaveta._anim.state() != QAbstractAnimation.State.Running:
            break
        QTest.qWait(25)
    assert (pl.tabela.viewport().width(), [cabecalho.sectionSize(j) for j in range(cabecalho.count())]) == antes
    g, t = pl.gaveta.mapTo(pl, QPoint(0, 0)), pl.tabela.mapTo(pl, QPoint(0, 0))
    assert g.y() == t.y() and pl.gaveta.height() == pl.tabela.height()
    assert g.x() + pl.gaveta.width() == t.x() + pl.tabela.width()                    # rente à borda direita
    faixa = pl.modelo.titulos.index("NIVEL DE RISCO")
    assert cabecalho.sectionViewportPosition(faixa) + cabecalho.sectionSize(faixa) < g.x() - t.x()
    QTest.keyClick(pl.gaveta, Qt.Key.Key_Escape)
    assert not pl.gaveta.aberto


# 2. N3: precisão
def test_n3_priorizacao_com_curva_que_fecha(tela, qt):
    pa = _abrir(tela, qt, Nivel.N3, "orcamento")
    o = pa.orcamento
    servico = tela.app.acervo
    fila = servico.priorizacao(pa.painel, tela.usuario, o.orcamento.value() * 1e6, regras.CRITERIOS[0])
    assert o.criterio.currentText() == vocabulario.ROTULO_CRITERIO[regras.CRITERIOS[0]]
    m = o.modelo
    assert m.rowCount() == len(fila.selecionadas)
    i_acum, i_risco = m.titulos.index("ACUMULADO NA FILA (R$)"), m.titulos.index("RISCO ELIMINADO ACUMULADO (%)")
    assert m.todas[-1][i_acum] == pytest.approx(fila.custo_total, abs=0.05)
    assert m.todas[-1][i_risco] == pytest.approx(fila.percentual_reduzido, abs=0.01)
    nome = vocabulario.ROTULO_CRITERIO[regras.CRITERIOS[0]]
    assert o.curva.marcas[nome] == pytest.approx((fila.custo_total, fila.percentual_reduzido))
    assert [c.nome for c in o.curva.curvas] == [vocabulario.ROTULO_CRITERIO[c] for c in regras.CRITERIOS]
    for c in o.curva.curvas:                                                     # a curva acumula até 100%
        assert c.pontos[-1][1] == pytest.approx(100.0) and all(b[0] >= a[0] for a, b in zip(c.pontos, c.pontos[1:]))
    assert not ORIGEM.search(o.cartao_curva.rodape.text()) and not hasattr(o, "base")
    assert o.cartoes["casos"].valor.text() == f"{len(fila.selecionadas)} de {fila.candidatas}"
    o.criterio.setCurrentIndex(1)                                                # trocar o critério refaz tudo
    qt.processEvents()
    outra = servico.priorizacao(pa.painel, tela.usuario, o.orcamento.value() * 1e6, regras.CRITERIOS[1])
    assert o.modelo.rowCount() == len(outra.selecionadas)


def test_n3_custo_por_responsavel_totais_sem_dupla_contagem(tela, qt):
    pa = _abrir(tela, qt, Nivel.N3, "responsaveis")
    r = pa.responsaveis
    painel = pa.painel
    distintos = set().union(*(set(l.codigos) for l in r.linhas))
    por_codigo = {p.codigo: p for p in painel.pendencias}
    passivo = sum(regras.custo_estimado(por_codigo[c], painel.regras) for c in distintos)
    assert r.cartoes["casos"].valor.text() == formatos.inteiro(len(distintos))
    assert r.cartoes["passivo"].contexto.text() == f"R$ {formatos.numero(passivo, 2)}"
    assert sum(l.custo for l in r.linhas) >= passivo                              # solidária: soma ≥ passivo
    assert [b.rotulo for b in r.barras.barras] == [l.nome for l in r.linhas[:10]]
    assert not ORIGEM.search(r.cartao_barras.rodape.text())
    r.mostrar_memoria(0)
    html = r.memoria.toPlainText()
    assert "Total do caso" in html and "TOTAL DA PENDÊNCIA" not in html


def test_resumo_com_rotulos_e_linha_total_que_fecha(tela, qt):
    pa = _abrir(tela, qt, Nivel.N3, "agregado")
    ag = pa.agregado
    itens = [ag.combo.itemText(i) for i in range(ag.combo.count())]
    assert itens == [vocabulario.ROTULO_AGRUPAMENTO[g] for g in analise.AGRUPAMENTOS]
    assert not [t for t in itens if t.isupper()]                                  # nada de "POR UF"
    assert not hasattr(ag, "base")                                                # sem "Base: ... corte"
    for i in range(ag.combo.count()):
        ag.combo.setCurrentIndex(i)
        titulos, linhas = ag.resumo.tabelas[ag.agrupamento]
        total = ag.modelo.total
        assert total is not None and total[0] == "Total" and ag.modelo.rowCount() == len(linhas) + 1
        j = titulos.index("PENDENCIAS")
        assert total[j] == sum(l[j] for l in linhas) == sum(p.ativa(pa.painel.hoje) for p in pa.painel.pendencias)
        k = titulos.index(analise.PERCENTUAL_ALEM_DO_PRAZO)
        a = titulos.index(analise.ALEM_DO_PRAZO)
        assert total[k] == round(100 * total[a] / total[j], 1)                     # refeito da soma
        c = titulos.index("CUSTO ESTIMADO")
        assert total[c] == pytest.approx(sum(l[c] for l in linhas), abs=0.01)
    ag.modelo.sort(titulos.index("PENDENCIAS"))                                    # o total fica no fim
    assert ag.modelo.texto(ag.modelo._linha(ag.modelo.rowCount() - 1), 0) == "Total"


def test_resumo_do_n1_sem_linha_total(tela, qt):
    pa = _abrir(tela, qt, Nivel.N1, "agregado")
    assert pa.agregado.modelo.total is None                                        # k=3: a soma não é o total


# 3. legenda do mapa com Todos
def test_legenda_com_todos_separa_os_encerrados_das_faixas(tela, qt):
    from ecosec.interface.componentes import simbologia as sb
    pa = _abrir(tela, qt, Nivel.N3, "mapa")
    m = pa.mapa.mapa
    assert pa.estado.filtro.situacao == "TODAS"
    m.ir_para_brasil()
    m._recalcular_legenda()
    linhas = dict(m.linhas_legenda)
    hoje = pa.painel.hoje
    ativos = sum(p.ativa(hoje) for p in pa.painel.pendencias)
    encerrados = len(pa.painel.pendencias) - ativos
    faixas = sum(int(v) for k, v in m.linhas_legenda if k.startswith("● "))
    assert faixas == ativos == int(linhas["ATIVOS POR FAIXA"])                  # as faixas contam só os ativos
    assert int(linhas["○ ENCERRADAS"]) == encerrados
    assert int(linhas["PENDÊNCIAS NA VISTA"]) == ativos + encerrados == m.contagens["na_vista"]
    rotulos = {e.chave: e.rotulo for e in m.entradas_legenda}
    assert rotulos["○ ENCERRADAS"] == "Encerrados (fora das faixas)" and rotulos["PENDÊNCIAS NA VISTA"] == "Casos na vista"
    assert rotulos["● CRITICO"] == "Crítico"
    vazados = [pt for pt in m.pontos if pt.vazado]
    assert vazados and all(pt.cor == sb.COR_ENCERRADO and not pt.anel for pt in vazados)


def test_n3_ano_em_lista_com_todos_e_marcos_do_ano(tela, qt):
    """No N3 a linha de baixo do mapa tem a lista "Ano": "Todos" primeiro e escolhido (a
    situação atual), depois os anos anteriores em ordem decrescente, sem o ano corrente. À direita,
    na mesma linha, os marcos regulatórios do ano escolhido, só quando o ano tem marco; os rótulos ficam como no
    acervo. A semântica não muda: o ano é a data de corte. No N2 a linha não aparece."""
    from PySide6.QtCore import QPoint

    pa = _abrir(tela, qt, Nivel.N3, "mapa")
    m, hoje = pa.mapa, pa.painel.hoje
    c, marcos = m.combo_ano, m.marcos_do_ano
    inicio = max(2006, min(p.data_identificacao.year for p in pa.painel.pendencias))
    assert [c.itemText(i) for i in range(c.count())] == ["Todos", *[str(a) for a in range(hoje.year - 1,
                                                                                          inicio - 1, -1)]]
    assert c.currentIndex() == 0 and pa.estado.filtro.ano is None
    assert f"situação atual, em {hoje:%d/%m/%Y}" in c.toolTip() and marcos.isHidden()
    eventos = sorted(pa.tela.app.acervo.eventos(), key=lambda e: e.data_evento)
    c.setCurrentText("2021")
    qt.processEvents()
    assert pa.estado.filtro.ano == 2021 and any(ch.dimensao == "ano" for ch in pa.barra.chips)
    assert "31/12/2021" in c.toolTip() and pa.titulo.text().startswith("Casos ativos em 31/12/2021")
    assert not marcos.isHidden() and marcos.text() == "Marcos regulatórios em 2021: " + "; ".join(
        e.rotulo for e in eventos if e.data_evento.year == 2021)
    l, cm = marcos.mapTo(m, QPoint(0, 0)), c.mapTo(m, QPoint(0, 0))          # à direita da lista, na mesma linha
    assert l.x() > cm.x() + c.width() and l.y() < cm.y() + c.height() and cm.y() < l.y() + marcos.height()
    assert not {e.data_evento.year for e in eventos} & {2015}
    c.setCurrentText("2015")                                                 # ano sem marco: a linha some
    qt.processEvents()
    assert pa.estado.filtro.ano == 2015 and marcos.isHidden()
    pa.estado.definir(ano=None)                                              # remover o chip: a situação atual
    qt.processEvents()
    assert c.currentText() == "Todos" and marcos.isHidden()
    c.setCurrentText("2009")
    qt.processEvents()
    assert marcos.text() == "Marcos regulatórios em 2009: CONAMA 420"
    c.setCurrentText("Todos")
    qt.processEvents()
    assert pa.estado.filtro.ano is None and marcos.isHidden()
    assert not hasattr(m, "slider") and not hasattr(m, "rotulo_ano")
    tela.encerrar()
    pa = _abrir(tela, qt, Nivel.N2, "mapa")
    assert pa.mapa.linha_tempo.isHidden()


# 3b. navegação do mapa
def _esperar_enquadramento(m):
    from PySide6.QtCore import QAbstractAnimation
    from PySide6.QtTest import QTest
    for _ in range(200):
        animacao = getattr(m, "_animacao_enquadramento", None)
        if animacao is None or animacao.state() != QAbstractAnimation.State.Running:
            break
        QTest.qWait(25)
    QTest.qWait(30)


def _barras(m) -> tuple[int, int]:
    return m.horizontalScrollBar().value(), m.verticalScrollBar().value()


def _arrastar(m, inicio, delta, passos=10):
    """Aperta em inicio, move em passos até `inicio + delta` e solta (o arrasto real, com o botão apertado)."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    QTest.mousePress(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, inicio)
    for i in range(1, passos + 1):
        QTest.mouseMove(m.viewport(), inicio + QPoint(delta.x() * i // passos, delta.y() * i // passos))
    QTest.mouseRelease(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, inicio + delta)
    QTest.qWait(50)                                   # o agregado se ativa adiado (QTimer)


def _ponto_clicavel(m):
    return next(pt for pt in m.pontos if pt.isVisible() and m.itemAt(m.mapFromScene(pt.scenePos())) is pt)


def _botoes_do_mapa(raiz) -> dict:
    from PySide6.QtWidgets import QAbstractButton
    return {b.text(): b for b in raiz.findChildren(QAbstractButton)
            if b.isVisible() and b.text() in ("−", "+", "Brasil", "UF")}


def test_arrasto_que_comeca_num_ponto_ou_agregado_move_o_mapa_sem_abrir_o_caso(tela, qt):
    """Ponto e agregado reagem ao soltar, e só se o mouse não andou mais que o limiar; um arrasto que começa
    em cima deles move o mapa (com muitos pontos, quase todo arrasto começa em cima de um)."""
    from PySide6.QtCore import QPoint
    mi = _abrir(tela, qt, Nivel.N3, "mapa").mapa
    m = mi.mapa
    recebidas = []
    m.pendencia_escolhida.connect(recebidas.append)
    m.ir_para_brasil()
    qt.processEvents()
    z0 = m.aumento
    ag = max((a for a in m.agregados if m.itemAt(m.mapFromScene(a.scenePos())) is a), key=lambda a: a.n)
    antes = _barras(m)
    _arrastar(m, m.mapFromScene(ag.scenePos()), QPoint(0, 40))
    _esperar_enquadramento(m)                                                      # o clique no agregado anima
    assert m.aumento == pytest.approx(z0) and ag in m.agregados                  # não aproximou
    assert _barras(m) == (antes[0], antes[1] - 40)                                # moveu o mapa
    m.ir_para_uf("SP")
    _esperar_enquadramento(m)
    pt = _ponto_clicavel(m)
    antes = _barras(m)
    _arrastar(m, m.mapFromScene(pt.scenePos()), QPoint(80, 80))
    assert recebidas == [] and not mi.ficha.aberto                                # não abriu o caso
    assert _barras(m) == (antes[0] - 80, antes[1] - 80)


def test_clique_num_ponto_abre_o_caso_ao_soltar_dentro_do_limiar(tela, qt):
    """Apertar não abre nada; soltar a até 4 px do aperto é clique (o mesmo sinal do Enter, a ficha abre);
    soltar além do limiar é arrasto."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    mi = _abrir(tela, qt, Nivel.N3, "mapa").mapa
    m = mi.mapa
    recebidas = []
    m.pendencia_escolhida.connect(recebidas.append)
    m.ir_para_uf("SP")
    _esperar_enquadramento(m)
    pt = _ponto_clicavel(m)
    pos = m.mapFromScene(pt.scenePos())
    QTest.mousePress(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert recebidas == []                                                         # apertar não abre
    QTest.mouseMove(m.viewport(), pos + QPoint(3, 0))
    QTest.mouseRelease(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos + QPoint(3, 0))
    QTest.qWait(400)
    assert recebidas == [pt.pendencia]
    assert mi.ficha.aberto and mi.ficha_titulo.text().startswith(pt.pendencia.codigo)
    pt = _ponto_clicavel(m)
    _arrastar(m, m.mapFromScene(pt.scenePos()), QPoint(6, 0), passos=2)          # além do limiar: arrasto
    assert len(recebidas) == 1


def test_zoom_para_no_limite_em_vez_de_recusar_o_passo(tela, qt):
    """O passo que passaria do limite (0,8 do país inteiro e 400) para exatamente no limite; no limite, mais
    um passo não muda nada. No N2 e no N3 a roda sozinha continua dando zoom (o Ctrl é só do N1)."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    mi = _abrir(tela, qt, Nivel.N3, "mapa").mapa
    m = mi.mapa
    m.ir_para_brasil()
    m.aproximar(1 / 1.15)
    assert m.aumento == pytest.approx(1 / 1.15)
    m.aproximar(1 / 1.15)                                                          # pediria 0,756
    assert m.aumento == pytest.approx(0.8)
    m.aproximar(1 / 1.15)
    assert m.aumento == pytest.approx(0.8)
    for _ in range(30):
        m.aproximar(1.6)
    assert m.aumento == pytest.approx(400)
    m.ir_para_brasil()
    centro = QPointF(m.viewport().rect().center())
    QApplication.sendEvent(m.viewport(), QWheelEvent(
        centro, QPointF(m.viewport().mapToGlobal(centro.toPoint())), QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
    assert m.aumento == pytest.approx(1.25)


@pytest.mark.parametrize("aumento", [1.0, 0.8])
def test_no_zoom_do_pais_ha_folga_para_arrastar_na_horizontal(tela, qt, aumento):
    """A área do mapa tem folga proporcional ao país (não 400 fixos): no país inteiro e no recuo máximo,
    o arrasto horizontal anda o que o mouse andou, para os dois lados."""
    from PySide6.QtCore import QPoint
    mi = _abrir(tela, qt, Nivel.N3, "mapa").mapa
    m = mi.mapa
    m.ir_para_brasil()
    m.aproximar(aumento)
    assert m.aumento == pytest.approx(aumento)
    h = m.horizontalScrollBar()
    assert h.maximum() - h.minimum() > 0
    centro = m.viewport().rect().center()
    antes = _barras(m)
    _arrastar(m, centro, QPoint(150, 0))
    assert _barras(m)[0] == antes[0] - 150
    _arrastar(m, centro, QPoint(-300, 0))
    assert _barras(m)[0] == antes[0] + 150


def test_botao_uf_do_n2_volta_a_uf_do_diretor_e_o_n3_continua_com_brasil(tela, qt):
    """No N2 o botão de vista base é "UF" e leva à UF do diretor (o enquadramento de ir_para_uf, no
    tamanho atual da vista); só a vista muda, o filtro fica. No N3, sem UF própria, o botão continua "Brasil"."""
    pa = _abrir(tela, qt, Nivel.N2, "mapa")
    mi, m = pa.mapa, pa.mapa.mapa
    _esperar_enquadramento(m)
    botoes = _botoes_do_mapa(mi)
    assert set(botoes) == {"−", "+", "UF"} and "SP" in botoes["UF"].toolTip()
    filtro = pa.estado.filtro
    m.ir_para_brasil()
    qt.processEvents()
    botoes["UF"].click()
    _esperar_enquadramento(m)
    visivel = m.mapToScene(m.viewport().rect()).boundingRect()
    assert visivel.contains(m.ufs["SP"].boundingRect()) and m.aumento > 3
    vista = (m.transform().m11(), visivel.center())
    m.ir_para_brasil()
    m.ir_para_uf("SP")
    _esperar_enquadramento(m)
    assert m.transform().m11() == pytest.approx(vista[0], rel=0.01)
    assert (m.mapToScene(m.viewport().rect()).boundingRect().center() - vista[1]).manhattanLength() < 2
    assert pa.estado.filtro == filtro
    tela.encerrar()
    pa = _abrir(tela, qt, Nivel.N3, "mapa")
    m = pa.mapa.mapa
    botoes = _botoes_do_mapa(pa.mapa)
    assert set(botoes) == {"−", "+", "Brasil"}
    m.ir_para_uf("RJ")
    _esperar_enquadramento(m)
    botoes["Brasil"].click()
    assert m.aumento == pytest.approx(1.0, abs=0.05)


LISTAS_DO_MAPA = ("combo_situacao", "combo_uf", "combo_municipio", "combo_classe", "combo_risco", "combo_atividade")
BOTOES_DO_MAPA = ("botao_menos", "botao_mais", "botao_base")


def _faixa_de_listas(mi) -> dict:
    """Retângulo (no mapa interativo) de cada lista e de cada botão da faixa de cima do mapa."""
    from PySide6.QtCore import QPoint, QRect
    return {n: QRect(getattr(mi, n).mapTo(mi, QPoint(0, 0)), getattr(mi, n).size())
            for n in LISTAS_DO_MAPA + BOTOES_DO_MAPA}


def _linhas_da_faixa(g) -> list[int]:
    """Os centros verticais distintos das listas (uma linha = centros a menos de 10 px uns dos outros)."""
    centros = sorted(g[n].center().y() for n in LISTAS_DO_MAPA)
    return [c for i, c in enumerate(centros) if i == 0 or c - centros[i - 1] >= 10]


def _setas_cobertas(mi) -> list[str]:
    """Listas cuja seta (a ponta direita) está debaixo de outro widget: o clique ali não chega à lista."""
    from PySide6.QtCore import QPoint
    cobertas = []
    for n in LISTAS_DO_MAPA:
        c = getattr(mi, n)
        quem = mi.childAt(c.mapTo(mi, QPoint(c.width() - 12, c.height() // 2)))
        if quem is not c and (quem is None or not c.isAncestorOf(quem)):
            cobertas.append(n)
    return cobertas


def _sobrepostos(g) -> list[tuple[str, str]]:
    from itertools import combinations
    return [(a, b) for a, b in combinations(g, 2) if g[a].intersects(g[b])]


@pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
def test_faixa_de_listas_do_mapa_numa_linha_sem_sobreposicao_em_1500(tela, qt, nivel):
    """Em 1500×950 (a resolução de referência), as 6 listas e − + Brasil/UF numa linha só, nenhuma por
    cima da outra, e a seta de cada lista clicável."""
    from PySide6.QtTest import QTest
    mi = _abrir(tela, qt, nivel, "mapa").mapa
    QTest.qWait(100)
    g = _faixa_de_listas(mi)
    assert _sobrepostos(g) == []
    assert _setas_cobertas(mi) == []
    assert len(_linhas_da_faixa(g)) == 1
    assert all(abs(g[b].center().y() - g["combo_situacao"].center().y()) < 10 for b in BOTOES_DO_MAPA)


@pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
def test_faixa_de_listas_do_mapa_quebra_em_duas_linhas_em_1366(tela, qt, nivel):
    """Em 1366×768 as listas não cabem numa linha: quebram em 2 (FlowLayout), sem sobreposição e com as
    setas clicáveis; − + Brasil/UF ficam fixos à direita, na primeira linha."""
    from PySide6.QtTest import QTest
    tela.resize(1366, 768)
    qt.processEvents()
    mi = _abrir(tela, qt, nivel, "mapa").mapa
    QTest.qWait(100)
    g = _faixa_de_listas(mi)
    assert _sobrepostos(g) == []
    assert _setas_cobertas(mi) == []
    assert len(_linhas_da_faixa(g)) == 2
    primeira = g["combo_situacao"].center().y()
    na_primeira = [n for n in LISTAS_DO_MAPA if abs(g[n].center().y() - primeira) < 10]
    for b in BOTOES_DO_MAPA:
        assert abs(g[b].center().y() - primeira) < 10
        assert all(g[b].left() > g[n].right() for n in na_primeira)


def _corte_embaixo(w) -> int:
    """Quantos pixels do fim de w ficam fora de algum widget acima dele (0 = inteiro à vista)."""
    from PySide6.QtCore import QPoint
    corte, pai = 0, w.parentWidget()
    while pai is not None:
        corte = max(corte, w.mapTo(pai, QPoint(0, w.height())).y() - pai.height())
        pai = pai.parentWidget()
    return corte


def _rolagem_da_coluna_n3(mi):
    """A área de rolagem que contém a coluna de camadas do N3 (None se a coluna não estiver numa)."""
    from PySide6.QtWidgets import QAbstractScrollArea
    pai = mi.coluna_n3.parentWidget()
    while pai is not None and pai is not mi:
        if isinstance(pai, QAbstractScrollArea):
            return pai
        pai = pai.parentWidget()
    return None


@pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
@pytest.mark.parametrize("largura, altura", [(1500, 950), (1366, 768)])
def test_mapa_inteiro_a_vista_em_1500_e_em_1366(tela, qt, nivel, largura, altura):
    """Em 1500×950 o mapa continua com pelo menos 380 px; em 1366×768 o espaço do mapa é de 291 px (N2) e
    279 (N3), então o mínimo cai para 270 e o mapa cabe inteiro, sem o fim cortado."""
    from PySide6.QtTest import QTest
    tela.resize(largura, altura)
    qt.processEvents()
    mi = _abrir(tela, qt, nivel, "mapa").mapa
    QTest.qWait(100)
    assert _corte_embaixo(mi.mapa) == 0
    assert mi.mapa.height() >= (380 if largura == 1500 else 270)


@pytest.mark.parametrize("largura, altura, rola", [(1500, 950, False), (1366, 768, False)])
def test_coluna_de_camadas_do_n3_rola_quando_falta_altura(tela, qt, largura, altura, rola):
    """A coluna do N3 fica numa área de rolagem, e o painel de camadas mantém a altura natural (sem espremer os
    textos uns por cima dos outros). Em 1500×950 e em 1366×768, cabe sem rolar."""
    from itertools import combinations
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtTest import QTest
    tela.resize(largura, altura)
    qt.processEvents()
    mi = _abrir(tela, qt, Nivel.N3, "mapa").mapa
    QTest.qWait(100)
    rolagem = _rolagem_da_coluna_n3(mi)
    assert rolagem is not None, "a coluna do N3 não está numa área de rolagem"
    assert (rolagem.verticalScrollBar().maximum() > 0) is rola
    pc = mi.painel_camadas
    assert pc.height() >= pc.sizeHint().height()
    linhas = {c: QRect(l.mapTo(pc, QPoint(0, 0)), l.size()) for c, l in pc.linhas.items()}
    assert [(a, b) for a, b in combinations(linhas, 2) if linhas[a].intersects(linhas[b])] == []
    assert all(l.height() >= l.minimumSizeHint().height() for l in pc.linhas.values())


# 4. nada de "escore", "KPI-0" ou "pendência"
@pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
def test_nenhum_escore_kpi_ou_pendencia_visivel(tela, qt, nivel):
    pa = _abrir(tela, qt, nivel)
    pa.mapa.mostrar_ficha(_escolhas(pa)[sinteticos.AREA])
    textos = []
    for aba in pa.DO_NIVEL[nivel]:
        pa.mostrar(aba)
        qt.processEvents()
        textos += _textos_visiveis(pa.paginas[aba])
    textos += [e.rotulo for e in pa.mapa.mapa.entradas_legenda] + [pa.mapa.texto_ficha()]
    proibidos = [t for t in textos if re.search(r"escore|KPI-0|pend[êe]ncia|PEND[ÊE]NCIA", t or "")]
    assert not proibidos, proibidos[:5]


def test_capturas_n23(tela, qt, tmp_path):
    """Capturas das abas do N2, gravadas na pasta temporária do teste."""
    pa = _abrir(tela, qt, Nivel.N2, "paineis_uf")
    assert pa.paineis_uf.grab().save(str(tmp_path / "paineis_uf.png"))
    tela.encerrar()
    pa = _abrir(tela, qt, Nivel.N3, "orcamento")
    assert pa.orcamento.grab().save(str(tmp_path / "priorizacao.png"))
    assert (tmp_path / "paineis_uf.png").stat().st_size > 10_000
