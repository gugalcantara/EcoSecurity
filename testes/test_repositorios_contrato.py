"""Testes de contrato dos repositórios.

A mesma bateria roda sobre a implementação em memória e sobre o MySQL real
(num banco descartável criado pelo teste): se as duas divergirem em alguma
regra, o teste acusa. Sem o MySQL preparado, os casos "mysql" aparecem como
pulados.
"""
from datetime import datetime, timedelta

import pytest

from ecosec.dominio.entidades import Administrador, Consentimento, RegistroTentativas, Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.repositorios.contratos import MatriculaDuplicada, RegistroInexistente
from ecosec.repositorios.memoria import (RepositorioAdministradoresMemoria, RepositorioConsentimentosMemoria,
                                         RepositorioTentativasMemoria, RepositorioUsuariosMemoria)


@pytest.fixture(params=["memoria", "mysql"])
def repos(request):
    if request.param == "memoria":
        return RepositorioUsuariosMemoria(), RepositorioTentativasMemoria(), RepositorioConsentimentosMemoria()
    from ecosec.repositorios.mysql import (RepositorioConsentimentosMySQL, RepositorioTentativasMySQL,
                                           RepositorioUsuariosMySQL)
    banco = request.getfixturevalue("banco_mysql_limpo")      # pula se não houver MySQL
    return (RepositorioUsuariosMySQL(banco), RepositorioTentativasMySQL(banco),
            RepositorioConsentimentosMySQL(banco))


def novo(matricula="R7K2M94", nivel=Nivel.N1, **extra):
    return Usuario(matricula=matricula, nome="Ana", nivel=nivel, senha_hash="$2b$x", **extra)


# Usuários
def test_adicionar_atribui_id_e_data(repos):
    usuarios, _, _ = repos
    gravado = usuarios.adicionar(novo())
    assert gravado.id is not None and gravado.criado_em is not None
    assert usuarios.por_id(gravado.id) == gravado


def test_ids_distintos(repos):
    usuarios, _, _ = repos
    a, b = usuarios.adicionar(novo("AAA")), usuarios.adicionar(novo("BBB"))
    assert a.id != b.id


def test_matricula_duplicada_recusada_mesmo_com_caixa_e_espacos(repos):
    usuarios, _, _ = repos
    usuarios.adicionar(novo("R7K2M94"))
    with pytest.raises(MatriculaDuplicada):
        usuarios.adicionar(novo(" r7k2m94 "))


def test_busca_por_matricula_ignora_caixa_e_espacos(repos):
    usuarios, _, _ = repos
    gravado = usuarios.adicionar(novo("R7K2M94"))
    assert usuarios.por_matricula("  r7k2m94") == gravado


def test_consulta_sem_resultado_devolve_none(repos):
    usuarios, _, _ = repos
    assert usuarios.por_id(999) is None
    assert usuarios.por_matricula("NAOEXISTE") is None


def test_atualizar_preserva_matricula_e_criacao(repos):
    import dataclasses
    usuarios, _, _ = repos
    gravado = usuarios.adicionar(novo())
    usuarios.atualizar(dataclasses.replace(gravado, ativo=False, matricula="OUTRA"))
    lido = usuarios.por_id(gravado.id)
    assert lido.ativo is False
    assert lido.matricula == gravado.matricula and lido.criado_em == gravado.criado_em


def test_atualizar_inexistente_e_erro(repos):
    usuarios, _, _ = repos
    with pytest.raises(RegistroInexistente):
        usuarios.atualizar(novo(id=42))


def test_listar_em_ordem_de_id(repos):
    usuarios, _, _ = repos
    for m in ("CCC", "AAA", "BBB"):
        usuarios.adicionar(novo(m))
    assert [u.matricula for u in usuarios.listar()] == ["CCC", "AAA", "BBB"]


