"""Ciclo de vida do acervo: saídas do cadastro, catálogo de códigos e visualização por nível.

Séries e calibração, ciclo de vida, catálogo, Índice de Pressão, segurança dos
documentos e do panorama, e interface (com cliques reais).
"""
import random
import re
from dataclasses import replace
from datetime import date, datetime, timedelta

import cv2
import pytest

from ecosec.acervo import analise, documentos, regras, sinteticos
from ecosec.acervo.geracao import ciclo, fluxos, saidas, series
from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.seguranca import autorizacao
from ecosec.seguranca.autorizacao import Classificacao, Efeito, Operacao, Papel
from ecosec.seguranca.conteudo import s9_rastreio
from ecosec.servicos.acervo import ErroAcervo, ServicoAcervo
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
HOJE = sinteticos.DATA_BASE
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
FINAIS = {"ENCERRAMENTO", "DESTINACAO", "RECOLHIMENTO"}


@pytest.fixture(scope="module")
def pendencias():
    return sinteticos.gerar()[0]


@pytest.fixture
def acervo():
    trilha = ServicoTrilha(RepositorioTrilhaMemoria())
    from ecosec.interface.rasterizar_documento import rasterizar
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), trilha, b"chave-teste",
                                            relogio=lambda: datetime(2026, 10, 1, 10, 0),
                                            rasterizar_documento=rasterizar)
    servico.data_referencia = HOJE
    return servico


def estoque(ps, ano):
    corte = min(date(ano, 12, 31), HOJE)
    return sum(p.ativa(corte) for p in ps)


# ================================================================ saídas e séries
def test_saidas_no_ano_analitico_confere_com_euler():
    n, lam, h, dt = 100.0, 20.0, 0.3, 1e-3
    estoque_, total = n, 0.0
    for _ in range(int(1 / dt)):
        saida = h * estoque_ * dt
        total += saida
        estoque_ += lam * dt - saida
    assert saidas.saidas_no_ano(n, lam, h) == pytest.approx(total, rel=1e-3)


def test_calibrar_cumpre_as_metas_e_recusa_meta_impossivel():
    entradas = {a: 30.0 for a in range(2006, 2027)}
    _, fluxo, _ = saidas.calibrar(entradas, saidas.Saida(0.1, saidas.METAS_AREA), 100)
    assert fluxo[2021] / fluxo[2019] == pytest.approx(0.90, rel=1e-3)
    assert fluxo[2022] / fluxo[2021] == pytest.approx(1.19, rel=1e-3)
    with pytest.raises(ValueError):
        saidas.calibrar(entradas, saidas.Saida(0.1, ((2010, 2009, 50.0),)), 100)


def test_ancoras_de_nivel():
    entradas = {a: 28 * 2.718281828 ** (-0.07 * (a - 2006)) for a in range(2006, 2027)}
    postos = saidas.calibrar_risco_base(entradas, saidas.Saida(0.0, saidas.METAS_AREA,
                                                               ancora=("FRACAO", 2006, 2019, 0.28)), 120)
    h, _, _ = saidas.calibrar(entradas, postos, 120)
    assert saidas.fracao_encerrada(entradas, h, 2006, 2019) == pytest.approx(0.28, abs=1e-3)
    assert 0.03 < postos.risco_base < 0.06
    constantes = {a: 30.0 for a in range(2006, 2027)}
    area = saidas.calibrar_risco_base(constantes, saidas.Saida(0.0, ancora=("NIVEL", 2019, 0.95)), 150)
    _, fluxo, _ = saidas.calibrar(constantes, area, 150)
    assert fluxo[2019] / constantes[2019] == pytest.approx(0.95, abs=1e-3)


def test_formas_sem_ancora_nao_bastam():
    """Regressão: as razões são cumpridas e mesmo assim o estoque só cresce."""
    entradas = {a: 30.0 for a in range(2006, 2027)}
    _, fluxo, est = saidas.calibrar(entradas, saidas.Saida(0.03, saidas.METAS_AREA), 150)
    assert fluxo[2021] / fluxo[2019] == pytest.approx(0.90, rel=1e-3)
    assert all(est[a] > est[a - 1] for a in range(2007, 2027))


