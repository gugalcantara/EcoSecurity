"""Perfis de acesso, escopo exclusivo e o administrador separado dos dados.

Domínio, S5, matriz e termo. Quatro perfis: Externo (quem não é do quadro do governo,
sem camada), servidor (N1), diretor (N2) e ministro (N3). Cada perfil vê só a própria camada. O administrador não é
um perfil: é um papel dado a um Externo, e por isso nunca tem camada.
"""
import pytest

from ecosec.dominio.entidades import ErroDominio, Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel


def _perfis():
    from ecosec.dominio.perfis import Perfil
    return Perfil


def _usuario(perfil, uf=None, id_=1, ativo=True):
    return Usuario(matricula=f"M{id_}", nome="Ana Lima", nivel=None, perfil=perfil, senha_hash="$2b$x", uf=uf,
                   id=id_, ativo=ativo)


# ================================================================ domínio
def test_quatro_perfis_cada_um_com_no_maximo_uma_camada():
    Perfil = _perfis()
    assert {p.name: p.camada for p in Perfil} == {"EXTERNO": None, "SERVIDOR": Nivel.N1, "DIRETOR": Nivel.N2,
                                                  "MINISTRO": Nivel.N3}
    assert [p.rotulo for p in Perfil] == ["Externo", "Servidor", "Diretor", "Ministro"]
    assert {p.name for p in Perfil if p.exige_uf} == {"DIRETOR"}


def test_escopo_exclusivo_cada_perfil_ve_so_a_propria_camada():
    """Substitui test_hierarquia_cada_nivel_alcanca_os_de_baixo (test_dominio.py)."""
    Perfil = _perfis()
    assert not hasattr(Nivel, "alcanca")                         # a regra de hierarquia saiu do domínio
    assert Perfil.MINISTRO.ve(Nivel.N3) and not Perfil.MINISTRO.ve(Nivel.N1) and not Perfil.MINISTRO.ve(Nivel.N2)
    assert Perfil.DIRETOR.ve(Nivel.N2) and not Perfil.DIRETOR.ve(Nivel.N1)
    assert Perfil.SERVIDOR.ve(Nivel.N1) and not Perfil.SERVIDOR.ve(Nivel.N2)
    assert not any(Perfil.EXTERNO.ve(n) for n in Nivel)


