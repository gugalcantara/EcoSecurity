"""S9 Rastreio: "Se vazar, de quem veio?"

Todo material liberado nos níveis 2 e 3 recebe uma MARCA D'ÁGUA invisível com
quem o recebeu e quando. Se uma cópia aparecer onde não devia, a marca
extraída dela aponta a origem do vazamento.

A marca (64 bits):  usuário (24) · minuto em que foi liberado (32) · CRC-8 (8)
o CRC detecta extração corrompida: sem ele, uma marca danificada poderia
apontar um inocente. Marca que não confere devolve None: nunca um palpite.

Dois métodos, comparados de propósito (etp 6.5):

LSB (bit menos significativo): troca o último bit de pixels escolhidos.
  Invisível (muda o tom em 1 de 255) e simples, mas frágil: qualquer
  recompressão JPEG reescreve esses bits. É o contraponto que justifica o DCT.

DCT (transformada discreta do cosseno, a mesma do JPEG): em cada bloco 8×8 da
  luminância, compara dois coeficientes de média frequência e força a ordem
  entre eles conforme o bit (1: c1 > c2; 0: c2 > c1). O JPEG quantiza sobretudo
  as altas frequências; as médias sobrevivem: e a marca com elas.
  Antes de marcar, a luminância é comprimida para [m, 255 - m]: num documento de
  fundo branco (255), somar energia ao bloco estouraria o limite e apagaria a
  marca exatamente onde há mais área livre. A folga m é a menor que a marca
  precisa: proporcional à força (≈ 0,3 × força). Uma folga fixa maior custava
  mais qualidade de imagem que a própria marca (medido: 26,9 dB só da compressão).

Os 64 bits se repetem por toda a imagem, em posições embaralhadas por uma chave
secreta; a extração vota bit a bit (maioria). Sem a chave, não se sabe onde a
marca está: nem para lê-la, nem para apagá-la seletivamente.
"""
import hashlib
import math
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone

import cv2
import numpy as np

from ecosec.dominio.camadas import CamadaSeguranca

CAMADA = CamadaSeguranca.S9_RASTREIO
BITS_USUARIO, BITS_MINUTO, BITS_CRC = 24, 32, 8
TOTAL_BITS = BITS_USUARIO + BITS_MINUTO + BITS_CRC
_EPOCA = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Marca:
    usuario_id: int
    momento: datetime                # precisão de minuto (o que cabe em 32 bits)


@dataclass(frozen=True)
class ParametrosMarca:
    metodo: str                      # "dct" ou "lsb"
    forca_dct: float
    coef_a: tuple[int, int]
    coef_b: tuple[int, int]

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosMarca":
        m = cfg.secao("s9_rastreio")
        return cls(m["metodo"], float(m["forca_dct"]), tuple(m["coef_a"]), tuple(m["coef_b"]))


# ------------------------------------------------------------ carga (bits)
def _crc8(valor: int) -> int:
    return zlib.crc32(valor.to_bytes(7, "big")) & 0xFF