def test_contagens_sistematicas():
    rng = random.Random(1)
    esperado = {a: 3.7 + (a % 3) * 0.45 for a in range(2006, 2027)}
    contagem = fluxos.contagens_sistematicas(esperado, rng)
    assert abs(sum(contagem.values()) - sum(esperado.values())) < 1
    assert all(abs(contagem[a] - esperado[a]) < 1 for a in esperado)


def test_pulso_cobre_os_anos_inteiros():
    linha = series.Linha(base=10, pulsos=((2020, 2021, 2.0),))
    assert series.intensidade(linha, 2021.5) == 20 and series.intensidade(linha, 2022.0) == 10


def test_metas_de_calibracao_atingidas(pendencias):
    from ferramentas.calibrar_series import conferir
    assert conferir(pendencias, imprimir=lambda *_: None) == []


def test_estoque_cai(pendencias):
    anos = range(2007, HOJE.year + 1)
    assert any(estoque(pendencias, a) < estoque(pendencias, a - 1) for a in anos)          # total
    area = [p for p in pendencias if p.classe_risco == sinteticos.AREA]
    assert estoque(area, 2022) < estoque(area, 2021)
    fontes = [p for p in pendencias if p.atividade == "AG-08"]
    assert estoque(fontes, 2023) < estoque(fontes, 2022)


def test_encerramentos_significativos(pendencias):
    fracao = sum(1 for p in pendencias if p.data_encerramento) / len(pendencias)
    assert 0.30 <= fracao <= 0.60
    postos = [p for p in pendencias if p.atividade == "AG-01" and 2006 <= p.data_identificacao.year <= 2019]
    ate_2019 = sum(1 for p in postos if p.data_encerramento and p.data_encerramento.year <= 2019) / len(postos)
    assert ate_2019 == pytest.approx(0.28, abs=0.05)


def test_norm_legado_nao_sai(pendencias):
    norm = [p for p in pendencias if series.linha_de(p.atividade, p.classe_risco, p.motivo) == "NORM"]
    assert norm and not any(p.data_encerramento for p in norm)


def test_mtr_sem_baixa_so_a_partir_de_2021(pendencias):
    mtr = [p for p in pendencias if p.motivo == "MP-08"]
    assert mtr and min(p.data_identificacao for p in mtr) >= date(2021, 1, 1)
    assert all(p.classe_risco == sinteticos.CLASSE_I for p in mtr)          # manifesto é de resíduo


def test_modo_poisson_tambem_gera_um_acervo_coerente():
    ps, _ = sinteticos.gerar(600, "poisson")
    assert len(ps) == 600 and any(p.data_encerramento for p in ps)


# ================================================================ ciclo de vida
def test_ciclo_de_vida_coerente(pendencias):
    for p in pendencias:
        datas = [d for _, d in p.etapas]
        assert all(a < b for a, b in zip(datas, datas[1:])), p.codigo
        assert p.etapas[0][1] == p.data_identificacao and p.etapa_atual == p.etapas[-1][0]
        encerrada = p.data_encerramento is not None
        assert encerrada == (p.etapa_atual in FINAIS), p.codigo
        if encerrada:
            assert p.data_encerramento == datas[-1] < HOJE
            assert p.situacao in ciclo.SITUACOES_FINAIS
            assert p.data_encerramento - p.data_identificacao >= timedelta(days=20)
        else:
            assert datas[-1] < HOJE


def test_encerrada_para_de_atrasar_e_nao_vence(pendencias):
    p = next(x for x in pendencias if x.data_encerramento and x.prazo_coleta < x.data_encerramento)
    assert p.dias_de_atraso(HOJE) == (p.data_encerramento - p.prazo_coleta).days
    assert not p.vencida(HOJE) and not p.ativa(HOJE)


def test_consistencia_e_quedas_no_mysql(acervo_mysql):
    from ferramentas.preparar_banco import SQL_CONSISTENCIA, SQL_QUEDAS
    with acervo_mysql.transacao() as c:
        c.execute(SQL_CONSISTENCIA)
        assert c.fetchall() == []
        c.execute(SQL_QUEDAS)
        assert c.fetchall()                                   # o estoque cai em pelo menos um ano
        c.execute("SELECT codigo, nome, cnae_subclasse FROM atividade_geradora")
        assert len(c.fetchall()) == 13


