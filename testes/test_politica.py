"""Política: a composição das camadas S1-S7 por nível."""
import math

import pytest

from ecosec.configuracao import carregar
from ecosec.dominio.camadas import CamadaSeguranca as C
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.seguranca.acesso.politica import (Evidencias, ParametrosAcesso, camadas_exigidas,
                                              decidir, primeira_falha)

PARAMS = ParametrosAcesso({Nivel.N1: 70.0, Nivel.N2: 60.0, Nivel.N3: 50.0},
                          exigir_segunda_pessoa=True, janela_custodia_segundos=120)
SEM_REGRA_DOIS = ParametrosAcesso(PARAMS.limiares, False, 120)


def usuario(id_, nivel, ativo=True):
    return Usuario(matricula=f"MAT{id_}", nome=f"P{id_}", nivel=nivel, senha_hash="$2b$x",
                   uf="SP" if nivel == 2 else None, ativo=ativo, id=id_)


ANA_N1, BIA_N2, CAIO_N3, DORA_N3 = usuario(1, 1), usuario(2, 2), usuario(3, 3), usuario(4, 3)


def ev_n1(**ajustes):
    base = dict(nivel_solicitado=1, faces_detectadas=1, qualidade_aprovada=True,
                distancia=40.0, identidade_medida=1, usuario_identificado=ANA_N1,
                consentimento_vigente=True)
    return Evidencias(**{**base, **ajustes})


def ev_n2(**ajustes):
    base = dict(nivel_solicitado=2, bloqueado=False, usuario_alegado=BIA_N2, senha_confere=True,
                faces_detectadas=1, qualidade_aprovada=True, distancia=40.0, identidade_medida=2,
                consentimento_vigente=True)
    return Evidencias(**{**base, **ajustes})


def ev_n3(**ajustes):
    base = dict(nivel_solicitado=3, bloqueado=False, usuario_alegado=CAIO_N3, senha_confere=True,
                senha_forte=True, faces_detectadas=1, qualidade_aprovada=True, distancia=30.0,
                identidade_medida=3, consentimento_vigente=True, vivacidade_confirmada=True,
                segundo_usuario=DORA_N3, segundo_autenticado=True, segundos_entre=45.0)
    return Evidencias(**{**base, **ajustes})


# ---------------------------------------------------------------- Camadas por nível
def test_camadas_exigidas_por_nivel():
    codigos = lambda n, regra=True: [c.codigo for c in camadas_exigidas(Nivel(n), regra)]
    assert codigos(1) == ["S3", "S4", "S5"]
    assert codigos(2) == ["S1", "S2", "S3", "S4", "S5"]
    assert codigos(3) == ["S1", "S2", "S3", "S4", "S5", "S6", "S7"]
    assert codigos(3, regra=False) == ["S1", "S2", "S3", "S4", "S5", "S6"]


# ---------------------------------------------------------------- Caminho feliz
@pytest.mark.parametrize("ev", [ev_n1(), ev_n2(), ev_n3()], ids=["N1", "N2", "N3"])
def test_concede_com_todas_as_evidencias(ev):
    decisao = decidir(ev, PARAMS)
    assert decisao.concedido, str(decisao)
    assert [v.camada for v in decisao.vereditos] == list(decisao.camadas_exigidas)


def test_n3_sem_regra_dos_dois_concede_sem_segunda_pessoa_e_nao_registra_s7():
    decisao = decidir(ev_n3(segundo_usuario=None, segundo_autenticado=None), SEM_REGRA_DOIS)
    assert decisao.concedido
    assert "S7" not in decisao.fatores_avaliados


def test_usuario_n3_nao_abre_o_nivel_1():
    """A S5 nega fora da camada do perfil (um nível não vê os de baixo)."""
    decisao = decidir(ev_n1(usuario_identificado=CAIO_N3, identidade_medida=3), PARAMS)
    assert decisao.motivo is Motivo.NIVEL_INSUFICIENTE and decisao.camada_que_negou is C.S5_HABILITACAO


# ---------------------------------------------------------------- Falha segura
def test_evidencias_vazias_negam_em_todos_os_niveis():
    for nivel in (1, 2, 3):
        decisao = decidir(Evidencias(nivel_solicitado=nivel), PARAMS)
        assert not decisao.concedido


@pytest.mark.parametrize("campo", [
    "bloqueado", "usuario_alegado", "senha_confere", "senha_forte", "faces_detectadas",
    "qualidade_aprovada", "distancia", "identidade_medida", "consentimento_vigente",
    "vivacidade_confirmada", "segundo_usuario", "segundo_autenticado", "segundos_entre"])
def test_n3_qualquer_evidencia_ausente_nega(campo):
    """O teste mais importante do arquivo: remover qualquer evidência nega."""
    assert not decidir(ev_n3(**{campo: None}), PARAMS).concedido


def test_excecao_dentro_de_camada_vira_erro_interno():
    decisao = decidir(ev_n1(distancia="não é número"), PARAMS)   # comparar str com float levanta
    assert decisao.motivo is Motivo.ERRO_INTERNO and not decisao.concedido


