"""Endereço granular, padrão de texto, geografia real, painel analítico e planilha."""
import hashlib
import re
from datetime import date, datetime

import cv2
import numpy as np
import pytest

from ecosec.acervo import analise, sinteticos
from ecosec.configuracao import carregar
from ecosec.dominio import texto
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.servicos.acervo import ErroAcervo, ServicoAcervo
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
HOJE = date(2026, 10, 13)
AGORA = datetime(2026, 10, 13, 10, 0)            # o relógio do serviço nos testes: rosto conferido "agora"
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
PADRAO = re.compile(texto.PADRAO_NOME)


@pytest.fixture(scope="module")
def base():
    return sinteticos.gerar()


@pytest.fixture
def acervo():
    trilha = ServicoTrilha(RepositorioTrilhaMemoria())
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), trilha, b"chave-teste",
                                            relogio=lambda: datetime(2026, 10, 13, 10, 0))
    servico.data_referencia = HOJE
    return servico


def ultimo(servico):
    return servico.trilha.recentes(1)[0].evento


# padrão de texto
@pytest.mark.parametrize("entrada, esperado", [
    ("São Bernardo do Campo", "SAO BERNARDO DO CAMPO"), ("Césio-137 (fonte)", "CESIO 137 FONTE"),
    ("Dias d'Ávila", "DIAS D AVILA"), ("  ação   civil  ", "ACAO CIVIL"), ("Ltda.", "LTDA")])
def test_nome_maiusculo_sem_acento_nem_simbolo(entrada, esperado):
    assert texto.nome(entrada) == esperado and PADRAO.fullmatch(esperado)


def test_referencia_mantem_a_pontuacao_que_da_sentido():
    assert texto.referencia("Lei 6.938/81, art. 14, §1º") == "LEI 6.938/81, ART. 14, PARAGRAFO 1"


@pytest.mark.parametrize("sigla, extenso", [("t", "TONELADAS"), ("kg", "QUILOGRAMAS"), ("L", "LITROS"),
                                            ("m²", "METROS QUADRADOS"), ("m³", "METROS CUBICOS"),
                                            ("TONELADAS", "TONELADAS")])
def test_unidade_por_extenso(sigla, extenso):
    assert texto.unidade(sigla) == extenso


def test_unidade_desconhecida_e_recusada():
    with pytest.raises(ValueError):
        texto.unidade("parsec")


def test_usuario_e_gravado_no_padrao():
    assert Usuario(matricula="X", nome="José da Conceição", nivel=1, senha_hash="$2b$x").nome == "JOSE DA CONCEICAO"


def test_trilha_padroniza_o_detalhe_antes_do_hash():
    trilha = ServicoTrilha(RepositorioTrilhaMemoria())
    registro = trilha.registrar("TESTE", "REGISTRADO", "X", detalhe="consulta à região; marca d'água")
    assert registro.evento.detalhe == "CONSULTA A REGIAO; MARCA D AGUA"
    assert trilha.verificar().integra                         # o hash cobre o texto como ficou gravado


# base gerada
def test_volume_e_distribuicao(base):
    pendencias, responsaveis = base
    assert len(pendencias) >= 200 and len(responsaveis) > len(pendencias)
    assert {p.uf for p in pendencias} == set(sinteticos.PESO_UF)
    assert {p.atividade for p in pendencias} == {a.codigo for a in sinteticos.ATIVIDADES}
    assert {p.motivo for p in pendencias} == {m.codigo for m in sinteticos.MOTIVOS}
    assert len({(p.uf, p.municipio) for p in pendencias}) >= 50


def test_base_e_deterministica():
    assert sinteticos.gerar() == sinteticos.gerar()


def test_todo_texto_no_padrao_do_banco(base):
    pendencias, responsaveis = base
    for p in pendencias:
        for campo in (p.substancia, p.classe_risco, p.logradouro, p.bairro, p.municipio, p.situacao, p.unidade):
            assert PADRAO.fullmatch(campo), (p.codigo, campo)
        assert p.complemento is None or PADRAO.fullmatch(p.complemento)
    assert all(PADRAO.fullmatch(r.nome) and PADRAO.fullmatch(r.situacao_cadastral) for r in responsaveis)
    for item in (*sinteticos.ATIVIDADES, *sinteticos.MOTIVOS):
        assert PADRAO.fullmatch(item.descricao)
    assert all(PADRAO.fullmatch(c.titulo) for c in sinteticos.CATALOGO)


