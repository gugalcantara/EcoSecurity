"""Resumo agregado e relatórios.

"vencida" são dois indicadores: FORA DA PREVISAO e ALEM DO PRAZO LIMITE, cada um com o seu
      percentual; a supressão do N1 trata o percentual novo como derivado da sua subcontagem.
formatador único de exibição por tipo de coluna; a exportação continua crua.
relatórios do N1 (A1-01, A1-02, A1-05) com os totais já suprimidos do resumo (k=3 com complementar).
A3-01: as quatro partes do custo fecham com o total.
"pendências ativas" (não "cadastradas"); KPI-03 ao lado do cartão fora da previsão.
atraso em anos com uma casa.
N2: o combo do resumo não oferece por UF nem por regiao; cabeçalho inteiro.
"""
import csv
import re
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from ecosec.acervo import analise, formatos, regras, relatorios, sinteticos, vocabulario
from ecosec.acervo.desenho import Fontes, Tela
from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.servicos.acervo import ServicoAcervo
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
HOJE = sinteticos.DATA_BASE
K = int(CFG["indice_pressao.supressao_minima"])
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
ATIVIDADES = {a.codigo: a for a in sinteticos.ATIVIDADES}
MOTIVOS = {m.codigo: m for m in sinteticos.MOTIVOS}
FONTES = Fontes.de_configuracao(CFG)
CATALOGO = {i.codigo: i for i in sinteticos.CATALOGO}


@pytest.fixture(scope="module")
def acervo():
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), ServicoTrilha(RepositorioTrilhaMemoria()),
                                            b"chave-teste", relogio=lambda: datetime(2026, 10, 1, 10, 0))
    servico.data_referencia = HOJE
    return servico


@pytest.fixture(scope="module")
def ativas(acervo):
    return regras.ativas(acervo.repo.pendencias(), HOJE)


def _dados(pendencias, nivel, k=K):
    return relatorios.DadosRelatorio(tuple(pendencias), None if nivel == 1 else {}, ATIVIDADES, MOTIVOS, HOJE,
                                     "Nacional", datetime(2026, 10, 1, 10, 0), nivel=nivel, supressao_minima=k)


def _textos(monkeypatch, codigo, dados) -> list[str]:
    """Todo texto desenhado no relatório (o desenho é imagem: o teste escuta a Tela)."""
    desenhados = []
    original = Tela.texto

    def escutar(self, x, y, conteudo, *args, **kwargs):
        desenhados.append(str(conteudo))
        return original(self, x, y, conteudo, *args, **kwargs)
    monkeypatch.setattr(Tela, "texto", escutar)
    relatorios.gerar(CATALOGO[codigo], dados, FONTES)
    return desenhados


def _celulas(titulos, linhas, coluna):
    n = list(titulos).index("PENDENCIAS")
    return {tuple(l[:n]): l[list(titulos).index(coluna)] for l in linhas}


# ================================================================ os dois indicadores, com nomes distintos
def test_titulos_do_resumo_seguem_a_ata_3():
    assert "VENCIDAS" not in analise.TITULOS_MEDIDAS
    assert not any("VENCIDA" in t for t in analise.TITULOS_MEDIDAS)
    assert {"FORA DA PREVISAO", "PERCENTUAL FORA DA PREVISAO", "ATRASO MEDIO FORA DA PREVISAO (DIAS)",
            "ALEM DO PRAZO LIMITE", "PERCENTUAL ALEM DO PRAZO LIMITE"} <= set(analise.TITULOS_MEDIDAS)
    i = analise.TITULOS_MEDIDAS.index
    assert i("PERCENTUAL ALEM DO PRAZO LIMITE") == i("ALEM DO PRAZO LIMITE") + 1      # lado a lado


def test_valores_do_resumo_batem_com_o_calculo_direto(ativas, acervo):
    titulos, linhas = analise.agregar(ativas, HOJE, "POR UF", ATIVIDADES, MOTIVOS, acervo.regras)
    r = acervo.regras
    for linha in linhas:
        uf = linha[0]
        ps = [p for p in ativas if p.uf == uf]
        fora = [p for p in ps if p.prazo_coleta < HOJE]
        alem = sum(regras.dias_alem_do_prazo_limite(p, HOJE, r) > 0 for p in ps)
        valor = dict(zip(titulos, linha))
        assert valor["PENDENCIAS"] == len(ps)
        assert valor["FORA DA PREVISAO"] == len(fora)
        assert valor["PERCENTUAL FORA DA PREVISAO"] == round(100 * len(fora) / len(ps), 1)
        assert valor["ATRASO MEDIO FORA DA PREVISAO (DIAS)"] == (
            round(sum(p.dias_de_atraso(HOJE) for p in fora) / len(fora)) if fora else 0)
        assert valor["ALEM DO PRAZO LIMITE"] == alem
        assert valor["PERCENTUAL ALEM DO PRAZO LIMITE"] == round(100 * alem / len(ps), 1)


