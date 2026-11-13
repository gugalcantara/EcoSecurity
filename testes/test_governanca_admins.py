"""Governança dos administradores: papéis, celular (TOTP), aprovação dupla e acesso de emergência."""
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Consentimento, Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import Perfil
from ecosec.repositorios.memoria import (RepositorioAdministradoresMemoria, RepositorioAmostrasMemoria,
                                         RepositorioConsentimentosMemoria, RepositorioTentativasMemoria,
                                         RepositorioTrilhaMemoria, RepositorioUsuariosMemoria)
from ecosec.seguranca.acesso import totp
from ecosec.servicos.administracao import ServicoAdministracao
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
INICIO = datetime(2026, 11, 2, 14, 0, 0)


class Relogio:
    def __init__(self):
        self.agora = INICIO

    def __call__(self):
        return self.agora

    def andar(self, segundos=31):
        self.agora += timedelta(seconds=segundos)


@pytest.fixture
def g():
    """O serviço com repositórios em memória, relógio controlado e trilha de verdade."""
    relogio = Relogio()
    usuarios, consentimentos = RepositorioUsuariosMemoria(relogio), RepositorioConsentimentosMemoria()
    rotulos = set()
    trilha = ServicoTrilha(RepositorioTrilhaMemoria(), relogio)
    servico = ServicoAdministracao.de_configuracao(
        CFG, usuarios, consentimentos, RepositorioAmostrasMemoria(), RepositorioTentativasMemoria(),
        ler_hash=lambda: None, gravar_hash=lambda h: None, administradores=RepositorioAdministradoresMemoria(),
        relogio=relogio, rotulos_modelo=lambda: rotulos, trilha=trilha)
    servico.relogio_mut, servico.rotulos, servico.segredos = relogio, rotulos, {}
    return servico


def pessoa(g, nome, nivel=Nivel.N3, perfil=None):
    """Um cadastro com rosto e consentimento. `perfil` manda sobre o nível: o administrador não tem camada."""
    u = g.usuarios.adicionar(Usuario(matricula=nome[:3].upper() + "X2", nome=nome, nivel=None if perfil else nivel,
                                     perfil=perfil, senha_hash="$2b$x", uf="SP" if nivel is Nivel.N2 else None))
    c = g.consentimentos.registrar(Consentimento(nome, "3.1", "a" * 64, INICIO))
    g.consentimentos.vincular(c.id, u.id)
    g.rotulos.add(u.id)
    return u


def celular(g, u):
    """Cadastra o celular de `u` e guarda o segredo para o teste gerar os códigos."""
    novo = g.novo_celular(u.id)
    codigos = g.confirmar_celular(u.id, novo, totp.codigo(novo.segredo, g.relogio()))
    g.segredos[u.id] = novo.segredo
    return codigos


def codigo(g, u):
    return totp.codigo(g.segredos[u.id], g.relogio())


def trio(g):
    """A (primeiro, pela configuração inicial), B e C, todos administradores com celular."""
    a = pessoa(g, "Ana Lima", perfil=Perfil.EXTERNO)        # o primeiro já nasce administrador
    b, c = pessoa(g, "Bruno Reis", perfil=Perfil.EXTERNO), pessoa(g, "Caio Dias", perfil=Perfil.EXTERNO)   # só Externo vira admin
    from ecosec.dominio.entidades import Administrador
    g.administradores.salvar(Administrador(a.id, INICIO))
    celular(g, a)
    assert g.tornar_administrador(a.id, b.id) is None                       # implantação: sozinho
    celular(g, b)
    g.relogio_mut.andar()
    assert g.tornar_administrador(a.id, c.id, codigo(g, b)) is None          # já com aprovação
    celular(g, c)
    g.relogio_mut.andar()
    return a, b, c


def eventos(g):
    """(motivo, quem, segundo, detalhe). A trilha grava o detalhe padronizado: MAIÚSCULAS, sem acento."""
    return [(r.evento.motivo, r.evento.usuario_id, r.evento.usuario2_id, r.evento.detalhe or "")
            for r in g.trilha.recentes(500)]


