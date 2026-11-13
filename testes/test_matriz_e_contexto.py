"""Governança no modelo "papel × dado × operação", MFA adaptativo, step-up, alertas, regras de negócio,
cobertura nacional e mapa vetorial."""
import dataclasses
from datetime import date, datetime, timedelta

import pytest

from ecosec.acervo import analise, regras, sinteticos
from ecosec.configuracao import carregar
from ecosec.dominio.camadas import CamadaSeguranca as C
from ecosec.dominio.entidades import EventoTrilha, RegistroTrilha, Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioEstacoesMemoria, RepositorioTrilhaMemoria
from ecosec.seguranca import autorizacao
from ecosec.seguranca.acesso import contexto
from ecosec.seguranca.acesso.contexto import ParametrosContexto
from ecosec.seguranca.acesso.politica import Evidencias, camadas_exigidas
from ecosec.seguranca.autorizacao import Classificacao, Efeito, Operacao, Papel
from ecosec.seguranca.evidencia import monitor
from ecosec.servicos.acervo import ErroAcervo, ServicoAcervo, VerificacaoNecessaria
from ecosec.servicos.autenticacao import Etapa
from ecosec.servicos.trilha import ServicoTrilha
from test_servico_autenticacao import SENHA_N2, SENHA_N3, alimentar, ambiente  # noqa: F401

CFG = carregar()
MONITOR = monitor.ParametrosMonitor.de_configuracao(CFG)
CONTEXTO = ParametrosContexto(True)
TERCA_14H, SABADO_14H = datetime(2026, 10, 6, 14, 0), datetime(2026, 10, 10, 14, 0)
SABADO_3H = datetime(2026, 10, 10, 3, 0)
AGORA = datetime(2026, 10, 13, 10, 0)
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)


@pytest.fixture
def acervo():
    trilha = ServicoTrilha(RepositorioTrilhaMemoria())
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), trilha, b"chave-teste", relogio=lambda: AGORA)
    servico.data_referencia = AGORA.date()
    return servico


def ultimo(servico):
    return servico.trilha.recentes(1)[0].evento


# matriz papel × dado × operação
def test_matriz_nega_o_que_nao_esta_nela():
    assert all(autorizacao.decidir(p, c, o).efeito in Efeito for p in Papel for c in Classificacao for o in Operacao)
    assert autorizacao.decidir(Papel.SERVIDOR, Classificacao.RESERVADO, Operacao.VISUALIZAR).efeito is Efeito.NEGADO


PAPEL_DA_CAMADA = {Classificacao.USO_INTERNO: Papel.SERVIDOR, Classificacao.RESERVADO: Papel.DIRETOR,
                   Classificacao.SECRETO: Papel.MINISTRO}


@pytest.mark.parametrize("classificacao, operacao, efeito", [
    (Classificacao.USO_INTERNO, Operacao.EXPORTAR_AGREGADO, Efeito.PERMITIDO),
    (Classificacao.USO_INTERNO, Operacao.EXPORTAR_REGISTROS, Efeito.NEGADO),
    (Classificacao.RESERVADO, Operacao.EXPORTAR_REGISTROS, Efeito.PERMITIDO_COM_VERIFICACAO),
    (Classificacao.RESERVADO, Operacao.EXPORTAR_RELATORIO, Efeito.PERMITIDO_COM_VERIFICACAO),
    (Classificacao.SECRETO, Operacao.VISUALIZAR, Efeito.PERMITIDO),
    (Classificacao.SECRETO, Operacao.EXPORTAR_AGREGADO, Efeito.NEGADO)])
def test_matriz_para_o_papel_da_camada(classificacao, operacao, efeito):
    """Cada classificação é do papel da sua camada (o ministro não responde por todas)."""
    assert autorizacao.decidir(PAPEL_DA_CAMADA[classificacao], classificacao, operacao).efeito is efeito


def test_so_o_administrador_administra_e_com_rosto():
    assert autorizacao.decidir(Papel.MINISTRO, Classificacao.SECRETO, Operacao.ADMINISTRAR).efeito is Efeito.NEGADO
    assert autorizacao.decidir(Papel.ADMINISTRADOR, Classificacao.USO_INTERNO,
                               Operacao.ADMINISTRAR).efeito is Efeito.PERMITIDO_COM_VERIFICACAO


