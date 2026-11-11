"""Visão: cada fase com imagens sintéticas e componentes falsos (sem câmera)."""
import dataclasses
import time

from pathlib import Path

import cv2
import numpy as np
import pytest
from cryptography.fernet import Fernet

from ecosec.configuracao import carregar
from ecosec.visao.aquisicao import Camera, ErroCamera
from ecosec.visao.gestos import DetectorGesto, Gesto, MedidaOlhos, ParametrosGestos
from ecosec.visao.pipeline import PipelineVisao, ResultadoQuadro
from ecosec.visao.preprocessamento import ParametrosPreprocessamento, Preprocessador
from ecosec.visao.qualidade import ParametrosQualidade, ProblemaQualidade, avaliar, medir
from ecosec.visao.reconhecimento import (ConfirmadorQuadros, ErroModelo, ParametrosLBPH,
                                         ReconhecedorLBPH)
from ecosec.visao.segmentacao import ParametrosSegmentacao, Segmentador, fracao_visivel, recortar

CFG = carregar()
RNG = np.random.default_rng(2026)


def textura(semente, tamanho=(200, 200)):
    """Imagem com textura própria: cada semente faz uma 'pessoa' diferente."""
    base = np.random.default_rng(semente).integers(40, 215, (50, 50)).astype(np.uint8)
    return cv2.resize(base, tamanho, interpolation=cv2.INTER_LINEAR)


def variacao(img, semente):
    ruido = np.random.default_rng(semente).normal(0, 4, img.shape)
    return np.clip(img + ruido, 0, 255).astype(np.uint8)


# ================================================================ Fase 1: Aquisição
class CapturaFalsa:
    def __init__(self, aberta=True, quadros=True):
        self.aberta, self.quadros, self.n = aberta, quadros, 0

    def isOpened(self):
        return self.aberta

    def set(self, *_):
        return True

    def read(self):
        if not self.quadros:
            return False, None
        self.n += 1
        time.sleep(0.002)
        return True, np.full((48, 64, 3), self.n % 256, np.uint8)

    def release(self):
        pass


def test_camera_entrega_o_quadro_mais_recente_e_descarta_os_velhos():
    cam = Camera(0, 64, 48, 1.0, abrir=lambda _: CapturaFalsa())
    with cam:
        time.sleep(0.15)                 # a câmera produz vários quadros sem ninguém ler
        quadro = cam.ler()
        assert quadro.shape == (48, 64, 3)
    assert cam.quadros_descartados > 0  # a fila de tamanho 1 jogou fora os antigos


def test_camera_que_nao_abre_e_erro():
    with pytest.raises(ErroCamera, match="indisponível"):
        Camera(0, 64, 48, 1.0, abrir=lambda _: CapturaFalsa(aberta=False)).iniciar()


def test_camera_parada_e_erro_no_prazo():
    cam = Camera(0, 64, 48, 0.2, abrir=lambda _: CapturaFalsa(quadros=False))
    with cam:
        with pytest.raises(ErroCamera, match="parou"):
            cam.ler()


def test_ler_sem_iniciar_e_erro():
    with pytest.raises(ErroCamera):
        Camera(0, 64, 48, 0.2, abrir=lambda _: CapturaFalsa()).ler()


# ================================================================ Fase 2: Pré-processamento
def test_normalizar_produz_200x200_cinza():
    pre = Preprocessador(ParametrosPreprocessamento.de_configuracao(CFG))
    face = pre.normalizar(textura(1, (137, 151)))
    assert face.shape == (200, 200) and face.dtype == np.uint8