def test_unidades_por_extenso(base):
    assert {p.unidade for p in base[0]} == {"TONELADAS", "METROS CUBICOS"}
    assert all(p.unidade == "METROS CUBICOS" for p in base[0] if p.classe_risco == sinteticos.RADIOATIVO)


def test_endereco_granular_e_cep(base):
    _, municipios = sinteticos.geografia()
    prefixos = {(m.uf, m.nome): set(m.cep_prefixos) for ms in municipios.values() for m in ms}
    for p in base[0]:
        assert re.fullmatch(r"[0-9]{8}", p.cep) and p.cep[:5] in prefixos[(p.uf, p.municipio)]
        assert re.fullmatch(r"[0-9]+|S/N", p.numero) and re.fullmatch(r"[A-Z]{2}", p.uf)
        assert p.endereco.startswith(f"{p.logradouro}, {p.numero}") and f"CEP {p.cep[:5]}-{p.cep[5:]}" in p.endereco


def test_coordenada_dentro_do_poligono_do_municipio(base):
    pais, municipios = sinteticos.geografia()
    por_nome = {(m.uf, m.nome): m for ms in municipios.values() for m in ms}
    for p in base[0]:
        m = por_nome[(p.uf, p.municipio)]
        assert any(cv2.pointPolygonTest(a, (p.longitude, p.latitude), False) > 0 for a in m.aneis), p.codigo
        # o contorno do país é simplificado: na costa (Cabedelo/PB), a cidade real passa dele por até ~3 km
        assert cv2.pointPolygonTest(pais, (p.longitude, p.latitude), True) >= -sinteticos.TOLERANCIA_CONTORNO


def test_datas_permitem_historico(base):
    pendencias = base[0]
    assert all(p.prazo_coleta >= p.data_identificacao for p in pendencias)
    assert len({p.data_identificacao.year for p in pendencias}) >= 10       # série temporal com história


def test_anel_fora_do_continente_e_ignorado():
    _, municipios = sinteticos.geografia()
    vitoria = next(m for m in municipios["ES"] if m.nome == "VITORIA")
    assert all(a[:, 0].mean() < -38 for a in vitoria.aneis)          # a Ilha da Trindade (lon ~ -29) fica de fora


# análise
def test_categorias_de_risco_por_faixa(base):
    p = base[0][0]
    assert analise.categoria(p, p.data_identificacao) in analise.CATEGORIAS
    assert analise.CATEGORIAS.index(analise.categoria(p, date(2040, 1, 1))) >= \
           analise.CATEGORIAS.index(analise.categoria(p, p.data_identificacao))       # sem coleta, só piora


def test_serie_conta_as_ativas_e_respeita_atividade(base):
    """A série conta as pendências ativas no fim de cada período, a curva pode cair."""
    pendencias = base[0]
    serie = analise.serie_risco(pendencias, date(2014, 1, 1), HOJE)
    totais = [sum(c.values()) for _, c in serie]
    assert totais != sorted(totais)                                          # não é mais monotônica
    assert totais[-1] == sum(p.ativa(HOJE) for p in pendencias) and serie[-1][0] == "2026"
    so_postos = analise.serie_risco(pendencias, date(2014, 1, 1), HOJE, atividade="AG-01")
    assert sum(so_postos[-1][1].values()) == sum(p.atividade == "AG-01" and p.ativa(HOJE) for p in pendencias)
    meses = analise.serie_risco(pendencias, date(2026, 1, 1), HOJE, por_mes=True)
    assert [r for r, _ in meses][:2] == ["01/2026", "02/2026"] and meses[-1][0] == "10/2026"


def test_csv_tem_todas_as_colunas(base):
    conteudo = analise.para_csv(analise.linhas(base[0][:3], HOJE)).decode("utf-8-sig").splitlines()
    assert conteudo[0].split(";") == list(analise.TITULOS) and len(conteudo) == 4


# painel e exportação
def test_n1_nao_tem_painel(acervo):
    with pytest.raises(ErroAcervo):
        acervo.painel(ANA_N1, 1)
    assert ultimo(acervo).resultado == "NEGADO"


