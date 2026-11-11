"""De ponta a ponta, sobre o MySQL (bancos descartáveis ecosec_teste_*): a governança dos administradores
como o grupo vai usar, inclusive fechando e reabrindo o sistema no meio.

Monta a aplicação de verdade (montar, modo "mysql") com o .env, o modelo facial e os bancos em lugares
temporários: nada do banco real, do .env real nem do modelo/lbph.enc real é tocado.
Pula (não aprova) se o MySQL não estiver preparado nesta máquina.
"""
import copy
from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest

from ecosec import segredos
from ecosec.aplicacao import montar
from ecosec.configuracao import Configuracao, carregar
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import Perfil
from ecosec.seguranca.acesso import totp
from ecosec.servicos.cadastro import DadosCadastro
from ecosec.visao.pipeline import ResultadoQuadro
from ecosec.visao.qualidade import MedidasQualidade

CFG = carregar()
SENHA_INSTALACAO = "Instala#2026x"
SENHAS = {"ANA": "Ministra#2026a", "BRUNO": "Ministro#2026b", "CAIO": "Ministro#2026c"}


def face(semente):
    base = np.random.default_rng(semente).integers(40, 215, (50, 50)).astype(np.uint8)
    return cv2.resize(base, (200, 200), interpolation=cv2.INTER_LINEAR)


def quadro(semente):
    return ResultadoQuadro(faces=((220, 120, 200, 200),), fonte="HAAR", largura=640, altura=480,
                           medidas=MedidasQualidade(300, 120, 40, 2), face_normalizada=face(semente),
                           recorte_cinza=np.zeros((10, 10), np.uint8))


@pytest.fixture
def ambiente(banco_mysql_limpo, acervo_mysql, tmp_path):
    """Config apontando para os bancos de teste e um .env temporário com a conta de testes."""
    dados = copy.deepcopy(CFG._dados)
    dados["banco"]["seguranca"] = banco_mysql_limpo.p.banco
    dados["banco"]["acervo"] = acervo_mysql.p.banco
    dados["caminhos"]["modelo"] = str(tmp_path / "modelo")            # Nunca o modelo/lbph.enc real
    (tmp_path / "modelo").mkdir()
    env = tmp_path / ".env"
    for chave_usuario, chave_senha in ((segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA),
                                       (segredos.DB_ACERVO_USUARIO, segredos.DB_ACERVO_SENHA)):
        segredos.gravar(chave_usuario, banco_mysql_limpo.p.usuario, env)
        segredos.gravar(chave_senha, banco_mysql_limpo.p.senha, env)
    return Configuracao(dados, CFG.origem), env


def abrir(cfg, env):
    app = montar(cfg, env, modo="mysql")
    app.autenticacao.contexto_parametros = None          # o MFA adaptativo tem testes próprios
    app.administracao.custo = app.cadastro.custo = app.autenticacao.p.custo_bcrypt = 4
    app.cadastro.frames_por_sessao = 3
    return app


def cadastrar(app, nome, nivel, senha, semente, perfil=None):
    aceite = app.cadastro.registrar_aceite(nome)
    coleta = app.cadastro.nova_coleta(aceite)
    for s in range(2):
        for i in range(3):
            coleta.oferecer(quadro(semente + 10 * s + i))
        if s == 0:
            coleta.avancar_sessao()
    return app.cadastro.concluir(DadosCadastro(nome, nivel, None, senha, senha, perfil=perfil), aceite, coleta)


def login(app, usuario, senha, semente, rosto_falha=False):
    sessao = app.autenticacao.nova_entrada()
    sessao.informar_credenciais(usuario.matricula, senha)
    if rosto_falha:
        sessao.cancelar()                                 # o mesmo que a câmera falhar no meio do rosto
        return sessao
    for i in range(app.autenticacao.p.frames_confirmacao):
        sessao.processar(quadro(semente + i))
    return sessao


def daqui_a(segundos):
    return datetime.now() + timedelta(seconds=segundos)


