"""Vocabulário, glossário, situação, remoções no N3 e N1 sem dado financeiro.

  - todo código que aparece no acervo tem rótulo de exibição; nenhum "escore" no código-fonte; nenhum "KPI-0"
    como título visível (só na dica);
  - situação Ativos / Encerrados / Todos, padrão Todos, com rótulo de campo e dica, no mapa e na planilha; as
    contagens "dentro · fora" continuam coerentes; os KPIs e o resumo continuam sobre os ativos;
  - o N3 sem "Painéis temáticos" e sem "Evolução";
  - aba Glossário nos três níveis, só com definições (nenhum dado do acervo);
  - nenhum "R$" no N1 (tela, dicas, resumo, exportação e relatórios A1); o serviço recusa o painel de custo e
    omite o KPI-05 no N1, com a recusa na trilha.
"""
import csv
import re
from datetime import datetime
from pathlib import Path

import pytest

from ecosec.acervo import fase, regras, sinteticos, vocabulario
from ecosec.acervo.filtro import SITUACOES, Filtro
from ecosec.acervo.geracao.ciclo import CICLOS, SITUACAO_DA_ETAPA
from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.servicos.acervo import ErroAcervo, ServicoAcervo
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
HOJE = sinteticos.DATA_BASE
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
USUARIOS = {Nivel.N1: ANA_N1, Nivel.N2: BIA_N2, Nivel.N3: CAIO_N3}
RAIZ = Path(__file__).resolve().parents[1]
TRAVESSAO = re.compile("[–—]")
DINHEIRO = re.compile(r"R\$")


@pytest.fixture(scope="module")
def acervo():
    trilha = ServicoTrilha(RepositorioTrilhaMemoria())
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), trilha, b"chave-teste",
                                            relogio=lambda: datetime(2026, 10, 1, 10, 0))
    servico.data_referencia = HOJE
    return servico


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


def _fora_do_glossario(raiz, classe) -> list:
    """Os widgets da classe, menos os da aba Glossário (que é o lugar dos códigos e das normas, por desenho)."""
    from ecosec.interface.glossario import PainelGlossario
    resultado = []
    for w in raiz.findChildren(classe):
        pai = w
        while pai is not None and not isinstance(pai, PainelGlossario):
            pai = pai.parentWidget()
        if pai is None:
            resultado.append(w)
    return resultado


def _textos_visiveis(raiz) -> list[str]:
    """Texto que a pessoa LÊ (sem dica): rótulos, botões, itens de combo, títulos e eixos e séries dos gráficos."""
    from PySide6.QtCharts import QChartView
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel
    textos = []
    for w in _fora_do_glossario(raiz, QLabel):
        textos.append(w.text())
    for w in _fora_do_glossario(raiz, QAbstractButton):
        textos.append(w.text())
    for w in _fora_do_glossario(raiz, QComboBox):
        textos += [w.itemText(i) for i in range(w.count())]
    for v in _fora_do_glossario(raiz, QChartView):
        ch = v.chart()
        textos.append(ch.title())
        textos += [e.titleText() for e in ch.axes()]
        textos += [s.name() for s in ch.series()]
        for s in ch.series():
            for nome in ("barSets",):
                if hasattr(s, nome):
                    textos += [b.label() for b in getattr(s, nome)()]
    return textos


def _dicas(raiz) -> list[str]:
    from PySide6.QtWidgets import QWidget
    return [w.toolTip() for w in _fora_do_glossario(raiz, QWidget) if w.toolTip()] + [raiz.toolTip()]


# vocabulário
def test_todo_codigo_do_acervo_tem_rotulo(acervo):
    pendencias = list(acervo.repo.pendencias())
    esperado = {
        "classe": {p.classe_risco for p in pendencias},
        "motivo": {p.motivo for p in pendencias} | {m.codigo for m in acervo.repo.motivos()},
        "atividade": {p.atividade for p in pendencias} | {a.codigo for a in acervo.repo.atividades()},
        "etapa": {e for etapas, _, _ in CICLOS.values() for e in etapas} | {p.etapa_atual for p in pendencias},
        "situacao_caso": {p.situacao for p in pendencias} | set(SITUACAO_DA_ETAPA.values()) | {"EM PROCESSO"}
                         | {c[2] for c in CICLOS.values()},
        "fase": set(fase.FASES),
        "faixa": set(regras.CATEGORIAS),
        "acao": set(regras.ACOES),
        "responsabilidade": {regras.responsabilidade(p) for p in pendencias} | set(regras.RESPONSABILIDADE_GRUPO.values()),
        "situacao": set(SITUACOES),
        "kpi": {"KPI-01", "KPI-02", "KPI-03", "KPI-03b", "KPI-04", "KPI-05"},
        "nivel": {"N1", "N2", "N3"},
    }
    for tipo, codigos in esperado.items():
        faltando = {c for c in codigos if vocabulario.termo(c, tipo) is None}
        assert not faltando, (tipo, faltando)
    # os KPIs que o serviço devolve têm o nome do vocabulário (o código fica só na dica)
    for kpi in acervo.kpis(CAIO_N3, 3):
        assert kpi.nome == vocabulario.rotulo(kpi.id, "kpi") and "KPI" not in kpi.nome