# ================================================================ formatador único (só exibição)
def test_formatador_por_tipo_de_coluna():
    assert formatos.exibir("CUSTO ESTIMADO", 1_958_612_345.0) == "R$ 1.958,6 mi"
    assert formatos.exibir("CUSTO ESTIMADO", 20_000.0).startswith("< R$")             # pequeno não vira zero
    assert formatos.exibir("CUSTO ESTIMADO", 365_800.0, planilha=True) == "R$ 365.800"
    assert formatos.exibir("PERCENTUAL FORA DA PREVISAO", 81.2) == "81,2%"
    assert formatos.exibir("PERCENTUAL ALEM DO PRAZO LIMITE", 100.0).endswith("%")
    assert formatos.exibir("PENDENCIAS", 1055) == "1.055"
    assert formatos.exibir("ATRASO MEDIO FORA DA PREVISAO (DIAS)", 4026) == "4.026"
    assert formatos.exibir("TONELADAS CLASSE I", 106165.84) == "106.165,8 t"
    assert formatos.exibir("M3 REJEITO RADIOATIVO", 0.17) == "0,2 m³"
    assert formatos.exibir("PENDENCIAS", analise.SUPRIMIDO) == analise.SUPRIMIDO
    assert formatos.anos(3981) == "10,9 anos"


def test_resumo_exibido_formatado_e_suprimido_intacto(acervo, ativas):
    titulos, linhas = acervo.resumo_agregado(ANA_N1, 1).tabelas["POR UF"]
    titulos_classe, linhas_classe = acervo.resumo_agregado(CAIO_N3, 3).tabelas["POR CLASSE DE RISCO"]
    for t, ls in ((titulos, linhas), (titulos_classe, linhas_classe)):
        for linha in ls:
            textos = {titulo: formatos.celula(t, lambda k: linha[k], j) for j, titulo in enumerate(t)}
            for titulo, texto in textos.items():
                assert "—" not in texto and "–" not in texto
                if linha[t.index(titulo)] == analise.SUPRIMIDO:
                    assert texto == analise.SUPRIMIDO
            if "CUSTO ESTIMADO" in textos and textos["CUSTO ESTIMADO"] != analise.SUPRIMIDO:   # N1: sem custo
                assert textos["CUSTO ESTIMADO"].startswith("R$")
            for coluna in ("PERCENTUAL FORA DA PREVISAO", "PERCENTUAL ALEM DO PRAZO LIMITE"):
                assert textos[coluna] == analise.SUPRIMIDO or textos[coluna].endswith("%")
    # a unidade que não se aplica à linha da classe sai "não se aplica", e não 0 nem travessão
    area = next(l for l in linhas_classe if l[0] == sinteticos.AREA)
    j = titulos_classe.index("TONELADAS CLASSE I")
    assert formatos.celula(titulos_classe, lambda k: area[k], j) == formatos.NAO_SE_APLICA
    j = titulos_classe.index("M3 SOLO AREA CONTAMINADA")
    assert formatos.celula(titulos_classe, lambda k: area[k], j).endswith(" m³")
    titulos_n3, linhas_n3 = acervo.resumo_agregado(CAIO_N3, 3).tabelas["POR UF"]
    total = sum(l[titulos_n3.index("PENDENCIAS")] for l in linhas_n3)
    assert total == len(ativas) and formatos.inteiro(total) == "1.028"                  # Era 1.055


def test_modelo_da_tabela_exibe_formatado_e_ordena_pelo_numero(qt, acervo):
    from PySide6.QtCore import Qt
    from ecosec.interface.painel_analitico import ModeloTabela
    titulos, linhas = acervo.resumo_agregado(CAIO_N3, 3).tabelas["POR UF"]
    modelo = ModeloTabela()
    modelo.definir(linhas, titulos)
    sp = next(i for i, l in enumerate(modelo.todas) if l[0] == "SP")
    exibido = {t: modelo.data(modelo.index(sp, j)) for j, t in enumerate(titulos)}
    assert exibido["CUSTO ESTIMADO"].startswith("R$ ") and exibido["CUSTO ESTIMADO"].endswith(" mi")
    assert exibido["PERCENTUAL FORA DA PREVISAO"].endswith("%")
    assert re.fullmatch(r"\d{1,3}(\.\d{3})*", exibido["ATRASO MEDIO FORA DA PREVISAO (DIAS)"])
    modelo.sort(titulos.index("CUSTO ESTIMADO"), Qt.SortOrder.DescendingOrder)
    custos = [l[titulos.index("CUSTO ESTIMADO")] for l in modelo.todas]
    assert custos == sorted(custos, reverse=True)                      # ordena pelo número, não pelo texto