def test_painel_n2_so_recebe_a_propria_uf_e_registra(acervo):
    painel = acervo.painel(BIA_N2, 2)
    assert painel.pendencias and {p.uf for p in painel.pendencias} == {"SP"} and painel.exporta
    assert (ultimo(acervo).motivo, ultimo(acervo).resultado) == ("PAINEL_ANALITICO", "CONCEDIDO")


def test_n3_ve_tudo_e_nao_exporta(acervo, tmp_path):
    painel = acervo.painel(CAIO_N3, 3)
    assert len(painel.pendencias) == len(sinteticos.gerar()[0]) and not painel.exporta
    with pytest.raises(ErroAcervo):
        acervo.exportar_planilha(painel, CAIO_N3, [p.codigo for p in painel.pendencias], tmp_path / "x.csv")
    assert not (tmp_path / "x.csv").exists() and ultimo(acervo).motivo == "EXPORTACAO_BLOQUEADA"


@pytest.mark.parametrize("extensao", ["csv", "xlsx"])
def test_exportacao_n2_grava_o_hash_do_arquivo_na_trilha(acervo, tmp_path, extensao):
    painel = acervo.painel(BIA_N2, 2)
    destino = tmp_path / f"planilha.{extensao}"
    resumo = acervo.exportar_planilha(painel, BIA_N2, [p.codigo for p in painel.pendencias[:5]], destino,
                                      "RISCO CRITICO", verificado_em=AGORA)
    assert hashlib.sha256(destino.read_bytes()).hexdigest() == resumo
    detalhe = ultimo(acervo).detalhe
    assert ultimo(acervo).motivo == "EXPORTACAO_PLANILHA" and resumo[:32].upper() in detalhe and "5 LINHAS" in detalhe


def test_xlsx_traz_a_aba_de_rastreio(acervo, tmp_path):
    from openpyxl import load_workbook
    painel = acervo.painel(BIA_N2, 2)
    acervo.exportar_planilha(painel, BIA_N2, [painel.pendencias[0].codigo], tmp_path / "p.xlsx", verificado_em=AGORA)
    livro = load_workbook(tmp_path / "p.xlsx")
    rastreio = dict(livro["RASTREIO"].iter_rows(values_only=True))
    assert livro.sheetnames == ["PASSIVOS", "RASTREIO"] and "MATRICULA BIA" in rastreio["EXPORTADO POR"]


def test_exportacao_fora_do_escopo_nao_sai(acervo, tmp_path):
    painel = acervo.painel(BIA_N2, 2)
    fora = next(p.codigo for p in sinteticos.gerar()[0] if p.uf != "SP")
    with pytest.raises(ErroAcervo):
        acervo.exportar_planilha(painel, BIA_N2, [fora], tmp_path / "x.csv", verificado_em=AGORA)
    assert not (tmp_path / "x.csv").exists()


def test_exportacao_e_pessoal(acervo, tmp_path):
    painel = acervo.painel(BIA_N2, 2)
    outra = Usuario(matricula="DUDA", nome="Duda", nivel=2, uf="SP", senha_hash="$2b$x", id=9)
    with pytest.raises(ErroAcervo):
        acervo.exportar_planilha(painel, outra, [painel.pendencias[0].codigo], tmp_path / "x.csv", verificado_em=AGORA)


def test_mapa_filtrado_registra_o_filtro_e_desenha_menos(acervo):
    inteiro = acervo.abrir("A3-03", CAIO_N3, 3)
    filtrado = acervo.abrir("A3-03", CAIO_N3, 3, ufs={"ES"}, categorias=("CRITICO",))
    assert "FILTRO UF ES RISCO CRITICO" in ultimo(acervo).detalhe
    vermelho = lambda img: int(np.sum((img[:, :, 2] > 180) & (img[:, :, 1] < 80) & (img[:, :, 0] < 90)))  # noqa: E731
    assert vermelho(filtrado.imagem) < vermelho(inteiro.imagem)


# banco real
def test_banco_recusa_texto_fora_do_padrao(acervo_mysql):
    with pytest.raises(Exception), acervo_mysql.transacao() as c:
        c.execute("INSERT INTO responsavel (pendencia_id, nome, vinculo) VALUES (1, 'Empresa Ltda.', 'SUCESSOR')")
    with pytest.raises(Exception), acervo_mysql.transacao() as c:
        c.execute("UPDATE pendencia SET cep = '1234-567' WHERE id = 1")