# ================================================================ catálogo
def test_catalogo_completo_e_corrigido():
    assert len(sinteticos.ATIVIDADES) == 13 and len(sinteticos.MOTIVOS) == 10
    texto_largo = re.compile(r"^[A-Z0-9 ,.;:()/-]+$")
    cnae = re.compile(r"^[0-9]{4}-[0-9]/[0-9]{2}(; [0-9]{4}-[0-9]/[0-9]{2})*$")
    for a in sinteticos.ATIVIDADES:
        assert len(a.nome) <= 40 and texto_largo.fullmatch(a.descricao_operacional) and cnae.fullmatch(a.cnae_subclasse)
        assert a.exemplos and a.rotulo == f"{a.codigo} · {a.nome}"
    for m in sinteticos.MOTIVOS:
        assert len(m.nome) <= 40 and m.descricao_operacional and m.base_legal
        assert m.grupo in ("COBRAVEL", "PUBLICO", "INFRAESTRUTURA", "FISCALIZACAO")
    mp = {m.codigo: m for m in sinteticos.MOTIVOS}
    assert "SUMULA 629" not in mp["MP-07"].base_legal and "TEMA 999" in mp["MP-07"].base_legal
    assert "ART. 29" in mp["MP-06"].base_legal and "280/2020" in mp["MP-08"].base_legal
    assert {a.codigo: a for a in sinteticos.ATIVIDADES}["AG-08"].cnae_subclasse == "8640-2/11"


def test_grupo_do_catalogo_concorda_com_as_regras():
    nomes = {"COBRAVEL": regras.COBRAVEL, "PUBLICO": regras.PUBLICO, "INFRAESTRUTURA": regras.INFRAESTRUTURA,
             "FISCALIZACAO": regras.FISCALIZACAO}
    for m in sinteticos.MOTIVOS:
        p = replace(sinteticos.gerar()[0][0], motivo=m.codigo)
        assert regras.responsabilidade(p) == nomes[m.grupo], m.codigo


def test_referencia_sql_e_gerada_do_codigo():
    from ecosec.configuracao import RAIZ_PROJETO
    from ecosec.repositorios.mysql.importacao import sql_referencia
    assert (RAIZ_PROJETO / "sql" / "acervo" / "02_referencia.sql").read_text(encoding="utf-8") == sql_referencia()


def test_planilha_mostra_codigo_e_nome(pendencias):
    atividades = {a.codigo: a for a in sinteticos.ATIVIDADES}
    motivos = {m.codigo: m for m in sinteticos.MOTIVOS}
    linha = analise.linhas(pendencias[:1], HOJE, None, atividades, motivos)[0]
    assert linha.ATIVIDADE == atividades[pendencias[0].atividade].rotulo and " · " in linha.MOTIVO


# ================================================================ índice de pressão
def test_indice_de_pressao(pendencias):
    ufs = sorted(analise.REGIAO_DA_UF)
    ip = analise.indice_pressao(pendencias, ufs, HOJE)
    assert all(0 <= x.indice <= 1 for x in ip.values())
    assert sorted(x.posto for x in ip.values()) == list(range(1, 28))
    vazio = analise.indice_pressao(pendencias, ufs + ["ZZ"], HOJE)["ZZ"]
    assert vazio.ativas == 0 and vazio.indice == 0
    with pytest.raises(ValueError):
        analise.indice_pressao(pendencias, ufs, HOJE, pesos={"volume": 0.5, "severidade": 0.2, "custo": 0.2,
                                                             "atraso": 0.2})


def test_uf_maior_em_tudo_tem_indice_um():
    # A UF "AA" sai de um caso crítico (um caso que não é crítico empataria "AA" com "BB" na fração crítica)
    base = next(p for p in sinteticos.gerar()[0] if p.ativa(HOJE) and regras.categoria(p, HOJE) == "CRITICO")
    ps = [replace(base, codigo=f"X{i}", uf="AA", data_encerramento=None) for i in range(5)]
    ps.append(replace(base, codigo="Y", uf="BB", data_encerramento=None, quantidade=0.01,
                      data_identificacao=HOJE - timedelta(days=1), prazo_coleta=HOJE + timedelta(days=300)))
    ip = analise.indice_pressao(ps, ["AA", "BB"], HOJE)
    assert ip["AA"].indice == 1.0 and ip["AA"].posto == 1


def test_pesos_da_configuracao_somam_um():
    assert sum(analise.pesos_pressao(CFG).values()) == pytest.approx(1.0)


