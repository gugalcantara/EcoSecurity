"""Anel 3, S10 Trilha: encadeamento, adulteração localizada, "sem registro, sem acesso"."""
from datetime import datetime, timedelta

import pytest

from ecosec.dominio.entidades import EventoTrilha, RegistroTrilha
from ecosec.dominio.motivos import Motivo
from ecosec.repositorios.memoria import RepositorioTrilhaMemoria
from ecosec.seguranca.evidencia import s10_trilha
from ecosec.servicos.trilha import ServicoTrilha

T0 = datetime(2026, 10, 6, 14, 0, 0, 123456)


def evento(i, **extra):
    base = dict(momento=T0 + timedelta(seconds=i), evento="AUTENTICACAO", resultado="NEGADO",
                motivo="SENHA_INCORRETA", camadas="S1,S2", nivel_solicitado=2, matricula_informada=f"M{i}")
    return EventoTrilha(**{**base, **extra})


def cadeia(n):
    registros, anterior = [], None
    for i in range(1, n + 1):
        r = s10_trilha.encadear(evento(i), anterior)
        registros.append(RegistroTrilha(r.evento, r.hash_anterior, r.hash_registro, i))
        anterior = r.hash_registro
    return registros


def adulterar(r: RegistroTrilha, **campos) -> RegistroTrilha:
    return RegistroTrilha(EventoTrilha(**{**r.evento.__dict__, **campos}), r.hash_anterior, r.hash_registro, r.id)


# ================================================================ lógica pura
def test_primeiro_registro_aponta_a_genese():
    assert cadeia(1)[0].hash_anterior == s10_trilha.GENESE


def test_trilha_integra():
    resultado = s10_trilha.verificar(cadeia(10))
    assert resultado.integra and resultado.registros_verificados == 10


def test_alterar_conteudo_e_localizado_na_propria_linha():
    registros = cadeia(10)
    registros[4] = adulterar(registros[4], resultado="CONCEDIDO")      # negado vira concedido
    resultado = s10_trilha.verificar(registros)
    assert (resultado.integra, resultado.id_rompido, resultado.problema) == (False, 5, "REGISTRO_ALTERADO")


def test_alterar_e_recalcular_o_hash_quebra_a_linha_seguinte():
    registros = cadeia(10)
    falso = adulterar(registros[4], resultado="CONCEDIDO")
    novo_hash = s10_trilha.calcular_hash(falso.evento, falso.hash_anterior)
    registros[4] = RegistroTrilha(falso.evento, falso.hash_anterior, novo_hash, 5)
    resultado = s10_trilha.verificar(registros)
    assert (resultado.id_rompido, resultado.problema) == (6, "ENCADEAMENTO_ROMPIDO")


def test_apagar_uma_linha_do_meio_e_detectado():
    registros = cadeia(10)
    del registros[3]
    assert s10_trilha.verificar(registros).id_rompido == 5


def test_limite_declarado_apagar_o_final_nao_quebra_a_corrente():
    """A corrente sozinha não vê: quem detecta é a âncora fora do banco (test_ancora_trilha.py)."""
    assert s10_trilha.verificar(cadeia(10)[:7]).integra


def test_serializacao_sem_ambiguidade():
    a = s10_trilha.calcular_hash(evento(1, motivo="A|B", camadas="C"), s10_trilha.GENESE)
    b = s10_trilha.calcular_hash(evento(1, motivo="A", camadas="B|C"), s10_trilha.GENESE)
    assert a != b


def test_distancia_arredondada_como_no_banco():
    r = s10_trilha.encadear(evento(1, distancia=41.123456789), None)
    assert r.evento.distancia == 41.1235
    assert s10_trilha.calcular_hash(r.evento, r.hash_anterior) == r.hash_registro


def test_mensagem_da_verificacao():
    registros = cadeia(3)
    registros[1] = adulterar(registros[1], motivo="CONCEDIDO")
    assert "registro 2" in str(s10_trilha.verificar(registros))


# ================================================================ repositório (memória e MySQL)
@pytest.fixture(params=["memoria", "mysql"])
def trilha(request):
    if request.param == "memoria":
        return ServicoTrilha(RepositorioTrilhaMemoria())
    from ecosec.repositorios.mysql import RepositorioTrilhaMySQL
    banco = request.getfixturevalue("banco_mysql_limpo")
    return ServicoTrilha(RepositorioTrilhaMySQL(banco))


def test_registrar_e_verificar(trilha):
    for i in range(5):
        trilha.registrar("AUTENTICACAO", "NEGADO", "SENHA_INCORRETA", camadas="S1,S2", nivel_solicitado=2,
                         matricula_informada=f"M{i}", distancia=None)
    trilha.registrar("CADASTRO", "REGISTRADO", "CADASTRO_CONCLUIDO", distancia=None)
    assert trilha.verificar().integra
    recentes = trilha.recentes(2)
    assert [r.evento.evento for r in recentes] == ["CADASTRO", "AUTENTICACAO"]