def test_governanca_de_ponta_a_ponta_no_mysql(ambiente):
    cfg, env = ambiente
    app = abrir(cfg, env)
    adm = app.administracao

    # ---- configuração inicial: senha de instalação e os cadastros (rosto no modelo, no disco temporário)
    assert adm.definir_senha_inicial(SENHA_INSTALACAO, SENHA_INSTALACAO) == []
    ana = cadastrar(app, "Ana Lima", Nivel.N3, SENHAS["ANA"], 100)
    # só um Externo (sem camada) vira administrador
    bruno = cadastrar(app, "Bruno Reis", None, SENHAS["BRUNO"], 200, perfil=Perfil.EXTERNO)
    caio = cadastrar(app, "Caio Dias", None, SENHAS["CAIO"], 300, perfil=Perfil.EXTERNO)
    duda = cadastrar(app, "Duda Melo", Nivel.N1, "servidora2026", 400)

    # ---- atualização de uma versão antiga: o admin único do .env passa para o banco ao abrir
    segredos.gravar(segredos.ADMIN_MATRICULA, ana.matricula, env)
    app = abrir(cfg, env)
    adm = app.administracao
    assert adm.eh_administrador(ana.id) and segredos.ler(segredos.ADMIN_MATRICULA, env) is None

    # ---- login único: Ana entra e é admin; a migração do .env a fez Externo com o papel de administrador, sem
    # camada: nenhuma aba do acervo
    entrada = login(app, ana, SENHAS["ANA"], 100)
    sessao = app.sessao.abrir(entrada)
    assert sessao is not None and sessao.administrador and sessao.niveis_com_aba == ()
    assert adm.usuario(ana.id).perfil.value == "EXTERNO" and adm.usuario(ana.id).nivel is None

    # ---- celulares e designação: implantação (sozinha) e depois com aprovação
    segredo = {}
    for pessoa in (ana,):
        novo = adm.novo_celular(pessoa.id)
        recuperacao_ana = adm.confirmar_celular(pessoa.id, novo, totp.codigo(novo.segredo, datetime.now()))
        segredo[pessoa.id] = novo.segredo
    assert len(recuperacao_ana) == 8
    assert adm.tornar_administrador(ana.id, bruno.id) is None                           # implantação
    novo = adm.novo_celular(bruno.id)
    recuperacao_bruno = adm.confirmar_celular(bruno.id, novo, totp.codigo(novo.segredo, datetime.now()))
    segredo[bruno.id] = novo.segredo
    assert adm.tornar_administrador(ana.id, caio.id, "000000")                          # código errado: recusa
    assert adm.tornar_administrador(ana.id, caio.id, totp.codigo(segredo[bruno.id], daqui_a(30))) is None
    novo = adm.novo_celular(caio.id)
    recuperacao_caio = adm.confirmar_celular(caio.id, novo, totp.codigo(novo.segredo, datetime.now()))
    segredo[caio.id] = novo.segredo

    # ---- o sistema fecha e abre de novo: tudo vem do banco (papéis, celular cifrado, rostos)
    app = abrir(cfg, env)
    adm = app.administracao
    assert {a.usuario_id for a in adm.administradores_ativos()} == {ana.id, bruno.id, caio.id}
    designacao_caio = adm.administradores.obter(caio.id)
    assert designacao_caio.designado_por == ana.id and designacao_caio.aprovado_por == bruno.id
    assert login(app, bruno, SENHAS["BRUNO"], 200).andamento.decisao.concedido      # rosto lido do disco
    assert adm.conferir_codigo_celular(ana.id, totp.codigo(segredo[ana.id], daqui_a(30)))[0] is Motivo.CONCEDIDO
    assert adm.conferir_codigo_celular(ana.id, recuperacao_ana[0])[0] is Motivo.CONCEDIDO   # perdeu o celular
    assert adm.conferir_codigo_celular(ana.id, recuperacao_ana[0])[0] is Motivo.CODIGO_INCORRETO  # uso único

    # ---- ação crítica com aprovação, e o mínimo de administradores
    assert adm.revogar_consentimento(duda.id, ana.id)                                   # sem o 2º admin: não
    assert adm.revogar_consentimento(duda.id, ana.id, totp.codigo(segredo[caio.id], daqui_a(30))) is None
    assert duda.id not in app.reconhecedor.rotulos()                                   # rosto eliminado
    assert adm.registrar_revisao(bruno.id, recuperacao_caio[0]) is None

    # ---- acesso de emergência: Ana acerta a senha, a câmera falha, o quórum (B e C) abre
    barrada = login(app, ana, SENHAS["ANA"], 100, rosto_falha=True)
    assert not barrada.andamento.decisao.concedido and barrada.credenciais_sem_rosto.id == ana.id
    assert adm.pode_oferecer_emergencia(ana.id)
    quorum = adm.nova_emergencia(ana.id)
    assert quorum.informar("000000").aceitos == 0
    assert quorum.informar(recuperacao_bruno[0]).aceitos == 1
    emergencia = quorum.informar(recuperacao_caio[1]).concedida
    assert emergencia is not None
    restrita = app.sessao.abrir_emergencia(emergencia)
    assert restrita.em_emergencia and restrita.niveis_com_aba == ()
    assert adm.refazer_celular(ana.id, ana.id, emergencia=emergencia) is None           # conserta o acesso
    assert not adm.celular_cadastrado(ana.id) and adm.codigos_restantes(ana.id) == 0

    # ---- a trilha encadeada no banco continua íntegra e conta a história com os dois nomes
    assert adm.verificar_trilha().integra
    motivos = [r.evento.motivo for r in adm.trilha_recente(500)]
    for esperado in ("ADMIN_MIGRADO", "CELULAR_CADASTRADO", "TORNAR_ADMINISTRADOR", "REVOGAR_CONSENTIMENTO",
                     "REVISAO_ACESSOS", "EMERGENCIA_ABERTA", "REFAZER_CELULAR", "APROVACAO_RECUSADA"):
        assert esperado in motivos, esperado