def test_risco_alto_deixa_so_consulta():
    for operacao in autorizacao.EXPORTACOES:
        assert not autorizacao.decidir(Papel.SERVIDOR, Classificacao.USO_INTERNO, operacao, "ALTO").permitido
    assert not autorizacao.decidir(Papel.MINISTRO, Classificacao.SECRETO, Operacao.VISUALIZAR, "ALTO").permitido
    assert autorizacao.decidir(Papel.DIRETOR, Classificacao.RESERVADO, Operacao.VISUALIZAR, "ALTO").permitido


def test_codigos_de_negacao_cabem_na_trilha():
    """log_acesso.motivo tem 40 caracteres: um código maior faria a negação não ser registrada no MySQL."""
    motivos = {autorizacao.decidir(p, c, o, r).motivo for p in Papel for c in Classificacao for o in Operacao
               for r in ("BAIXO", "ALTO")}
    assert max(len(m) for m in motivos | {"VERIFICACAO_EXIGIDA"}) <= 40


def test_matriz_concorda_com_a_regra_de_exportacao_dos_niveis():
    """A tela explica a exportação por nível (Nivel.exportacao): a matriz não pode dizer outra coisa."""
    from ecosec.dominio.niveis import Exportacao
    for nivel in Nivel:
        classificacao = Classificacao.do_nivel(nivel)
        efeito = autorizacao.decidir(PAPEL_DA_CAMADA[classificacao], classificacao, Operacao.EXPORTAR_RELATORIO).efeito
        assert (efeito is Efeito.NEGADO) == (nivel.exportacao is Exportacao.BLOQUEADA)


# contexto (função pura)
@pytest.mark.parametrize("momento, conhecida, falhas, nivel", [
    (TERCA_14H, True, 0, "BAIXO"), (TERCA_14H, None, 0, "BAIXO"),     # 1ª estação da pessoa: só registra
    (SABADO_14H, True, 0, "BAIXO"), (SABADO_3H, True, 0, "BAIXO"),    # horário nunca é sinal
    (datetime(2026, 10, 6, 23, 0), True, 0, "BAIXO"),
    (TERCA_14H, False, 0, "MEDIO"), (TERCA_14H, True, 2, "MEDIO"), (SABADO_3H, False, 0, "MEDIO"),
    (TERCA_14H, False, 1, "ALTO"), (SABADO_3H, False, 1, "ALTO")])
def test_sinais_de_contexto(momento, conhecida, falhas, nivel):
    assert contexto.avaliar(momento, CONTEXTO, conhecida, falhas).nivel == nivel


@pytest.mark.parametrize("hora", range(24))
@pytest.mark.parametrize("dia", range(7))
def test_horario_nunca_e_sinal_de_risco(dia, hora):
    """Não há expediente: qualquer dia e hora dão o mesmo risco."""
    momento = datetime(2026, 10, 5 + dia, hora, 30)                   # 05/10/2026 é segunda-feira
    risco = contexto.avaliar(momento, CONTEXTO, True, 0)
    assert risco.nivel == "BAIXO" and not risco.sinais


def test_nao_existe_parametro_de_expediente():
    from dataclasses import fields
    assert [f.name for f in fields(ParametrosContexto)] == ["ativo"]
    assert set(CFG.secao("contexto")) == {"ativo", "verificacao_minutos"}


def test_contexto_desligado_e_sempre_baixo():
    assert contexto.avaliar(SABADO_14H, dataclasses.replace(CONTEXTO, ativo=False), False, 5).nivel == "BAIXO"


def test_estacao_vira_impressao_e_nao_nome():
    impressao = contexto.impressao_estacao()
    assert len(impressao) == 64 and all(c in "0123456789abcdef" for c in impressao)


def test_politica_inclui_a_s6_quando_o_contexto_pede():
    assert C.S6_VIVACIDADE not in camadas_exigidas(Nivel.N2, False)
    camadas = camadas_exigidas(Nivel.N2, False, exigir_vivacidade=True)
    assert C.S6_VIVACIDADE in camadas and camadas.index(C.S6_VIVACIDADE) > camadas.index(C.S5_HABILITACAO)
    assert Evidencias(nivel_solicitado=2).exigir_vivacidade is False