def test_rotulos_unicos_definidos_e_sem_travessao():
    por_tipo = {}
    for t in vocabulario.TODOS_OS_TERMOS:
        assert t.rotulo and t.definicao, t
        assert t.tipo in vocabulario.TIPOS
        por_tipo.setdefault(t.tipo, []).append(t.rotulo)
        for texto in (t.rotulo, t.longo, t.definicao, t.formula, t.unidade, t.referencia):
            assert not TRAVESSAO.search(texto), t
            assert "escore" not in texto.lower(), t
        assert vocabulario.codigo(t.rotulo, t.tipo) == t.codigo         # o combo volta ao código
    for tipo, rotulos in por_tipo.items():
        assert len(rotulos) == len(set(rotulos)), tipo
    # os nomes de exibição esperados
    assert vocabulario.rotulo(sinteticos.CLASSE_I) == "Resíduo perigoso"
    assert vocabulario.rotulo("KPI-03") == "Casos além do prazo legal"
    assert vocabulario.rotulo("SCORE", "risco") == "Score de risco"
    assert [vocabulario.ROTULO_SITUACAO[s] for s in SITUACOES] == ["Ativos", "Encerrados", "Todos"]
    # a dica leva a definição, a conta e o código; o rótulo não leva o código
    dica = vocabulario.dica("KPI-03")
    assert "KPI-03" in dica and "÷" in dica and "KPI" not in vocabulario.rotulo("KPI-03")
    assert "NBR 10.004" in vocabulario.dica(sinteticos.CLASSE_I)
    assert vocabulario.rotulo("XYZ-99") == "XYZ-99"                      # desconhecido: nunca erro na tela


def test_nenhum_escore_no_codigo_fonte():
    achados = []
    for arquivo in (RAIZ / "ecosec").rglob("*.py"):
        if arquivo.name == "vocabulario.py":                             # a regra escrita: "score", não "escore"
            continue
        for i, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
            if "escore" in linha.lower():
                achados.append(f"{arquivo.name}:{i}")
    assert not achados


def test_glossario_tem_as_secoes_pedidas_e_a_busca_ignora_acento():
    titulos = vocabulario.SECOES_GLOSSARIO
    for pedida in ("Classes", "Situação", "Risco e score", "Indicadores (KPIs)", "Fases e etapas",
                   "Responsabilidade financeira", "Motivos", "Atividades", "Campos da ficha", "Prazos",
                   "Níveis de acesso e sigilo"):
        assert pedida in titulos
    assert sum(len(s.termos) for s in vocabulario.glossario()) == len(vocabulario.TODOS_OS_TERMOS)
    achados = [t.rotulo for s in vocabulario.buscar("residuo perigoso") for t in s.termos]
    assert "Resíduo perigoso" in achados
    assert any(t.codigo == "KPI-03" for s in vocabulario.buscar("kpi-03") for t in s.termos)
    assert vocabulario.buscar("zzzz inexistente") == []


# N1 sem dado financeiro (serviço)
def test_servico_n1_sem_custo_e_recusa_registrada(acervo):
    with pytest.raises(ErroAcervo):
        acervo.painel_custo(ANA_N1, 1)
    registro = acervo.trilha.recentes(1)[0].evento
    assert registro.resultado == "NEGADO" and registro.motivo == "CUSTO_NO_NIVEL_1"
    assert [k.id for k in acervo.kpis(ANA_N1, 1)] == ["KPI-01", "KPI-02", "KPI-03", "KPI-03b", "KPI-04"]
    assert "KPI-05" in [k.id for k in acervo.kpis(BIA_N2, 2)]
    assert all(item.custo is None for item in acervo.panorama(ANA_N1, 1).pressao.values())
    assert all(item.custo is not None for item in acervo.panorama(CAIO_N3, 3).pressao.values())
    resumo = acervo.resumo_agregado(ANA_N1, 1)
    for titulos, linhas in resumo.tabelas.values():
        assert "CUSTO ESTIMADO" not in titulos
    assert "CUSTO ESTIMADO" in acervo.resumo_agregado(BIA_N2, 2).tabelas["POR UF"][0]