# ---------------------------------------------------------------- papéis e implantação
def test_implantacao_deixa_o_primeiro_agir_sozinho_e_a_trilha_marca(g):
    a, b, _ = trio(g)
    designacao_b = next(e for e in eventos(g) if e[0] == "TORNAR_ADMINISTRADOR" and "IMPLANTACAO" in e[3])
    assert designacao_b[1] == a.id and designacao_b[2] is None
    assert g.administradores.obter(b.id).designado_por == a.id


def test_com_dois_admins_a_acao_critica_exige_o_codigo_de_outro(g):
    a, b, c = trio(g)
    assert g.exige_aprovacao
    aprovacao_c = next(e for e in eventos(g) if e[0] == "TORNAR_ADMINISTRADOR" and e[2] == b.id)
    assert aprovacao_c[1] == a.id                                          # pediu A, aprovou B
    d = pessoa(g, "Duda Melo", perfil=Perfil.EXTERNO)
    assert "Código não aceito" in g.tornar_administrador(a.id, d.id)        # sem código
    assert not g.eh_administrador(d.id)


def test_ninguem_aprova_o_proprio_pedido(g):
    a, _, _ = trio(g)
    d = pessoa(g, "Duda Melo", perfil=Perfil.EXTERNO)
    assert g.tornar_administrador(a.id, d.id, codigo(g, a))                 # o código do próprio a não vale
    assert not g.eh_administrador(d.id)


def test_codigo_de_aprovacao_nao_vale_duas_vezes(g):
    a, b, _ = trio(g)
    d, e = pessoa(g, "Duda Melo", perfil=Perfil.EXTERNO), pessoa(g, "Eva Nunes", perfil=Perfil.EXTERNO)
    c_b = codigo(g, b)
    assert g.tornar_administrador(a.id, d.id, c_b) is None
    assert g.tornar_administrador(a.id, e.id, c_b)                          # mesmo código, recusado


def test_codigo_de_recuperacao_aprova_uma_vez(g):
    a, b, c = trio(g)
    d, e = pessoa(g, "Duda Melo", perfil=Perfil.EXTERNO), pessoa(g, "Eva Nunes", perfil=Perfil.EXTERNO)
    assert g.refazer_celular(a.id, b.id, codigo(g, c)) is None
    g.relogio_mut.andar()
    recuperacao = celular(g, b)[0]                                         # B com celular e códigos novos
    assert g.tornar_administrador(a.id, d.id, recuperacao) is None
    assert g.tornar_administrador(a.id, e.id, recuperacao)                  # já usado


def test_erros_de_aprovacao_bloqueiam_so_as_aprovacoes_de_quem_pediu(g):
    a, b, c = trio(g)
    d = pessoa(g, "Duda Melo", perfil=Perfil.EXTERNO)
    for _ in range(3):
        g.tornar_administrador(a.id, d.id, "000000")
    assert "bloqueadas" in g.tornar_administrador(a.id, d.id, codigo(g, b))
    assert g.tornar_administrador(b.id, d.id, codigo(g, c)) is None          # B continua pedindo normalmente


def test_minimo_de_dois_administradores(g):
    a, b, c = trio(g)
    assert g.remover_administrador(a.id, c.id, codigo(g, b)) is None
    g.relogio_mut.andar()
    assert "menos de 2" in g.remover_administrador(a.id, b.id, codigo(g, b))
    assert g.eh_administrador(b.id)


def test_desativar_um_admin_exige_aprovacao_e_desativar_usuario_comum_nao(g):
    a, b, c = trio(g)
    comum = pessoa(g, "Fabio Ramos", Nivel.N1)
    assert g.definir_ativo(comum.id, False, a.id) is None                   # ação de proteção: sozinho
    assert g.definir_ativo(c.id, False, a.id)                               # admin: sem código, recusa
    assert g.usuarios.por_id(c.id).ativo
    assert g.definir_ativo(c.id, False, a.id, codigo(g, b)) is None
    assert not g.eh_administrador(c.id) and not g.administradores.obter(c.id).ativo
    g.definir_ativo(c.id, True, a.id)                                       # reativar o cadastro...
    assert not g.eh_administrador(c.id)                                     # ...não devolve o papel


def test_revogar_consentimento_com_admins_exige_o_segundo(g):
    a, b, _ = trio(g)
    comum = pessoa(g, "Fabio Ramos", Nivel.N1)
    assert g.revogar_consentimento(comum.id, a.id)                          # sem código: recusa
    assert g.consentimentos.vigente_de(comum.id) is not None
    assert g.revogar_consentimento(comum.id, a.id, codigo(g, b)) is None
    assert g.consentimentos.vigente_de(comum.id) is None


