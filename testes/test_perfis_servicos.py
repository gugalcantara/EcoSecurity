"""Os serviços com perfis, escopo exclusivo e o administrador sem dado.

- acervo: o administrador é recusado em cada método público que entrega dado, com NEGADO na trilha, mesmo com um
  painel, resumo ou relatório de outra pessoa nas mãos; catálogo e S5 exclusivos; a comparação UF × Brasil do N2
  fica no escopo do N2; o nome do responsável fora da trilha;
- administração: atribuir perfil, excluir, o primeiro administrador na configuração inicial, a
  trilha mascarada para o administrador;
- autenticação: sem perfil não entra; o administrador entra, mas não abre camada nenhuma;
- identificação 1:N só do administrador; relatórios do sistema com o perfil.

Os símbolos novos são importados dentro dos testes: cada um fica vermelho pelo próprio motivo.
"""
import dataclasses
from datetime import datetime, timedelta

import pytest

from ecosec.configuracao import carregar
from ecosec.dominio import texto
from ecosec.dominio.entidades import Administrador, Consentimento, Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.repositorios.memoria import (RepositorioAcervoMemoria, RepositorioAdministradoresMemoria,
                                         RepositorioAmostrasMemoria, RepositorioConsentimentosMemoria,
                                         RepositorioTentativasMemoria, RepositorioTrilhaMemoria,
                                         RepositorioUsuariosMemoria)
from ecosec.seguranca.acesso import totp
from ecosec.servicos.acervo import ErroAcervo, ServicoAcervo
from ecosec.servicos.administracao import ServicoAdministracao
from ecosec.servicos.trilha import ServicoTrilha
from test_servico_autenticacao import CUSTO, alimentar, ambiente, entrar  # noqa: F401
from test_servico_cadastro_admin import cadastro, coleta_completa  # noqa: F401

CFG = carregar()
AGORA = datetime(2026, 11, 7, 10, 0)
SENHA_FORTE = "Perfil#Forte2026"


def Perfil():  # noqa: N802
    from ecosec.dominio.perfis import Perfil as P
    return P


# Os perfis que já existem como nível são criados pela API de hoje (nivel=): assim os testes deles mostram o
# comportamento atual que muda, e não só a falta do módulo de perfis. A compatibilidade de `nivel=` é exigida
# em test_perfis.py::test_usuario_guarda_o_perfil_e_o_nivel_vira_a_camada.
POR_NIVEL = {"SERVIDOR": 1, "DIRETOR": 2, "MINISTRO": 3}


def usuario(perfil_nome, id_, uf=None):
    if perfil_nome in POR_NIVEL:
        return Usuario(matricula=f"U{id_}X", nome=f"Pessoa {perfil_nome.title()}", nivel=POR_NIVEL[perfil_nome],
                       senha_hash="$2b$x", uf=uf, id=id_)
    return Usuario(matricula=f"U{id_}X", nome=f"Pessoa {perfil_nome.title()}", nivel=None,
                   perfil=Perfil()[perfil_nome], senha_hash="$2b$x", uf=uf, id=id_)


# ================================================================ acervo
@pytest.fixture
def acervo():
    trilha = ServicoTrilha(RepositorioTrilhaMemoria())
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), trilha, b"chave-teste",
                                            relogio=lambda: AGORA)
    servico.data_referencia = AGORA.date()
    return servico


def ultimo(servico):
    return servico.trilha.recentes(1)[0].evento


def _nas_maos_do_admin(acervo, admin, tmp_path):
    """O que o ministro obteve (painel, resumo, relatório, um caso, um documento, um responsável), com o dono
    trocado para o administrador: o objeto "vazou". A autorização tem de valer na chamada, pelo papel de quem pede."""
    caio = usuario("MINISTRO", 3)
    painel = acervo.painel(caio, 3)
    resumo = acervo.resumo_agregado(caio, 3)
    entrega = acervo.abrir("A3-01", caio, 3)
    codigo = next(p.codigo for p in painel.pendencias if acervo.documentos(painel, caio, p.codigo))
    documento = acervo.documentos(painel, caio, codigo)[0].id
    nome = acervo.custo_por_responsavel(painel, caio)[0].nome
    trocar = dict(usuario_id=admin.id)
    return dict(painel=dataclasses.replace(painel, **trocar), resumo=dataclasses.replace(resumo, **trocar),
                entrega=dataclasses.replace(entrega, **trocar), codigo=codigo, documento=documento, nome=nome,
                destino=tmp_path)


