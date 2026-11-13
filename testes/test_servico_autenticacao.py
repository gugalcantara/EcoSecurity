"""Serviço de autenticação, ponta a ponta, sem câmera: quadros fabricados,
reconhecedor com distâncias programadas e relógio controlado pelo teste."""
import dataclasses
import random
from datetime import datetime, timedelta

import numpy as np
import pytest

from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Consentimento, Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.repositorios.memoria import (RepositorioConsentimentosMemoria, RepositorioTentativasMemoria,
                                         RepositorioUsuariosMemoria)
from ecosec.seguranca.acesso import s2_conhecimento
from ecosec.seguranca.acesso.s6_vivacidade import Desafio
from ecosec.servicos.autenticacao import Etapa, ParametrosAutenticacao, ServicoAutenticacao
from ecosec.visao.gestos import DetectorGesto, MedidaOlhos
from ecosec.visao.pipeline import ResultadoQuadro

CUSTO = 4
SENHA_N2 = "diretor2026"
SENHA_N3 = "Custodia#2026"


class Relogio:
    def __init__(self):
        self.t = 1000.0
        self.data = datetime(2026, 10, 6, 14, 0)

    def monotonico(self):
        return self.t

    def agora(self):
        return self.data + timedelta(seconds=self.t - 1000.0)

    def avancar(self, segundos):
        self.t += segundos


class ReconhecedorFalso:
    """distancias[id] = distância que o rosto em cena tem até aquela pessoa."""

    def __init__(self):
        self.distancias = {}

    def identificar(self, _):
        if not self.distancias:
            return None
        rotulo = min(self.distancias, key=self.distancias.get)
        return rotulo, self.distancias[rotulo]

    def verificar(self, _, rotulo):
        return self.distancias.get(rotulo)


class GestoFalso:
    """Cumpre o gesto no 2º quadro com rosto."""

    def __init__(self, *_):
        self.n, self.progresso = 0, 0.0

    def alimentar(self, r):
        self.n += 1 if r.face_unica else 0
        return self.n >= 2


def quadro(faces=1, boa=True):
    rets = tuple((100 + 120 * i, 100, 100, 100) for i in range(faces))
    face = np.zeros((200, 200), np.uint8) if (faces == 1 and boa) else None
    return ResultadoQuadro(faces=rets, fonte="HAAR", largura=640, altura=480,
                           recorte_cinza=np.zeros((100, 100), np.uint8) if faces == 1 else None,
                           face_normalizada=face)


@pytest.fixture
def ambiente():
    cfg = carregar()
    relogio = Relogio()
    usuarios, tentativas = RepositorioUsuariosMemoria(), RepositorioTentativasMemoria()
    consentimentos = RepositorioConsentimentosMemoria()
    rec = ReconhecedorFalso()
    p = ParametrosAutenticacao.de_configuracao(cfg)
    p.custo_bcrypt = CUSTO
    # a regra dos dois está desligada no config do projeto, mas a S7 continua no
    # sistema: estes testes a ligam para provar que ela funciona
    p.acesso = dataclasses.replace(p.acesso, exigir_segunda_pessoa=True)

    def criar(nome, nivel, senha, consentir=True, ativo=True):
        u = usuarios.adicionar(Usuario(matricula=f"M{nome.upper()}", nome=nome, nivel=nivel,
                                       senha_hash=s2_conhecimento.gerar_hash(senha, CUSTO),
                                       uf="SP" if nivel == 2 else None, ativo=ativo))
        if consentir:
            c = consentimentos.registrar(Consentimento(nome, "1.0", "a" * 64, relogio.agora()))
            consentimentos.vincular(c.id, u.id)
        return u

    servico = ServicoAutenticacao(usuarios, tentativas, consentimentos, rec, p, relogio=relogio.agora,
                                  monotonico=relogio.monotonico, criar_detector=GestoFalso)
    return dataclasses.make_dataclass("Amb", ["servico", "rec", "relogio", "criar", "tentativas", "p",
                                              "usuarios"])(
        servico, rec, relogio, criar, tentativas, p, usuarios)


def alimentar(sessao, n, **kw):
    andamento = None
    for _ in range(n):
        andamento = sessao.processar(quadro(**kw))
    return andamento


def esgotar_prazo(amb, sessao, **kw):
    amb.relogio.avancar(amb.p.timeout_rosto + 1)
    return sessao.processar(quadro(**kw))


# Nível 1 (1:N)
def test_n1_reconhece_e_concede(ambiente):
    ana = ambiente.criar("ana", 1, "senha1234")
    ambiente.rec.distancias = {ana.id: 30.0}
    sessao = ambiente.servico.nova_sessao(1)
    assert sessao.andamento.etapa is Etapa.ROSTO             # N1 começa direto no rosto
    andamento = alimentar(sessao, ambiente.p.frames_confirmacao)
    assert andamento.decisao.concedido
    assert sessao.usuario_autenticado.id == ana.id
    assert andamento.decisao.fatores_avaliados == "S3,S4,S5"


def test_n1_rosto_desconhecido_nega_no_prazo(ambiente):
    ana = ambiente.criar("ana", 1, "senha1234")
    ambiente.rec.distancias = {ana.id: 95.0}                 # longe de todos
    sessao = ambiente.servico.nova_sessao(1)
    alimentar(sessao, 20)
    assert sessao.andamento.etapa is Etapa.ROSTO             # ainda tentando
    assert esgotar_prazo(ambiente, sessao).decisao.motivo is Motivo.FACE_NAO_RECONHECIDA


