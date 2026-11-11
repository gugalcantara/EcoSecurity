"""Domínio: níveis, camadas, motivos e invariantes das entidades."""
import dataclasses
from datetime import datetime

import pytest

from ecosec.dominio.camadas import Anel, CamadaSeguranca, camadas_do_anel
from ecosec.dominio.entidades import Consentimento, ErroDominio, Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Exportacao, ModoBiometrico, Nivel


# ---------------------------------------------------------------- Níveis
def test_modo_biometrico_por_nivel():
    assert Nivel.N1.modo is ModoBiometrico.IDENTIFICACAO
    assert Nivel.N2.modo is ModoBiometrico.VERIFICACAO
    assert Nivel.N3.modo is ModoBiometrico.VERIFICACAO


def test_exportacao_por_nivel():
    assert [n.exportacao for n in Nivel] == [Exportacao.LIVRE, Exportacao.COM_MARCA,
                                             Exportacao.BLOQUEADA]


def test_sem_hierarquia_cada_perfil_ve_so_a_propria_camada():
    """Escopo exclusivo: nenhum nível alcança os de baixo."""
    from ecosec.dominio.perfis import Perfil
    assert not hasattr(Nivel, "alcanca")
    assert not Perfil.MINISTRO.ve(Nivel.N1) and Perfil.DIRETOR.ve(Nivel.N2) and not Perfil.SERVIDOR.ve(Nivel.N2)


# ---------------------------------------------------------------- Camadas
def test_dez_camadas_com_codigos_sequenciais():
    assert [c.codigo for c in CamadaSeguranca] == [f"S{i}" for i in range(1, 11)]


def test_aneis_agrupam_as_camadas():
    assert len(camadas_do_anel(Anel.ACESSO)) == 7
    assert [c.codigo for c in camadas_do_anel(Anel.CONTEUDO)] == ["S8", "S9"]
    assert [c.codigo for c in camadas_do_anel(Anel.EVIDENCIA)] == ["S10"]


def test_nivel_1_nao_passa_por_senha_nem_vivacidade():
    assert not CamadaSeguranca.S2_CONHECIMENTO.atua_no(Nivel.N1)
    assert not CamadaSeguranca.S6_VIVACIDADE.atua_no(Nivel.N1)
    assert CamadaSeguranca.S4_INERENCIA.atua_no(Nivel.N1)


def test_vivacidade_e_custodia_so_no_nivel_3():
    for camada in (CamadaSeguranca.S6_VIVACIDADE, CamadaSeguranca.S7_CUSTODIA):
        assert camada.niveis == {Nivel.N3}


# ---------------------------------------------------------------- Motivos
def test_todo_motivo_tem_mensagem():
    for motivo in Motivo:
        assert motivo.mensagem


def test_falhas_de_identidade_dizem_o_mesmo_na_tela():
    # rosto desconhecido x rosto de outra pessoa com a senha certa
    assert Motivo.FACE_NAO_RECONHECIDA.mensagem == Motivo.CREDENCIAL_ALHEIA.mensagem
    # matrícula inexistente x senha errada
    assert Motivo.USUARIO_INEXISTENTE.mensagem == Motivo.SENHA_INCORRETA.mensagem


def test_so_concedido_concede():
    assert [m for m in Motivo if m.concede] == [Motivo.CONCEDIDO]


def test_motivo_aponta_a_camada():
    assert Motivo.BLOQUEADO.camada is CamadaSeguranca.S1_CONTENCAO
    assert Motivo.CREDENCIAL_ALHEIA.camada is CamadaSeguranca.S4_INERENCIA


# ---------------------------------------------------------------- Entidades
def _usuario(**ajustes):
    base = dict(matricula="R7K2M94", nome="Ana", nivel=Nivel.N1, senha_hash="$2b$hash")
    return Usuario(**{**base, **ajustes})


def test_nivel_2_sem_uf_nao_pode_existir():
    with pytest.raises(ErroDominio, match="UF"):
        _usuario(nivel=Nivel.N2)
    assert _usuario(nivel=Nivel.N2, uf="SP").uf == "SP"


def test_uf_invalida_recusada():
    with pytest.raises(ErroDominio):
        _usuario(uf="XX")


@pytest.mark.parametrize("campo", ["matricula", "nome", "senha_hash"])
def test_campos_obrigatorios(campo):
    with pytest.raises(ErroDominio):
        _usuario(**{campo: "  " if campo != "senha_hash" else ""})


def test_nivel_inteiro_vira_enum():
    assert _usuario(nivel=3).nivel is Nivel.N3


def test_hash_da_senha_nao_aparece_no_repr():
    assert "$2b$hash" not in repr(_usuario())


def test_usuario_e_imutavel():
    usuario = _usuario()
    with pytest.raises(dataclasses.FrozenInstanceError):
        usuario.ativo = False
    assert dataclasses.replace(usuario, ativo=False).ativo is False


def test_consentimento_vigente_ate_revogar():
    termo = Consentimento("Ana", "1.0", "a" * 64, datetime(2026, 10, 6))
    assert termo.vigente
    assert not dataclasses.replace(termo, revogado_em=datetime(2026, 10, 7)).vigente


def test_matricula_acima_do_limite_nao_pode_existir():
    from ecosec.dominio.entidades import MATRICULA_MAX
    with pytest.raises(ErroDominio):
        _usuario(matricula="X" * (MATRICULA_MAX + 1))