METODOS_DO_ACERVO = {
    "abrir": lambda s, u, o: s.abrir("A3-01", u, 3),
    "painel": lambda s, u, o: s.painel(u, 3),
    "resumo_agregado": lambda s, u, o: s.resumo_agregado(u, 3),
    "panorama": lambda s, u, o: s.panorama(u, 1),
    "painel_classe": lambda s, u, o: s.painel_classe(u, 1),
    "painel_uf": lambda s, u, o: s.painel_uf(u, 1),
    "painel_custo": lambda s, u, o: s.painel_custo(u, 3),
    "painel_encerramento": lambda s, u, o: s.painel_encerramento(u, 1),
    "kpis": lambda s, u, o: s.kpis(u, 1),
    "referencia_nacional": lambda s, u, o: s.referencia_nacional(u),
    "painel_n1": lambda s, u, o: s.painel_n1(u, 1),
    "responsaveis_da_pendencia": lambda s, u, o: s.responsaveis_da_pendencia(o["painel"], u, o["codigo"]),
    "documentos": lambda s, u, o: s.documentos(o["painel"], u, o["codigo"]),
    "abrir_documento": lambda s, u, o: s.abrir_documento(o["painel"], u, o["codigo"], o["documento"]),
    "custo_por_responsavel": lambda s, u, o: s.custo_por_responsavel(o["painel"], u),
    "memoria_por_responsavel": lambda s, u, o: s.memoria_por_responsavel(o["painel"], u, o["nome"]),
    # os três que hoje só recebem o painel passam a receber também quem pede
    "priorizacao": lambda s, u, o: s.priorizacao(o["painel"], u),
    "custodias": lambda s, u, o: s.custodias(o["painel"], u),
    "pendencias_da_custodia": lambda s, u, o: s.pendencias_da_custodia(o["painel"], u, None),
    "exportar_resumo": lambda s, u, o: s.exportar_resumo(o["resumo"], u, "POR UF", o["destino"] / "r.csv"),
    "exportar_planilha": lambda s, u, o: s.exportar_planilha(o["painel"], u, [o["codigo"]], o["destino"] / "p.csv"),
    "exportar_ficha": lambda s, u, o: s.exportar_ficha(o["painel"], u, o["codigo"], o["destino"] / "f.csv"),
    "exportar": lambda s, u, o: s.exportar(o["entrega"], u, o["destino"] / "a.png"),
}
# Fora da lista, por não entregarem dado do acervo: catalogo (títulos dos relatórios), eventos (marcos
# regulatórios públicos), pesos_da_pressao (parâmetros do config), hoje e identificar_marca (auditoria de cópia).


@pytest.mark.parametrize("metodo", sorted(METODOS_DO_ACERVO))
def test_administrador_e_recusado_em_cada_metodo_do_acervo(acervo, tmp_path, metodo):
    admin = usuario("EXTERNO", 9)                 # o administrador é um Externo com o papel: sem camada
    objetos = _nas_maos_do_admin(acervo, admin, tmp_path)
    antes = len(acervo.trilha.recentes(10000))
    with pytest.raises(ErroAcervo):
        METODOS_DO_ACERVO[metodo](acervo, admin, objetos)
    novos = acervo.trilha.recentes(10000)[: len(acervo.trilha.recentes(10000)) - antes]
    assert novos, "a recusa tem de ficar na trilha"
    assert all(r.evento.resultado == "NEGADO" and r.evento.usuario_id == admin.id for r in novos)
    assert not list(tmp_path.glob("*.*"))                              # nenhum arquivo saiu


def test_catalogo_e_exclusivo_por_camada(acervo):
    """Substitui test_catalogo_por_nivel (test_acervo.py: 6 no N2 e 9 no N3)."""
    for nivel in Nivel:
        assert {r.codigo[:2] for r in acervo.catalogo(nivel)} == {f"A{nivel.value}"}, nivel
        assert len(acervo.catalogo(nivel)) == 3