def test_repositorio_mysql_devolve_o_endereco_granular(acervo_mysql):
    from ecosec.repositorios.mysql import RepositorioAcervoMySQL
    pendencias = RepositorioAcervoMySQL(acervo_mysql).pendencias()
    assert pendencias == sinteticos.gerar()[0]


# interface
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


def clicar(segmentado, chave):
    """Clique DE VERDADE no item (o Fluent passa "checked" ao callback: foi o defeito de 13/10)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(segmentado.items[chave], Qt.MouseButton.LeftButton)
    QTest.qWait(50)


def test_n1_ve_panorama_e_resumo_agregados(tela):
    """O N1 tem o panorama por UF (coroplético, só totais) e o resumo; nenhum registro individual."""
    tela.iniciar(ANA_N1, Nivel.N1)
    assert tela.modo.isVisible()
    clicar(tela.modo, "painel")
    p = tela.painel_analitico
    assert list(p.abas.items) == ["panorama", "agregado", "glossario"]           # O Glossário
    assert p.pilha.currentWidget() is p.paginas["panorama"].property("cartao")
    assert p.painel is None and not p.agregado.botao_csv.isHidden()     # nenhum registro individual no N1
    assert not p.panorama.mapa.pontos                                     # coroplético: nenhum ponto na cena


@pytest.mark.parametrize("nivel, usuario", [(Nivel.N3, CAIO_N3), (Nivel.N2, BIA_N2)])
def test_abas_trocam_com_clique_real(tela, nivel, usuario):
    tela.iniciar(usuario, nivel)
    clicar(tela.modo, "painel")
    p = tela.painel_analitico
    for chave in p.DO_NIVEL[nivel]:
        clicar(p.abas, chave)
        assert p.pilha.currentWidget() is p.paginas[chave].property("cartao"), chave
    clicar(tela.modo, "relatorios")
    assert tela.esquerda.isVisible()


def test_filtro_do_mapa_aplica_sem_botao(tela):
    tela.iniciar(CAIO_N3, Nivel.N3)
    clicar(tela.modo, "painel")
    mapa = tela.painel_analitico.mapa
    # O mapa é a primeira aba do N3 (visível ao abrir); conta pontos desenhados, sem a agregação
    mapa.caixa_agrupar.setChecked(False)
    mapa.combo_uf.setCurrentText("ES")
    hoje = tela.painel_analitico.painel.hoje
    # O padrão da situação é Todos (identificados até hoje), e o texto diz "casos"
    todos = sum(p.uf == "ES" and p.data_identificacao <= hoje for p in sinteticos.gerar()[0])
    assert mapa.contagem.text().startswith(f"{todos} casos no mapa")
    visiveis = [pt.pendencia.uf for pt in mapa.mapa.pontos if pt.isVisible()]
    assert visiveis and set(visiveis) == {"ES"}


# resumo agregado
def test_resumo_n1_so_tem_totais_e_exporta_livre(acervo, tmp_path):
    resumo = acervo.resumo_agregado(ANA_N1, 1)
    codigos = {p.codigo for p in sinteticos.gerar()[0]}
    for titulos, linhas in resumo.tabelas.values():
        assert "PENDENCIAS" in titulos and not any(str(v) in codigos for l in linhas for v in l)
        assert not {"LATITUDE", "LONGITUDE", "LOGRADOURO", "CEP"} & set(titulos)
    titulos, linhas = resumo.tabelas["POR UF"]
    assert sum(l[1] for l in linhas) == sum(p.ativa(resumo.hoje) for p in sinteticos.gerar()[0])   # só ativas
    resumo_hash = acervo.exportar_resumo(resumo, ANA_N1, "POR UF", tmp_path / "r.csv")
    assert hashlib.sha256((tmp_path / "r.csv").read_bytes()).hexdigest() == resumo_hash
    assert ultimo(acervo).motivo == "EXPORTACAO_RESUMO"


def test_resumo_n2_e_da_propria_uf_e_n3_nao_exporta(acervo, tmp_path):
    n2 = acervo.resumo_agregado(BIA_N2, 2)
    assert [l[0] for l in n2.tabelas["POR UF"][1]] == ["SP"] and n2.exporta
    n3 = acervo.resumo_agregado(CAIO_N3, 3)
    with pytest.raises(ErroAcervo):
        acervo.exportar_resumo(n3, CAIO_N3, "POR UF", tmp_path / "x.xlsx")
    assert not (tmp_path / "x.xlsx").exists() and ultimo(acervo).motivo == "EXPORTACAO_BLOQUEADA"


def test_resumo_por_faixa_segue_a_ordem_de_gravidade(acervo):
    _, linhas = acervo.resumo_agregado(CAIO_N3, 3).tabelas["POR NIVEL DE RISCO"]
    assert [l[0] for l in linhas] == [c for c in analise.CATEGORIAS if c in {l[0] for l in linhas}]


def test_n3_painel_tem_tres_secoes_e_nao_exporta(tela, qt):
    tela.iniciar(CAIO_N3, Nivel.N3)
    tela.mostrar_modo("painel")
    qt.processEvents()
    p = tela.painel_analitico
    todas = sinteticos.gerar()[0]
    ativas = sum(x.ativa(p.painel.hoje) for x in todas)
    # A planilha abre em Todos (o cadastro inteiro, com encerrados)
    assert p.abas.isVisible() and len(p.planilha.modelo.todas) == len(todas)
    p.planilha.combo_situacao.setCurrentIndex(0)
    assert len(p.planilha.modelo.todas) == ativas                                 # Ativos
    p.planilha.combo_situacao.setCurrentIndex(2)
    assert len(p.planilha.modelo.todas) == len(todas)
    assert not p.planilha.botao_csv.isVisible() and len(p.mapa.mapa.pontos) == len(todas)
    # Este teste conta pontos desenhados (isVisible) na escala país; sem a agregação por zoom, que
    # esconde os pontos dentro dos agregados (a agregação tem os próprios testes)
    p.mapa.caixa_agrupar.setChecked(False)
    # O filtro é único; com "ativas e encerradas" o mapa mostra as encerradas como ponto vazado
    assert sum(pt.isVisible() for pt in p.mapa.mapa.pontos) == len(todas)
    assert sum(pt.isVisible() and not pt.vazado for pt in p.mapa.mapa.pontos) == ativas
    assert not tela.esquerda.isVisible()                    # o painel usa a largura toda
    tela.mostrar_modo("relatorios")
    assert tela.esquerda.isVisible()


def test_n2_painel_mapa_da_uf_e_planilha_que_exporta(tela, qt):
    tela.iniciar(BIA_N2, Nivel.N2)
    tela.mostrar_modo("painel")
    qt.processEvents()
    p = tela.painel_analitico
    # O N2 ganhou os "Painéis da UF" (classe, custo e encerramento, sem k)
    assert list(p.abas.items) == ["mapa", "paineis_uf", "planilha", "agregado", "glossario"]
    assert not p.planilha.botao_xlsx.isHidden()
    assert {pt.pendencia.uf for pt in p.mapa.mapa.pontos} == {"SP"}               # o mapa do N2 é a própria UF
    assert not p.mapa.mapa.custodias                                              # custódia é SECRETA (N3)
    clicar(p.abas, "planilha")
    p.planilha.combo_risco.setCurrentText("Crítico")                    # Rótulo do vocabulário
    assert all(l.NIVEL_DE_RISCO == "CRITICO" and l.UF == "SP" for l in p.planilha.modelo.todas)


def test_planilha_ordena_e_pagina(tela, qt):
    tela.iniciar(CAIO_N3, Nivel.N3)
    tela.mostrar_modo("painel")
    pl = tela.painel_analitico.planilha
    coluna = pl.modelo.titulos.index("NIVEL DE RISCO")        # o score não aparece na grade; a faixa ordena por ele
    from PySide6.QtCore import Qt
    pl.modelo.sort(coluna, Qt.SortOrder.DescendingOrder)
    valores = [l.CRITICIDADE for l in pl.modelo.todas]
    assert valores == sorted(valores, reverse=True)
    assert pl.modelo.rowCount() == 50 and pl.modelo.paginas == -(-len(valores) // 50)
    pl._ir(+1)
    assert pl.modelo.pagina == 1 and pl.anterior.isEnabled()