def test_revogar_consentimento_de_admin_respeita_o_minimo_de_administradores(g):
    a, b, c = trio(g)
    assert g.remover_administrador(a.id, c.id, codigo(g, b)) is None        # ficam 2 admins
    g.relogio_mut.andar()
    assert "menos de 2" in g.revogar_consentimento(b.id, a.id, codigo(g, b))
    assert g.eh_administrador(b.id) and g.usuarios.por_id(b.id).ativo
    assert g.consentimentos.vigente_de(b.id) is not None


def test_quem_nao_e_admin_nao_faz_acao_critica(g):
    a, b, _ = trio(g)
    comum, d = pessoa(g, "Fabio Ramos"), pessoa(g, "Duda Melo", perfil=Perfil.EXTERNO)
    assert "Só um administrador" in g.tornar_administrador(comum.id, d.id, codigo(g, b))


def test_so_externo_ativo_com_rosto_e_consentimento_vira_admin(g):
    """Só um Externo (sem camada) vira admin, e continua Externo."""
    a, b, _ = trio(g)
    diretora = pessoa(g, "Gina Souza", Nivel.N2)
    assert diretora.id not in {u.id for u in g.candidatos_a_administrador()}
    assert g.tornar_administrador(a.id, diretora.id, codigo(g, b))                # quem tem camada não vira admin
    externo = pessoa(g, "Iara Melo", perfil=Perfil.EXTERNO)
    assert g.tornar_administrador(a.id, externo.id, codigo(g, b)) is None
    depois = g.usuarios.por_id(externo.id)
    assert g.eh_administrador(externo.id) and depois.perfil is Perfil.EXTERNO and depois.nivel is None
    sem_rosto = pessoa(g, "Hugo Lima", perfil=Perfil.EXTERNO)
    g.rotulos.discard(sem_rosto.id)
    assert sem_rosto.id not in {u.id for u in g.candidatos_a_administrador()}


# ---------------------------------------------------------------- celular do próprio admin
def test_celular_so_vale_depois_do_primeiro_codigo_e_entrega_os_codigos_de_recuperacao(g):
    a = pessoa(g, "Ana Lima", perfil=Perfil.EXTERNO)
    from ecosec.dominio.entidades import Administrador
    g.administradores.salvar(Administrador(a.id, INICIO))
    novo = g.novo_celular(a.id)
    assert novo.uri.startswith("otpauth://totp/") and not g.celular_cadastrado(a.id)
    assert g.confirmar_celular(a.id, novo, "000000") is None
    codigos = g.confirmar_celular(a.id, novo, totp.codigo(novo.segredo, g.relogio()))
    assert len(codigos) == 8 and g.celular_cadastrado(a.id) and g.codigos_restantes(a.id) == 8
    assert novo.segredo not in (g.administradores.obter(a.id).segredo_totp or "")   # gravado cifrado
    assert g.novo_celular(a.id) is None                                     # não se troca sozinho


def test_codigo_do_celular_abre_o_painel_uma_vez_e_erros_bloqueiam(g):
    a, _, _ = trio(g)
    c = codigo(g, a)
    assert g.conferir_codigo_celular(a.id, c) == (Motivo.CONCEDIDO, None)
    assert g.conferir_codigo_celular(a.id, c)[0] is Motivo.CODIGO_INCORRETO     # repetido
    g.conferir_codigo_celular(a.id, "000000")
    motivo, ate = g.conferir_codigo_celular(a.id, "111111")
    assert motivo is Motivo.BLOQUEADO and ate == g.relogio() + timedelta(minutes=15)
    g.relogio_mut.andar()
    assert g.conferir_codigo_celular(a.id, codigo(g, a))[0] is Motivo.BLOQUEADO   # nem confere


def test_codigo_de_recuperacao_abre_o_painel_de_quem_perdeu_o_celular(g):
    a = pessoa(g, "Ana Lima", perfil=Perfil.EXTERNO)
    from ecosec.dominio.entidades import Administrador
    g.administradores.salvar(Administrador(a.id, INICIO))
    codigos = celular(g, a)
    assert g.conferir_codigo_celular(a.id, codigos[3].lower().replace("-", ""))[0] is Motivo.CONCEDIDO
    assert g.codigos_restantes(a.id) == 7
    assert "RECUPERACAO" in eventos(g)[0][3]