@pytest.mark.parametrize("perfil, nivel, codigo", [("MINISTRO", 1, "A1-01"), ("MINISTRO", 2, "A2-01"),
                                                   ("DIRETOR", 1, "A1-05")])
def test_ninguem_abre_relatorio_de_outra_camada(acervo, perfil, nivel, codigo):
    u = usuario(perfil, 3, uf="SP" if perfil == "DIRETOR" else None)
    with pytest.raises(ErroAcervo):
        acervo.abrir(codigo, u, nivel)
    ev = ultimo(acervo)
    assert (ev.resultado, ev.motivo, ev.usuario_id) == ("NEGADO", "NIVEL_INSUFICIENTE", u.id)


def test_comparacao_com_o_pais_e_do_escopo_do_diretor(acervo):
    """A linha NACIONAL protegida (k=3) continua no painel do N2, classificada como do N2."""
    bia = usuario("DIRETOR", 2, uf="SP")
    ref = acervo.referencia_nacional(bia)
    assert ref.supressao_minima == 3
    ev = ultimo(acervo)
    assert (ev.motivo, ev.nivel_solicitado) == ("REFERENCIA_NACIONAL", 2)
    with pytest.raises(ErroAcervo):
        acervo.referencia_nacional(usuario("MINISTRO", 3))          # o país do N2 não é escopo do N3
    with pytest.raises(ErroAcervo):
        acervo.referencia_nacional(usuario("SERVIDOR", 1))          # nem do N1, que tem o próprio panorama


def test_priorizacao_e_do_ministro_e_o_diretor_e_recusado(acervo):
    bia, caio = usuario("DIRETOR", 2, uf="SP"), usuario("MINISTRO", 3)
    with pytest.raises(ErroAcervo):
        acervo.priorizacao(acervo.painel(bia, 2), bia)
    ev = ultimo(acervo)
    assert (ev.resultado, ev.usuario_id) == ("NEGADO", bia.id)
    assert acervo.priorizacao(acervo.painel(caio, 3), caio).selecionadas is not None


def test_trilha_nao_grava_o_nome_do_responsavel(acervo):
    """O detalhe da memória de cálculo leva só a contagem; o nome não vai para a trilha."""
    caio = usuario("MINISTRO", 3)
    painel = acervo.painel(caio, 3)
    nome = acervo.custo_por_responsavel(painel, caio)[0].nome
    acervo.memoria_por_responsavel(painel, caio, nome)
    ev = ultimo(acervo)
    assert ev.motivo == "MEMORIA_CUSTO_RESPONSAVEL"
    assert texto.referencia(nome) not in (ev.detalhe or "") and nome not in (ev.detalhe or "")


# ================================================================ sessão
def test_sessao_do_admin_nao_tem_aba_e_cada_perfil_tem_so_a_sua():
    from ecosec.servicos.sessao import SessaoAplicacao
    casos = [("EXTERNO", True, (), "Administrador"), ("EXTERNO", False, (), "Externo"),
             ("MINISTRO", False, (Nivel.N3,), "Ministro"), ("SERVIDOR", False, (Nivel.N1,), "Servidor"),
             ("DIRETOR", False, (Nivel.N2,), "Diretor")]
    for nome, administrador, abas, papel in casos:
        u = usuario(nome, 1, uf="SP" if nome == "DIRETOR" else None)
        s = SessaoAplicacao(u, None, administrador, AGORA)
        assert (s.niveis_com_aba, s.papel) == (abas, papel), nome
    import ecosec.servicos.sessao as modulo
    assert not hasattr(modulo, "Situacao")                         # sem "incluído no seu nível" nem "sem acesso"


# ================================================================ administração
class Relogio:
    def __init__(self):
        self.agora = AGORA

    def __call__(self):
        return self.agora

    def andar(self, segundos=31):
        self.agora += timedelta(seconds=segundos)