def test_exportacao_do_resumo_continua_com_numeros_crus(acervo, tmp_path):
    resumo = acervo.resumo_agregado(ANA_N1, 1)
    destino = tmp_path / "resumo.csv"
    acervo.exportar_resumo(resumo, ANA_N1, "POR UF", destino)
    leitor = list(csv.reader(destino.read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))
    titulos, linhas = leitor[0], leitor[1:]
    assert titulos == list(resumo.tabelas["POR UF"][0])                     # os títulos novos
    for linha in linhas:
        for titulo, valor in zip(titulos[1:], linha[1:]):
            assert valor == analise.SUPRIMIDO or float(valor) is not None, (titulo, valor)
            assert "R$" not in valor and "%" not in valor and "mi" not in valor


# ================================================================ a supressão do N1 com as colunas novas
def test_resumo_n1_novas_colunas_nao_revelam_subcontagem(acervo):
    for agrupamento, (titulos, linhas) in acervo.resumo_agregado(ANA_N1, 1).tabelas.items():
        totais = _celulas(titulos, linhas, "PENDENCIAS")
        for coluna, derivadas in analise.SUBCONTAGENS.items():
            parte = _celulas(titulos, linhas, coluna)
            for chave, v in parte.items():
                if v != analise.SUPRIMIDO:
                    assert not (0 < v < K or 0 < totais[chave] - v < K), (agrupamento, chave, coluna)
            for derivada in derivadas:
                for chave, v in _celulas(titulos, linhas, derivada).items():
                    assert (v == analise.SUPRIMIDO) == (parte[chave] == analise.SUPRIMIDO), (agrupamento, derivada)
                    if derivada.startswith("PERCENTUAL") and v != analise.SUPRIMIDO:
                        # o percentual visível só reconstrói uma subcontagem que já é visível
                        assert round(v * totais[chave] / 100) == parte[chave], (agrupamento, chave, derivada)


def test_percentual_alem_do_prazo_cai_junto_com_a_subcontagem_pequena(acervo):
    base = next(p for p in acervo.repo.pendencias() if p.ativa(HOJE))
    novo, antigo = HOJE - timedelta(days=30), HOJE - timedelta(days=40 * 365)   # dentro e além do prazo-limite
    montado = []
    for uf, recentes, velhas in (("SP", 9, 1), ("RJ", 5, 5), ("MG", 4, 6), ("ES", 6, 4)):
        for i in range(recentes + velhas):
            ident = novo if i < recentes else antigo
            montado.append(replace(base, codigo=f"{uf}{i}", uf=uf, data_encerramento=None, data_identificacao=ident,
                                   prazo_coleta=ident + timedelta(days=10)))
    original = acervo.repo._pendencias
    acervo.repo._pendencias = montado
    try:
        titulos, linhas = acervo.resumo_agregado(ANA_N1, 1).tabelas["POR UF"]
    finally:
        acervo.repo._pendencias = original
    alem = _celulas(titulos, linhas, "ALEM DO PRAZO LIMITE")
    pct = _celulas(titulos, linhas, "PERCENTUAL ALEM DO PRAZO LIMITE")
    assert alem[("SP",)] == analise.SUPRIMIDO and pct[("SP",)] == analise.SUPRIMIDO     # 1 de 10
    assert sum(v == analise.SUPRIMIDO for v in alem.values()) >= 2                      # e a complementar
    assert all((pct[c] == analise.SUPRIMIDO) == (v == analise.SUPRIMIDO) for c, v in alem.items())


# ================================================================ relatórios do N1 com os totais suprimidos
@pytest.fixture(scope="module")
def acervo_a_mao(ativas):
    """SP e RJ com 10 pendências de AG-01; MG com 2 de AG-02: MG e AG-02 têm de sair SUPRIMIDO no N1."""
    base = ativas[0]
    montado = []
    for uf, n, atividade in (("SP", 10, "AG-01"), ("RJ", 10, "AG-01"), ("MG", 2, "AG-02")):
        for i in range(n):
            montado.append(replace(base, codigo=f"{uf}{i:02d}", uf=uf, atividade=atividade, data_encerramento=None,
                                   data_identificacao=HOJE - timedelta(days=30)))
    return montado


@pytest.mark.parametrize("codigo", ["A1-01", "A1-02", "A1-05"])
def test_relatorio_do_n1_mostra_suprimido_para_grupo_pequeno(monkeypatch, acervo_a_mao, codigo):
    textos = _textos(monkeypatch, codigo, _dados(acervo_a_mao, nivel=1))
    assert analise.SUPRIMIDO in textos
    # nem o número (barra "2  (9,1%)", bolha "MG 2") nem um percentual que o revele
    assert "MG 2" not in textos and not any(t.startswith("2  (") for t in textos)
    assert not any("9,1%" in t for t in textos)