def test_ida_e_volta_preserva_o_hash(trilha):
    trilha.registrar("AUTENTICACAO", "CONCEDIDO", "CONCEDIDO", camadas="S3,S4,S5", nivel_solicitado=1,
                     distancia=33.33333, detalhe="ação com acentuação e \"aspas\"")
    assert trilha.verificar().integra                      # microssegundos, decimais e texto voltam iguais


def test_gravacoes_concorrentes_nao_bifurcam_a_corrente(trilha):
    import threading
    def gravar(n):
        for i in range(10):
            trilha.registrar("AUTENTICACAO", "NEGADO", "SENHA_INCORRETA", matricula_informada=f"T{n}{i}")
    threads = [threading.Thread(target=gravar, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    resultado = trilha.verificar()
    assert resultado.integra and resultado.registros_verificados == 40


def test_adulteracao_real_no_mysql_e_localizada(banco_mysql_limpo):
    """O que se demonstra na banca: alterar uma linha direto no banco (como root)."""
    from ecosec.repositorios.mysql import RepositorioTrilhaMySQL
    trilha = ServicoTrilha(RepositorioTrilhaMySQL(banco_mysql_limpo))
    ids = [trilha.registrar("AUTENTICACAO", "NEGADO", "SENHA_INCORRETA", matricula_informada=f"M{i}").id
           for i in range(6)]
    with banco_mysql_limpo.transacao() as c:                # a conta de teste tem UPDATE; a da aplicação, não
        c.execute("UPDATE log_acesso SET resultado = 'CONCEDIDO', motivo = 'CONCEDIDO' WHERE id = %s", (ids[3],))
    resultado = trilha.verificar()
    assert (resultado.integra, resultado.id_rompido) == (False, ids[3])


# ================================================================ integração com os serviços
def test_login_registra_o_desfecho_na_trilha(tmp_path):
    from ecosec.aplicacao import montar
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    app.autenticacao.p.custo_bcrypt = 4
    sessao = app.autenticacao.nova_sessao(2)
    sessao.informar_credenciais("NAOEXISTE", "senha errada")
    [registro] = app.autenticacao.trilha.recentes(5)
    ev = registro.evento
    assert (ev.evento, ev.resultado, ev.motivo, ev.matricula_informada) == \
           ("AUTENTICACAO", "NEGADO", "USUARIO_INEXISTENTE", "NAOEXISTE")
    assert ev.distancia is None and "senha" not in (ev.detalhe or "")


def test_sem_registro_sem_acesso():
    """Se a trilha não grava, um acesso que seria CONCEDIDO vira negação."""
    import numpy as np

    from ecosec.configuracao import carregar
    from ecosec.dominio.entidades import Consentimento, Usuario
    from ecosec.repositorios.memoria import (RepositorioConsentimentosMemoria, RepositorioTentativasMemoria,
                                             RepositorioUsuariosMemoria)
    from ecosec.servicos.autenticacao import ParametrosAutenticacao, ServicoAutenticacao
    from ecosec.visao.pipeline import ResultadoQuadro

    class TrilhaQuebrada:
        def registrar(self, *_a, **_k):
            raise OSError("disco cheio")

    class Reconhecedor:
        def identificar(self, _):
            return 1, 20.0

    usuarios, consentimentos = RepositorioUsuariosMemoria(), RepositorioConsentimentosMemoria()
    ana = usuarios.adicionar(Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x"))
    c = consentimentos.registrar(Consentimento("Ana", "1.1", "a" * 64, T0))
    consentimentos.vincular(c.id, ana.id)
    servico = ServicoAutenticacao(usuarios, RepositorioTentativasMemoria(), consentimentos, Reconhecedor(),
                                  ParametrosAutenticacao.de_configuracao(carregar()), trilha=TrilhaQuebrada())
    sessao = servico.nova_sessao(1)
    quadro = ResultadoQuadro(faces=((0, 0, 100, 100),), fonte="HAAR", largura=640, altura=480,
                             face_normalizada=np.zeros((200, 200), np.uint8))
    andamento = None
    for _ in range(servico.p.frames_confirmacao):
        andamento = sessao.processar(quadro)
    assert andamento.decisao.motivo is Motivo.ERRO_INTERNO and not andamento.decisao.concedido


def test_acoes_do_admin_vao_para_a_trilha(tmp_path):
    from ecosec.aplicacao import montar
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    adm = app.administracao
    adm.custo = 4
    adm.definir_senha_inicial("Admin#Forte2026", "Admin#Forte2026")
    adm.autenticar("errada")
    adm.autenticar("Admin#Forte2026")
    motivos = [r.evento.motivo for r in reversed(adm.trilha_recente())]
    assert motivos == ["ADMIN_SENHA_DEFINIDA", "SENHA_INCORRETA", "ADMIN_AUTENTICADO"]
    assert adm.verificar_trilha().integra