def test_exportacao_do_resumo_n1_sem_custo(acervo, tmp_path):
    resumo = acervo.resumo_agregado(ANA_N1, 1)
    for agrupamento in resumo.tabelas:
        destino = tmp_path / f"{agrupamento.replace(' ', '_')}.csv"
        acervo.exportar_resumo(resumo, ANA_N1, agrupamento, destino)
        conteudo = destino.read_text(encoding="utf-8-sig")
        titulos = next(csv.reader(conteudo.splitlines(), delimiter=";"))
        assert titulos == list(resumo.tabelas[agrupamento][0]) and "CUSTO ESTIMADO" not in titulos, agrupamento
        assert not DINHEIRO.search(conteudo), agrupamento


def test_relatorios_a1_sem_reais(acervo, monkeypatch):
    from ecosec.acervo import desenho
    escritos = []
    original = desenho.Tela.texto

    def capturar(self, x, y, conteudo, *args, **kwargs):
        escritos.append(str(conteudo))
        return original(self, x, y, conteudo, *args, **kwargs)
    monkeypatch.setattr(desenho.Tela, "texto", capturar)
    codigos = [r.codigo for r in acervo.catalogo(1)]
    assert codigos and all(c.startswith("A1") for c in codigos)
    for codigo in codigos:
        acervo.abrir(codigo, ANA_N1, 1)
    assert escritos and not [t for t in escritos if DINHEIRO.search(t) or "custo estimado" in t.lower()]
    assert not [t for t in escritos if "KPI-0" in t or "NBR 10004" in t]


# abas e glossário (tela)
@pytest.mark.parametrize("nivel, abas", [
    (Nivel.N1, ["panorama", "agregado", "glossario"]),
    (Nivel.N2, ["mapa", "paineis_uf", "planilha", "agregado", "glossario"]),
    (Nivel.N3, ["mapa", "orcamento", "responsaveis", "planilha", "agregado", "glossario"])])
def test_abas_por_nivel_com_glossario_e_sem_paineis_e_evolucao_no_n3(tela, qt, nivel, abas):
    pa = _abrir(tela, qt, nivel)
    assert list(pa.abas.items) == abas
    assert "evolucao" not in pa.paginas and not hasattr(pa, "evolucao")
    if nivel is Nivel.N3:
        pa.mostrar("panorama")                                            # seção que o N3 não tem: não abre
        assert pa.pilha.currentWidget() is not pa.paginas["panorama"].property("cartao")


@pytest.mark.parametrize("nivel", [Nivel.N1, Nivel.N2, Nivel.N3])
def test_glossario_em_todo_nivel_so_com_definicoes(tela, qt, nivel):
    pa = _abrir(tela, qt, nivel, "glossario")
    g = pa.glossario
    assert pa.pilha.currentWidget() is g.property("cartao")
    assert not pa.barra.isVisible()                                      # não segue o filtro: não tem dado
    # O termo de nível é só o da própria camada; os das outras duas nem são citados
    assert len(g.termos_visiveis()) == len(vocabulario.TODOS_OS_TERMOS) - 2
    assert {t.codigo for t in g.termos_visiveis() if t.tipo == "nivel"} == {f"N{nivel.value}"}
    textos = " ".join(g.textos())
    assert "Resíduo perigoso" in textos and "NBR 10.004" in textos and "Casos além do prazo legal" in textos
    # nenhum dado do acervo: código de caso, município, nome de responsável, valor em reais
    pendencias = tela.app.acervo.repo.pendencias()
    assert not re.search(r"PD-\d{4}", textos) and not DINHEIRO.search(textos)
    municipios = {p.municipio for p in pendencias if len(p.municipio) > 6}
    assert not [m for m in municipios if m in textos.upper()]
    g.busca.setText("classe i")
    qt.processEvents()
    visiveis = g.termos_visiveis()
    assert visiveis and any(t.codigo == sinteticos.CLASSE_I for t in visiveis)
    assert len(visiveis) < len(vocabulario.TODOS_OS_TERMOS)
    g.busca.setText("zzzz inexistente")
    assert g.termos_visiveis() == [] and not g.vazio.isHidden()
    g.busca.setText("")
    assert len(g.termos_visiveis()) == len(vocabulario.TODOS_OS_TERMOS) - 2     # Só o nível da camada


