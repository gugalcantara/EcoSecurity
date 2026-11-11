"""Código do celular (TOTP, RFC 6238): o fator de posse do administrador.

A senha prova o que a pessoa sabe e o rosto, o que ela É. O código de 6 dígitos
prova o que ela tem: o celular onde o segredo foi cadastrado (Google
Authenticator, Microsoft Authenticator e similares).

Como funciona (RFC 4226 + RFC 6238):
    contador = segundos desde 1970 // 30           (muda a cada 30 s)
    mac      = HMAC-SHA1(segredo, contador em 8 bytes)
    corte    = 4 bytes de `mac`, a partir da posição dada pelo último meio-byte
    código   = (corte sem o bit de sinal) mod 10^6
O celular e o sistema guardam o mesmo segredo e calculam o mesmo número sem
conversar: por isso funciona sem internet, só precisa do relógio certo.

Decisões:
- Implementado aqui, sem biblioteca: são poucas linhas, e os vetores de teste
  da própria RFC 6238 provam que o cálculo está certo (testes/test_totp.py).
- Tolerância de um passo para cada lado (±30 s): relógios levemente diferentes.
- Anti-repetição: um código só vale se o seu passo for maior que o último já
  aceito daquela pessoa. Quem viu o código por cima do ombro não o reusa.
- Comparação em tempo constante (hmac.compare_digest).
- Funções puras: o instante vem de fora, como na S1.

Códigos de recuperação: cada admin recebe alguns, impressos, para o dia em que
perder o celular. São de uso único, têm 80 bits de acaso (16 caracteres de um
alfabeto de 32) e só o SHA-256 deles é guardado.
"""
import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime
from urllib.parse import quote, urlencode

PASSO_SEGUNDOS = 30
DIGITOS = 6
TOLERANCIA_PASSOS = 1
BYTES_SEGREDO = 20                     # 160 bits, o tamanho recomendado pela RFC 4226 para o SHA-1

# Alfabeto dos códigos de recuperação: sem I, L, o e U (confundem com 1, 1, 0 e V na leitura do papel)
ALFABETO_RECUPERACAO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
GRUPOS_RECUPERACAO, TAMANHO_GRUPO = 4, 4


def gerar_segredo() -> str:
    """Segredo novo em base32 (o formato que os aplicativos leem), sem o '=' de preenchimento."""
    return base64.b32encode(secrets.token_bytes(BYTES_SEGREDO)).decode("ascii").rstrip("=")


def _chave(segredo_b32: str) -> bytes:
    limpo = segredo_b32.strip().replace(" ", "").upper()
    return base64.b32decode(limpo + "=" * (-len(limpo) % 8))


def passo(instante: datetime, passo_segundos: int = PASSO_SEGUNDOS) -> int:
    """Número do intervalo de 30 s em que `instante` cai (o 'contador' da RFC 6238)."""
    return int(instante.timestamp()) // passo_segundos


def hotp(chave: bytes, contador: int, digitos: int = DIGITOS) -> str:
    """RFC 4226: o código de um contador. Base do TOTP."""
    mac = hmac.new(chave, struct.pack(">Q", contador), hashlib.sha1).digest()
    deslocamento = mac[-1] & 0x0F
    corte = struct.unpack(">I", mac[deslocamento:deslocamento + 4])[0] & 0x7FFFFFFF
    return str(corte % 10 ** digitos).zfill(digitos)


def codigo(segredo_b32: str, instante: datetime, digitos: int = DIGITOS) -> str:
    """O código que o celular mostra em `instante`."""
    return hotp(_chave(segredo_b32), passo(instante), digitos)


def _normalizar_codigo(texto: str) -> str:
    return "".join(texto.split())


def conferir(segredo_b32: str, informado: str, instante: datetime, ultimo_passo: int | None = None) -> int | None:
    """Devolve o PASSO aceito (para gravar como o último usado) ou None.

    Nega código já usado (passo <= ultimo_passo) e qualquer coisa que não sejam
    exatamente 6 dígitos. Sem segredo cadastrado, nega."""
    informado = _normalizar_codigo(informado or "")
    if not segredo_b32 or len(informado) != DIGITOS or not informado.isdigit():
        return None
    chave, atual = _chave(segredo_b32), passo(instante)
    for p in range(atual - TOLERANCIA_PASSOS, atual + TOLERANCIA_PASSOS + 1):
        if ultimo_passo is not None and p <= ultimo_passo:
            continue
        if hmac.compare_digest(hotp(chave, p), informado):
            return p
    return None


def uri_provisionamento(segredo_b32: str, conta: str, emissor: str = "EcoSecurity") -> str:
    """O texto do QR que o aplicativo do celular escaneia (formato otpauth:// do Google Authenticator)."""
    rotulo = quote(f"{emissor}:{conta}")
    parametros = urlencode({"secret": segredo_b32, "issuer": emissor, "algorithm": "SHA1",
                            "digits": DIGITOS, "period": PASSO_SEGUNDOS})
    return f"otpauth://totp/{rotulo}?{parametros}"


# ---------------------------------------------------------------- códigos de recuperação
def gerar_codigos_recuperacao(quantidade: int) -> list[str]:
    """Códigos no formato XXXX-XXXX-XXXX-XXXX. Mostrados UMA vez; só o hash é guardado."""
    def um() -> str:
        letras = "".join(secrets.choice(ALFABETO_RECUPERACAO) for _ in range(GRUPOS_RECUPERACAO * TAMANHO_GRUPO))
        return "-".join(letras[i:i + TAMANHO_GRUPO] for i in range(0, len(letras), TAMANHO_GRUPO))
    return [um() for _ in range(quantidade)]


def normalizar_recuperacao(texto: str) -> str:
    """Aceita o código com ou sem hífens e espaços, em minúsculas ou maiúsculas."""
    return "".join(c for c in (texto or "").upper() if c.isalnum())


def eh_formato_recuperacao(texto: str) -> bool:
    limpo = normalizar_recuperacao(texto)
    return (len(limpo) == GRUPOS_RECUPERACAO * TAMANHO_GRUPO
            and all(c in ALFABETO_RECUPERACAO for c in limpo))


def hash_recuperacao(texto: str) -> str:
    return hashlib.sha256(normalizar_recuperacao(texto).encode("ascii")).hexdigest()
