"""Anel 2: S8 Tarja e S9 Rastreio, com imagens sintéticas (documento e mapa)."""
from datetime import datetime, timezone

import cv2
import numpy as np
import pytest

from ecosec.configuracao import carregar
from ecosec.dominio.niveis import Nivel
from ecosec.seguranca.conteudo import s8_tarja, s9_rastreio
from ecosec.seguranca.conteudo.s8_tarja import ParametrosTarja, Regiao
from ecosec.seguranca.conteudo.s9_rastreio import Marca, ParametrosMarca

CFG = carregar()
PT = ParametrosTarja.de_configuracao(CFG)
PM = ParametrosMarca.de_configuracao(CFG)
CHAVE = b"chave-de-teste"
MARCA = Marca(4321, datetime(2026, 10, 6, 15, 42, tzinfo=timezone.utc))


@pytest.fixture
def documento():
    img = np.full((600, 800, 3), 255, np.uint8)
    for i in range(18):
        cv2.putText(img, f"Pendencia PD-{i:04d}  Lodo galvanico  20,2 t  Municipio Ficticio", (30, 40 + i * 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1, cv2.LINE_AA)
    return img


ENDERECO = Regiao(20, 15, 600, 60, "ENDERECO", nivel_minimo=2)
COORDENADA = Regiao(20, 300, 300, 120, "COORDENADA", nivel_minimo=2)
CUSTODIA = Regiao(400, 450, 350, 100, "CUSTODIA", nivel_minimo=3)


def nitidez(img):
    return cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()


def recorte(img, r):
    return img[r.y:r.y + r.altura, r.x:r.x + r.largura]


# ================================================================ S8 Tarja
def test_original_nunca_e_alterado(documento):
    copia = documento.copy()
    resultado = s8_tarja.aplicar(documento, [ENDERECO], Nivel.N1, PT, regioes_revisadas=True)
    assert np.array_equal(documento, copia)
    assert resultado.imagem is not documento


def test_regiao_acima_do_nivel_e_suprimida_e_o_resto_fica_igual(documento):
    r = s8_tarja.aplicar(documento, [ENDERECO], Nivel.N1, PT, True)
    assert nitidez(recorte(r.imagem, ENDERECO)) < nitidez(recorte(documento, ENDERECO)) * 0.05
    fora = np.ones(documento.shape[:2], bool)
    fora[ENDERECO.y:ENDERECO.y + ENDERECO.altura, ENDERECO.x:ENDERECO.x + ENDERECO.largura] = False
    assert np.array_equal(r.imagem[fora], documento[fora])
    assert r.suprimidas == (ENDERECO,)


def test_mesmo_item_em_tres_niveis(documento):
    regioes = [ENDERECO, CUSTODIA]
    n1 = s8_tarja.aplicar(documento, regioes, Nivel.N1, PT, True)
    n2 = s8_tarja.aplicar(documento, regioes, Nivel.N2, PT, True)
    n3 = s8_tarja.aplicar(documento, regioes, Nivel.N3, PT, True)
    assert len(n1.suprimidas) == 2 and n2.suprimidas == (CUSTODIA,) and n3.suprimidas == ()
    assert np.array_equal(n3.imagem, documento)


def test_posicao_recebe_supressao_solida_sem_estrutura(documento):
    """Borrar preserva o centroide; para rótulo de POSIÇÃO a área fica sem variância nenhuma."""
    documento[350:360, 150:160] = (0, 0, 255)                   # o "ponto" no mapa
    area = recorte(s8_tarja.aplicar(documento, [COORDENADA], Nivel.N1, PT, True).imagem, COORDENADA)
    assert area.reshape(-1, 3).std(axis=0).max() == 0


def test_borrao_preservaria_a_posicao(documento):
    """Por que a supressão sólida existe: com o gaussiano, o ponto ainda é localizável."""
    documento[350:360, 150:160] = (0, 0, 255)
    gauss = ParametrosTarja("gaussiano", PT.kernel_gaussiano, PT.passadas_gaussiano, PT.bloco_pixelizacao,
                            frozenset())
    area = recorte(s8_tarja.aplicar(documento, [COORDENADA], Nivel.N1, gauss, True).imagem, COORDENADA)
    vermelho = area[..., 2].astype(int) - area[..., 1].astype(int)
    y, x = np.unravel_index(np.argmax(vermelho), vermelho.shape)
    assert abs((COORDENADA.x + x) - 155) < 6 and abs((COORDENADA.y + y) - 355) < 6


def test_item_nao_revisado_e_todo_suprimido_abaixo_do_n3(documento):
    for nivel in (Nivel.N1, Nivel.N2):
        r = s8_tarja.aplicar(documento, [], nivel, PT, regioes_revisadas=False)
        assert r.item_inteiro and r.imagem.reshape(-1, 3).std(axis=0).max() == 0
    assert np.array_equal(s8_tarja.aplicar(documento, [], Nivel.N3, PT, False).imagem, documento)


def test_regiao_fora_da_imagem_e_recortada_ou_ignorada(documento):
    parcial = Regiao(700, 550, 300, 300, "ENDERECO", 2)
    fora = Regiao(5000, 5000, 10, 10, "ENDERECO", 2)
    r = s8_tarja.aplicar(documento, [parcial, fora], Nivel.N1, PT, True)
    assert r.suprimidas == (parcial,)


@pytest.mark.parametrize("metodo", ["gaussiano", "pixelizacao", "solido"])
def test_metodos_destroem_o_texto(documento, metodo):
    p = ParametrosTarja(metodo, PT.kernel_gaussiano, PT.passadas_gaussiano, PT.bloco_pixelizacao, frozenset())
    area = recorte(s8_tarja.aplicar(documento, [ENDERECO], Nivel.N1, p, True).imagem, ENDERECO)
    assert nitidez(area) < nitidez(recorte(documento, ENDERECO)) * 0.15


def test_parametros_invalidos():
    with pytest.raises(ValueError):
        ParametrosTarja("apagar", 61, 3, 16, frozenset())
    with pytest.raises(ValueError):
        ParametrosTarja("gaussiano", 60, 3, 16, frozenset())


# ================================================================ S9 Rastreio
def test_carga_ida_e_volta():
    assert s9_rastreio.decodificar(s9_rastreio.codificar(MARCA)) == MARCA


def test_carga_corrompida_nao_aponta_ninguem():
    bits = s9_rastreio.codificar(MARCA)
    bits[5] ^= 1                                                # um bit trocado
    assert s9_rastreio.decodificar(bits) is None                # CRC: nunca um inocente


@pytest.mark.parametrize("metodo", ["dct", "lsb"])
def test_marca_recuperada(documento, metodo):
    p = ParametrosMarca(metodo, PM.forca_dct, PM.coef_a, PM.coef_b)
    assert s9_rastreio.extrair(s9_rastreio.marcar(documento, MARCA, CHAVE, p), CHAVE, p) == MARCA


@pytest.mark.parametrize("qualidade", [90, 75, 50])
def test_dct_sobrevive_a_jpeg(documento, qualidade):
    marcada = s9_rastreio.inserir_dct(documento, MARCA, CHAVE, PM)
    _, buf = cv2.imencode(".jpg", marcada, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
    assert s9_rastreio.extrair_dct(cv2.imdecode(buf, cv2.IMREAD_COLOR), CHAVE, PM) == MARCA


def test_lsb_nao_sobrevive_a_jpeg_mas_nao_acusa_inocente(documento):
    marcada = s9_rastreio.inserir_lsb(documento, MARCA, CHAVE)
    _, buf = cv2.imencode(".jpg", marcada, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert s9_rastreio.extrair_lsb(cv2.imdecode(buf, cv2.IMREAD_COLOR), CHAVE) is None


def test_sem_a_chave_nao_se_le_a_marca(documento):
    marcada = s9_rastreio.inserir_dct(documento, MARCA, CHAVE, PM)
    assert s9_rastreio.extrair_dct(marcada, b"outra-chave", PM) is None


def test_imagem_sem_marca_nao_aponta_ninguem(documento):
    assert s9_rastreio.extrair(documento, CHAVE, PM) is None


def test_marca_pouco_visivel(documento):
    """PSNR medido: LSB ~55 dB (invisível); DCT ~28 dB, dominado pela compressão
    de luminância que dá folga à marca no fundo branco."""
    assert cv2.PSNR(documento, s9_rastreio.inserir_lsb(documento, MARCA, CHAVE)) > 50
    assert cv2.PSNR(documento, s9_rastreio.inserir_dct(documento, MARCA, CHAVE, PM)) > 27


def test_original_nao_e_alterado_pela_marca(documento):
    copia = documento.copy()
    s9_rastreio.inserir_dct(documento, MARCA, CHAVE, PM)
    s9_rastreio.inserir_lsb(documento, MARCA, CHAVE)
    assert np.array_equal(documento, copia)


def test_cinza_tambem_e_marcado():
    cinza = np.full((256, 256), 200, np.uint8)
    cv2.putText(cinza, "EcoSecurity", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 2, 30, 3)
    assert s9_rastreio.extrair_dct(s9_rastreio.inserir_dct(cinza, MARCA, CHAVE, PM), CHAVE, PM) == MARCA


def test_imagem_pequena_demais_para_dct():
    with pytest.raises(ValueError):
        s9_rastreio.inserir_dct(np.zeros((16, 16, 3), np.uint8), MARCA, CHAVE, PM)


def test_regiao_dentro_de_regiao_solida_nao_cria_contraste(documento):
    """Vazamento real encontrado no mapa: a supressão de uma região pequena dentro de uma
    grande, já suprimida, desenhava um retângulo de outro tom exatamente onde ela estava."""
    grande = Regiao(100, 100, 400, 300, "DISTRIBUICAO_GEOGRAFICA", 2)
    pequena = Regiao(450, 200, 120, 20, "CUSTODIA", 3)          # sai parcialmente da grande, pela direita
    documento[205:215, 455:475] = (200, 60, 30)                 # o marcador azul da instalação
    for ordem in ([grande, pequena], [pequena, grande]):        # vale em qualquer ordem de entrada
        area = recorte(s8_tarja.aplicar(documento, ordem, Nivel.N1, PT, True).imagem, grande)
        assert area.reshape(-1, 3).std(axis=0).max() == 0