# Tentativas
def test_tentativas_salvar_e_obter(repos):
    _, tentativas, _ = repos
    assert tentativas.obter("X1") is None
    tentativas.salvar(RegistroTentativas("x1", 2))
    assert tentativas.obter(" X1 ").falhas == 2
    bloqueio = datetime(2026, 10, 6, 14, 15, 0, 123456)
    tentativas.salvar(RegistroTentativas("X1", 0, bloqueio))                # atualiza a mesma linha
    assert tentativas.obter("X1") == RegistroTentativas("X1", 0, bloqueio)


def test_tentativas_valem_para_matricula_inexistente(repos):
    # a S1 indexa pela matrícula digitada: o repositório não exige usuário
    _, tentativas, _ = repos
    tentativas.salvar(RegistroTentativas("NINGUEM", 1))
    assert tentativas.obter("NINGUEM").falhas == 1


# Consentimentos
def _termo(momento=datetime(2026, 10, 6, 10)):
    return Consentimento("Ana", "1.0", "a" * 64, momento)


def test_consentimento_registrado_antes_do_usuario_e_vinculado_depois(repos):
    usuarios, _, consentimentos = repos
    termo = consentimentos.registrar(_termo())
    assert termo.id is not None and termo.usuario_id is None
    usuario = usuarios.adicionar(novo())
    assert consentimentos.vigente_de(usuario.id) is None
    consentimentos.vincular(termo.id, usuario.id)
    assert consentimentos.vigente_de(usuario.id).id == termo.id


def test_revogar_marca_e_nao_apaga(repos):
    usuarios, _, consentimentos = repos
    u = usuarios.adicionar(novo())
    termo = consentimentos.registrar(_termo())
    consentimentos.vincular(termo.id, u.id)
    assert consentimentos.revogar(u.id, datetime(2026, 10, 7)) is True
    assert consentimentos.vigente_de(u.id) is None
    assert consentimentos.revogar(u.id, datetime(2026, 10, 8)) is False   # nada mais vigente


def test_vigente_e_o_mais_recente(repos):
    usuarios, _, consentimentos = repos
    u = usuarios.adicionar(novo())
    for dia in (6, 8, 7):
        c = consentimentos.registrar(_termo(datetime(2026, 10, dia)))
        consentimentos.vincular(c.id, u.id)
    assert consentimentos.vigente_de(u.id).momento == datetime(2026, 10, 8)


def test_atualizar_sem_mudanca_nao_e_registro_inexistente(repos):
    # no MySQL, UPDATE que grava o mesmo valor "altera" 0 linhas (por isso FOUND_ROWS)
    usuarios, _, _ = repos
    u = usuarios.adicionar(novo())
    usuarios.atualizar(u)
    assert usuarios.por_id(u.id) == u


def test_injecao_de_sql_na_matricula_e_so_texto(repos):
    usuarios, tentativas, _ = repos
    usuarios.adicionar(novo("R7K2M94"))
    assert usuarios.por_matricula("' OR '1'='1") is None
    tentativas.salvar(RegistroTentativas("x');DROP TABLE u;--", 1))      # 19 caracteres
    assert usuarios.por_matricula("R7K2M94") is not None             # a tabela continua lá


def test_vincular_inexistente_e_erro(repos):
    _, _, consentimentos = repos
    with pytest.raises(RegistroInexistente):
        consentimentos.vincular(999, 1)


def test_matricula_maior_que_a_coluna_e_recusada_igual_nos_dois(repos):
    from ecosec.repositorios.contratos import ErroRepositorio
    _, tentativas, _ = repos
    with pytest.raises(ErroRepositorio):
        tentativas.salvar(RegistroTentativas("X" * 21, 1))


def test_consentimento_guarda_a_finalidade_b(repos):
    import dataclasses
    usuarios, _, consentimentos = repos
    u = usuarios.adicionar(novo())
    c = consentimentos.registrar(dataclasses.replace(_termo(), usuario_id=u.id, autoriza_pesquisa=True))
    assert consentimentos.vigente_de(u.id).autoriza_pesquisa is True and c.autoriza_pesquisa is True