def test_clahe_espalha_o_histograma_de_imagem_apagada():
    pre = Preprocessador(ParametrosPreprocessamento(2.0, (8, 8), 0, (200, 200)))
    apagada = (textura(2) // 4 + 100).astype(np.uint8)     # tons espremidos em 100-153
    assert pre.normalizar(apagada).std() > apagada.std()


def test_kernel_par_e_recusado():
    with pytest.raises(ValueError):
        Preprocessador(ParametrosPreprocessamento(2.0, (8, 8), 4, (200, 200)))


# ================================================================ Fase 3: Segmentação
class DetectorFalso:
    def __init__(self, faces):
        self.faces, self.chamadas = faces, 0

    def detectar(self, _):
        self.chamadas += 1
        return list(self.faces)


class RastreadorFalso:
    def init(self, *_):
        pass

    def update(self, _):
        return True, (11, 11, 50, 50)


def _segmentador(faces, a_cada=5):
    p = ParametrosSegmentacao.de_configuracao(CFG)
    p = ParametrosSegmentacao(p.haar_face, p.scale_factor, p.min_neighbors, p.min_size, a_cada,
                              p.fracao_minima_visivel)
    detector = DetectorFalso(faces)
    return Segmentador(p, detector, RastreadorFalso), detector


def test_haar_a_cada_n_quadros_e_kcf_entre_eles():
    seg, detector = _segmentador([(10, 10, 50, 50)], a_cada=5)
    quadro = np.zeros((100, 100, 3), np.uint8)
    fontes = [seg.processar(quadro, quadro[..., 0])[1] for _ in range(10)]
    assert fontes == ["HAAR", "KCF", "KCF", "KCF", "KCF"] * 2
    assert detector.chamadas == 2


def test_nao_rastreia_quando_ha_duas_faces():
    seg, detector = _segmentador([(0, 0, 40, 40), (50, 50, 40, 40)])
    quadro = np.zeros((100, 100, 3), np.uint8)
    for _ in range(3):
        faces, fonte = seg.processar(quadro, quadro[..., 0])
        assert fonte == "HAAR" and len(faces) == 2       # sem KCF: toda vez é Haar
    assert detector.chamadas == 3


def test_recorte_na_borda():
    img = np.zeros((100, 100), np.uint8)
    assert fracao_visivel((-10, 0, 40, 40), 100, 100) == pytest.approx(0.75)
    assert recortar(img, (-10, 0, 40, 40), 0.9) is None           # face saindo do quadro
    assert recortar(img, (10, 10, 40, 40), 0.9).shape == (40, 40)
    assert fracao_visivel((0, 0, 0, 10), 100, 100) == 0.0


# ================================================================ Portão de qualidade
PQ = ParametrosQualidade.de_configuracao(CFG)


def test_imagem_boa_aprovada():
    assert avaliar(medir(textura(3)), PQ) == ()


def test_imagem_borrada_reprovada():
    borrada = cv2.GaussianBlur(textura(3), (31, 31), 0)
    assert ProblemaQualidade.DESFOCADA in avaliar(medir(borrada), PQ)


def test_imagem_escura_reprovada_com_dica_acionavel():
    escura = (textura(3) // 6).astype(np.uint8)
    problemas = avaliar(medir(escura), PQ)
    assert ProblemaQualidade.ESCURA in problemas
    assert "luz" in ProblemaQualidade.ESCURA.dica


def test_ruido_detectado():
    ruidosa = np.clip(textura(3) + np.random.default_rng(0).normal(0, 40, (200, 200)), 0, 255)
    assert ProblemaQualidade.RUIDOSA in avaliar(medir(ruidosa.astype(np.uint8)), PQ)


def test_medida_nan_reprova():
    from ecosec.visao.qualidade import MedidasQualidade
    assert avaliar(MedidasQualidade(float("nan"), 100, 50, 1), PQ)


# ================================================================ Pipeline
def test_pipeline_so_normaliza_com_uma_face_boa():
    pipe = PipelineVisao.de_configuracao(CFG)
    cena = np.full((480, 640), 120, np.uint8)
    cena[100:300, 200:400] = textura(4)                     # a "face" onde o detector a aponta
    quadro = cv2.cvtColor(cena, cv2.COLOR_GRAY2BGR)
    pipe.segmentador, _ = _segmentador([(200, 100, 200, 200)])
    r = pipe.processar(quadro)
    assert r.quantidade_faces == 1 and r.face_normalizada.shape == (200, 200)
    assert r.dica is None

    pipe.segmentador, _ = _segmentador([(0, 0, 100, 100), (300, 200, 100, 100)])
    r = pipe.processar(quadro)
    assert r.face_normalizada is None and "uma pessoa" in r.dica

    pipe.segmentador, _ = _segmentador([])
    assert pipe.processar(quadro).dica.startswith("Posicione")


# ================================================================ Fases 4 e 5: LBPH
def _reconhecedor():
    rec = ReconhecedorLBPH(ParametrosLBPH.de_configuracao(CFG))
    rec.adicionar([variacao(textura(10), s) for s in range(5)], rotulo=1)
    rec.adicionar([variacao(textura(20), s) for s in range(5)], rotulo=2)   # update()
    return rec


def test_identifica_a_pessoa_certa_com_distancia_menor():
    rec = _reconhecedor()
    rotulo, distancia = rec.identificar(variacao(textura(10), 99))
    assert rotulo == 1
    _, distancia_outra = rec.identificar(textura(30))     # ninguém cadastrado
    assert distancia < distancia_outra                     # menor = mais parecido


def test_verificacao_compara_so_com_o_alegado():
    rec = _reconhecedor()
    sonda = variacao(textura(10), 99)                      # é a pessoa 1
    assert rec.verificar(sonda, 1) < rec.verificar(sonda, 2)
    assert rec.verificar(sonda, 1) == pytest.approx(rec.identificar(sonda)[1])


def test_alegado_fora_do_modelo_e_none():
    assert _reconhecedor().verificar(textura(10), 77) is None


def test_modelo_vazio_nao_reconhece_ninguem():
    rec = ReconhecedorLBPH(ParametrosLBPH.de_configuracao(CFG))
    assert rec.identificar(textura(1)) is None and rec.verificar(textura(1), 1) is None
    assert rec.rotulos() == set()


def test_modelo_cifrado_ida_e_volta(tmp_path):
    rec, chave = _reconhecedor(), Fernet.generate_key()
    arquivo = tmp_path / "lbph.enc"
    rec.salvar_cifrado(arquivo, chave)
    assert b"opencv" not in arquivo.read_bytes().lower()   # nada legível no disco
    lido = ReconhecedorLBPH.carregar_cifrado(arquivo, chave, rec.p)
    assert lido.rotulos() == {1, 2}
    assert lido.identificar(variacao(textura(20), 5))[0] == 2


def test_modelo_com_chave_errada_e_recusado(tmp_path):
    rec = _reconhecedor()
    rec.salvar_cifrado(tmp_path / "m.enc", Fernet.generate_key())
    with pytest.raises(ErroModelo, match="decifra"):
        ReconhecedorLBPH.carregar_cifrado(tmp_path / "m.enc", Fernet.generate_key(), rec.p)


def test_confirmador_exige_quadros_seguidos():
    conf = ConfirmadorQuadros(3, limiar=50)
    assert conf.alimentar(1, 40) is None and conf.alimentar(1, 42) is None
    assert conf.alimentar(1, 44) == (1, pytest.approx(42.0))


def test_confirmador_zera_com_divergencia():
    conf = ConfirmadorQuadros(3, limiar=50)
    conf.alimentar(1, 40), conf.alimentar(1, 40)
    conf.alimentar(1, 80)                                   # fora do limiar
    assert conf.confirmados == 0
    conf.alimentar(1, 40), conf.alimentar(2, 40)            # troca de identidade
    assert conf.confirmados == 1


# ================================================================ Gestos (vivacidade)
# os testes do contorno do olho (EAR) fixam o modo "ear"; os do modo "regiao" (o padrão) ficam mais abaixo
PG = dataclasses.replace(ParametrosGestos.de_configuracao(CFG), sinal_piscada="ear")


def _quadro_com_face(x, w=100):
    return ResultadoQuadro(faces=((x, 100, w, w),), fonte="HAAR", largura=640, altura=480,
                           recorte_cinza=np.zeros((w, w), np.uint8))


class OlhosFalsos:
    """Sequência de aberturas do olho (EAR). O Haar "vê olho" sempre, como na câmera real."""

    def __init__(self, sequencia):
        self.sequencia = iter(sequencia)

    def medir(self, _):
        return MedidaOlhos(1, 100.0, ear=next(self.sequencia))


def _piscadas(sequencia, xs=None):
    gesto = DetectorGesto(Gesto.PISCAR, PG, OlhosFalsos(sequencia))
    xs = xs or [200] * len(sequencia)
    return [gesto.alimentar(_quadro_com_face(x)) for x in xs]


def test_piscada_aberto_fechado_reaberto_por_ear():
    resultados = _piscadas([0.30] * 5 + [0.15, 0.14] + [0.25])
    assert resultados == [False] * 7 + [True]


def test_foto_nunca_pisca():
    """Foto (parada ou mexida): a abertura do olho não muda, só oscila um pouco."""
    ruido = [0.30 + 0.01 * ((i % 5) - 2) for i in range(60)]
    assert not any(_piscadas(ruido))


def test_um_quadro_isolado_nao_fecha():
    assert not any(_piscadas([0.30] * 5 + [0.15] + [0.30] * 5))


def test_piscada_com_deriva_lenta_do_sinal():
    """Com a câmera real o patamar desce devagar: a reabertura vale pela RECUPERAÇÃO, não pela volta ao antigo."""
    deriva = [0.30 - 0.004 * i for i in range(12)]                  # 0,30 -> 0,256
    assert _piscadas(deriva + [0.12, 0.11, 0.20])[-1] is True       # reabriu em 0,20 (bem abaixo dos 0,30 antigos)


def test_rosto_deslizando_nao_vira_piscada():
    """Mover o rosto atrapalha o ajuste dos pontos: quadros em deslocamento não contam."""
    sequencia = [0.30] * 5 + [0.12, 0.12, 0.30]
    xs = [200] * 5 + [230, 260, 290]                                 # 0,3 largura por quadro
    assert not any(_piscadas(sequencia, xs))


def test_formula_do_ear():
    from ecosec.visao.gestos import ear
    aberto = np.array([[0, 0], [10, -4], [20, -4], [30, 0], [20, 4], [10, 4]], float)
    fechado = np.array([[0, 0], [10, -1], [20, -1], [30, 0], [20, 1], [10, 1]], float)
    assert ear(aberto) == pytest.approx(8 / 30) and ear(fechado) == pytest.approx(2 / 30)


def test_modelo_de_landmarks_trocado_ou_ausente_e_recusado(tmp_path):
    from ecosec.visao.gestos import ErroModeloLandmarks, carregar_landmarks
    falso = tmp_path / "lbfmodel.yaml"
    falso.write_text("%YAML:1.0\n", encoding="utf-8")
    with pytest.raises(ErroModeloLandmarks, match="não confere"):
        carregar_landmarks(str(falso), PG.modelo_landmarks_sha256)
    with pytest.raises(ErroModeloLandmarks, match="não encontrado"):
        carregar_landmarks(str(tmp_path / "nao_existe.yaml"), PG.modelo_landmarks_sha256)


@pytest.mark.skipif(not Path(PG.modelo_landmarks).exists(), reason="modelo LBF não baixado")
def test_modelo_real_mede_a_abertura_dos_olhos():
    from ecosec.visao.gestos import DetectorOlhos, carregar_landmarks
    detector = DetectorOlhos(PG.haar_olhos, PG.vizinhos_olhos,
                             carregar_landmarks(PG.modelo_landmarks, PG.modelo_landmarks_sha256))
    rosto = cv2.GaussianBlur(np.random.default_rng(3).integers(40, 215, (200, 180)).astype(np.uint8), (5, 5), 0)
    medida = detector.medir(rosto)
    assert medida is not None and medida.ear is not None and 0 <= medida.ear < 2


def test_sair_de_cena_nao_conta_como_olho_fechado():
    gesto = DetectorGesto(Gesto.PISCAR, PG, OlhosFalsos([2, 2, 2, 2]))
    vazio = ResultadoQuadro(faces=(), fonte="HAAR", largura=640, altura=480)
    for r in [_quadro_com_face(200)] * 3 + [vazio] * 5 + [_quadro_com_face(200)]:
        assert gesto.alimentar(r) is False


# direção obrigatória e só deslizamento (o modo anterior), para conferir o sentido na imagem bruta
PG_DIRECAO = dataclasses.replace(PG, deslocamento_minimo=0.35, direcao_livre=False, giro_minimo=0.0)


def test_mover_para_a_esquerda_da_pessoa_e_mais_x_na_imagem_bruta():
    gesto = DetectorGesto(Gesto.MOVER_ESQUERDA, PG_DIRECAO)
    assert not gesto.alimentar(_quadro_com_face(200))
    assert not gesto.alimentar(_quadro_com_face(220))       # 0,2 da largura
    assert gesto.alimentar(_quadro_com_face(240))           # 0,4 >= 0,35


def test_mover_para_o_lado_errado_nao_cumpre_com_direcao_obrigatoria():
    gesto = DetectorGesto(Gesto.MOVER_DIREITA, PG_DIRECAO)
    gesto.alimentar(_quadro_com_face(200))
    assert not gesto.alimentar(_quadro_com_face(300))       # foi para a esquerda da pessoa
    assert gesto.alimentar(_quadro_com_face(150))


class GiroFalso:
    """O giro da cabeça (nariz x meio dos olhos) que a câmera "vê" em cada quadro."""

    def __init__(self, giros):
        self.giros = iter(giros)

    def giro(self, _):
        return next(self.giros)


PG_MOVER = dataclasses.replace(PG, deslocamento_minimo=0.15, giro_minimo=0.15, direcao_livre=True)


def test_mover_com_direcao_livre_vale_qualquer_lado():
    gesto = DetectorGesto(Gesto.MOVER_DIREITA, PG_MOVER, GiroFalso([0.0] * 5))
    gesto.alimentar(_quadro_com_face(200))
    assert gesto.alimentar(_quadro_com_face(220))           # 0,2 para o lado "errado": vale


def test_virar_a_cabeca_cumpre_o_gesto_sem_deslizar():
    gesto = DetectorGesto(Gesto.MOVER_ESQUERDA, PG_MOVER, GiroFalso([0.01, 0.05, 0.10, 0.18]))
    assert [gesto.alimentar(_quadro_com_face(200)) for _ in range(4)] == [False, False, False, True]


def test_parado_nao_cumpre_o_mover():
    """Parado, o giro medido na câmera real oscilou até 0,06 e o centro, pouco: nada disso cumpre."""
    giros = [0.02 * ((i % 5) - 2) for i in range(40)]
    gesto = DetectorGesto(Gesto.MOVER_ESQUERDA, PG_MOVER, GiroFalso(giros))
    assert not any(gesto.alimentar(_quadro_com_face(200 + (i % 3))) for i in range(40))


def test_remover_uma_pessoa_preserva_as_outras():
    rec = _reconhecedor()
    rec.adicionar([variacao(textura(30), s) for s in range(5)], rotulo=3)
    sonda1, sonda3 = variacao(textura(10), 50), variacao(textura(30), 50)
    antes = rec.identificar(sonda1), rec.identificar(sonda3)
    assert rec.remover(2) is True and rec.rotulos() == {1, 3}
    assert (rec.identificar(sonda1), rec.identificar(sonda3)) == antes      # distâncias idênticas
    assert rec.verificar(variacao(textura(20), 50), 2) is None              # a pessoa 2 sumiu
    assert rec.remover(2) is False


def test_remover_a_ultima_pessoa_esvazia_o_modelo():
    rec = ReconhecedorLBPH(ParametrosLBPH.de_configuracao(CFG))
    rec.adicionar([textura(1)], rotulo=9)
    assert rec.remover(9) and not rec.treinado and rec.identificar(textura(1)) is None


def test_salvar_nao_cria_arquivo_temporario(tmp_path, monkeypatch):
    """O modelo é dado biométrico: não pode passar por arquivo em claro, nem por um instante."""
    import tempfile

    def proibido(*_a, **_k):
        raise AssertionError("arquivo temporário criado")
    monkeypatch.setattr(tempfile, "TemporaryDirectory", proibido)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", proibido)
    rec, chave = _reconhecedor(), Fernet.generate_key()
    rec.salvar_cifrado(tmp_path / "m.enc", chave)
    assert ReconhecedorLBPH.carregar_cifrado(tmp_path / "m.enc", chave, rec.p).rotulos() == {1, 2}
    assert [a.name for a in tmp_path.iterdir()] == ["m.enc"]                # nem .tmp sobrou


# ---------------------------------------------------------------- piscada pela região dos olhos (modo padrão)
PG_REGIAO = dataclasses.replace(ParametrosGestos.de_configuracao(CFG), sinal_piscada="regiao")
_ABERTO = np.random.default_rng(7).normal(0, 1, (16, 64)).astype(np.float32)     # íris e esclera: um padrão
_FECHADO = np.random.default_rng(8).normal(0, 1, (16, 64)).astype(np.float32)    # pálpebra: outro padrão


def _olho(padrao, escuro, ruido=0.05, semente=0):
    regiao = padrao + np.random.default_rng(semente).normal(0, ruido, padrao.shape).astype(np.float32)
    return MedidaOlhos(1, 100.0, ear=0.30, regiao=regiao, escuro_regiao=escuro)


class OlhosRegiao:
    def __init__(self, medidas):
        self.medidas = iter(medidas)

    def medir(self, _):
        return next(self.medidas)


def _piscadas_regiao(medidas, xs=None):
    gesto = DetectorGesto(Gesto.PISCAR, PG_REGIAO, OlhosRegiao(medidas))
    xs = xs or [200] * len(medidas)
    return [gesto.alimentar(_quadro_com_face(x)) for x in xs]


ABERTOS = [_olho(_ABERTO, 0.20, semente=i) for i in range(15)]


def test_regiao_piscada_fechou_e_reabriu():
    fechados = [_olho(_FECHADO, 0.10, semente=100 + i) for i in range(2)]
    resultados = _piscadas_regiao(ABERTOS + fechados + [_olho(_ABERTO, 0.20, semente=200)])
    assert resultados[-1] is True and not any(resultados[:-1])


def test_regiao_foto_parada_nunca_pisca():
    assert not any(_piscadas_regiao([_olho(_ABERTO, 0.20, semente=i) for i in range(80)]))


def test_regiao_so_o_escuro_mudando_nao_pisca():
    """Deslizar muda a luz e o "escuro" cai; sem a região mudar junto, não é piscada."""
    luz = [_olho(_ABERTO, 0.08, semente=300 + i) for i in range(4)]
    assert not any(_piscadas_regiao(ABERTOS + luz + ABERTOS[:3]))


def test_regiao_um_quadro_isolado_nao_fecha():
    um = [_olho(_FECHADO, 0.10, semente=400)]
    assert not any(_piscadas_regiao(ABERTOS + um + ABERTOS[:5]))


def test_regiao_rosto_deslizando_nao_vira_piscada():
    fechados = [_olho(_FECHADO, 0.10, semente=500 + i) for i in range(3)]
    xs = [200] * 15 + [230, 260, 290] + [320]
    assert not any(_piscadas_regiao(ABERTOS + fechados + [_olho(_ABERTO, 0.20)], xs))


def test_regiao_sem_olhos_localizados_e_inconclusivo():
    assert not any(_piscadas_regiao([MedidaOlhos(1, 100.0, ear=0.30)] * 30))


def test_sinal_da_piscada_errado_no_config_impede_a_abertura(tmp_path):
    import copy

    from ecosec.aplicacao import montar
    from ecosec.configuracao import Configuracao, ErroConfiguracao
    dados = copy.deepcopy(CFG._dados)
    dados["s6_vivacidade"]["sinal_piscada"] = "olhos"
    with pytest.raises(ErroConfiguracao, match="sinal_piscada"):
        montar(Configuracao(dados, CFG.origem), tmp_path / ".env", modo="memoria")