def test_nivel_invalido():
    assert decidir(Evidencias(nivel_solicitado=4), PARAMS).motivo is Motivo.NIVEL_INVALIDO


def test_distancia_nan_nega():
    assert not decidir(ev_n2(distancia=math.nan), PARAMS).concedido


# ---------------------------------------------------------------- Ordem e motivo
@pytest.mark.parametrize("ev, motivo, camada", [
    (ev_n2(bloqueado=True), Motivo.BLOQUEADO, C.S1_CONTENCAO),
    (ev_n2(senha_confere=False), Motivo.SENHA_INCORRETA, C.S2_CONHECIMENTO),
    (ev_n2(usuario_alegado=None), Motivo.USUARIO_INEXISTENTE, C.S2_CONHECIMENTO),
    (ev_n3(senha_forte=False), Motivo.SENHA_FRACA, C.S2_CONHECIMENTO),
    (ev_n2(faces_detectadas=2), Motivo.MULTIPLAS_FACES, C.S3_QUALIDADE),
    (ev_n2(distancia=61.0), Motivo.CREDENCIAL_ALHEIA, C.S4_INERENCIA),
    (ev_n1(distancia=71.0), Motivo.FACE_NAO_RECONHECIDA, C.S4_INERENCIA),
    (ev_n1(usuario_identificado=usuario(1, 1, ativo=False)), Motivo.USUARIO_INATIVO, C.S5_HABILITACAO),
    (ev_n2(consentimento_vigente=False), Motivo.CONSENTIMENTO_AUSENTE, C.S5_HABILITACAO),
    (ev_n2(usuario_alegado=usuario(2, 1)), Motivo.NIVEL_INSUFICIENTE, C.S5_HABILITACAO),
    (ev_n3(vivacidade_confirmada=False), Motivo.VIVACIDADE_NAO_CONFIRMADA, C.S6_VIVACIDADE),
    (ev_n3(segundo_usuario=CAIO_N3), Motivo.SEGUNDA_PESSOA_INVALIDA, C.S7_CUSTODIA),
    (ev_n3(segundos_entre=500), Motivo.JANELA_EXPIRADA, C.S7_CUSTODIA),
])
def test_motivo_e_camada_de_cada_negacao(ev, motivo, camada):
    decisao = decidir(ev, PARAMS)
    assert decisao.motivo is motivo
    assert decisao.camada_que_negou is camada


def test_para_na_primeira_negacao():
    # senha errada e rosto errado: só a S2 aparece, a câmera nem seria aberta
    decisao = decidir(ev_n2(senha_confere=False, distancia=99.0), PARAMS)
    assert decisao.fatores_avaliados == "S1,S2"


def test_senha_errada_nunca_revela_rosto():
    decisao = decidir(ev_n2(senha_confere=False), PARAMS)
    assert C.S4_INERENCIA not in [v.camada for v in decisao.vereditos]


def test_resumo_legivel():
    assert str(decidir(ev_n2(distancia=61.0), PARAMS)) == (
        "S1 ✓  S2 ✓  S3 ✓  S4 ✗ CREDENCIAL_ALHEIA  →  CREDENCIAL_ALHEIA")


# ---------------------------------------------------------------- Avaliação progressiva
def test_progressiva_ate_s2_antes_de_abrir_a_camera():
    # só senha coletada: até a S2 está tudo certo, mesmo sem nenhuma evidência facial
    ev = Evidencias(nivel_solicitado=2, bloqueado=False, usuario_alegado=BIA_N2, senha_confere=True)
    assert primeira_falha(ev, PARAMS, C.S2_CONHECIMENTO) is None
    assert decidir(ev, PARAMS).concedido is False


def test_progressiva_devolve_a_falha():
    ev = Evidencias(nivel_solicitado=2, bloqueado=False, usuario_alegado=BIA_N2, senha_confere=False)
    assert primeira_falha(ev, PARAMS, C.S2_CONHECIMENTO).motivo is Motivo.SENHA_INCORRETA


def test_progressiva_n3_ate_s6_para_a_primeira_pessoa():
    ev = ev_n3(segundo_usuario=None, segundo_autenticado=None, segundos_entre=None)
    assert primeira_falha(ev, PARAMS, C.S6_VIVACIDADE) is None


def test_progressiva_excecao_nao_aprova():
    ev = ev_n1(distancia="x")
    assert primeira_falha(ev, PARAMS, C.S5_HABILITACAO).motivo is Motivo.ERRO_INTERNO


# ---------------------------------------------------------------- Configuração
def test_parametros_lidos_do_config():
    p = ParametrosAcesso.de_configuracao(carregar())
    # um nível mais sensível nunca aceita mais que um menos sensível; o N3 é estritamente o mais rígido
    assert p.limiares[Nivel.N1] >= p.limiares[Nivel.N2] > p.limiares[Nivel.N3]
    assert p.exigir_segunda_pessoa is False     # desligada: o cargo de ministro tem uma única pessoa