def test_n1_ninguem_diante_da_camera(ambiente):
    sessao = ambiente.servico.nova_sessao(1)
    alimentar(sessao, 5, faces=0)
    assert esgotar_prazo(ambiente, sessao, faces=0).decisao.motivo is Motivo.FACE_AUSENTE


def test_duas_faces_zeram_a_confirmacao(ambiente):
    ana = ambiente.criar("ana", 1, "senha1234")
    ambiente.rec.distancias = {ana.id: 30.0}
    sessao = ambiente.servico.nova_sessao(1)
    alimentar(sessao, ambiente.p.frames_confirmacao - 1)
    andamento = sessao.processar(quadro(faces=2))
    assert andamento.progresso == 0 and "uma pessoa" in andamento.mensagem


def test_n1_sem_consentimento_nega(ambiente):
    ana = ambiente.criar("ana", 1, "senha1234", consentir=False)
    ambiente.rec.distancias = {ana.id: 30.0}
    sessao = ambiente.servico.nova_sessao(1)
    assert alimentar(sessao, 5).decisao.motivo is Motivo.CONSENTIMENTO_AUSENTE


def test_n1_pedindo_nivel_2_nega_por_nivel(ambiente):
    ana = ambiente.criar("ana", 1, "senha1234")
    ambiente.rec.distancias = {ana.id: 30.0}
    sessao = ambiente.servico.nova_sessao(2)
    sessao.informar_credenciais(ana.matricula, "senha1234")
    assert alimentar(sessao, 5).decisao.motivo is Motivo.NIVEL_INSUFICIENTE