def test_mesmo_acervo_no_n3_mostra_os_numeros(monkeypatch, acervo_a_mao):
    textos = _textos(monkeypatch, "A1-05", _dados(acervo_a_mao, nivel=3))
    assert analise.SUPRIMIDO not in textos
    assert any(t.startswith("2  (") for t in textos)


def test_relatorio_n1_usa_as_mesmas_celulas_do_resumo(monkeypatch, acervo, ativas):
    """No acervo real, o POR UF do A1-01 e o do resumo do N1 escondem as mesmas UFs (hoje, nenhuma)."""
    titulos, linhas = acervo.resumo_agregado(ANA_N1, 1).tabelas["POR UF"]
    resumo = {l[0]: l[titulos.index("PENDENCIAS")] for l in linhas}
    dados = _dados(ativas, nivel=1)
    assert relatorios._coluna(relatorios._tabela_do_resumo(dados, "POR UF")) == resumo


# ================================================================
def test_a3_01_partes_do_custo_fecham_com_o_total(monkeypatch, ativas, acervo):
    dados = replace(_dados(ativas, nivel=3), regras=acervo.regras)
    total, partes = relatorios.custos_por_responsabilidade(ativas, dados)
    # O rótulo das partes vem do vocabulário ("Fiscalização e rastreio")
    assert len(partes) == 4 and any("fiscalização" in r.lower() for r, _ in partes)
    assert sum(v for _, v in partes) == pytest.approx(total, abs=0.1)
    (_, texto_total), cartoes = relatorios.cartoes_de_custo(ativas, dados)

    def mi(texto):
        return float(texto.removeprefix("R$ ").removesuffix(" mi").replace(".", "").replace(",", "."))
    assert sum(mi(v) for _, v in cartoes) == pytest.approx(mi(texto_total), abs=0.1)
    textos = _textos(monkeypatch, "A3-01", dados)
    assert texto_total in textos and all(v in textos for _, v in cartoes)


@pytest.mark.parametrize("codigo, nivel", [("A1-01", 1), ("A3-01", 3), ("A2-01", 3)])
def test_textos_dizem_ativas_e_nao_cadastradas(monkeypatch, ativas, codigo, nivel):
    textos = _textos(monkeypatch, codigo, _dados(ativas, nivel=nivel))
    assert not any("cadastrada" in t for t in textos)
    if codigo == "A1-01":
        # O substantivo visível é "caso"
        assert "Casos ativos" in textos and not any("pendências" in t for t in textos)
        rotulos = " ".join(textos)
        # O nome do indicador, sem o código; e nenhum valor em reais no N1
        assert vocabulario.rotulo("KPI-03b", "kpi") in textos and vocabulario.rotulo("KPI-03", "kpi") in textos
        assert "além do prazo legal" in rotulos and "KPI-03" not in rotulos
        assert "R$" not in rotulos


def test_atraso_em_anos_com_uma_casa(monkeypatch, ativas):
    textos = _textos(monkeypatch, "A3-02", _dados(ativas, nivel=3))
    assert not any("dias de atraso" in t for t in textos)
    assert any(re.search(r"\d+,\d anos de atraso", t) for t in textos)
    textos = _textos(monkeypatch, "A2-02", _dados([p for p in ativas if p.uf == "SP"], nivel=2))
    assert not any(re.fullmatch(r"\d+ d", t) for t in textos)
    assert any(re.fullmatch(r"\d+,\d anos", t) for t in textos)


# ================================================================ o resumo no N2
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


@pytest.mark.parametrize("usuario, nivel, com_uf", [(BIA_N2, Nivel.N2, False), (CAIO_N3, Nivel.N3, True)])
def test_combo_do_resumo_no_n2_sem_por_uf_nem_por_regiao(tela, qt, usuario, nivel, com_uf):
    tela.iniciar(usuario, nivel)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    pa.mostrar("agregado")
    qt.processEvents()
    combo = pa.agregado.combo
    # O combo mostra o rótulo do vocabulário ("Por UF"); o código fica em `agrupamento`
    itens = [combo.itemText(i) for i in range(combo.count())]
    assert ("Por UF" in itens) == com_uf and ("Por região" in itens) == com_uf
    assert pa.agregado.agrupamento in pa.agregado.resumo.tabelas and pa.agregado.modelo.rowCount() > 0
    cabecalho = pa.agregado.tabela.horizontalHeader()
    for j, titulo in enumerate(pa.agregado.modelo.titulos):              # o título cabe inteiro na coluna
        exibido = vocabulario.titulo_coluna(titulo)                     # O título de exibição
        assert cabecalho.sectionSize(j) >= cabecalho.fontMetrics().horizontalAdvance(exibido), titulo