@pytest.fixture
def g():
    relogio = Relogio()
    usuarios, consentimentos = RepositorioUsuariosMemoria(relogio), RepositorioConsentimentosMemoria()
    rotulos, guardado = set(), {}
    trilha = ServicoTrilha(RepositorioTrilhaMemoria(), relogio)
    servico = ServicoAdministracao.de_configuracao(
        CFG, usuarios, consentimentos, RepositorioAmostrasMemoria(), RepositorioTentativasMemoria(),
        ler_hash=lambda: guardado.get("hash"), gravar_hash=lambda h: guardado.__setitem__("hash", h),
        administradores=RepositorioAdministradoresMemoria(), relogio=relogio, rotulos_modelo=lambda: rotulos,
        trilha=trilha, eliminar_biometria=rotulos.discard)
    servico.custo = 4
    servico.relogio_mut, servico.rotulos, servico.segredos = relogio, rotulos, {}
    return servico


def pessoa(g, nome, perfil, uf=None):
    u = g.usuarios.adicionar(dataclasses.replace(usuario(perfil, None, uf), matricula=nome[:3].upper() + "Y2",
                                                 nome=nome))
    c = g.consentimentos.registrar(Consentimento(nome, "3.1", "a" * 64, AGORA))
    g.consentimentos.vincular(c.id, u.id)
    g.rotulos.add(u.id)
    return u


def celular(g, u):
    novo = g.novo_celular(u.id)
    g.confirmar_celular(u.id, novo, totp.codigo(novo.segredo, g.relogio()))
    g.segredos[u.id] = novo.segredo


def codigo(g, u):
    return totp.codigo(g.segredos[u.id], g.relogio())


def dois_admins(g):
    a, b = pessoa(g, "Ana Lima", "EXTERNO"), pessoa(g, "Bruno Reis", "EXTERNO")
    g.administradores.salvar(Administrador(a.id, AGORA))
    celular(g, a)
    assert g.tornar_administrador(a.id, b.id) is None                  # implantação: sozinho
    celular(g, b)
    g.relogio_mut.andar()
    return a, b


def test_so_um_externo_vira_administrador_e_continua_sem_camada(g):
    """O administrador é um papel dado a um Externo: quem tem camada não vira admin, e o Externo continua Externo."""
    a = pessoa(g, "Ana Lima", "EXTERNO")
    g.administradores.salvar(Administrador(a.id, AGORA))
    ministro, externo = pessoa(g, "Caio Dias", "MINISTRO"), pessoa(g, "Eva Lima", "EXTERNO")
    assert g.tornar_administrador(a.id, ministro.id)                               # recusado: tem camada
    assert not g.eh_administrador(ministro.id)
    assert g.tornar_administrador(a.id, externo.id) is None
    depois = g.usuarios.por_id(externo.id)
    assert depois.perfil is Perfil().EXTERNO and depois.nivel is None and g.eh_administrador(externo.id)
    assert g.atribuir_perfil(a.id, externo.id, Perfil().SERVIDOR)                  # o admin não recebe camada


def test_atribuir_camada_3_pede_segundo_admin_e_n1_n2_nao(g):
    """Decisão."""
    a, b = dois_admins(g)
    x, y = pessoa(g, "Xavier Lopes", "EXTERNO"), pessoa(g, "Yara Nunes", "EXTERNO")
    assert g.atribuir_perfil(a.id, x.id, Perfil().MINISTRO)                        # recusado: falta o código
    assert g.usuarios.por_id(x.id).perfil is Perfil().EXTERNO
    assert g.atribuir_perfil(a.id, x.id, Perfil().MINISTRO, codigo=codigo(g, b)) is None
    assert g.usuarios.por_id(x.id).perfil is Perfil().MINISTRO
    ev = g.trilha.recentes(5)
    assert any(r.evento.motivo == "ATRIBUIR_PERFIL" and r.evento.usuario2_id == b.id for r in ev)
    g.relogio_mut.andar()
    assert g.atribuir_perfil(a.id, y.id, Perfil().MINISTRO)                        # camada 3: crítico
    assert g.atribuir_perfil(a.id, y.id, Perfil().SERVIDOR) is None                # N1: sozinho
    assert g.atribuir_perfil(a.id, y.id, Perfil().DIRETOR)                         # diretor sem UF: recusado
    assert g.atribuir_perfil(a.id, y.id, Perfil().DIRETOR, uf="SP") is None        # N2: sozinho
    assert g.usuarios.por_id(y.id).uf == "SP"
    assert g.atribuir_perfil(a.id, y.id, Perfil().EXTERNO) is None                 # tirar acesso: sozinho
    assert g.usuarios.por_id(y.id).uf is None