def test_refazer_celular_apaga_segredo_e_codigos_e_exige_aprovacao(g):
    a, b, c = trio(g)
    assert g.refazer_celular(a.id, c.id)                                    # sem aprovação: recusa
    assert g.refazer_celular(a.id, c.id, codigo(g, b)) is None
    assert not g.celular_cadastrado(c.id) and g.codigos_restantes(c.id) == 0
    assert g.novo_celular(c.id) is not None                                 # C cadastra um novo


# ---------------------------------------------------------------- acesso de emergência
def test_emergencia_so_para_admin_e_so_com_quorum_possivel(g):
    a = pessoa(g, "Ana Lima", perfil=Perfil.EXTERNO)
    from ecosec.dominio.entidades import Administrador
    g.administradores.salvar(Administrador(a.id, INICIO))
    celular(g, a)
    assert not g.pode_oferecer_emergencia(a.id)                             # 1 admin: quórum impossível
    a, b, c = trio_sobre(g, a)
    comum = pessoa(g, "Fabio Ramos")
    assert g.pode_oferecer_emergencia(a.id) and not g.pode_oferecer_emergencia(comum.id)


def trio_sobre(g, a):
    b, c = pessoa(g, "Bruno Reis", perfil=Perfil.EXTERNO), pessoa(g, "Caio Dias", perfil=Perfil.EXTERNO)
    g.tornar_administrador(a.id, b.id)
    celular(g, b)
    g.relogio_mut.andar()
    g.tornar_administrador(a.id, c.id, codigo(g, b))
    celular(g, c)
    g.relogio_mut.andar()
    return a, b, c


def test_quorum_de_dois_em_qualquer_ordem(g):
    a, b, c = trio(g)
    sessao = g.nova_emergencia(a.id)
    passo = sessao.informar(codigo(g, c))                                   # primeiro o de C...
    assert passo.aceitos == 1 and passo.concedida is None
    assert sessao.informar(codigo(g, c)).aceitos == 1                       # C de novo não conta
    passo = sessao.informar(codigo(g, b))                                   # ...depois o de B
    assert passo.concedida is not None and set(passo.concedida.confirmado_por) == {b.id, c.id}
    assert passo.concedida.fim == g.relogio() + timedelta(minutes=30)
    aberta = next(r.evento for r in g.trilha.recentes(50) if r.evento.motivo == "EMERGENCIA_ABERTA")
    assert aberta.usuario_id == a.id and "QUORUM" in aberta.detalhe


def test_erro_na_emergencia_e_generico_e_trava_globalmente(g):
    a, b, c = trio(g)
    sessao = g.nova_emergencia(a.id)
    sessao.informar(codigo(g, b))
    mensagens = {sessao.informar(ruim).mensagem.split(" Tente")[0] for ruim in ("000000", "ZZZZ-ZZZZ-ZZZZ-ZZZZ")}
    assert mensagens == {"Código não aceito."}                              # nunca diz qual falhou
    assert sessao.informar("123123").bloqueado_ate is not None
    outra = g.nova_emergencia(b.id)                                         # a trava é global
    assert outra.informar(codigo(g, c)).bloqueado_ate is not None


def test_codigos_da_emergencia_precisam_chegar_dentro_da_janela(g):
    a, b, c = trio(g)
    sessao = g.nova_emergencia(a.id)
    sessao.informar(codigo(g, b))
    g.relogio_mut.andar(6 * 60)
    passo = sessao.informar(codigo(g, c))
    assert "acabou" in passo.mensagem and passo.aceitos == 0 and passo.concedida is None


def test_emergencia_so_conserta_o_acesso_e_expira(g):
    a, b, c = trio(g)
    sessao = g.nova_emergencia(a.id)
    sessao.informar(codigo(g, b))
    emergencia = sessao.informar(codigo(g, c)).concedida
    assert g.refazer_celular(a.id, a.id, emergencia=emergencia) is None     # consertar: pode, sem novo código
    with pytest.raises(TypeError):
        g.remover_administrador(a.id, b.id, emergencia=emergencia)           # nem existe essa porta
    g.relogio_mut.andar(31 * 60)
    assert "expirou" in g.refazer_celular(a.id, b.id, emergencia=emergencia)