# ================================================================ segurança
def test_panorama_n1_so_totais_e_suprime_no_servico(acervo):
    p = acervo.panorama(ANA_N1, 1)
    campos = {type(v).__name__ for v in vars(p).values()}
    assert "Pendencia" not in campos and p.escopo == "NACIONAL" and len(p.pressao) == 27
    assert all(not hasattr(x, "latitude") for x in p.pressao.values())
    for uf, item in p.pressao.items():
        if item.suprimida:
            assert item.criticas == 0 and item.custo == 0 and p.por_classe[uf] == {}
    acervo.supressao_minima = 10_000
    p = acervo.panorama(ANA_N1, 1)
    assert all(x.suprimida or not x.ativas for x in p.pressao.values())
    assert acervo.trilha.recentes(1)[0].evento.motivo == "PANORAMA_AGREGADO"


def test_matriz_dos_documentos():
    decidir = autorizacao.decidir
    assert decidir(Papel.DIRETOR, Classificacao.RESERVADO, Operacao.LISTAR_DOCUMENTOS).efeito is Efeito.PERMITIDO
    assert decidir(Papel.DIRETOR, Classificacao.RESERVADO, Operacao.VISUALIZAR_DOCUMENTO).efeito is Efeito.NEGADO
    assert decidir(Papel.MINISTRO, Classificacao.SECRETO, Operacao.VISUALIZAR_DOCUMENTO).efeito is Efeito.PERMITIDO
    for c in Classificacao:
        assert decidir(Papel.MINISTRO, c, Operacao.EXPORTAR_DOCUMENTO).efeito is Efeito.NEGADO


def test_n2_lista_metadados_e_nao_abre_documento(acervo):
    painel = acervo.painel(BIA_N2, 2)
    p = next(x for x in painel.pendencias if documentos.documentos_da_pendencia(x, HOJE))
    lista = acervo.documentos(painel, BIA_N2, p.codigo)
    assert lista and all(d.pendencia_codigo == p.codigo for d in lista)
    with pytest.raises(ErroAcervo):
        acervo.abrir_documento(painel, BIA_N2, p.codigo, lista[0].id)
    assert acervo.trilha.recentes(1)[0].evento.resultado == "NEGADO"
    fora = next(x for x in sinteticos.gerar()[0] if x.uf != "SP")
    with pytest.raises(ErroAcervo):
        acervo.documentos(painel, BIA_N2, fora.codigo)                     # outra UF: nada sai


def test_n2_nao_recebe_pessoa_fisica(acervo):
    painel = acervo.painel(BIA_N2, 2)
    for p in painel.pendencias[:200]:
        assert all(r.nivel_minimo <= 2 for r in acervo.responsaveis_da_pendencia(painel, BIA_N2, p.codigo))


def test_documento_do_n3_sai_marcado_e_registrado(acervo, qt):
    from ecosec.servicos.documentos import url_verificacao
    painel = acervo.painel(CAIO_N3, 3)
    p = next(x for x in painel.pendencias if x.motivo == "MP-08" and documentos.documentos_da_pendencia(x, HOJE))
    doc = documentos.documentos_da_pendencia(p, HOJE)[-1]
    entrega = acervo.abrir_documento(painel, CAIO_N3, p.codigo, doc.id)
    marca = s9_rastreio.extrair(entrega.imagem, b"chave-teste", acervo.p_marca)
    assert marca is not None and marca.usuario_id == CAIO_N3.id                 # a S9 sobrevive (aplicada por último)
    assert entrega.hash_consulta[:16].upper() in entrega.marca_visivel
    registro = acervo.trilha.recentes(1)[0].evento
    assert registro.motivo == "ABERTURA_DOCUMENTO" and entrega.hash_consulta[:16].upper() in registro.detalhe.upper()
    texto_qr = None
    for escala in (1.0, 1.5, 2.0):
        recorte = cv2.resize(entrega.imagem, None, fx=escala, fy=escala, interpolation=cv2.INTER_NEAREST)
        texto_qr = cv2.QRCodeDetector().detectAndDecode(recorte)[0] or texto_qr
    gerador = next((r.nome for r in acervo.repo.responsaveis(3, p.uf) if r.pendencia_codigo == p.codigo
                    and r.vinculo == "GERADOR_ORIGINAL"), None)
    campos = documentos.campos(doc, p, painel.atividades, painel.motivos, gerador)
    assert texto_qr == url_verificacao(campos, entrega.hash_documento)