def test_ninguem_altera_o_proprio_perfil(g):
    a, b = dois_admins(g)
    assert g.atribuir_perfil(a.id, a.id, Perfil().MINISTRO, codigo=codigo(g, b))
    assert g.usuarios.por_id(a.id).perfil is Perfil().EXTERNO and g.eh_administrador(a.id)


def test_admin_nao_recebe_camada_e_tirar_o_papel_respeita_o_minimo_de_dois(g):
    a, b = dois_admins(g)
    assert g.atribuir_perfil(a.id, b.id, Perfil().MINISTRO, codigo=codigo(g, b))   # admin: tire o papel antes
    assert g.remover_administrador(a.id, b.id, codigo(g, b))                      # ficaria com 1 admin
    assert g.eh_administrador(b.id) and g.usuarios.por_id(b.id).nivel is None


def test_excluir_e_logico_irreversivel_critico_e_preserva_a_prova(g):
    """Revoga, desativa, elimina o rosto, marca excluído; trilha e consentimentos ficam."""
    a, b = dois_admins(g)
    x = pessoa(g, "Xavier Lopes", "SERVIDOR")
    assert g.excluir_usuario(a.id, x.id)                                           # sem o 2º admin: recusado
    assert g.usuarios.por_id(x.id).ativo
    assert g.excluir_usuario(a.id, x.id, codigo=codigo(g, b)) is None
    depois = g.usuarios.por_id(x.id)
    assert depois is not None and not depois.ativo and depois.excluido_em is not None
    assert x.id not in g.rotulos                                                   # rosto eliminado
    assert g.consentimentos.vigente_de(x.id) is None and g.consentimentos.de_usuario(x.id)   # a prova fica
    assert x.id not in {l.usuario.id for l in g.listar()}                          # some da lista
    assert g.definir_ativo(x.id, True)                                             # não volta
    assert g.atribuir_perfil(a.id, x.id, Perfil().SERVIDOR)                        # nem ganha perfil
    assert g.verificar_trilha().integra                                            # nada apagado nem reescrito


def test_primeiro_administrador_nasce_na_configuracao_inicial(g):
    """O primeiro cadastro, Externo, vira o primeiro admin pela senha de instalação já digitada para
    abrir a configuração; sem o "Você é o administrador?" no login."""
    assert g.definir_senha_inicial("Admin#Forte2026", "Admin#Forte2026") == []
    primeiro = pessoa(g, "Ana Lima", "EXTERNO")
    assert g.vincular_primeiro_administrador(primeiro.id)                          # sem a senha: recusado
    assert g.autenticar("Admin#Forte2026") is Motivo.CONCEDIDO
    ministro = pessoa(g, "Caio Dias", "MINISTRO")
    assert g.vincular_primeiro_administrador(ministro.id)                          # precisa ser Externo
    assert g.vincular_primeiro_administrador(primeiro.id) is None
    assert g.eh_administrador(primeiro.id)
    outro = pessoa(g, "Bruno Reis", "EXTERNO")
    assert g.vincular_primeiro_administrador(outro.id)                             # uma vez só
    assert not g.eh_administrador(outro.id)