# Nível 2
def test_n2_concede(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    ambiente.rec.distancias = {bia.id: 40.0}
    sessao = ambiente.servico.nova_sessao(2)
    assert sessao.andamento.etapa is Etapa.CREDENCIAIS
    andamento = sessao.informar_credenciais(" " + bia.matricula.lower(), SENHA_N2)
    assert andamento.etapa is Etapa.ROSTO
    assert alimentar(sessao, 5).decisao.concedido


def test_n2_senha_errada_nao_abre_a_camera(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    sessao = ambiente.servico.nova_sessao(2)
    andamento = sessao.informar_credenciais(bia.matricula, "errada000")
    assert andamento.etapa is Etapa.CONCLUIDA
    assert andamento.decisao.motivo is Motivo.SENHA_INCORRETA


def test_n2_tres_erros_bloqueiam_e_ai_nem_a_senha_certa_entra(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    for _ in range(3):
        ambiente.servico.nova_sessao(2).informar_credenciais(bia.matricula, "errada000")
    sessao = ambiente.servico.nova_sessao(2)
    assert sessao.informar_credenciais(bia.matricula, SENHA_N2).decisao.motivo is Motivo.BLOQUEADO


def test_o_erro_que_bloqueia_ja_informa_ate_quando(ambiente):
    """Sem isto, a pessoa só descobria o bloqueio numa 4ª tentativa."""
    bia = ambiente.criar("bia", 2, SENHA_N2)
    andamentos = [ambiente.servico.nova_sessao(2).informar_credenciais(bia.matricula, "errada000")
                  for _ in range(3)]
    assert andamentos[0].bloqueado_ate is None and andamentos[1].bloqueado_ate is None
    assert andamentos[2].bloqueado_ate == ambiente.tentativas.obter(bia.matricula).bloqueado_ate


def test_bloqueio_expira(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    ambiente.rec.distancias = {bia.id: 40.0}
    for _ in range(3):
        ambiente.servico.nova_sessao(2).informar_credenciais(bia.matricula, "errada000")
    ambiente.relogio.avancar(15 * 60 + 1)
    sessao = ambiente.servico.nova_sessao(2)
    assert sessao.informar_credenciais(bia.matricula, SENHA_N2).etapa is Etapa.ROSTO


def test_matricula_inexistente_tambem_bloqueia(ambiente):
    for _ in range(3):
        ambiente.servico.nova_sessao(2).informar_credenciais("NAOEXISTE", "x")
    registro = ambiente.tentativas.obter("NAOEXISTE")
    assert registro.bloqueado_ate is not None


def test_n2_rosto_de_outra_pessoa_e_credencial_alheia_e_conta_falha(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    ambiente.rec.distancias = {bia.id: 85.0}
    sessao = ambiente.servico.nova_sessao(2)
    sessao.informar_credenciais(bia.matricula, SENHA_N2)
    alimentar(sessao, 10)
    assert esgotar_prazo(ambiente, sessao).decisao.motivo is Motivo.CREDENCIAL_ALHEIA
    assert ambiente.tentativas.obter(bia.matricula).falhas == 1


def test_desistir_na_etapa_do_rosto_conta_como_falha(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    for _ in range(3):
        sessao = ambiente.servico.nova_sessao(2)
        sessao.informar_credenciais(bia.matricula, SENHA_N2)
        andamento = sessao.cancelar()
        assert andamento.cancelada and not andamento.decisao.concedido
    assert ambiente.tentativas.obter(bia.matricula).bloqueado_ate is not None


def test_sucesso_zera_falhas(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    ambiente.rec.distancias = {bia.id: 40.0}
    ambiente.servico.nova_sessao(2).informar_credenciais(bia.matricula, "errada000")
    sessao = ambiente.servico.nova_sessao(2)
    sessao.informar_credenciais(bia.matricula, SENHA_N2)
    alimentar(sessao, 5)
    assert ambiente.tentativas.obter(bia.matricula).falhas == 0


def test_n2_inativo_nega(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2, ativo=False)
    ambiente.rec.distancias = {bia.id: 40.0}
    sessao = ambiente.servico.nova_sessao(2)
    sessao.informar_credenciais(bia.matricula, SENHA_N2)
    assert alimentar(sessao, 5).decisao.motivo is Motivo.USUARIO_INATIVO


# Nível 3
def autenticar_pessoa_n3(amb, sessao, usuario, senha=SENHA_N3):
    sessao.informar_credenciais(usuario.matricula, senha)
    alimentar(sessao, amb.p.frames_confirmacao)                # rosto
    andamento = None
    for _ in range(amb.p.quantidade_desafios):   # gesto falso: 2 quadros + conferência pós-gesto
        andamento = alimentar(sessao, 2 + amb.p.conferidos_minimos)
    return andamento


def test_n3_completo_com_duas_pessoas(ambiente):
    caio, dora = ambiente.criar("caio", 3, SENHA_N3), ambiente.criar("dora", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0, dora.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    andamento = autenticar_pessoa_n3(ambiente, sessao, caio)
    assert andamento.etapa is Etapa.CREDENCIAIS and andamento.pessoa == 2
    andamento = autenticar_pessoa_n3(ambiente, sessao, dora)
    assert andamento.decisao.concedido, str(andamento.decisao)
    assert andamento.decisao.fatores_avaliados == "S1,S2,S3,S4,S5,S6,S7"


def test_n3_mesma_pessoa_duas_vezes(ambiente):
    caio = ambiente.criar("caio", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    autenticar_pessoa_n3(ambiente, sessao, caio)
    andamento = sessao.informar_credenciais(caio.matricula, SENHA_N3)
    assert andamento.decisao.motivo is Motivo.SEGUNDA_PESSOA_INVALIDA


def test_n3_janela_da_segunda_pessoa_expira(ambiente):
    caio, dora = ambiente.criar("caio", 3, SENHA_N3), ambiente.criar("dora", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0, dora.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    autenticar_pessoa_n3(ambiente, sessao, caio)
    ambiente.relogio.avancar(ambiente.p.acesso.janela_custodia_segundos + 1)
    assert sessao.verificar_prazo().decisao.motivo is Motivo.JANELA_EXPIRADA


def test_n3_segunda_pessoa_de_nivel_2_e_negada(ambiente):
    caio, bia = ambiente.criar("caio", 3, SENHA_N3), ambiente.criar("bia", 2, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0, bia.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    autenticar_pessoa_n3(ambiente, sessao, caio)
    andamento = autenticar_pessoa_n3(ambiente, sessao, bia)
    assert not andamento.decisao.concedido


def test_n3_senha_fraca_nega(ambiente):
    caio = ambiente.criar("caio", 3, "fraca123")
    sessao = ambiente.servico.nova_sessao(3)
    assert sessao.informar_credenciais(caio.matricula, "fraca123").decisao.motivo is Motivo.SENHA_FRACA


def test_n3_trocar_a_foto_pelo_proprio_rosto_no_gesto_e_negado(ambiente):
    """Ataque: a foto da vítima passa na S4; depois o atacante faz o gesto com o próprio rosto."""
    caio = ambiente.criar("caio", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    sessao.informar_credenciais(caio.matricula, SENHA_N3)
    alimentar(sessao, 5)
    assert sessao.andamento.etapa is Etapa.DESAFIO
    ambiente.rec.distancias = {caio.id: 90.0}                  # outro rosto em cena
    sessao.s.criar_detector = lambda _: type("Nunca", (), {"alimentar": lambda s, r: False,
                                                            "progresso": 0.0})()
    andamento = alimentar(sessao, ambiente.p.divergentes_maximos + 2)
    assert andamento.decisao.motivo is Motivo.VIVACIDADE_NAO_CONFIRMADA


def test_n3_desafio_com_prazo(ambiente):
    caio = ambiente.criar("caio", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    sessao.informar_credenciais(caio.matricula, SENHA_N3)
    alimentar(sessao, 5)
    ambiente.relogio.avancar(ambiente.p.timeout_desafio + 1)
    assert sessao.processar(quadro()).decisao.motivo is Motivo.VIVACIDADE_NAO_CONFIRMADA


def test_n3_sem_regra_dos_dois_concede_com_uma_pessoa(ambiente):
    ambiente.p.acesso = dataclasses.replace(ambiente.p.acesso, exigir_segunda_pessoa=False)
    caio = ambiente.criar("caio", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0}
    andamento = autenticar_pessoa_n3(ambiente, ambiente.servico.nova_sessao(3), caio)
    assert andamento.decisao.concedido
    assert "S7" not in andamento.decisao.fatores_avaliados


def test_andamento_mostra_camadas_aprovadas(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    ambiente.rec.distancias = {bia.id: 40.0}
    sessao = ambiente.servico.nova_sessao(2)
    andamento = sessao.informar_credenciais(bia.matricula, SENHA_N2)
    assert {c.codigo for c in andamento.aprovadas} == {"S1", "S2"}
    assert andamento.limiar == ambiente.p.acesso.limiares[Nivel.N2]


def test_n3_gesto_com_rosto_fora_da_qualidade_nao_vale(ambiente):
    """Ataque: depois de a foto passar na S4, fazer o gesto com o próprio rosto
    borrado de propósito: sem quadro aprovado, nenhuma conferência aconteceria."""
    caio = ambiente.criar("caio", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    sessao.informar_credenciais(caio.matricula, SENHA_N3)
    alimentar(sessao, 5)
    assert sessao.andamento.etapa is Etapa.DESAFIO
    sessao.s.criar_detector = lambda _: type("Sempre", (), {"alimentar": lambda s, r: True,
                                                             "progresso": 1.0})()
    andamento = alimentar(sessao, 30, boa=False)          # gesto "feito", rosto nunca conferido
    assert andamento.etapa is Etapa.DESAFIO and "olhe para a câmera" in andamento.mensagem
    ambiente.relogio.avancar(ambiente.p.timeout_desafio + 1)
    assert sessao.processar(quadro(boa=False)).decisao.motivo is Motivo.VIVACIDADE_NAO_CONFIRMADA


def test_n3_conferencias_antes_do_gesto_nao_valem(ambiente):
    """Ataque: a foto da vítima aparece em quadros bons (conferidos) e é trocada
    pelo rosto do atacante, borrado, para fazer o gesto. As conferências têm de
    vir depois do gesto."""
    caio = ambiente.criar("caio", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    sessao.informar_credenciais(caio.matricula, SENHA_N3)
    alimentar(sessao, 5)
    feito = {"n": 0}

    class GestoNoTerceiro:
        progresso = 0.0

        def alimentar(self, r):
            feito["n"] += 1
            return feito["n"] >= 3
    sessao.s.criar_detector = lambda _: GestoNoTerceiro()
    alimentar(sessao, 2)                                   # foto da vítima: quadros bons
    alimentar(sessao, 1, boa=False)                        # troca: gesto feito com rosto borrado
    andamento = alimentar(sessao, 10, boa=False)           # e nunca mais um quadro conferido
    assert andamento.etapa is Etapa.DESAFIO and andamento.desafio_indice == 1


def _n3_com_desafios(ambiente, desafios):
    ambiente.p.desafios, ambiente.p.gesto_obrigatorio = tuple(desafios), None
    caio = ambiente.criar("caio", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    sessao.informar_credenciais(caio.matricula, SENHA_N3)
    alimentar(sessao, 5)
    criados = []

    def fabrica(_):
        criados.append(1)
        return type("G", (), {"alimentar": lambda s, r: False, "progresso": 0.5})()
    sessao.s.criar_detector = fabrica
    return sessao, criados


def test_n3_rosto_que_some_reinicia_a_piscada(ambiente):
    sessao, criados = _n3_com_desafios(ambiente, ["PISCAR"])
    andamento = sessao.processar(quadro(faces=0))
    assert criados and "dentro do quadro" in andamento.mensagem


def test_n3_rosto_que_some_ao_virar_nao_reinicia_o_mover(ambiente):
    """Virando a cabeça, o detector frontal perde o rosto por instantes: o mover não recomeça."""
    sessao, criados = _n3_com_desafios(ambiente, ["MOVER_ESQUERDA"])
    andamento = sessao.processar(quadro(faces=0))
    assert not criados and andamento.etapa is Etapa.DESAFIO and "dentro do quadro" not in andamento.mensagem


def test_matricula_gigante_nega_como_inexistente_sem_erro_interno(ambiente):
    sessao = ambiente.servico.nova_sessao(2)
    andamento = sessao.informar_credenciais("A" * 500, "qualquer")
    assert andamento.decisao.motivo is Motivo.USUARIO_INEXISTENTE      # não ERRO_INTERNO
    assert ambiente.tentativas.obter("A" * 20) is None                # nada gravado


# login de entrada e step-up
class TrilhaFalsa:
    def __init__(self):
        self.eventos = []

    def registrar(self, evento, resultado, motivo, **campos):
        self.eventos.append((evento, resultado, motivo, campos))


def entrar(amb, usuario, senha, distancia=30.0):
    """Login de entrada completo; devolve (sessão, identidade comprovada)."""
    amb.rec.distancias = {usuario.id: distancia}
    sessao = amb.servico.nova_entrada()
    assert sessao.andamento.etapa is Etapa.CREDENCIAIS
    sessao.informar_credenciais(usuario.matricula, senha)
    alimentar(sessao, amb.p.frames_confirmacao)
    return sessao, sessao.identidade_comprovada


def test_entrada_servidor_entra_com_matricula_senha_e_rosto(ambiente):
    ana = ambiente.criar("ana", 1, "servidor2026")
    sessao, identidade = entrar(ambiente, ana, "servidor2026")
    assert sessao.andamento.decisao.concedido                 # o servidor (N1) também entra
    assert sessao.andamento.decisao.fatores_avaliados == "S1,S2,S3,S4,S5"
    assert identidade.usuario_id == ana.id and identidade.matricula == ana.matricula


def test_entrada_usa_o_limiar_do_nivel_2(ambiente):
    # limiares próprios, com folga entre o N1 e o N2 (no config os dois podem ser iguais)
    ambiente.p.acesso = dataclasses.replace(ambiente.p.acesso,
                                            limiares={Nivel.N1: 70.0, Nivel.N2: 60.0, Nivel.N3: 50.0})
    ana = ambiente.criar("ana", 1, "servidor2026")
    limiares = ambiente.p.acesso.limiares
    entre = (limiares[Nivel.N1] + limiares[Nivel.N2]) / 2     # passaria no N1, não no N2
    sessao, identidade = entrar(ambiente, ana, "servidor2026", distancia=entre)
    assert esgotar_prazo(ambiente, sessao).decisao.motivo is Motivo.CREDENCIAL_ALHEIA
    assert identidade is None


def test_entrada_senha_errada_conta_para_a_contencao(ambiente):
    ana = ambiente.criar("ana", 1, "servidor2026")
    sessao = ambiente.servico.nova_entrada()
    assert sessao.informar_credenciais(ana.matricula, "errada000").decisao.motivo is Motivo.SENHA_INCORRETA
    assert ambiente.tentativas.obter(ana.matricula).falhas == 1


def test_entrada_inativo_nao_entra(ambiente):
    ana = ambiente.criar("ana", 1, "servidor2026", ativo=False)
    sessao, identidade = entrar(ambiente, ana, "servidor2026")
    assert sessao.andamento.decisao.motivo is Motivo.USUARIO_INATIVO and identidade is None


def test_identidade_so_vem_de_login_de_entrada(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    ambiente.rec.distancias = {bia.id: 30.0}
    sessao = ambiente.servico.nova_sessao(2)                  # acesso a nível, não login
    sessao.informar_credenciais(bia.matricula, SENHA_N2)
    alimentar(sessao, ambiente.p.frames_confirmacao)
    assert sessao.andamento.decisao.concedido and sessao.identidade_comprovada is None


def test_step_up_n2_abre_com_as_evidencias_do_login_e_so_a_propria_camada(ambiente):
    """O diretor abre só a camada do perfil, não o N1 (escopo exclusivo)."""
    bia = ambiente.criar("bia", 2, SENHA_N2)
    _, identidade = entrar(ambiente, bia, SENHA_N2)
    assert ambiente.servico.abrir_nivel(identidade, 1).motivo is Motivo.NIVEL_INSUFICIENTE
    assert ambiente.servico.abrir_nivel(identidade, 2).concedido
    assert not ambiente.servico.abrir_nivel(identidade, 3).concedido     # N3 nunca abre sem vivacidade


def test_step_up_servidor_nao_abre_o_nivel_2(ambiente):
    ana = ambiente.criar("ana", 1, "servidor2026")
    _, identidade = entrar(ambiente, ana, "servidor2026")
    assert ambiente.servico.abrir_nivel(identidade, 2).motivo is Motivo.NIVEL_INSUFICIENTE


def test_step_up_rele_o_cadastro_desativar_vale_na_proxima_aba(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    _, identidade = entrar(ambiente, bia, SENHA_N2)
    ambiente.usuarios.atualizar(dataclasses.replace(ambiente.usuarios.por_id(bia.id), ativo=False))
    assert ambiente.servico.abrir_nivel(identidade, 2).motivo is Motivo.USUARIO_INATIVO


def test_step_up_n3_comeca_no_rosto_e_pede_vivacidade_e_segunda_pessoa(ambiente):
    caio, dora = ambiente.criar("caio", 3, SENHA_N3), ambiente.criar("dora", 3, SENHA_N3)
    _, identidade = entrar(ambiente, caio, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0, dora.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3, identidade=identidade)
    assert sessao.andamento.etapa is Etapa.ROSTO                   # sem pedir matrícula e senha de novo
    alimentar(sessao, ambiente.p.frames_confirmacao)
    assert sessao.andamento.etapa is Etapa.DESAFIO                 # o que o login não provou
    for _ in range(ambiente.p.quantidade_desafios):
        andamento = alimentar(sessao, 2 + ambiente.p.conferidos_minimos)
    assert andamento.etapa is Etapa.CREDENCIAIS and andamento.pessoa == 2
    andamento = autenticar_pessoa_n3(ambiente, sessao, dora)
    assert andamento.decisao.concedido and andamento.decisao.fatores_avaliados == "S1,S2,S3,S4,S5,S6,S7"


def test_step_up_n3_rosto_de_outra_pessoa_e_negado(ambiente):
    caio, eva = ambiente.criar("caio", 3, SENHA_N3), ambiente.criar("eva", 3, SENHA_N3)
    _, identidade = entrar(ambiente, caio, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 95.0, eva.id: 20.0}        # outra pessoa sentou diante da tela
    sessao = ambiente.servico.nova_sessao(3, identidade=identidade)
    alimentar(sessao, 10)
    assert esgotar_prazo(ambiente, sessao).decisao.motivo is Motivo.CREDENCIAL_ALHEIA
    assert ambiente.tentativas.obter(f"{caio.matricula}#N3").falhas == 1   # conta para a contenção do N3
    assert ambiente.tentativas.obter(caio.matricula).falhas == 0          # o login segue livre


def test_step_up_n3_com_senha_fraca_no_login_e_negado(ambiente):
    caio = ambiente.criar("caio", 3, "fraca123")
    _, identidade = entrar(ambiente, caio, "fraca123")             # o login (fatores do N2) aceita
    assert identidade is not None and identidade.senha_forte is False
    sessao = ambiente.servico.nova_sessao(3, identidade=identidade)
    assert sessao.andamento.decisao.motivo is Motivo.SENHA_FRACA   # o N3 não


def test_conferencia_do_administrador_exige_o_rosto_do_logado(ambiente):
    caio = ambiente.criar("caio", 3, SENHA_N3)
    _, identidade = entrar(ambiente, caio, SENHA_N3)
    sessao = ambiente.servico.nova_verificacao_admin(identidade)
    assert sessao.andamento.etapa is Etapa.ROSTO
    ambiente.rec.distancias = {caio.id: 30.0}
    assert alimentar(sessao, ambiente.p.frames_confirmacao).decisao.concedido
    outra = ambiente.servico.nova_verificacao_admin(identidade)
    ambiente.rec.distancias = {caio.id: 95.0}
    alimentar(outra, 5)
    assert not esgotar_prazo(ambiente, outra).decisao.concedido


def test_trilha_distingue_entrada_step_up_e_administrador(ambiente):
    trilha = ambiente.servico.trilha = TrilhaFalsa()
    bia = ambiente.criar("bia", 2, SENHA_N2)               # o step-up é o da camada dela
    _, identidade = entrar(ambiente, bia, SENHA_N2)
    ambiente.servico.abrir_nivel(identidade, 2)
    sessao = ambiente.servico.nova_verificacao_admin(identidade)
    alimentar(sessao, ambiente.p.frames_confirmacao)
    eventos = [(e, r, c.get("nivel_solicitado"), c.get("detalhe")) for e, r, _, c in trilha.eventos]
    assert eventos[0][:3] == ("ENTRADA", "CONCEDIDO", None)
    assert eventos[1][:3] == ("AUTENTICACAO", "CONCEDIDO", 2) and "step-up" in eventos[1][3]
    assert eventos[2][:2] == ("ADMIN", "CONCEDIDO") and "administrador" in eventos[2][3]


def test_step_up_sem_trilha_nao_abre(ambiente):
    class TrilhaFora:
        def registrar(self, *a, **k):
            raise ConnectionError("banco fora do ar")
    bia = ambiente.criar("bia", 2, SENHA_N2)
    _, identidade = entrar(ambiente, bia, SENHA_N2)
    ambiente.servico.trilha = TrilhaFora()
    assert ambiente.servico.abrir_nivel(identidade, 2).motivo is Motivo.ERRO_INTERNO


def test_n3_sem_regra_dos_dois_conclui_com_rosto_senha_e_vivacidade(ambiente):
    ambiente.servico.p.acesso = dataclasses.replace(ambiente.p.acesso, exigir_segunda_pessoa=False)
    caio = ambiente.criar("caio", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0}
    andamento = autenticar_pessoa_n3(ambiente, ambiente.servico.nova_sessao(3), caio)
    assert andamento.decisao.concedido
    assert andamento.decisao.fatores_avaliados == "S1,S2,S3,S4,S5,S6"      # a S7 não vira "aprovada" sem avaliar


# piscada no step-up do N3
class OlhosGravados:
    """A abertura do olho (EAR) que a câmera "vê" agora. Só a medida do olho é falsa:
    o detector do gesto é o real (DetectorGesto), o mesmo do N3."""

    def __init__(self):
        self.ear = 0.30

    def medir(self, _):
        return MedidaOlhos(1, 100.0, ear=self.ear)


OLHO_PISCANDO = [0.30] * 6 + [0.12, 0.12] + [0.30]      # aberto, fechado em 2 quadros, reaberto
OLHO_DE_FOTO = [0.30]                                     # a abertura do olho numa foto não muda


def quadro_em(x):
    """Quadro bom com o rosto na posição x (a distância vem do reconhecedor falso)."""
    return ResultadoQuadro(faces=((x, 100, 100, 100),), fonte="HAAR", largura=640, altura=480,
                           recorte_cinza=np.zeros((100, 100), np.uint8),
                           face_normalizada=np.zeros((200, 200), np.uint8))


def detector_real(amb):
    import dataclasses
    olhos = OlhosGravados()
    gestos = dataclasses.replace(amb.p.gestos, sinal_piscada="ear")        # a medida falsa é a do contorno (EAR)
    amb.servico.criar_detector = lambda gesto: DetectorGesto(gesto, gestos, olhos)
    return olhos


def fazer_o_que_a_tela_pede(amb, sessao, olhos, aberturas, quadros=400):
    """Quadro a quadro (15 por segundo): desliza o rosto 10 px por quadro quando a tela
    pede deslizar; os olhos seguem aberturas quando ela pede piscar.
    Devolve o andamento final e os gestos pedidos, na ordem."""
    pedidos, atual, passo = [], None, 0
    for _ in range(quadros):
        a = sessao.andamento
        if a.decisao is not None:
            break
        if (a.desafio_indice, a.desafio) != atual:             # gesto novo: recomeça do centro
            atual, passo = (a.desafio_indice, a.desafio), 0
            pedidos.append(a.desafio)
        olhos.ear = aberturas[min(passo, len(aberturas) - 1)]
        lado = {Desafio.MOVER_ESQUERDA: 1, Desafio.MOVER_DIREITA: -1}.get(a.desafio, 0)
        passo += 1
        amb.relogio.avancar(1 / 15)
        sessao.processar(quadro_em(200 + lado * 10 * min(passo, 4)))     # até 0,4 da largura da face
    return sessao.andamento, pedidos


def step_up_n3_com_detector_real(amb):
    amb.servico.p.acesso = dataclasses.replace(amb.p.acesso, exigir_segunda_pessoa=False)
    caio = amb.criar("caio", 3, SENHA_N3)
    _, identidade = entrar(amb, caio, SENHA_N3)
    olhos = detector_real(amb)
    sessao = amb.servico.nova_sessao(3, identidade=identidade)
    alimentar(sessao, amb.p.frames_confirmacao)                # rosto
    assert sessao.andamento.etapa is Etapa.DESAFIO
    return sessao, olhos


def test_piscada_e_detectada_em_sequencia_de_quadros(ambiente):
    """Com o config do projeto, o step-up do N3 pede a piscada, e uma piscada de verdade
    (olho aberto, fechado em 2 quadros, reaberto), pelo detector real, conclui o acesso."""
    sessao, olhos = step_up_n3_com_detector_real(ambiente)
    andamento, pedidos = fazer_o_que_a_tela_pede(ambiente, sessao, olhos, OLHO_PISCANDO)
    assert Desafio.PISCAR in pedidos, f"o step-up não pediu a piscada: {pedidos}"
    assert andamento.decisao.concedido, str(andamento.decisao)
    assert andamento.decisao.fatores_avaliados == "S1,S2,S3,S4,S5,S6"


def test_piscada_nao_e_detectada_em_quadros_estaticos(ambiente):
    """Ataque de foto (s6_vivacidade.py:44-47): o atacante mostra a foto impressa da vítima
    e a desliza quando a tela pede; o olho da foto nunca fecha. Só com os deslizes, a foto
    passava na prova de vida; com a piscada, o N3 nega."""
    sessao, olhos = step_up_n3_com_detector_real(ambiente)
    andamento, pedidos = fazer_o_que_a_tela_pede(ambiente, sessao, olhos, OLHO_DE_FOTO)
    assert not andamento.decisao.concedido, f"a foto deslizada passou na prova de vida (gestos: {pedidos})"
    assert andamento.decisao.motivo is Motivo.VIVACIDADE_NAO_CONFIRMADA


def test_step_up_n3_exige_piscada_quando_configurada(ambiente):
    """Config do projeto: os três gestos no sorteio e a piscada em toda sequência, em
    posição sorteada; o outro gesto continua imprevisível."""
    ambiente.servico.p.acesso = dataclasses.replace(ambiente.p.acesso, exigir_segunda_pessoa=False)
    ambiente.servico.gerador = random.Random(2026)            # determinístico só no teste
    caio = ambiente.criar("caio", 3, SENHA_N3)
    _, identidade = entrar(ambiente, caio, SENHA_N3)
    sequencias = []
    for _ in range(30):
        sessao = ambiente.servico.nova_sessao(3, identidade=identidade)
        alimentar(sessao, ambiente.p.frames_confirmacao)
        pedidos = []
        for _ in range(ambiente.p.quantidade_desafios):        # gesto falso: 2 quadros + conferência pós-gesto
            pedidos.append(sessao.andamento.desafio)
            andamento = alimentar(sessao, 2 + ambiente.p.conferidos_minimos)
        assert andamento.decisao.concedido
        sequencias.append(tuple(pedidos))
    sem_piscada = [s for s in sequencias if Desafio.PISCAR not in s]
    assert not sem_piscada, f"{len(sem_piscada)} de 30 sequências sem piscada: {sem_piscada[:3]}"
    assert {s.index(Desafio.PISCAR) for s in sequencias} == {0, 1}
    assert {d for s in sequencias for d in s} == set(Desafio)


def test_step_up_n3_aceita_apenas_deslizar_quando_configurado(ambiente):
    """Com só os deslizes e sem gesto
    obrigatório (o config), o N3 conclui deslizando o rosto, sem piscar."""
    ambiente.p.desafios, ambiente.p.gesto_obrigatorio = ("MOVER_ESQUERDA", "MOVER_DIREITA"), None
    sessao, olhos = step_up_n3_com_detector_real(ambiente)
    andamento, pedidos = fazer_o_que_a_tela_pede(ambiente, sessao, olhos, OLHO_DE_FOTO)
    assert len(pedidos) == ambiente.p.quantidade_desafios
    assert set(pedidos) <= {Desafio.MOVER_ESQUERDA, Desafio.MOVER_DIREITA}
    assert andamento.decisao.concedido, str(andamento.decisao)


# contenção do step-up e tela de bloqueio
def falhar_gesto_n3(amb, identidade, usuario):
    amb.rec.distancias = {usuario.id: 30.0}
    sessao = amb.servico.nova_sessao(3, identidade=identidade)
    alimentar(sessao, amb.p.frames_confirmacao)                  # rosto confere
    assert sessao.andamento.etapa is Etapa.DESAFIO
    amb.relogio.avancar(amb.p.timeout_desafio + 1)               # o gesto não é detectado a tempo
    return sessao.processar(quadro())


def test_falhar_o_gesto_do_n3_tranca_so_o_n3_e_nao_o_login(ambiente):
    """Regressão: três gestos não detectados no N3 trancavam o login inteiro."""
    caio = ambiente.criar("caio", 3, SENHA_N3)
    _, identidade = entrar(ambiente, caio, SENHA_N3)
    for _ in range(ambiente.p.contencao.tentativas_maximas):
        assert falhar_gesto_n3(ambiente, identidade, caio).decisao.motivo is Motivo.VIVACIDADE_NAO_CONFIRMADA
    bloqueada = ambiente.servico.nova_sessao(3, identidade=identidade)
    assert bloqueada.andamento.decisao.motivo is Motivo.BLOQUEADO           # o N3 ficou trancado
    assert bloqueada.andamento.bloqueado_ate is not None                     # e a tela diz até quando
    # a matrícula não ficou bloqueada: fora do N3 a negação é pelo perfil (S5), não pela contenção (S1)
    assert ambiente.servico.abrir_nivel(identidade, 2).motivo is Motivo.NIVEL_INSUFICIENTE
    _, de_novo = entrar(ambiente, caio, SENHA_N3)                            # e o login também
    assert de_novo is not None


def test_matricula_bloqueada_informa_ate_quando(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    for _ in range(ambiente.p.contencao.tentativas_maximas):
        ambiente.servico.nova_entrada().informar_credenciais(bia.matricula, "errada000")
    andamento = ambiente.servico.nova_entrada().informar_credenciais(bia.matricula, SENHA_N2)
    assert andamento.decisao.motivo is Motivo.BLOQUEADO and andamento.bloqueado_ate > ambiente.relogio.agora()


def test_credenciais_comecam_destacando_a_s1(ambiente):
    from ecosec.dominio.camadas import CamadaSeguranca as C
    andamento = ambiente.servico.nova_entrada().andamento
    assert andamento.etapa is Etapa.CREDENCIAIS and andamento.atual is C.S1_CONTENCAO   # a S1 vem primeiro
    mensagem = andamento.mensagem.lower()
    assert "matrícula" in mensagem and "senha" in mensagem         # pede as credenciais
    assert "(S1)" not in andamento.mensagem                       # sem a sigla da camada
    for detalhe in ("primeiro", "depois", "confere"):              # nem a ordem das verificações
        assert detalhe not in mensagem, detalhe


def test_desbloquear_a_sessao_com_a_senha_do_logado(ambiente):
    trilha = ambiente.servico.trilha = TrilhaFalsa()
    bia = ambiente.criar("bia", 2, SENHA_N2)
    _, identidade = entrar(ambiente, bia, SENHA_N2)
    assert ambiente.servico.desbloquear(identidade, "errada000") is Motivo.SENHA_INCORRETA
    assert ambiente.servico.desbloquear(identidade, SENHA_N2) is Motivo.CONCEDIDO
    assert ambiente.tentativas.obter(bia.matricula).falhas == 0
    assert [(e, r, m) for e, r, m, _ in trilha.eventos[-2:]] == [("SESSAO", "NEGADO", "SENHA_INCORRETA"),
                                                                  ("SESSAO", "CONCEDIDO", "DESBLOQUEIO")]


def test_adivinhar_a_senha_na_tela_de_bloqueio_tranca_a_conta(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    _, identidade = entrar(ambiente, bia, SENHA_N2)
    motivos = [ambiente.servico.desbloquear(identidade, f"errada{i:03d}")
               for i in range(ambiente.p.contencao.tentativas_maximas)]
    assert motivos[-1] is Motivo.BLOQUEADO
    assert ambiente.servico.desbloquear(identidade, SENHA_N2) is Motivo.BLOQUEADO   # nem a certa, agora



def test_quadro_borrado_isolado_no_gesto_nao_nega(ambiente):
    """O rosto em movimento se afasta do modelo; só divergências SEGUIDAS negam."""
    caio = ambiente.criar("caio", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    sessao.informar_credenciais(caio.matricula, SENHA_N3)
    alimentar(sessao, ambiente.p.frames_confirmacao)
    sessao.s.criar_detector = lambda _: type("Nunca", (), {"alimentar": lambda s, r: False, "progresso": 0.0})()
    sessao._proximo_gesto()
    for i in range(12):                                       # borrado, bom, borrado, bom...
        ambiente.rec.distancias = {caio.id: 90.0 if i % 2 == 0 else 30.0}
        andamento = sessao.processar(quadro())
    assert andamento.decisao is None and andamento.etapa is Etapa.DESAFIO


def test_rosto_em_movimento_dentro_da_tolerancia_nao_diverge(ambiente):
    caio = ambiente.criar("caio", 3, SENHA_N3)
    ambiente.rec.distancias = {caio.id: 30.0}
    sessao = ambiente.servico.nova_sessao(3)
    sessao.informar_credenciais(caio.matricula, SENHA_N3)
    alimentar(sessao, ambiente.p.frames_confirmacao)
    limiar_n3 = ambiente.p.acesso.limiares[Nivel.N3]
    ambiente.rec.distancias = {caio.id: (limiar_n3 + ambiente.p.limiar_durante_gesto) / 2}   # acima do N3, abaixo da tolerância
    andamento = alimentar(sessao, 15)
    assert andamento.decisao is None or andamento.decisao.motivo is not Motivo.VIVACIDADE_NAO_CONFIRMADA