def test_codigo_de_recuperacao_conta_como_voto_no_quorum(g):
    a, b, c = trio(g)
    g.refazer_celular(a.id, b.id, codigo(g, c))
    g.relogio_mut.andar()
    codigos_b = celular(g, b)
    sessao = g.nova_emergencia(a.id)
    sessao.informar(codigo(g, a))
    assert sessao.informar(codigos_b[0]).concedida is not None


# ---------------------------------------------------------------- migração e sessão
def test_admin_do_env_antigo_passa_para_o_banco_uma_vez(g):
    a = pessoa(g, "Ana Lima")
    assert g.migrar_administrador_legado(a.matricula) and g.eh_administrador(a.id)
    assert not g.migrar_administrador_legado(a.matricula)                   # tabela já tem gente
    assert not g.migrar_administrador_legado(None)


def test_admin_nao_tem_aba_de_nivel_e_a_emergencia_nenhuma(g):
    """O administrador não tem camada (antes via a aba do N3, porque era ministro também)."""
    from ecosec.servicos.sessao import SessaoAplicacao
    a, _, _ = trio(g)
    normal = SessaoAplicacao(g.usuarios.por_id(a.id), None, True, INICIO)
    assert normal.niveis_com_aba == () and normal.papel == "Administrador"
    emergencia = SessaoAplicacao(g.usuarios.por_id(a.id), None, True, INICIO, emergencia=object())
    assert emergencia.niveis_com_aba == () and emergencia.papel == "Acesso de emergência"


def test_emergencia_e_codigos_recusados_viram_alerta_no_monitor(g):
    from ecosec.seguranca.evidencia import monitor
    a, b, c = trio(g)
    d = pessoa(g, "Duda Melo", perfil=Perfil.EXTERNO)
    g.tornar_administrador(a.id, d.id, "000000")                            # aprovação com código errado
    sessao = g.nova_emergencia(a.id)
    sessao.informar("111111")                                               # código errado na emergência
    sessao.informar(codigo(g, b))
    sessao.informar(codigo(g, c))
    regras = {(al.gravidade, al.regra) for al in monitor.detectar(g.trilha.recentes(500))}
    assert ("ALTO", "ACESSO_DE_EMERGENCIA") in regras
    assert ("MEDIO", "APROVACAO_RECUSADA") in regras and ("MEDIO", "EMERGENCIA_RECUSADA") in regras


# ---------------------------------------------------------------- âncora da trilha pelo painel
def ultimo(g):
    return g.trilha.repo.todos()[-1]


def test_ancora_pelo_painel_pede_o_codigo_do_proprio_celular_e_aponta_para_o_registro(g):
    a, b, _ = trio(g)
    ancora, recusa = g.gerar_ancora(a.id, "000000")
    assert ancora is None and "Código não aceito" in recusa
    assert ultimo(g).evento.motivo == "CODIGO_INCORRETO" and ultimo(g).evento.usuario_id == a.id
    ancora, recusa = g.gerar_ancora(a.id, codigo(g, b))          # o código de outro administrador não serve
    assert ancora is None and recusa
    g.relogio_mut.andar()
    proprio = codigo(g, a)
    ancora, recusa = g.gerar_ancora(a.id, proprio)
    assert recusa is None
    registro = ultimo(g)
    assert (ancora.id, ancora.hash) == (registro.id, registro.hash_registro)   # a âncora cobre a própria geração
    assert (registro.evento.motivo, registro.evento.resultado, registro.evento.usuario_id) == (
        "ANCORA_TRILHA", "REGISTRADO", a.id)
    assert g.conferir_ancora_trilha(ancora).valida
    assert g.gerar_ancora(a.id, proprio)[0] is None               # o mesmo código não vale duas vezes


def test_quem_nao_e_administrador_nao_gera_nem_confere_ancora(g):
    trio(g)
    servidor = pessoa(g, "Davi Sousa", Nivel.N1)
    assert g.gerar_ancora(servidor.id, "123456") == (None, "Só um administrador pode fazer isso.")
    assert g.conferir_ancora_painel(servidor.id, "ECOSEC-TRILHA 1 " + "a" * 64)[1] == (
        "Só um administrador pode fazer isso.")


