"""Segredos do .env: protegidos pelo Windows (DPAPI) e com backup por frase-senha."""
import pytest

from ecosec import segredos

DPAPI = pytest.mark.skipif(not segredos.dpapi_disponivel(), reason="DPAPI só existe no Windows")


@DPAPI
def test_valor_gravado_fica_ilegivel_no_arquivo_e_volta_intacto(tmp_path):
    env = tmp_path / ".env"
    segredos.gravar("DB_SENHA", "s3gr3do-${HOME}", env)
    texto = env.read_text(encoding="utf-8")
    assert "s3gr3do" not in texto and "DB_SENHA='dpapi:" in texto        # o nome continua legível
    assert segredos.ler("DB_SENHA", env) == "s3gr3do-${HOME}"


@DPAPI
def test_env_antigo_em_texto_puro_continua_lido_e_e_convertido(tmp_path):
    env = tmp_path / ".env"
    env.write_text('A="um"\nB="dois"\n', encoding="utf-8")
    assert segredos.ler("A", env) == "um"
    assert segredos.proteger_existentes(env) == 2
    assert segredos.proteger_existentes(env) == 0                         # idempotente
    assert "um" not in env.read_text(encoding="utf-8") and segredos.ler("B", env) == "dois"


@DPAPI
def test_valor_de_outra_conta_ou_corrompido_nao_abre_e_diz_o_que_fazer(tmp_path):
    env = tmp_path / ".env"
    env.write_text('X="dpapi:AAAA"\n', encoding="utf-8")
    with pytest.raises(segredos.ErroSegredo, match="restaurar"):
        segredos.ler("X", env)


def test_backup_restaura_com_a_frase_certa_e_recusa_a_errada(tmp_path):
    env = tmp_path / ".env"
    segredos.gravar("CHAVE_CIFRAGEM", "chave-do-modelo", env)
    segredos.gravar("DB_SEGURANCA_SENHA", "senha-do-banco", env)
    pacote = segredos.exportar_backup("frase longa o bastante", env)
    assert b"chave-do-modelo" not in pacote and b"senha-do-banco" not in pacote
    assert segredos.importar_backup(pacote, "frase longa o bastante") == {
        "CHAVE_CIFRAGEM": "chave-do-modelo", "DB_SEGURANCA_SENHA": "senha-do-banco"}
    with pytest.raises(segredos.ErroSegredo, match="incorreta"):
        segredos.importar_backup(pacote, "outra frase qualquer")


def test_backup_exige_frase_minima_e_recusa_arquivo_estranho(tmp_path):
    with pytest.raises(segredos.ErroSegredo, match="12"):
        segredos.exportar_backup("curta", tmp_path / ".env")
    with pytest.raises(segredos.ErroSegredo, match="não é um backup"):
        segredos.importar_backup(b"qualquer coisa", "frase longa o bastante")


def test_apagar_remove_so_a_chave_pedida(tmp_path):
    env = tmp_path / ".env"
    segredos.gravar("A", "1", env)
    segredos.gravar("B", "2", env)
    segredos.apagar("A", env)
    segredos.apagar("NAO_EXISTE", env)
    assert segredos.nomes(env) == ["B"]


def test_chave_totp_e_propria_e_nunca_e_trocada(tmp_path):
    env = tmp_path / ".env"
    totp = segredos.garantir_chave_totp(env)
    assert segredos.garantir_chave_totp(env) == totp
    assert segredos.garantir_chave_cifragem(env) != totp


@DPAPI
def test_env_de_outra_conta_vira_erro_de_abertura_com_a_orientacao(tmp_path):
    """Programa e ferramentas tratam ErroAbertura: o .env de outra conta não pode estourar como traceback."""
    from ecosec.aplicacao import ErroAbertura, montar
    env = tmp_path / ".env"
    env.write_text('DB_SEGURANCA_USUARIO="dpapi:AAAA"\nDB_SEGURANCA_SENHA="dpapi:AAAA"\n', encoding="utf-8")
    with pytest.raises(ErroAbertura, match="restaurar"):
        montar(caminho_env=env, modo="mysql")