# situação
@pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
def test_situacao_abre_em_todos_no_mapa_e_na_planilha(tela, qt, nivel):
    assert Filtro().situacao == "TODAS" and Filtro().vazio()
    pa = _abrir(tela, qt, nivel, "planilha")
    painel = pa.painel
    for combo in (pa.planilha.combo_situacao, pa.mapa.combo_situacao):
        assert [combo.itemText(i) for i in range(combo.count())] == ["Ativos", "Encerrados", "Todos"]
        assert combo.currentText() == "Todos"
        assert "Ativos:" in combo.toolTip() and "Encerrados:" in combo.toolTip()
    assert "Situação do caso" in _textos_visiveis(pa.planilha) and "Situação do caso" in _textos_visiveis(pa.mapa)
    todos = {p.codigo for p in painel.pendencias if p.data_identificacao <= painel.hoje}
    assert {l.CODIGO for l in pa.planilha.modelo.todas} == todos
    assert pa.mapa.mapa.contagens["total"] >= 0
    assert pa.mapa.contagem.text().startswith(vocabulario.casos(len(todos)))
    assert "casos ativos e encerrados" in pa.barra.contagem.text()
    # o cabeçalho continua o estoque ativo (os KPIs são sobre os ativos)
    ativas = sum(p.ativa(painel.hoje) for p in painel.pendencias)
    assert pa.titulo.text().startswith(f"Casos ativos em {painel.hoje:%d/%m/%Y}: {ativas:,}".replace(",", "."))
    # Ativos: chip com o rótulo do campo, e a contagem dentro · fora no universo dos ativos
    pa.planilha.combo_situacao.setCurrentIndex(0)
    qt.processEvents()
    assert pa.estado.filtro.situacao == "ATIVAS" and pa.mapa.combo_situacao.currentText() == "Ativos"
    assert [c.rotulo for c in pa.barra.chips] == ["Situação do caso: Ativos"]
    assert {l.CODIGO for l in pa.planilha.modelo.todas} == {p.codigo for p in painel.pendencias
                                                            if p.ativa(painel.hoje)}
    assert pa.barra.contagem.text().startswith(f"{ativas:,} dentro · 0 fora (de {ativas:,} casos ativos".replace(",", "."))
    # o mapa e a planilha mostram o mesmo recorte; Limpar volta ao padrão Todos
    pa.estado.limpar()
    qt.processEvents()
    assert pa.planilha.combo_situacao.currentText() == pa.mapa.combo_situacao.currentText() == "Todos"


def test_dentro_e_fora_coerentes_em_cada_situacao(tela, qt):
    pa = _abrir(tela, qt, Nivel.N3, "planilha")
    for situacao in SITUACOES:
        pa.estado.definir(situacao=situacao, ufs={"SP"})
        qt.processEvents()
        texto = pa.barra.contagem.text()
        dentro, fora, universo = (int(x.replace(".", "")) for x in re.findall(r"[\d.]+(?= dentro| fora|\s+casos)",
                                                                                  texto)[:3])
        assert dentro + fora == universo
        assert dentro == len(pa.planilha.modelo.todas)
        assert vocabulario.FRASE_SITUACAO[situacao] in texto


def test_resumo_continua_sobre_os_ativos_com_todos(tela, qt):
    from ecosec.interface.painel_analitico import filtro_do_resumo
    assert filtro_do_resumo(Filtro()) is None
    assert filtro_do_resumo(Filtro(ufs={"SP"})) == Filtro(ufs={"SP"}, situacao="ATIVAS")
    assert filtro_do_resumo(Filtro(situacao="ENCERRADAS")).situacao == "ENCERRADAS"
    pa = _abrir(tela, qt, Nivel.N3, "agregado")
    ativas = sum(p.ativa(pa.painel.hoje) for p in pa.painel.pendencias)
    titulos, linhas = pa.agregado.resumo.tabelas["POR UF"]
    assert sum(l[titulos.index("PENDENCIAS")] for l in linhas) == ativas
    assert "ativos" in pa.agregado.aviso_filtro.text()