def test_sem_rasterizador_injetado_o_documento_nao_sai_e_nada_e_registrado(acervo):
    acervo.rasterizar_documento = None
    painel = acervo.painel(CAIO_N3, 3)
    p = next(x for x in painel.pendencias if documentos.documentos_da_pendencia(x, HOJE))
    with pytest.raises(ErroAcervo):
        acervo.abrir_documento(painel, CAIO_N3, p.codigo, documentos.documentos_da_pendencia(p, HOJE)[0].id)
    assert not any(r.evento.motivo == "ABERTURA_DOCUMENTO" for r in acervo.trilha.recentes(1000))


def test_verificar_documento_pelo_qr(pendencias):
    from ecosec.servicos.documentos import hash_documento, url_verificacao
    from ferramentas.verificar_documento import pelo_qr
    p = next(x for x in pendencias if documentos.documentos_da_pendencia(x, HOJE))
    doc = documentos.documentos_da_pendencia(p, HOJE)[0]
    gerador = next((r.nome for r in sinteticos.gerar()[1] if r.pendencia_codigo == p.codigo
                    and r.vinculo == "GERADOR_ORIGINAL"), None)
    campos = documentos.campos(doc, p, {a.codigo: a for a in sinteticos.ATIVIDADES},
                               {m.codigo: m for m in sinteticos.MOTIVOS}, gerador)
    achado = pelo_qr(url_verificacao(campos, hash_documento(campos)))
    assert achado and achado[1].codigo == p.codigo and achado[2]
    assert pelo_qr(url_verificacao(campos, "0" * 64))[2] is False


def test_custodia_so_no_n3(acervo):
    with pytest.raises(ErroAcervo):
        acervo.custodias(acervo.painel(BIA_N2, 2), BIA_N2)
    painel = acervo.painel(CAIO_N3, 3)
    tipos = {c.tipo for c, _ in acervo.custodias(painel, CAIO_N3)}
    assert tipos == {"DEFINITIVO", "INTERMEDIARIO", "NORM", "INICIAL"}


def test_relatorios_contam_so_ativas(acervo):
    entrega = acervo.abrir("A1-01", ANA_N1, 1)
    assert entrega.imagem is not None
    resumo = acervo.resumo_agregado(ANA_N1, 1)
    assert sum(l[1] for l in resumo.tabelas["POR UF"][1]) == sum(p.ativa(HOJE) for p in sinteticos.gerar()[0])


def test_priorizacao_ignora_encerradas(acervo):
    painel = acervo.painel(CAIO_N3, 3)
    fila = acervo.priorizacao(painel, CAIO_N3, 1e12)
    assert fila.selecionadas and all(p.ativa(HOJE) for p, _, _ in fila.selecionadas)


# ================================================================ interface (componentes)
def test_botao_exportar_mostra_o_cadeado_mas_nao_decide(qt):
    from types import SimpleNamespace

    from ecosec.interface.componentes.botao_exportar import BotaoExportar
    agora = datetime(2026, 10, 17, 12, 0)
    sessao = SimpleNamespace(verificacao=SimpleNamespace(momento=agora - timedelta(minutes=5, seconds=1)))
    botao = BotaoExportar("Exportar", sessao, 5, relogio=lambda: agora)
    assert not botao.livre and "verificação facial" in botao.toolTip()
    sessao.verificacao.momento = agora - timedelta(minutes=2)
    botao.atualizar()
    assert botao.livre and "liberada" in botao.toolTip()


def test_servico_exige_rosto_mesmo_com_cadeado_aberto(acervo, tmp_path):
    """O cadeado é só informativo: com a conferência vencida, o serviço pede o rosto de novo."""
    from ecosec.servicos.acervo import VerificacaoNecessaria
    painel = acervo.painel(BIA_N2, 2)
    with pytest.raises(VerificacaoNecessaria):
        acervo.exportar_planilha(painel, BIA_N2, [painel.pendencias[0].codigo], tmp_path / "x.csv",
                                 verificado_em=datetime(2026, 10, 1, 9, 0))
    assert not (tmp_path / "x.csv").exists()


def test_camada_propaga_opacidade_e_visibilidade(qt):
    from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsScene

    from ecosec.interface.componentes.camada import Camada
    cena, camada = QGraphicsScene(), Camada("pendencias", 10)
    cena.addItem(camada)
    filho = QGraphicsEllipseItem(0, 0, 5, 5)
    filho.setParentItem(camada)
    camada.setOpacity(0.4)
    assert filho.effectiveOpacity() == pytest.approx(0.4)
    camada.setVisible(False)
    assert not filho.isVisible()