def test_bloqueadas_lista_so_as_vigentes(repos):
    _, tentativas, _ = repos
    agora = datetime(2026, 10, 7, 12, 0)
    tentativas.salvar(RegistroTentativas("VIGENTE", 0, agora + timedelta(minutes=10)))
    tentativas.salvar(RegistroTentativas("VENCIDO", 0, agora - timedelta(minutes=1)))
    tentativas.salvar(RegistroTentativas("SEMBLOQUEIO", 2, None))
    assert [r.matricula for r in tentativas.bloqueadas(agora)] == ["VIGENTE"]


# Administradores
@pytest.fixture(params=["memoria", "mysql"])
def admins(request):
    if request.param == "memoria":
        return RepositorioUsuariosMemoria(), RepositorioAdministradoresMemoria()
    from ecosec.repositorios.mysql import RepositorioAdministradoresMySQL, RepositorioUsuariosMySQL
    banco = request.getfixturevalue("banco_mysql_limpo")
    return RepositorioUsuariosMySQL(banco), RepositorioAdministradoresMySQL(banco)


DESIGNACAO = datetime(2026, 11, 2, 10, 0, 0, 250000)


def test_administrador_salvo_e_lido_igual(admins):
    usuarios, adms = admins
    a, b, c = (usuarios.adicionar(novo(m, Nivel.N3)) for m in ("AAA", "BBB", "CCC"))
    registro = Administrador(c.id, DESIGNACAO, designado_por=a.id, aprovado_por=b.id, segredo_totp="gAAAA-opaco")
    adms.salvar(registro)
    assert adms.obter(c.id) == registro and adms.obter(a.id) is None
    adms.salvar(Administrador(a.id, DESIGNACAO - timedelta(days=1)))
    assert [x.usuario_id for x in adms.listar()] == [a.id, c.id]        # em ordem de designação


def test_tirar_o_papel_marca_e_mantem_a_linha(admins):
    import dataclasses
    usuarios, adms = admins
    u = usuarios.adicionar(novo("AAA", Nivel.N3))
    adms.salvar(Administrador(u.id, DESIGNACAO))
    adms.salvar(dataclasses.replace(adms.obter(u.id), ativo=False, removido_em=DESIGNACAO + timedelta(hours=1)))
    lido = adms.obter(u.id)
    assert lido.ativo is False and lido.removido_em == DESIGNACAO + timedelta(hours=1)


def test_passo_do_codigo_so_avanca(admins):
    usuarios, adms = admins
    u = usuarios.adicionar(novo("AAA", Nivel.N3))
    adms.salvar(Administrador(u.id, DESIGNACAO, segredo_totp="x"))
    assert adms.registrar_passo(u.id, 100) is True
    assert adms.registrar_passo(u.id, 100) is False                     # o mesmo código, de novo
    assert adms.registrar_passo(u.id, 99) is False
    assert adms.registrar_passo(u.id, 101) is True and adms.obter(u.id).ultimo_passo == 101
    assert adms.registrar_passo(999, 5) is False                        # quem não é administrador


def test_codigos_de_recuperacao_sao_de_uso_unico_e_trocar_inutiliza_os_antigos(admins):
    usuarios, adms = admins
    u = usuarios.adicionar(novo("AAA", Nivel.N3))
    adms.salvar(Administrador(u.id, DESIGNACAO))
    adms.trocar_codigos(u.id, ["a" * 64, "b" * 64], DESIGNACAO)
    validos = adms.codigos_validos(u.id)
    assert sorted(c.hash_codigo for c in validos) == ["a" * 64, "b" * 64]
    assert adms.usar_codigo(validos[0].id, DESIGNACAO) is True
    assert adms.usar_codigo(validos[0].id, DESIGNACAO) is False           # já usado
    assert len(adms.codigos_validos(u.id)) == 1
    adms.trocar_codigos(u.id, ["c" * 64], DESIGNACAO)
    assert [c.hash_codigo for c in adms.codigos_validos(u.id)] == ["c" * 64]


def test_dominio_recusa_quem_aprova_o_proprio_pedido():
    from ecosec.dominio.entidades import ErroDominio
    with pytest.raises(ErroDominio):
        Administrador(3, DESIGNACAO, designado_por=1, aprovado_por=1)