# rótulos na tela e N1 sem R$
def test_combos_mostram_rotulos_e_filtram_pelo_codigo(tela, qt):
    pa = _abrir(tela, qt, Nivel.N3, "planilha")
    pl = pa.planilha
    itens = [pl.combo_classe.itemText(i) for i in range(pl.combo_classe.count())]
    assert itens[1:] == ["Área contaminada", "Resíduo perigoso", "Material radioativo"]
    pl.combo_classe.setCurrentText("Material radioativo")
    qt.processEvents()
    assert pa.estado.filtro.classes == {sinteticos.RADIOATIVO}
    assert pa.mapa.combo_classe.currentText() == "Material radioativo"
    assert "Classe: Material radioativo" in [c.rotulo for c in pa.barra.chips]
    # a célula mostra o rótulo; o título da coluna também; a exportação continua com o valor cru
    modelo = pl.modelo
    j = modelo.titulos.index("CLASSE DE RISCO")
    assert modelo.texto(modelo.todas[0], j) == "Material radioativo"
    from PySide6.QtCore import Qt
    assert "score de risco" in modelo.data(modelo.index(0, modelo.titulos.index("NIVEL DE RISCO")), Qt.ItemDataRole.ToolTipRole)  # Na dica da faixa
    assert getattr(modelo.todas[0], "CLASSE_DE_RISCO") == sinteticos.RADIOATIVO


def test_nenhum_kpi_como_titulo_visivel(tela, qt):
    pa = _abrir(tela, qt, Nivel.N1)
    pn = pa.panorama
    desenhados = []                                 # Os gráficos do N1 desenham o próprio texto
    for chave in pn.secoes:
        pn.mostrar_secao(chave)
        qt.processEvents()
        for grafico in pn.secoes[chave].graficos():
            if hasattr(grafico, "preparar"):
                grafico.preparar()
                desenhados += grafico.textos()
    visiveis = _textos_visiveis(pa) + desenhados
    assert not [t for t in visiveis if "KPI-0" in t or "NBR 10004" in t]
    assert any("KPI-03" in d for d in _dicas(pa))                       # o código continua na dica
    assert {c.nome.text() for c in pn.cartoes.values() if c.id.startswith("KPI")} == {
        vocabulario.rotulo(k) for k in ("KPI-01", "KPI-02", "KPI-03", "KPI-03b", "KPI-04")}
    tela.encerrar()
    pa = _abrir(tela, qt, Nivel.N2, "paineis_uf")
    for chave in pa.paineis_uf.paineis:
        pa.paineis_uf.mostrar_painel(chave)
        qt.processEvents()
    assert not [t for t in _textos_visiveis(pa) if "KPI-0" in t or "NBR 10004" in t]


def test_n1_sem_reais_em_tela_dica_e_resumo(tela, qt):
    pa = _abrir(tela, qt, Nivel.N1)
    pn = pa.panorama
    assert "KPI-05" not in pn.cartoes                                     # Faixa do painel novo
    for chave in pn.secoes:
        pn.mostrar_secao(chave)
        qt.processEvents()
    for i in range(pn.combo_indicador.count()):                           # todos os indicadores do mapa
        pn.combo_indicador.setCurrentIndex(i)
        qt.processEvents()
        desenhados = []
        for grafico in pn.graficos():
            if hasattr(grafico, "preparar"):
                grafico.preparar()
                desenhados += grafico.textos() + grafico.dicas()
        assert not [t for t in _textos_visiveis(pa) + _dicas(pa) + desenhados if DINHEIRO.search(t)]
        dicas_uf = [regiao.toolTip() for regiao in pn.mapa.ufs.values()]
        assert dicas_uf and all(dicas_uf) and not [d for d in dicas_uf if DINHEIRO.search(d)]
    pa.mostrar("agregado")
    for i in range(pa.agregado.combo.count()):
        pa.agregado.combo.setCurrentIndex(i)
        qt.processEvents()
        modelo = pa.agregado.modelo
        from PySide6.QtCore import Qt
        textos = [str(modelo.headerData(j, Qt.Orientation.Horizontal)) for j in range(modelo.columnCount())]
        textos += [modelo.texto(l, j) for l in modelo.todas for j in range(modelo.columnCount())]
        assert not [t for t in textos if DINHEIRO.search(t)] and "CUSTO ESTIMADO" not in modelo.titulos