def test_trilha_para_o_admin_mascara_o_detalhe_do_acervo(g):
    """As linhas antigas são imutáveis; a visão do administrador esconde o que é do acervo."""
    t = g.trilha
    t.registrar("CONSULTA", "CONCEDIDO", "MEMORIA_CUSTO_RESPONSAVEL", nivel_solicitado=3, usuario_id=1,
                detalhe="3 pendencias; RESPONSAVEL FICTICIO LTDA")
    t.registrar("CONSULTA", "CONCEDIDO", "ABERTURA_DOCUMENTO", nivel_solicitado=3, usuario_id=1,
                detalhe="DOC TAC 0042/2019; PND-0007; SHA256 0123456789abcdef")
    t.registrar("CONSULTA", "NEGADO", "FORA_DO_ESCOPO", nivel_solicitado=2, usuario_id=1, detalhe="PND-0008")
    t.registrar("CONSULTA", "CONCEDIDO", "CONSULTA_ACERVO", nivel_solicitado=3, usuario_id=1,
                detalhe="A3-01; 2 regiões suprimidas; filtro UF SP RISCO CRITICO")
    t.registrar("ADMIN", "REGISTRADO", "USUARIO_DESATIVADO", usuario_id=1, detalhe="motivo administrativo")
    visivel = " | ".join(r.evento.detalhe or "" for r in g.trilha_visivel())
    for segredo in ("RESPONSAVEL FICTICIO", "0042/2019", "PND-0007", "PND-0008", "UF SP", "CRITICO"):
        assert segredo not in visivel, segredo
    assert "A3-01" in visivel                                      # o código do relatório fica
    assert "MOTIVO ADMINISTRATIVO" in visivel.upper()              # o que é da administração fica inteiro
    assert any("RESPONSAVEL FICTICIO" in (r.evento.detalhe or "") for r in t.recentes(10))   # o banco não muda
    assert g.verificar_trilha().integra


# ================================================================ autenticação
def _criar(amb, perfil, nome, senha=SENHA_FORTE, uf=None):
    from ecosec.seguranca.acesso import s2_conhecimento
    hash_ = s2_conhecimento.gerar_hash(senha, CUSTO)
    if perfil in POR_NIVEL:
        u = amb.usuarios.adicionar(Usuario(matricula=f"M{nome.upper()}", nome=nome, nivel=POR_NIVEL[perfil],
                                           senha_hash=hash_, uf=uf))
    else:
        u = amb.usuarios.adicionar(Usuario(matricula=f"M{nome.upper()}", nome=nome, nivel=None,
                                           perfil=Perfil()[perfil], senha_hash=hash_, uf=uf))
    c = amb.servico.consentimentos.registrar(Consentimento(nome, "3.1", "a" * 64, amb.relogio.agora()))
    amb.servico.consentimentos.vincular(c.id, u.id)
    return u


def test_externo_sem_o_papel_nao_entra_e_nao_conta_como_erro(ambiente):
    """O Externo só registra a matrícula; sem o papel de administrador, o login é negado na S5."""
    zeca = _criar(ambiente, "EXTERNO", "zeca")
    sessao, identidade = entrar(ambiente, zeca, SENHA_FORTE)
    assert identidade is None and sessao.andamento.decisao.motivo is Motivo.SEM_ACESSO
    registro = ambiente.tentativas.obter(zeca.matricula)
    assert registro is None or registro.falhas == 0


def test_administrador_entra_mas_nao_abre_camada_nenhuma(ambiente):
    rafa = _criar(ambiente, "EXTERNO", "rafa")
    ambiente.servico.eh_administrador = lambda usuario_id: usuario_id == rafa.id   # o papel, na tabela administrador
    sessao, identidade = entrar(ambiente, rafa, SENHA_FORTE)
    assert sessao.andamento.decisao.concedido
    for nivel in (1, 2, 3):
        assert ambiente.servico.abrir_nivel(identidade, nivel).motivo is Motivo.NIVEL_INSUFICIENTE, nivel
    verificacao = ambiente.servico.nova_verificacao_admin(identidade)      # o painel continua pedindo o rosto
    alimentar(verificacao, ambiente.p.frames_confirmacao)
    assert verificacao.andamento.decisao.concedido


@pytest.mark.parametrize("perfil, uf, abre, nao_abre", [("MINISTRO", None, (), (1, 2)),
                                                        ("DIRETOR", "SP", (2,), (1,))])
def test_step_up_so_abre_a_camada_do_perfil(ambiente, perfil, uf, abre, nao_abre):
    """Substitui test_step_up_n1_e_n2_abrem_com_as_evidencias_do_login (test_servico_autenticacao.py)."""
    u = _criar(ambiente, perfil, "pessoa", uf=uf)
    _, identidade = entrar(ambiente, u, SENHA_FORTE)
    assert identidade is not None
    for nivel in abre:
        assert ambiente.servico.abrir_nivel(identidade, nivel).concedido
    for nivel in nao_abre:
        assert ambiente.servico.abrir_nivel(identidade, nivel).motivo is Motivo.NIVEL_INSUFICIENTE