# contexto no login
def _com_contexto(amb, estacao="ESTACAO-A"):
    amb.servico.estacoes = RepositorioEstacoesMemoria()
    amb.servico.contexto_parametros = CONTEXTO
    amb.servico.estacao_atual = lambda: estacao
    return amb


def _entrar(amb, usuario, senha):
    sessao = amb.servico.nova_entrada()
    sessao.informar_credenciais(usuario.matricula, senha)
    return sessao


def test_estacao_habitual_e_o_login_de_sempre(ambiente):
    amb = _com_contexto(ambiente)
    bia = amb.criar("bia", 2, SENHA_N2)
    amb.rec.distancias = {bia.id: 40.0}
    amb.servico.estacoes.registrar(bia.id, "ESTACAO-A", TERCA_14H)
    sessao = _entrar(amb, bia, SENHA_N2)
    assert C.S6_VIVACIDADE not in sessao.andamento.camadas
    assert alimentar(sessao, 5).decisao.concedido
    assert sessao.identidade_comprovada.risco.nivel == "BAIXO"


def test_madrugada_de_sabado_e_o_login_de_sempre(ambiente):
    """Sem expediente: de madrugada, no fim de semana, na estação habitual, nada muda."""
    amb = _com_contexto(ambiente)
    amb.relogio.data = SABADO_3H
    caio = amb.criar("caio", 3, SENHA_N3)
    amb.rec.distancias = {caio.id: 30.0}
    amb.servico.estacoes.registrar(caio.id, "ESTACAO-A", TERCA_14H)
    sessao = _entrar(amb, caio, SENHA_N3)
    assert C.S6_VIVACIDADE not in sessao.andamento.camadas
    assert alimentar(sessao, 5).decisao.concedido
    identidade = sessao.identidade_comprovada
    assert identidade.risco.nivel == "BAIXO" and not identidade.risco.so_consulta
    n3 = amb.servico.nova_sessao(3, identidade=identidade)
    assert n3.andamento.decisao is None or n3.andamento.decisao.motivo is not Motivo.RISCO_CONTEXTUAL


def test_estacao_nova_pede_prova_de_vida_ja_no_login(ambiente):
    amb = _com_contexto(ambiente, estacao="ESTACAO-NOVA")
    bia = amb.criar("bia", 2, SENHA_N2)
    amb.rec.distancias = {bia.id: 40.0}
    amb.servico.estacoes.registrar(bia.id, "ESTACAO-A", TERCA_14H)
    sessao = _entrar(amb, bia, SENHA_N2)
    assert C.S6_VIVACIDADE in sessao.andamento.camadas
    andamento = alimentar(sessao, 5)                          # rosto confirmado: agora vem o gesto
    assert andamento.etapa is Etapa.DESAFIO
    final = alimentar(sessao, 10)
    assert final.decisao.concedido and C.S6_VIVACIDADE.codigo in final.decisao.fatores_avaliados
    assert sessao.identidade_comprovada.risco.nivel == "MEDIO"


def test_risco_alto_entra_mas_nao_abre_o_n3_nem_confere_para_exportar(ambiente):
    amb = _com_contexto(ambiente, estacao="ESTACAO-NOVA")
    caio = amb.criar("caio", 3, SENHA_N3)
    amb.rec.distancias = {caio.id: 30.0}
    amb.servico.estacoes.registrar(caio.id, "ESTACAO-A", TERCA_14H)
    _entrar(amb, caio, "senha errada")                        # erro recente + estação nova = os dois sinais
    sessao = _entrar(amb, caio, SENHA_N3)
    alimentar(sessao, 15)
    identidade = sessao.identidade_comprovada
    assert identidade is not None and identidade.risco.so_consulta
    n3 = amb.servico.nova_sessao(3, identidade=identidade)
    assert n3.andamento.decisao.motivo is Motivo.RISCO_CONTEXTUAL
    operacao = amb.servico.nova_verificacao_operacao(identidade)
    assert operacao.andamento.decisao.motivo is Motivo.RISCO_CONTEXTUAL