def codificar(marca: Marca) -> np.ndarray:
    if not 0 <= marca.usuario_id < 2 ** BITS_USUARIO:
        raise ValueError("usuário fora da faixa da marca")
    minuto = int((marca.momento.astimezone(timezone.utc) - _EPOCA).total_seconds() // 60)
    if not 0 <= minuto < 2 ** BITS_MINUTO:
        raise ValueError("momento fora da faixa da marca")
    corpo = (marca.usuario_id << BITS_MINUTO) | minuto
    valor = (corpo << BITS_CRC) | _crc8(corpo)
    return np.array([(valor >> (TOTAL_BITS - 1 - i)) & 1 for i in range(TOTAL_BITS)], dtype=np.uint8)


def decodificar(bits: np.ndarray) -> Marca | None:
    valor = 0
    for b in bits[:TOTAL_BITS]:
        valor = (valor << 1) | int(b)
    corpo, crc = valor >> BITS_CRC, valor & 0xFF
    if _crc8(corpo) != crc:
        return None                                    # corrompida: nenhum palpite
    usuario, minuto = corpo >> BITS_MINUTO, corpo & (2 ** BITS_MINUTO - 1)
    momento = _EPOCA.timestamp() + minuto * 60
    return Marca(usuario, datetime.fromtimestamp(momento, timezone.utc))


def _ordem(n_posicoes: int, chave: bytes) -> np.ndarray:
    """Posições embaralhadas pela chave: sem ela, não se sabe onde a marca está."""
    semente = int.from_bytes(hashlib.sha256(b"ecosec-marca|" + chave).digest()[:8], "big")
    return np.random.default_rng(semente).permutation(n_posicoes)


def _votar(lidos: np.ndarray, indices_bit: np.ndarray) -> np.ndarray:
    votos = np.zeros(TOTAL_BITS)
    contagem = np.zeros(TOTAL_BITS)
    np.add.at(votos, indices_bit, lidos)
    np.add.at(contagem, indices_bit, 1)
    return (votos > contagem / 2).astype(np.uint8)


# ------------------------------------------------------------ LSB
def _canal_lsb(img: np.ndarray) -> np.ndarray:
    return img[..., 0] if img.ndim == 3 else img       # canal azul: o olho é menos sensível a ele


def inserir_lsb(img: np.ndarray, marca: Marca, chave: bytes) -> np.ndarray:
    saida = img.copy()
    canal = _canal_lsb(saida)
    plano = canal.reshape(-1)
    ordem = _ordem(plano.size, chave)
    bits = codificar(marca)
    usados = (plano.size // TOTAL_BITS) * TOTAL_BITS
    alvos = ordem[:usados]
    plano[alvos] = (plano[alvos] & 0xFE) | np.tile(bits, usados // TOTAL_BITS)
    if img.ndim == 3:
        saida[..., 0] = plano.reshape(canal.shape)
    else:
        saida = plano.reshape(canal.shape)
    return saida


def extrair_lsb(img: np.ndarray, chave: bytes) -> Marca | None:
    plano = _canal_lsb(img).reshape(-1)
    usados = (plano.size // TOTAL_BITS) * TOTAL_BITS
    if usados == 0:
        return None
    alvos = _ordem(plano.size, chave)[:usados]
    return decodificar(_votar(plano[alvos] & 1, np.tile(np.arange(TOTAL_BITS), usados // TOTAL_BITS)))


# ------------------------------------------------------------ DCT
def _luminancia(img: np.ndarray):
    if img.ndim == 2:
        return img.astype(np.float32), None
    ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    return ycrcb[..., 0].astype(np.float32), ycrcb


def _recompor(y: np.ndarray, ycrcb) -> np.ndarray:
    y8 = np.clip(np.round(y), 0, 255).astype(np.uint8)
    if ycrcb is None:
        return y8
    ycrcb = ycrcb.copy()
    ycrcb[..., 0] = y8
    return cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)


def inserir_dct(img: np.ndarray, marca: Marca, chave: bytes, p: ParametrosMarca) -> np.ndarray:
    y, ycrcb = _luminancia(img)
    folga = math.ceil(0.3 * p.forca_dct)                  # amplitude máxima que a marca soma a um pixel
    y = folga + y * ((255 - 2 * folga) / 255)             # [0,255] -> [folga, 255-folga]
    alt, larg = (y.shape[0] // 8) * 8, (y.shape[1] // 8) * 8
    blocos = [(i, j) for i in range(0, alt, 8) for j in range(0, larg, 8)]
    usados = (len(blocos) // TOTAL_BITS) * TOTAL_BITS
    if usados == 0:
        raise ValueError("Imagem pequena demais para a marca DCT.")
    bits = np.tile(codificar(marca), usados // TOTAL_BITS)
    (ua, va), (ub, vb) = p.coef_a, p.coef_b
    for k, indice in enumerate(_ordem(len(blocos), chave)[:usados]):
        i, j = blocos[indice]
        d = cv2.dct(y[i:i + 8, j:j + 8])
        a, b = d[ua, va], d[ub, vb]
        meio = (a + b) / 2
        if bits[k]:
            d[ua, va], d[ub, vb] = meio + p.forca_dct / 2, meio - p.forca_dct / 2
        else:
            d[ua, va], d[ub, vb] = meio - p.forca_dct / 2, meio + p.forca_dct / 2
        y[i:i + 8, j:j + 8] = cv2.idct(d)
    return _recompor(y, ycrcb)


def extrair_dct(img: np.ndarray, chave: bytes, p: ParametrosMarca) -> Marca | None:
    y, _ = _luminancia(img)
    alt, larg = (y.shape[0] // 8) * 8, (y.shape[1] // 8) * 8
    blocos = [(i, j) for i in range(0, alt, 8) for j in range(0, larg, 8)]
    usados = (len(blocos) // TOTAL_BITS) * TOTAL_BITS
    if usados == 0:
        return None
    (ua, va), (ub, vb) = p.coef_a, p.coef_b
    lidos = np.empty(usados, dtype=np.uint8)
    for k, indice in enumerate(_ordem(len(blocos), chave)[:usados]):
        i, j = blocos[indice]
        d = cv2.dct(y[i:i + 8, j:j + 8])
        lidos[k] = 1 if d[ua, va] > d[ub, vb] else 0
    return decodificar(_votar(lidos, np.tile(np.arange(TOTAL_BITS), usados // TOTAL_BITS)))


# ------------------------------------------------------------ fachada
def marcar(img: np.ndarray, marca: Marca, chave: bytes, p: ParametrosMarca) -> np.ndarray:
    return inserir_dct(img, marca, chave, p) if p.metodo == "dct" else inserir_lsb(img, marca, chave)


def extrair(img: np.ndarray, chave: bytes, p: ParametrosMarca) -> Marca | None:
    """Tenta o método configurado e, se falhar, o outro (a imagem pode ter vindo de outra configuração)."""
    if p.metodo == "dct":
        return extrair_dct(img, chave, p) or extrair_lsb(img, chave)
    return extrair_lsb(img, chave) or extrair_dct(img, chave, p)