def test_painel_deslizante_abre_e_esc_fecha(qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel, QWidget

    from ecosec.interface.componentes.painel_deslizante import PainelDeslizante
    pai = QWidget()
    pai.resize(900, 500)
    pai.show()
    painel = PainelDeslizante(pai, 300)
    painel.adicionar_aba("a", "A", QLabel("x"))
    # Sonda com teto em vez de espera fixa (a animação de 260 ms atrasava sob carga na suíte inteira,
    # depois que o mapa passou a ser a primeira aba visível do N3 já registrava a sensibilidade a tempo)
    def esperar(condicao, teto=3000):
        decorrido = 0
        while not condicao() and decorrido < teto:
            QTest.qWait(25)
            decorrido += 25
    painel.abrir()
    esperar(lambda: painel.x() == 600)
    assert painel.aberto and painel.isVisible() and painel.x() == 600
    QTest.keyClick(painel, Qt.Key.Key_Escape)
    esperar(lambda: not painel.isVisible())
    assert not painel.aberto and not painel.isVisible()
    pai.close()


def test_quintis_da_legenda():
    from ecosec.interface.componentes.legenda_quantis import quintis
    limites, classe = quintis({str(i): float(i) for i in range(10)})
    assert len(limites) == 5 and classe["0"] == 0 and classe["9"] == 4


def test_grafico_de_estoque_desenha_e_marca_o_ano(qt, pendencias):
    from ecosec.interface.componentes.grafico_estoque import GraficoEstoque
    g = GraficoEstoque()
    g.resize(800, 400)
    g.show()
    serie = analise.serie_estoque(pendencias, 2006, 2026, HOJE)
    g.mostrar(serie, sinteticos.EVENTOS, ano=2022)
    assert serie["acumulado"][2026] == len(pendencias)
    assert g.total[2026] == sum(p.ativa(HOJE) for p in pendencias)
    # Só as áreas; total no título e no rótulo do ano; eventos numerados na cena
    assert len(g.chart().series()) == 3
    assert len(g.vistas[0].rotulos_evento) == len(sinteticos.EVENTOS)
    from ecosec.interface.componentes.grafico_estoque import MODOS
    g.mostrar(serie, sinteticos.EVENTOS, modo=MODOS[1])                   # saldo anual: entradas x saídas
    assert any(v < 0 for v in g.saldo.values())                           # algum ano com o estoque caindo
    assert g.saldo[2023] == serie["entradas"][2023] - serie["saidas"][2023]
    g.close()


# ================================================================ interface (telas)
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


def test_panorama_legenda_barras_e_ano(tela, qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    tela.iniciar(ANA_N1, Nivel.N1)
    tela.mostrar_modo("painel")
    qt.processEvents()
    pn = tela.painel_analitico.panorama
    pn.mostrar_secao("onde")                      # O coroplético fica em "Onde estão os casos?"
    qt.processEvents()
    assert pn.panorama is not None and not pn.mapa.pontos
    assert "Índice de pressão" in pn.mapa.ufs["SP"].toolTip()
    QTest.mouseClick(pn.legenda.caixas[4], Qt.MouseButton.LeftButton)          # clique real no último quintil
    assert pn.estado.selecao and all(pn._quintil_de[uf] == 4 for uf in pn.estado.selecao)
    # As barras por classe que seguiam o mapa viraram o ranking das UFs, que realça a mesma seleção
    assert {l["chave"] for l in pn.ranking.linhas if l.get("destaque")} == set(pn.estado.selecao)
    pn.estado.definir(selecao=frozenset(), foco="SP")
    assert [l["chave"] for l in pn.ranking.linhas if l.get("destaque")] == ["SP"]
    sp = next(l for l in pn.ranking.linhas if l["chave"] == "SP")
    assert f"{pn.panorama.pressao['SP'].ativas:,} casos ativos".replace(",", ".") in sp["dica"]
    pn.estado.definir(classe=sinteticos.AREA)
    assert pn.panorama.classe == sinteticos.AREA and pn.combo_classe.currentText() == "Área contaminada"
    pn.combo_ano.setCurrentText("2015")                    # A lista no lugar do slider e do rótulo do ano
    assert pn.panorama.ano == 2015 and pn.combo_ano.currentText() == "2015"


def test_mapa_n3_camadas_linha_do_tempo_arvore_e_documento(tela, qt):
    from PySide6.QtTest import QTest
    tela.iniciar(CAIO_N3, Nivel.N3)
    tela.mostrar_modo("painel")
    qt.processEvents()
    m = tela.painel_analitico.mapa
    # Este teste conta pontos desenhados (isVisible) na escala país; sem a agregação por zoom, que
    # esconde os pontos dentro dos agregados (a agregação tem os próprios testes)
    m.caixa_agrupar.setChecked(False)
    hoje = tela.painel_analitico.painel.hoje
    # O padrão é Todos (ativos cheios, encerrados vazados)
    assert sum(pt.isVisible() for pt in m.mapa.pontos) == sum(p.pendencia.data_identificacao <= hoje
                                                              for p in m.mapa.pontos)
    assert sum(pt.isVisible() and not pt.vazado for pt in m.mapa.pontos) == sum(p.pendencia.ativa(hoje)
                                                                                for p in m.mapa.pontos)
    m.opacidades["pendencias"].setValue(30)
    assert m.mapa.camadas["pendencias"].opacity() == pytest.approx(0.3)
    m.caixas_custodia["NORM"].setChecked(False)
    assert not any(i.isVisible() for i in m.mapa.custodias if i.data(0) == "CUSTODIA:NORM")
    assert all(m.arvore.topLevelItem(i).text(0)[0] != "△" for i in range(m.arvore.topLevelItemCount()))
    m.combo_ano.setCurrentText("2012")                     # A lista no lugar do slider
    antes = sum(pt.isVisible() for pt in m.mapa.pontos)
    assert antes == sum(pt.pendencia.data_identificacao <= date(2012, 12, 31) for pt in m.mapa.pontos)   # Todos
    m.caixas_n3["densidade"].setChecked(True)
    QTest.qWait(50)
    assert m.mapa.camada_visivel("densidade")
    # árvore: carga preguiçosa (o serviço só é chamado ao expandir)
    chamadas = m.arvore.chamadas
    raiz = next(m.arvore.topLevelItem(i) for i in range(m.arvore.topLevelItemCount())
                if m.arvore.topLevelItem(i).text(0).startswith("□"))
    assert m.arvore.chamadas == chamadas
    raiz.setExpanded(True)
    assert m.arvore.chamadas == chamadas + 1 and raiz.childCount() >= 1
    # ficha no painel lateral e documento
    p = next(pt.pendencia for pt in m.mapa.pontos if documentos.documentos_da_pendencia(pt.pendencia, hoje))
    m.mostrar_ficha(p)
    QTest.qWait(400)
    assert m.ficha.aberto and m.ficha_titulo.text().startswith(p.codigo)
    assert m.lista_documentos.count() == len(documentos.documentos_da_pendencia(p, hoje))
    assert not m.botao_exportar_ficha.isVisibleTo(m)                         # o N3 não exporta
    entrega = m.abrir_documento(p.codigo, documentos.documentos_da_pendencia(p, hoje)[0].id)
    assert entrega is not None and m.janela_documento.visualizador.scene().items()
    m.janela_documento.close()


def test_mapa_n2_camadas_e_ficha_com_cadeado(tela, qt):
    from PySide6.QtTest import QTest
    tela.iniciar(BIA_N2, Nivel.N2)
    tela.mostrar_modo("painel")
    qt.processEvents()
    m = tela.painel_analitico.mapa
    assert m.linha_camadas.isVisibleTo(m) and not m.coluna_n3.isVisibleTo(m)
    m.caixas_n2["municipios"].setChecked(True)
    assert m.mapa.municipios_forcados and all(r.isVisible() for r in m.mapa.municipios.values())
    p = next(pt.pendencia for pt in m.mapa.pontos if pt.isVisible())
    m.mostrar_ficha(p)
    QTest.qWait(400)
    assert m.ficha.aberto and m.botao_exportar_ficha.isVisibleTo(m)
    # O aviso fala só do acesso de quem lê, sem citar o Nível 3
    assert "metadados" in m.aviso_documentos.text() and "Nível" not in m.aviso_documentos.text()
    assert not m.botao_abrir_documento.isVisibleTo(m)
    assert m.mapa.marca_dagua.startswith("RESERVADO · BIA")