def test_login_concedido_registra_a_estacao(ambiente):
    amb = _com_contexto(ambiente, estacao="ESTACAO-B")
    bia = amb.criar("bia", 2, SENHA_N2)
    amb.rec.distancias = {bia.id: 40.0}
    alimentar(_entrar(amb, bia, SENHA_N2), 5)
    assert amb.servico.estacoes.conhecidas(bia.id) == {"ESTACAO-B"}


def test_verificacao_de_operacao_confere_o_rosto_e_tem_contencao_propria(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    ambiente.rec.distancias = {bia.id: 40.0}
    sessao = _entrar(ambiente, bia, SENHA_N2)
    alimentar(sessao, 5)
    operacao = ambiente.servico.nova_verificacao_operacao(sessao.identidade_comprovada)
    assert operacao.andamento.etapa is Etapa.ROSTO
    assert alimentar(operacao, 5).decisao.concedido
    assert operacao._chaves[0] == f"{bia.matricula}#OPR"


# step-up e matriz no serviço
def test_exportar_dados_nominais_pede_rosto_recente(acervo, tmp_path):
    painel = acervo.painel(BIA_N2, 2)
    codigos = [p.codigo for p in painel.pendencias[:3]]
    with pytest.raises(VerificacaoNecessaria):
        acervo.exportar_planilha(painel, BIA_N2, codigos, tmp_path / "a.csv")
    assert ultimo(acervo).motivo == "VERIFICACAO_EXIGIDA" and not (tmp_path / "a.csv").exists()
    with pytest.raises(VerificacaoNecessaria):                # 6 min atrás: fora da janela de 5
        acervo.exportar_planilha(painel, BIA_N2, codigos, tmp_path / "a.csv", verificado_em=AGORA - timedelta(minutes=6))
    acervo.exportar_planilha(painel, BIA_N2, codigos, tmp_path / "a.csv", verificado_em=AGORA - timedelta(minutes=2))
    assert (tmp_path / "a.csv").exists()


def test_n1_exporta_agregado_sem_step_up(acervo, tmp_path):
    resumo = acervo.resumo_agregado(ANA_N1, 1)
    acervo.exportar_resumo(resumo, ANA_N1, "POR REGIAO", tmp_path / "r.csv")
    assert (tmp_path / "r.csv").exists()


def test_sessao_de_risco_alto_nao_exporta_nada(acervo, tmp_path):
    resumo = acervo.resumo_agregado(ANA_N1, 1)
    with pytest.raises(ErroAcervo) as erro:
        acervo.exportar_resumo(resumo, ANA_N1, "POR UF", tmp_path / "r.csv", risco="ALTO")
    assert "só para consulta" in str(erro.value) and ultimo(acervo).motivo == "RISCO_CONTEXTUAL_ALTO"


def test_sessao_guarda_a_ultima_conferencia_do_rosto():
    from ecosec.servicos.autenticacao import IdentidadeComprovada
    from ecosec.servicos.sessao import SessaoAplicacao
    sessao = SessaoAplicacao(BIA_N2, IdentidadeComprovada(2, "BIA", False, Evidencias(2)), False, TERCA_14H)
    assert sessao.verificacao.momento == TERCA_14H and sessao.risco == "BAIXO"
    sessao.verificacao.registrar(TERCA_14H + timedelta(minutes=30))
    sessao.verificacao.registrar(TERCA_14H + timedelta(minutes=10))          # nunca volta no tempo
    assert sessao.verificacao.momento == TERCA_14H + timedelta(minutes=30)
    assert dataclasses.replace(sessao, administrador=True).verificacao is sessao.verificacao


# regras de negócio
@pytest.fixture(scope="module")
def base():
    return sinteticos.gerar()


def test_prazo_limite_e_custo_seguem_a_classe(base):
    r = regras.ParametrosRegras.de_configuracao(CFG)
    p = next(x for x in base[0] if x.classe_risco == regras.RADIOATIVO)
    assert regras.prazo_limite(p, r) == p.data_identificacao + timedelta(days=r.sla_dias[regras.RADIOATIVO])
    assert regras.custo_estimado(p, r) == round(sum(c.valor for c in regras.memoria_de_calculo(p, r)), 2)


def test_escalonamento_ao_ministerio_publico(base):
    r = regras.ParametrosRegras.de_configuracao(CFG)
    hoje = date(2026, 10, 17)
    for p in base[0]:
        acao = regras.acao_recomendada(p, hoje, r)
        assert acao in regras.ACOES
        if acao == regras.ESCALAR_MP:
            assert regras.responsabilidade(p) == regras.COBRAVEL and regras.categoria(p, hoje) == "CRITICO"
            assert p.dias_de_atraso(hoje) > r.escalonamento_mp_dias
    assert any(regras.acao_recomendada(p, hoje, r) == regras.ESCALAR_MP for p in base[0])


@pytest.mark.parametrize("criterio", regras.CRITERIOS)
def test_fila_do_orcamento_respeita_o_teto_e_so_leva_publicas(base, criterio):
    r = regras.ParametrosRegras.de_configuracao(CFG)
    fila = regras.priorizar(base[0], date(2026, 10, 17), r, 3_000_000, criterio)
    assert fila.custo_total <= 3_000_000 and 0 < len(fila.selecionadas) < fila.candidatas
    assert all(regras.responsabilidade(p) == regras.PUBLICO for p, _, _ in fila.selecionadas)
    mais = regras.priorizar(base[0], date(2026, 10, 17), r, 6_000_000, criterio)
    assert mais.percentual_reduzido >= fila.percentual_reduzido     # mais orçamento nunca reduz menos risco


def test_planilha_e_resumo_trazem_as_regras(base):
    hoje = date(2026, 10, 17)
    linha = analise.linhas(base[0][:1], hoje)[0]
    assert linha.ACAO_RECOMENDADA in regras.ACOES and linha.CUSTO_ESTIMADO > 0
    atividades = {a.codigo: a for a in sinteticos.ATIVIDADES}
    motivos = {m.codigo: m for m in sinteticos.MOTIVOS}
    titulos, linhas = analise.agregar(base[0], hoje, "POR REGIAO", atividades, motivos)
    assert {l[0] for l in linhas} == set(analise.REGIOES) and "CUSTO ESTIMADO" in titulos


def test_priorizacao_e_decisao_do_n3(acervo):
    with pytest.raises(ErroAcervo):
        acervo.priorizacao(acervo.painel(BIA_N2, 2), BIA_N2)
    fila = acervo.priorizacao(acervo.painel(CAIO_N3, 3), CAIO_N3, 2_000_000)
    assert fila.custo_total <= 2_000_000


# cobertura nacional
def test_todas_as_27_ufs_e_todas_as_regioes(base):
    assert {p.uf for p in base[0]} == set(sinteticos.PESO_UF) and len(sinteticos.PESO_UF) == 27
    assert {analise.REGIAO_DA_UF[p.uf] for p in base[0]} == set(analise.REGIOES)
    assert sum(analise.REGIAO_DA_UF[p.uf] == "NORTE" for p in base[0]) >= 40


def test_garimpo_so_onde_ha_garimpo(base):
    ufs = {p.uf for p in base[0] if p.atividade == "AG-13"}
    assert ufs and ufs <= set(sinteticos.AFINIDADE["AG-13"])


def test_divisas_das_27_ufs():
    assert set(sinteticos.divisas_uf()) == set(sinteticos.PESO_UF)


# monitor de anomalias
def _registro(momento, evento, resultado, motivo, **kw):
    return RegistroTrilha(EventoTrilha(momento=momento, evento=evento, resultado=resultado, motivo=motivo, **kw),
                          "0" * 64, "1" * 64)


def test_varredura_de_matriculas_e_rajada_de_exportacoes():
    t0 = TERCA_14H
    registros = [_registro(t0 + timedelta(minutes=i), "ENTRADA", "NEGADO", "SENHA_INCORRETA",
                           matricula_informada=f"M{i}") for i in range(4)]
    registros += [_registro(t0 + timedelta(minutes=i), "EXPORTACAO", "CONCEDIDO", "EXPORTACAO_PLANILHA", usuario_id=7)
                  for i in range(3)]
    regras_ = {a.regra for a in monitor.detectar(registros, MONITOR) if a.gravidade == "ALTO"}
    assert {"VARREDURA_DE_MATRICULAS", "RAJADA_DE_EXPORTACOES"} <= regras_


def test_acesso_de_madrugada_e_no_fim_de_semana_nao_gera_alerta():
    """Sem expediente: login e consultas ao N3 no sábado às 3h não são anomalia."""
    registros = [_registro(SABADO_3H, "ENTRADA", "CONCEDIDO", "CONCEDIDO", usuario_id=1)]
    registros += [_registro(SABADO_3H + timedelta(minutes=i), "CONSULTA", "CONCEDIDO", "CONSULTA_ACERVO",
                            nivel_solicitado=3, usuario_id=1) for i in range(12)]
    assert monitor.detectar(registros, MONITOR) == []


def test_sem_padrao_nao_alerta():
    registros = [_registro(TERCA_14H, "ENTRADA", "CONCEDIDO", "CONCEDIDO", usuario_id=1)]
    assert monitor.detectar(registros, MONITOR) == []


def test_relatorios_s08_e_s09_no_painel_do_administrador(tmp_path):
    from ecosec.aplicacao import montar
    from ecosec.servicos.relatorios_sistema import RELATORIOS
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    assert {"S-08", "S-09"} <= set(RELATORIOS)
    s09 = app.relatorios_sistema.gerar("S-09")
    assert ("MINISTRO", "SECRETO", "exportar relatorio", "Negado") in s09.linhas
    assert app.relatorios_sistema.gerar("S-08").colunas[0] == "Gravidade"


# mapa vetorial e priorização na tela
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


def _painel_n3(tela):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    tela.iniciar(CAIO_N3, Nivel.N3)
    QTest.mouseClick(tela.modo.items["painel"], Qt.MouseButton.LeftButton)
    QTest.qWait(50)
    return tela.painel_analitico


def test_mapa_vetorial_aproxima_ate_o_municipio(tela):
    mapa = _painel_n3(tela).mapa
    vetorial = mapa.mapa
    assert len(vetorial.ufs) == 27 and len(vetorial.pontos) == len(sinteticos.gerar()[0])
    assert vetorial.aumento == pytest.approx(1.0, abs=0.05) and not any(r.isVisible() for r in vetorial.municipios.values())
    mapa.combo_uf.setCurrentText("PA")
    mapa.combo_municipio.setCurrentIndex(1)
    # o mapa é a primeira aba do N3: visível, o enquadramento é animado. Espera a animação terminar
    # (sondando, com teto)
    from PySide6.QtCore import QAbstractAnimation
    from PySide6.QtTest import QTest
    animando = lambda: getattr(vetorial, "_animacao_enquadramento", None) is not None and         vetorial._animacao_enquadramento.state() == QAbstractAnimation.State.Running  # noqa: E731
    decorrido = 0
    while animando() and decorrido < 5000:
        QTest.qWait(25)
        decorrido += 25
    QTest.qWait(30)
    assert vetorial.aumento > 14 and any(n.isVisible() for n in vetorial.nomes)       # municípios e nomes
    mapa._voltar_ao_brasil()
    assert vetorial.aumento == pytest.approx(1.0, abs=0.05)


def test_clique_no_ponto_abre_a_ficha(tela):
    mapa = _painel_n3(tela).mapa
    ponto = mapa.mapa.pontos[0]
    mapa.mapa.pendencia_escolhida.emit(ponto.pendencia)
    assert mapa.ficha_titulo.text().startswith(ponto.pendencia.codigo) and "Ação recomendada" in mapa.texto_ficha()


def test_mapa_leva_marca_dagua_visivel(tela):
    assert _painel_n3(tela).mapa.mapa.marca_dagua.startswith("SECRETO · CAIO")


def test_priorizacao_responde_ao_orcamento(tela):
    orcamento = _painel_n3(tela).orcamento
    orcamento.orcamento.setValue(1)
    pouco = orcamento.modelo.rowCount()
    orcamento.orcamento.setValue(8)
    assert orcamento.modelo.rowCount() > pouco and "casos" in orcamento.resultado.text()     # "casos"