def test_tres_codigos_errados_na_ancora_trancam_o_codigo_do_celular(g):
    a, _, _ = trio(g)
    for _ in range(3):
        _, recusa = g.gerar_ancora(a.id, "000000")
    assert "bloqueado" in recusa
    g.relogio_mut.andar()
    _, recusa = g.gerar_ancora(a.id, codigo(g, a))                # nem confere enquanto está bloqueado
    assert "bloqueado" in recusa


def test_trilha_adulterada_nao_e_ancorada(g):
    a, _, _ = trio(g)
    repo = g.trilha.repo
    r = repo._registros[1]
    repo._registros[1] = type(r)(replace(r.evento, resultado="CONCEDIDO"), r.hash_anterior, r.hash_registro, r.id)
    g.relogio_mut.andar()
    ancora, recusa = g.gerar_ancora(a.id, codigo(g, a))
    assert ancora is None and "não está íntegra" in recusa
    assert ultimo(g).evento.motivo == "ANCORA_TRILHA" and ultimo(g).evento.resultado == "NEGADO"


def test_conferir_ancora_pelo_painel_registra_e_pega_a_cauda_apagada(g):
    a, _, _ = trio(g)
    g.relogio_mut.andar()
    ancora, _ = g.gerar_ancora(a.id, codigo(g, a))
    conferencia, recusa = g.conferir_ancora_painel(a.id, ancora.texto())
    assert recusa is None and conferencia.valida
    assert (ultimo(g).evento.motivo, ultimo(g).evento.resultado) == ("CONFERENCIA_ANCORA", "REGISTRADO")
    assert g.conferir_ancora_painel(a.id, "qualquer coisa")[0] is None
    del g.trilha.repo._registros[ancora.id - 1:]                  # o que o root faria direto no banco
    conferencia, _ = g.conferir_ancora_painel(a.id, ancora.texto())
    assert not conferencia.valida and conferencia.problema == "ANCORA_AUSENTE"


# ---------------------------------------------------------------- ferramentas de terminal (experimento)
def com_senha(g, u, senha="Admin#2026abc"):
    from ecosec.seguranca.acesso import s2_conhecimento
    g.usuarios.atualizar(replace(g.usuarios.por_id(u.id), senha_hash=s2_conhecimento.gerar_hash(senha, 4)))
    return senha


def test_ferramenta_pede_matricula_senha_e_codigo_de_um_administrador(g):
    a, _, _ = trio(g)
    senha = com_senha(g, a)
    assert g.autorizar_ferramenta(a.matricula, "errada", codigo(g, a), "EXPERIMENTO")[0] is None
    assert ultimo(g).evento.motivo == "FERRAMENTA_RECUSADA"
    _, recusa = g.autorizar_ferramenta(a.matricula, senha, "000000", "EXPERIMENTO")
    assert "Código não aceito" in recusa
    g.relogio_mut.andar()
    uid, recusa = g.autorizar_ferramenta(a.matricula.lower(), senha, codigo(g, a), "EXPERIMENTO")
    assert (uid, recusa) == (a.id, None)
    assert (ultimo(g).evento.motivo, ultimo(g).evento.usuario_id) == ("FERRAMENTA_INICIO", a.id)
    g.registrar_fim_ferramenta(a.id, "EXPERIMENTO", "5 tentativas gravadas")
    assert ultimo(g).evento.motivo == "FERRAMENTA_FIM" and "5 TENTATIVAS" in ultimo(g).evento.detalhe


def test_ferramenta_recusa_quem_nao_e_administrador_e_tranca_apos_tres_erros(g):
    trio(g)
    servidor = pessoa(g, "Davi Sousa", Nivel.N1)
    senha = com_senha(g, servidor)
    assert g.autorizar_ferramenta(servidor.matricula, senha, "123456", "EXPERIMENTO")[0] is None
    for _ in range(2):
        _, recusa = g.autorizar_ferramenta("ZZZ9999", "x", "123456", "EXPERIMENTO")
    assert "incorretas" in recusa
    _, recusa = g.autorizar_ferramenta("ZZZ9999", "x", "123456", "EXPERIMENTO")
    assert "Bloqueado" in recusa