# ================================================================ cadastro
def test_cadastro_externo_exige_senha_forte_e_nao_tem_camada(cadastro):
    from ecosec.servicos.cadastro import DadosCadastro
    fraca = DadosCadastro("Zeca Lima", None, None, "senha1234", "senha1234", perfil=Perfil().EXTERNO)
    assert cadastro.validar(fraca)                                     # o Externo pode virar administrador
    forte = DadosCadastro("Zeca Lima", None, None, SENHA_FORTE, SENHA_FORTE, perfil=Perfil().EXTERNO)
    assert cadastro.validar(forte) == []
    aceite = cadastro.registrar_aceite("Zeca Lima")
    u = cadastro.concluir(forte, aceite, coleta_completa(cadastro, 5, aceite=aceite))
    assert u.perfil is Perfil().EXTERNO and u.nivel is None and u.uf is None
    assert cadastro.consentimentos.vigente_de(u.id) is not None       # passou pelo termo e pelo rosto


@pytest.mark.parametrize("perfil", ["EXTERNO", "MINISTRO"])
def test_cadastro_dos_perfis_sensiveis_exige_senha_forte(cadastro, perfil):
    from ecosec.servicos.cadastro import DadosCadastro
    assert cadastro.validar(DadosCadastro("Rafa Lima", None, None, "senha1234", "senha1234",
                                          perfil=Perfil()[perfil]))


# ================================================================ identificação e relatórios do sistema
@pytest.fixture
def app(tmp_path):
    from ecosec.aplicacao import montar
    a = montar(caminho_env=tmp_path / ".env", modo="memoria")
    a.administracao.custo = a.cadastro.custo = a.autenticacao.p.custo_bcrypt = 4
    a.cadastro.frames_por_sessao = 3
    a.cadastro.leitura_minima_segundos = 0
    return a


def cadastrar_perfil(app, nome, perfil, semente, uf=None, senha=SENHA_FORTE):
    from ecosec.servicos.cadastro import DadosCadastro
    from test_interface import quadro
    aceite = app.cadastro.registrar_aceite(nome)
    coleta = app.cadastro.nova_coleta(aceite)
    for s in range(2):
        for i in range(3):
            coleta.oferecer(quadro(semente + 10 * s + i))
        if s == 0:
            coleta.avancar_sessao()
    return app.cadastro.concluir(DadosCadastro(nome, None, uf, senha, senha, perfil=Perfil()[perfil]), aceite,
                                 coleta)


def test_identificacao_1n_so_para_o_administrador(app):
    """Identidade de pessoas é gestão de acesso, não acervo; o ministro não identifica mais."""
    from ecosec.servicos.identificacao import ErroIdentificacao
    ministro = cadastrar_perfil(app, "Caio Mendes", "MINISTRO", 900)
    admin = cadastrar_perfil(app, "Rafael Duarte", "EXTERNO", 700)
    app.administracao.administradores.salvar(Administrador(admin.id, AGORA))        # o papel de administrador
    with pytest.raises(ErroIdentificacao):
        app.identificacao.nova_sessao(operador_id=ministro.id)
    assert app.identificacao.nova_sessao(operador_id=admin.id) is not None


def test_relatorios_do_sistema_mostram_o_perfil_e_mascaram_o_acervo(app):
    cadastrar_perfil(app, "Caio Mendes", "EXTERNO", 900)
    for codigo_relatorio in ("S-06", "S-10"):
        tabela = app.relatorios_sistema.gerar(codigo_relatorio)
        assert "Perfil" in tabela.colunas and "Nível" not in tabela.colunas, codigo_relatorio
    s06 = app.relatorios_sistema.gerar("S-06")
    assert any("Externo" in map(str, linha) for linha in s06.linhas)
    app.administracao.trilha.registrar("EXPORTACAO", "CONCEDIDO", "EXPORTACAO_FICHA", nivel_solicitado=2,
                                       usuario_id=1, detalhe="CSV; 1 linhas; sha256 abc; FICHA PND-0042")
    s07 = " ".join(str(c) for linha in app.relatorios_sistema.gerar("S-07").linhas for c in linha)
    assert "PND-0042" not in s07