def test_usuario_guarda_o_perfil_e_o_nivel_vira_a_camada():
    Perfil = _perfis()
    externo = _usuario(Perfil.EXTERNO)
    assert externo.perfil is Perfil.EXTERNO and externo.nivel is None
    assert Usuario(matricula="W", nome="Eva", nivel=None, senha_hash="$2b$x").perfil is Perfil.EXTERNO
    # compatibilidade: quem ainda cria pelo nível recebe o perfil equivalente
    assert Usuario(matricula="X", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x").perfil is Perfil.DIRETOR
    assert Usuario(matricula="Y", nome="Caio", nivel=3, senha_hash="$2b$x").perfil is Perfil.MINISTRO
    assert Usuario(matricula="Z", nome="Ana", nivel=1, senha_hash="$2b$x").perfil is Perfil.SERVIDOR


@pytest.mark.parametrize("perfil, uf", [("DIRETOR", None), ("EXTERNO", "SP"), ("MINISTRO", "SP")])
def test_invariantes_de_uf_por_perfil(perfil, uf):
    Perfil = _perfis()
    with pytest.raises(ErroDominio):
        _usuario(Perfil[perfil], uf=uf)


def test_perfil_e_nivel_incoerentes_sao_recusados():
    Perfil = _perfis()
    with pytest.raises(ErroDominio):
        Usuario(matricula="X", nome="Ana", nivel=3, perfil=Perfil.EXTERNO, senha_hash="$2b$x")
    with pytest.raises(ErroDominio):
        Usuario(matricula="X", nome="Ana", nivel=1, perfil=Perfil.MINISTRO, senha_hash="$2b$x")


def test_motivos_novos_falam_de_acesso_e_de_perfil():
    assert Motivo.SEM_ACESSO.mensagem == "Este cadastro não tem acesso ao sistema. Procure o administrador."
    assert Motivo.NIVEL_INSUFICIENTE.mensagem == "Este conteúdo não faz parte do seu perfil."
    from ecosec.servicos.autenticacao import FALHAS_DE_IDENTIDADE
    assert Motivo.SEM_ACESSO not in FALHAS_DE_IDENTIDADE           # não é ataque: não conta na S1


# ================================================================ S5
@pytest.mark.parametrize("perfil, administrador, entra", [
    ("EXTERNO", False, False), ("EXTERNO", True, True), ("SERVIDOR", False, True), ("DIRETOR", False, True),
    ("MINISTRO", False, True)])
def test_s5_no_login_exige_camada_ou_o_papel_de_administrador(perfil, administrador, entra):
    from ecosec.seguranca.acesso import s5_habilitacao
    Perfil = _perfis()
    uf = "SP" if perfil == "DIRETOR" else None
    v = s5_habilitacao.avaliar(_usuario(Perfil[perfil], uf=uf), True, Nivel.N1, entrada=True,
                               administrador=administrador)
    assert v.aprovado is entra
    if not entra:
        assert v.motivo is Motivo.SEM_ACESSO


@pytest.mark.parametrize("perfil, administrador, nivel, concede", [
    ("MINISTRO", False, Nivel.N1, False), ("MINISTRO", False, Nivel.N2, False), ("MINISTRO", False, Nivel.N3, True),
    ("DIRETOR", False, Nivel.N1, False), ("DIRETOR", False, Nivel.N2, True), ("SERVIDOR", False, Nivel.N1, True),
    ("EXTERNO", True, Nivel.N1, False), ("EXTERNO", True, Nivel.N2, False), ("EXTERNO", True, Nivel.N3, False)])
def test_s5_ao_abrir_uma_camada_exige_que_seja_a_do_perfil(perfil, administrador, nivel, concede):
    """Substitui test_usuario_n3_pode_pedir_nivel_1 (test_politica.py). O administrador não abre camada nenhuma."""
    from ecosec.seguranca.acesso import s5_habilitacao
    Perfil = _perfis()
    uf = "SP" if perfil == "DIRETOR" else None
    v = s5_habilitacao.avaliar(_usuario(Perfil[perfil], uf=uf), True, nivel, administrador=administrador)
    assert v.aprovado is concede
    if not concede:
        assert v.motivo is Motivo.NIVEL_INSUFICIENTE


def test_s7_segunda_pessoa_da_camada_3_vale_e_externo_nao():
    """Outro ministro confirma; um Externo (inclusive o administrador) nunca."""
    from ecosec.seguranca.acesso import s7_custodia
    Perfil = _perfis()
    ministro, outro = _usuario(Perfil.MINISTRO, id_=1), _usuario(Perfil.MINISTRO, id_=2)
    externo = _usuario(Perfil.EXTERNO, id_=3)
    assert s7_custodia.avaliar(ministro, outro, True, 10, 120).aprovado
    assert s7_custodia.avaliar(ministro, externo, True, 10, 120).motivo is Motivo.SEGUNDA_PESSOA_INVALIDA


# ================================================================ matriz (S-09)
def test_papeis_e_camadas():
    from ecosec.seguranca.autorizacao import Papel, papel_de
    Perfil = _perfis()
    assert {p.name: p.camada for p in Papel} == {"SERVIDOR": Nivel.N1, "DIRETOR": Nivel.N2, "MINISTRO": Nivel.N3,
                                                 "ADMINISTRADOR": None}
    assert papel_de(Perfil.MINISTRO) is Papel.MINISTRO
    assert papel_de(Perfil.EXTERNO, administrador=True) is Papel.ADMINISTRADOR
    with pytest.raises(ValueError):
        papel_de(Perfil.EXTERNO)                                  # Externo sem o papel: nenhum papel


def test_matriz_o_administrador_nao_le_dado_nenhum():
    from ecosec.seguranca import autorizacao
    from ecosec.seguranca.autorizacao import Classificacao, Efeito, Operacao, Papel
    for classificacao in Classificacao:
        for operacao in Operacao:
            if operacao is Operacao.ADMINISTRAR:
                continue
            a = autorizacao.decidir(Papel.ADMINISTRADOR, classificacao, operacao)
            assert a.efeito is Efeito.NEGADO, (classificacao, operacao)
    assert autorizacao.decidir(Papel.ADMINISTRADOR, Classificacao.USO_INTERNO,
                               Operacao.ADMINISTRAR).efeito is Efeito.PERMITIDO_COM_VERIFICACAO


@pytest.mark.parametrize("papel, propria", [("SERVIDOR", 1), ("DIRETOR", 2), ("MINISTRO", 3)])
def test_matriz_escopo_exclusivo_fora_da_camada_e_negado(papel, propria):
    """Substitui os casos USO INTERNO e RESERVADO de test_matriz_para_o_ministro (test_modelo_chines.py)."""
    from ecosec.seguranca import autorizacao
    from ecosec.seguranca.autorizacao import Classificacao, Efeito, Operacao, Papel
    for classificacao in Classificacao:
        a = autorizacao.decidir(Papel[papel], classificacao, Operacao.VISUALIZAR)
        if int(classificacao) == propria:
            assert a.efeito is Efeito.PERMITIDO
        else:
            assert (a.efeito, a.motivo) == (Efeito.NEGADO, "NIVEL_INSUFICIENTE"), classificacao


def test_matriz_priorizar_e_da_camada_3():
    from ecosec.seguranca import autorizacao
    from ecosec.seguranca.autorizacao import Classificacao, Efeito, Operacao, Papel
    assert autorizacao.decidir(Papel.MINISTRO, Classificacao.SECRETO, Operacao.PRIORIZAR).efeito is Efeito.PERMITIDO
    assert autorizacao.decidir(Papel.DIRETOR, Classificacao.RESERVADO, Operacao.PRIORIZAR).efeito is Efeito.NEGADO


def test_s09_tem_os_tres_perfis_e_o_admin_sem_dado():
    from ecosec.seguranca import autorizacao
    linhas = autorizacao.tabela()
    assert {p for p, _, _, _ in linhas} == {"SERVIDOR", "DIRETOR", "MINISTRO", "ADMINISTRADOR"}
    admin = [(c, o, e) for p, c, o, e in linhas if p == "ADMINISTRADOR"]
    assert all(e == "NEGADO" for c, o, e in admin if o != "ADMINISTRAR")


# ================================================================ termo
CONTATO = "controlador@ecosecurity.sim.br"
HASHES_V3_1 = {True: "1c7f2ff9388dd015bd5ffb59bd41522fc9601316f2c14e4c684508019326b3d5",
               False: "88a92c54377f3b06716d4badda7506f3c6adcacc4658648d7f8e14f2945ea491"}
HASHES_V3_2 = {True: "cc29fb8d7a2ea354a206a98d0694169c85c0f93ca48323a552dfc7b78b72cdd1",
               False: "e52830c7faa8774f8f7e84496b1d7d786f64e479da9186c3480e92c7c308fc94"}
# a 3.3, arquivada em 08/11/2026, com os hashes calculados antes de a 3.4 entrar
HASHES_V3_3 = {True: "0f5d49f35fc1e1d8bb21159c08ce0be85b8421e3fe686c668754e92ac5fea498",
               False: "1e7533ed21ea5f5d06fd697d7fccca8f85b4995d4eb3ea659aeb93ffb875c206"}


@pytest.mark.parametrize("versao, modulo, hashes", [("3.1", "termo_v3_1", HASHES_V3_1),
                                                    ("3.2", "termo_v3_2", HASHES_V3_2),
                                                    ("3.3", "termo_v3_3", HASHES_V3_3)])
def test_termos_arquivados_continuam_conferindo(versao, modulo, hashes):
    """A 3.2 tem aceite real no banco do aplicativo: arquivada sem nenhuma alteração."""
    import importlib
    from ecosec.dominio import termo
    arquivado = importlib.import_module(f"ecosec.dominio.{modulo}")
    assert arquivado.VERSAO == versao and termo.VERSAO == "3.4"
    for escolha, h in hashes.items():
        assert termo.calcular_hash(arquivado.renderizar("Ana Lima", CONTATO, escolha)) == h
        assert termo.confere(versao, "Ana Lima", CONTATO, escolha, h) is True
    assert set(termo.VERSOES) >= {"2.0", "3.0", "3.1", "3.2", "3.3", "3.4"}


def test_termo_vigente_descreve_os_quatro_perfis_e_o_papel_de_administrador():
    from ecosec.dominio import termo, termo_v3_1, termo_v3_3
    texto = termo.renderizar("Ana Lima", CONTATO, True)
    assert "Versão 3.4" in texto
    assert termo.calcular_hash(texto) not in (HASHES_V3_1[True], HASHES_V3_2[True], HASHES_V3_3[True])
    # a 3.4 é a 3.3 sem o rodapé de documento simulado: as cláusulas são as mesmas
    assert termo.CLAUSULAS == termo_v3_3.CLAUSULAS and texto.endswith("Finalidade (b): AUTORIZO.")
    assert "perfil de acesso atribuído (externo, servidor, diretor ou ministro)" in texto
    assert "papel de administrador" in texto and "código do celular" in texto
    assert "Ministério Público" not in texto
    # descritiva: as finalidades e o resumo são os mesmos da 3.1
    assert termo.FINALIDADE_A == termo_v3_1.FINALIDADE_A and termo.FINALIDADE_B == termo_v3_1.FINALIDADE_B
    assert termo.RESUMO == termo_v3_1.RESUMO
    assert "—" not in texto and "DOCUMENTO SIMULADO" not in texto
