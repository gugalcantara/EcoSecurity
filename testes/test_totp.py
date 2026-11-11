"""Código do celular (TOTP): o cálculo confere com a norma e as regras de uso valem."""
import base64
from datetime import datetime, timedelta, timezone

import pytest

from ecosec.seguranca.acesso import totp

# Apêndice B da RFC 6238 (SHA-1): segredo "12345678901234567890", 8 dígitos
SEGREDO_RFC = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
VETORES_RFC = [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
               (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")]


@pytest.mark.parametrize("segundos, esperado", VETORES_RFC)
def test_vetores_da_rfc_6238(segundos, esperado):
    instante = datetime.fromtimestamp(segundos, tz=timezone.utc)
    assert totp.codigo(SEGREDO_RFC, instante, digitos=8) == esperado


def test_segredo_novo_e_base32_de_160_bits_e_nunca_repete():
    a, b = totp.gerar_segredo(), totp.gerar_segredo()
    assert a != b
    assert len(totp._chave(a)) == 20


AGORA = datetime(2026, 11, 2, 15, 0, 10)


def test_aceita_o_codigo_atual_e_devolve_o_passo():
    s = totp.gerar_segredo()
    assert totp.conferir(s, totp.codigo(s, AGORA), AGORA) == totp.passo(AGORA)


def test_tolera_um_passo_de_relogio_para_cada_lado_e_nao_mais():
    s = totp.gerar_segredo()
    assert totp.conferir(s, totp.codigo(s, AGORA - timedelta(seconds=30)), AGORA) is not None
    assert totp.conferir(s, totp.codigo(s, AGORA + timedelta(seconds=30)), AGORA) is not None
    assert totp.conferir(s, totp.codigo(s, AGORA - timedelta(seconds=90)), AGORA) is None


def test_codigo_ja_usado_nao_vale_de_novo():
    s = totp.gerar_segredo()
    c = totp.codigo(s, AGORA)
    usado = totp.conferir(s, c, AGORA)
    assert totp.conferir(s, c, AGORA + timedelta(seconds=5), ultimo_passo=usado) is None


def test_codigo_de_outro_segredo_ou_mal_formado_nega():
    s = SEGREDO_RFC
    validos = {totp.codigo(s, AGORA + timedelta(seconds=30 * d)) for d in (-1, 0, 1)}
    errado = next(f"{n:06d}" for n in range(10 ** 6) if f"{n:06d}" not in validos)
    assert totp.conferir(s, errado, AGORA) is None
    for ruim in ("", "12345", "1234567", "abcdef", None):
        assert totp.conferir(s, ruim, AGORA) is None
    assert totp.conferir("", "123456", AGORA) is None                  # sem segredo cadastrado


def test_aceita_codigo_digitado_com_espaco():
    s = totp.gerar_segredo()
    c = totp.codigo(s, AGORA)
    assert totp.conferir(s, f"{c[:3]} {c[3:]}", AGORA) is not None


def test_uri_que_o_aplicativo_escaneia():
    uri = totp.uri_provisionamento("ABCDEF234567", "7Q3JYV8")
    assert uri.startswith("otpauth://totp/EcoSecurity%3A7Q3JYV8?")
    assert "secret=ABCDEF234567" in uri and "issuer=EcoSecurity" in uri and "digits=6" in uri


def test_codigos_de_recuperacao_tem_formato_e_hash_insensivel_a_hifen_e_caixa():
    codigos = totp.gerar_codigos_recuperacao(8)
    assert len(set(codigos)) == 8
    for c in codigos:
        assert len(c) == 19 and c.count("-") == 3 and totp.eh_formato_recuperacao(c)
        assert not set(c.replace("-", "")) & set("ILOU")
    c = codigos[0]
    assert totp.hash_recuperacao(c) == totp.hash_recuperacao(c.replace("-", "").lower())
    assert not totp.eh_formato_recuperacao("123456")                    # um código TOTP não é de recuperação
