"""Detecção dos gestos da prova de vivacidade (usada pela S6).

A S6 sorteia o desafio e decide; aqui está a visão: perceber, quadro a quadro,
se o gesto aconteceu.

PISCAR: abertura do olho por landmarks. O FacemarkLBF do OpenCV (Local Binary
  Features, parente do LBPH) ajusta 68 pontos ao rosto; seis contornam cada
  olho. A razão de aspecto do olho (EAR, Soukupová e Čech, 2016):
        EAR = (|p2 - p6| + |p3 - p5|) / (2 |p1 - p4|)
  fica perto de 0,3 com o olho aberto e despenca ao fechar. Não depende de luz
  nem de textura; numa foto (parada ou em movimento) a abertura não muda.
    abertos (N quadros, referência) ─▶ EAR caiu Q% (M quadros) ─▶ recuperou metade = piscou
  A reabertura é medida pela recuperação a partir do mínimo, não pela volta à
  referência: com a câmera real, o patamar do sinal deriva devagar (aproximar
  o rosto, mudar a luz) e o olho reaberto nem sempre volta ao valor antigo.
  Quadros com o rosto em deslocamento não contam (o ajuste dos pontos piora).

  REGIÃO DOS OLHOS (alternativa ao EAR, escolhida em `sinal_piscada` conforme a
  câmera; ver config/ecosec.toml). Com webcam de baixa
  qualidade, o FacemarkLBF quase não fecha o contorno do olho: numa gravação
  com gabarito (10 piscadas em instantes conhecidos, 20 quadros/s) o EAR caiu
  só 12% a 27% na piscada, do tamanho do ruído, e nunca chegou aos 40% pedidos.
  Os pontos continuam ótimos para localizar os olhos; a piscada passa a ser
  medida nos pixels dessa região:
    mudança  diferença média entre a região normalizada e a mediana das
             regiões do último ~1 s (a pálpebra cobre íris e esclera: a
             imagem muda muito e volta)
    escuro   fração de pixels escuros na região (íris e pupila somem ao fechar)
  Os dois têm de subir juntos (o menor dos dois, cada um na sua escala): o
  "escuro" sozinho dispara ao deslizar (a luz muda), a "mudança" sozinha tem
  pouca folga. No gabarito: piscadas 1,05 a 1,46; parado até 0,19; deslizando
  até 0,70; limiar 0,85. Uma foto (parada ou deslizada) não muda a região dos
  olhos, porque os pontos acompanham o olho.

  Histórico (07/10/2026, dados da câmera real): o Haar de olhos achava "olho"
  em 100% dos quadros, inclusive fechados; a textura da faixa dos olhos pegou só
  3 de ~5 piscadas e "piscava" ao deslizar o rosto (borrão de movimento). Os dois
  sinais seguem medidos, para a ferramenta de calibração comparar.

MOVER: vale DESLIZAR o rosto (o centro da face anda uma fração da LARGURA da
  face; em pixels, perto da câmera o mesmo gesto andaria mais) ou virar a cabeça
  (o nariz se afasta do meio dos olhos, medido pelos landmarks, em distâncias
  entre os olhos). Basta um dos dois.
  Desde 02/11/2026 (medido com a câmera real: virando a cabeça, o detector
  frontal perdia o rosto em 20% a 45% dos quadros e o centro andava pouco; só
  4 de 8 gestos chegavam aos 25% exigidos): a direção pedida orienta a pessoa,
  mas com `direcao_livre` qualquer lado vale. O mover não é a defesa contra a
  foto (deslizar uma foto impressa também cumpre): quem barra a foto é a
  piscada, obrigatória. O mover prova que há alguém se mexendo AGORA.
  O vídeo bruto da webcam não é espelhado: a esquerda da pessoa aparece na
  DIREITA da imagem. Por isso "esquerda" é +x aqui (e o nariz de quem vira
  para a própria esquerda também vai para +x).

Quadro inconclusivo não conta para nada. Um caso real que motiva isso: quando o
rosto sai do quadro, o recorte dos olhos fica vazio e o Haar responde "nenhum
olho" sem erro; contar isso como olho fechado deixaria alguém "piscar"
simplesmente saindo de cena.
"""
import hashlib
import statistics
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

from ecosec.visao.pipeline import ResultadoQuadro
from ecosec.visao.segmentacao import carregar_cascata


class Gesto(str, Enum):
    PISCAR = "PISCAR"
    MOVER_ESQUERDA = "MOVER_ESQUERDA"
    MOVER_DIREITA = "MOVER_DIREITA"


@dataclass(frozen=True)
class ParametrosGestos:
    haar_olhos: str
    vizinhos_olhos: int              # minNeighbors do Haar de olhos (menor = mais sensível)
    frames_olho_aberto: int          # quadros abertos para formar a referência do EAR
    frames_olho_fechado: int
    queda_ear_minima: float          # fechado: EAR <= referência × (1 - queda)
    recuperacao_ear: float           # reaberto: recuperou esta fração da queda, a partir do mínimo
    movimento_maximo: float          # deslocamento do rosto (em larguras) entre quadros, acima: inconclusivo
    deslocamento_minimo: float
    modelo_landmarks: str            # caminho do lbfmodel.yaml (relativo à raiz do projeto)
    modelo_landmarks_sha256: str
    sinal_piscada: str = "regiao"    # "regiao" (pixels da região dos olhos) ou "ear" (contorno do olho)
    limiar_regiao: float = 0.85      # pontuação combinada que conta como olho fechado
    escala_mudanca: float = 0.40     # quanto a "mudança" vale 1,0 na pontuação
    escala_escuro: float = 0.30      # quanto a queda do "escuro" vale 1,0 na pontuação
    giro_minimo: float = 0.15        # MOVER: nariz x meio dos olhos, em distâncias entre os olhos (0 = desliga)
    direcao_livre: bool = True       # MOVER: qualquer lado vale (a instrução só orienta)

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosGestos":
        from ecosec.configuracao import RAIZ_PROJETO
        v = cfg.secao("s6_vivacidade")
        sinal = str(v.get("sinal_piscada", "regiao"))
        if sinal not in ("regiao", "ear"):
            raise ValueError(f"[s6_vivacidade] sinal_piscada = {sinal!r}: use \"regiao\" ou \"ear\".")
        return cls(v["haar_olhos"], int(v["vizinhos_olhos"]), int(v["frames_olho_aberto"]),
                   int(v["frames_olho_fechado"]), float(v["queda_ear_minima"]), float(v["recuperacao_ear"]),
                   float(v["movimento_maximo_piscada"]), float(v["deslocamento_minimo"]),
                   str(RAIZ_PROJETO / v["modelo_landmarks"]), str(v["modelo_landmarks_sha256"]).lower(),
                   sinal, float(v.get("limiar_regiao", 0.85)), float(v.get("escala_mudanca", 0.40)),
                   float(v.get("escala_escuro", 0.30)), float(v.get("giro_minimo", 0.15)),
                   bool(v.get("direcao_livre", True)))


class ErroModeloLandmarks(RuntimeError):
    """Modelo de landmarks ausente ou diferente do conferido: a vivacidade não roda (e não aprova)."""


_MODELOS: dict = {}
_TRAVA_MODELOS = threading.Lock()


def carregar_landmarks(caminho: str, sha256: str):
    """Carrega uma vez (0,7 s, 54 MB) e reaproveita. Confere o SHA-256 antes: um
    arquivo trocado poderia devolver pontos que fazem qualquer coisa "piscar"."""
    with _TRAVA_MODELOS:
        if caminho in _MODELOS:
            return _MODELOS[caminho]
        arquivo = Path(caminho)
        if not arquivo.exists():
            raise ErroModeloLandmarks(f"Modelo de landmarks não encontrado: {arquivo}. Baixe com "
                                      "python -m ferramentas.baixar_modelo_landmarks")
        resumo = hashlib.sha256()
        with arquivo.open("rb") as f:
            for bloco in iter(lambda: f.read(1 << 20), b""):
                resumo.update(bloco)
        if resumo.hexdigest() != sha256:
            raise ErroModeloLandmarks(f"O modelo de landmarks não confere (SHA-256 diferente do configurado): "
                                      f"{arquivo}. Baixe de novo.")
        modelo = cv2.face.createFacemarkLBF()
        modelo.loadModel(str(arquivo))
        _MODELOS[caminho] = modelo
        return modelo


def ear(pontos: np.ndarray) -> float:
    """Razão de aspecto de UM olho, pelos seis pontos do contorno (p1..p6)."""
    p1, p2, p3, p4, p5, p6 = pontos
    largura = np.linalg.norm(p1 - p4)
    return float((np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)) / (2 * largura)) if largura else 0.0


@dataclass(frozen=True)
class MedidaOlhos:
    olhos: int                       # olhos detectados na faixa
    energia: float                   # variância do Laplaciano da faixa dos olhos (equalizada)
    # sinais CANDIDATOS, medidos para a calibração escolher o que separa a piscada
    # (o Haar de olhos acha "olho" até com o olho fechado: a posição dele é confiável,
    # a presença não). None quando não há caixa de olho no quadro.
    energia_crua: float | None = None    # a mesma textura, sem equalizar o contraste
    escuro: float | None = None          # fração de pixels escuros nas caixas dos olhos (cai ao fechar)
    brilho: float | None = None          # brilho nas caixas dos olhos / brilho da faixa (sobe ao fechar)
    ear: float | None = None             # abertura média dos olhos por landmarks
    # região dos dois olhos localizada pelos landmarks (o sinal padrão da piscada): os recortes
    # normalizados (média 0, desvio 1, só em memória) e a fração de pixels escuros neles
    regiao: np.ndarray | None = field(default=None, repr=False, compare=False)
    escuro_regiao: float | None = None


# faixa dos olhos dentro do recorte da face (frações da altura): acima ficam
# testa e sobrancelhas, abaixo o nariz; ambos só atrapalham os dois sinais
FAIXA_OLHOS = (0.18, 0.55)
LARGURA_FAIXA = 240                  # a faixa é ampliada: olhos de webcam são pequenos para o Haar


class DetectorOlhos:
    def __init__(self, arquivo: str, vizinhos: int = 3, landmarks=None):
        self._cascata = carregar_cascata(arquivo)
        self.vizinhos = vizinhos
        self._landmarks = landmarks          # FacemarkLBF já carregado (None: sem EAR)

    def _pontos(self, recorte: np.ndarray) -> np.ndarray | None:
        """Os 68 pontos do rosto, em coordenadas do recorte (None: o ajuste falhou)."""
        if self._landmarks is None:
            return None
        # margem: o modelo foi treinado com caixas de detector de face, e pontos perto
        # da borda do recorte (sobrancelhas) precisam de pixels em volta
        h, w = recorte.shape[:2]
        mv, mh = int(h * 0.15), int(w * 0.15)
        com_margem = cv2.copyMakeBorder(recorte, mv, mv, mh, mh, cv2.BORDER_REPLICATE)
        ok, pontos = self._landmarks.fit(com_margem, np.array([[mh, mv, w, h]], dtype=np.int32))
        if not ok or not len(pontos):
            return None
        return pontos[0][0] - np.array([mh, mv], dtype=np.float32)

    @staticmethod
    def _recorte_olho(rosto: np.ndarray, contorno: np.ndarray) -> np.ndarray | None:
        """Retângulo centrado no olho: largura 1,6 x a do olho, altura metade disso, reduzido a 32x16.
        Medido pela LARGURA do olho (que quase não muda ao piscar), não pela altura do contorno."""
        cx, cy = contorno[:, 0].mean(), contorno[:, 1].mean()
        largura = float(np.linalg.norm(contorno[0] - contorno[3])) * 1.6
        altura = largura * 0.5
        x0, x1 = int(cx - largura / 2), int(cx + largura / 2)
        y0, y1 = int(cy - altura / 2), int(cy + altura / 2)
        if x0 < 0 or y0 < 0 or x1 > rosto.shape[1] or y1 > rosto.shape[0] or x1 - x0 < 6 or y1 - y0 < 3:
            return None
        return cv2.resize(rosto[y0:y1, x0:x1], (32, 16), interpolation=cv2.INTER_AREA).astype(np.float32)

    def giro(self, recorte: np.ndarray) -> float | None:
        """Quanto a cabeça está virada: ponta do nariz (ponto 30) menos o meio dos olhos, em x, dividido pela
        distância entre os olhos. ~0 de frente; positivo quando o nariz vai para +x (esquerda da pessoa)."""
        p = self._pontos(recorte)
        if p is None:
            return None
        esquerdo, direito = p[36:42].mean(axis=0), p[42:48].mean(axis=0)
        entre = float(np.linalg.norm(esquerdo - direito))
        return float((p[30][0] - (esquerdo[0] + direito[0]) / 2) / entre) if entre else None

    def _olhos_por_pontos(self, recorte: np.ndarray) -> tuple[float | None, np.ndarray | None, float | None]:
        """(EAR, região normalizada, fração escura). Nada é guardado: tudo vive só neste quadro."""
        p = self._pontos(recorte)
        if p is None:
            return None, None, None
        abertura = (ear(p[36:42]) + ear(p[42:48])) / 2
        rosto = recorte.astype(np.float32)
        olhos = [self._recorte_olho(rosto, p[36:42]), self._recorte_olho(rosto, p[42:48])]
        if any(o is None for o in olhos):
            return abertura, None, None
        junto = np.hstack(olhos)
        mediana = float(np.median(rosto)) or 1.0
        regiao = (junto - junto.mean()) / (float(junto.std()) or 1.0)
        return abertura, regiao, float(np.mean(junto < 0.6 * mediana))

    def medir(self, recorte_face_cinza: np.ndarray) -> MedidaOlhos | None:
        altura = recorte_face_cinza.shape[0]
        faixa = recorte_face_cinza[int(altura * FAIXA_OLHOS[0]): int(altura * FAIXA_OLHOS[1])]
        if faixa.size == 0 or faixa.shape[1] < 8:
            return None                                   # inconclusivo, nunca "zero olhos"
        escala = LARGURA_FAIXA / faixa.shape[1]
        crua = cv2.resize(faixa, (LARGURA_FAIXA, max(8, int(faixa.shape[0] * escala))),
                          interpolation=cv2.INTER_LINEAR)
        faixa = cv2.equalizeHist(crua)
        lado = LARGURA_FAIXA // 8
        olhos = self._cascata.detectMultiScale(faixa, 1.1, self.vizinhos, minSize=(lado, lado))
        energia = float(cv2.Laplacian(faixa, cv2.CV_64F).var())
        energia_crua = float(cv2.Laplacian(crua, cv2.CV_64F).var())
        escuro = brilho = None
        if len(olhos):
            # os dois maiores achados (os olhos); o miolo da caixa, sem a sobrancelha que às vezes entra
            caixas = sorted(olhos, key=lambda c: c[2] * c[3], reverse=True)[:2]
            pixels = np.concatenate([crua[y + h // 4: y + h, x: x + w].ravel() for x, y, w, h in caixas])
            referencia = float(np.median(crua)) or 1.0
            escuro = float(np.mean(pixels < 0.6 * referencia))
            brilho = float(np.mean(pixels)) / referencia
        abertura, regiao, escuro_regiao = self._olhos_por_pontos(recorte_face_cinza)
        return MedidaOlhos(len(olhos), energia, energia_crua, escuro, brilho, abertura, regiao, escuro_regiao)


class DetectorGesto:
    """Acompanha UM gesto. `alimentar` devolve True quando ele se completa."""

    def __init__(self, gesto: Gesto, p: ParametrosGestos, detector_olhos=None):
        self.gesto = Gesto(gesto)
        self.p = p
        self._olhos = detector_olhos
        precisa_pontos = self.gesto is Gesto.PISCAR or p.giro_minimo > 0
        if precisa_pontos and self._olhos is None:
            self._olhos = DetectorOlhos(p.haar_olhos, p.vizinhos_olhos,
                                        carregar_landmarks(p.modelo_landmarks, p.modelo_landmarks_sha256))
        self._giro_inicial = None       # MOVER: giro da cabeça no começo do gesto
        self.ultimo_giro = 0.0
        self._fase = "ABERTOS"          # PISCAR: ABERTOS -> PRONTO -> FECHADOS -> (reabriu)
        self._seguidos = 0
        self._abertos: deque = deque(maxlen=15)          # EAR dos quadros abertos (referência)
        self._referencia_fixa = self._minimo = None
        # modo "regiao": histórico de olhos ABERTOS (~1 s a 20 quadros/s); o olho fechado nunca entra nele
        self._regioes: deque = deque(maxlen=20)
        self._mudancas: deque = deque(maxlen=20)
        self._escuros: deque = deque(maxlen=20)
        self.ultima_pontuacao = 0.0     # para a calibração e os testes
        self._centro_anterior = None
        self._x_inicial = None          # MOVER
        self.progresso = 0.0            # 0..1 para a tela
        self.ultima_medida: MedidaOlhos | None = None    # para a ferramenta de calibração
        self.ultimo_deslocamento = 0.0

    @property
    def referencia(self) -> float | None:
        return statistics.median(self._abertos) if self._abertos else None

    def alimentar(self, r: ResultadoQuadro) -> bool:
        face = r.face_unica
        if face is None or r.recorte_cinza is None:
            return False                                  # inconclusivo
        if self.gesto is Gesto.PISCAR:
            return self._piscar(self._olhos.medir(r.recorte_cinza), face)
        return self._mover(face, r.recorte_cinza)

    def _moveu(self, face) -> bool:
        x, _, w, _ = face
        centro = (x + w / 2) / w
        anterior, self._centro_anterior = self._centro_anterior, centro
        return anterior is not None and abs(centro - anterior) > self.p.movimento_maximo

    def _piscar(self, m: MedidaOlhos | None, face) -> bool:
        self.ultima_medida = m
        if self.p.sinal_piscada == "regiao":
            return self._piscar_regiao(m, face)
        if m is None or m.ear is None:
            return False                                  # sem pontos: inconclusivo
        if self._moveu(face):                             # rosto em deslocamento: não conta
            self._seguidos = 0
            if self._fase == "FECHADOS":
                self._fase = "PRONTO"
            return False
        valor = m.ear
        if self._fase == "ABERTOS":
            self._abertos.append(valor)
            if len(self._abertos) >= self.p.frames_olho_aberto:
                self._fase, self.progresso = "PRONTO", 0.33
        elif self._fase == "PRONTO":
            referencia = self.referencia
            limite = referencia * (1 - self.p.queda_ear_minima)
            if valor <= limite:
                self._seguidos += 1
                if self._seguidos >= self.p.frames_olho_fechado:
                    self._fase, self.progresso = "FECHADOS", 0.66
                    self._referencia_fixa, self._minimo = referencia, valor
            else:
                self._seguidos = 0
                if valor > referencia * (1 - self.p.queda_ear_minima / 2):
                    self._abertos.append(valor)           # a referência acompanha a deriva lenta
        elif self._fase == "FECHADOS":
            self._minimo = min(self._minimo, valor)
            queda = self._referencia_fixa - self._minimo
            if valor - self._minimo >= self.p.recuperacao_ear * queda:
                self.progresso = 1.0
                return True
        return False

    def _pontuacao(self, m: MedidaOlhos) -> tuple[float, float]:
        """(pontuação de olho fechado, mudança medida). A pontuação é o menor dos dois sinais, cada um na
        sua escala: os dois precisam subir juntos (o escuro sozinho dispara ao deslizar)."""
        referencia = np.median(np.stack(list(self._regioes)[:-3]), axis=0)
        mudanca = float(np.mean(np.abs(m.regiao - referencia)))
        base_m = statistics.median(self._mudancas) if self._mudancas else mudanca
        base_e = statistics.median(self._escuros) or 1e-6
        sobe_m = (mudanca - base_m) / self.p.escala_mudanca
        cai_e = (base_e - m.escuro_regiao) / base_e / self.p.escala_escuro
        return min(sobe_m, cai_e), mudanca

    def _piscar_regiao(self, m: MedidaOlhos | None, face) -> bool:
        if m is None or m.regiao is None or m.escuro_regiao is None:
            return False                                  # olhos não localizados: inconclusivo
        if self._moveu(face):                             # rosto em deslocamento: não conta
            self._seguidos = 0
            if self._fase == "FECHADOS":
                self._fase = "PRONTO"
            return False
        if self._fase == "ABERTOS":                       # forma o histórico do olho aberto
            if len(self._regioes) >= 6:                   # a referência deixa de fora os 3 mais recentes
                self._mudancas.append(self._pontuacao(m)[1])
            self._regioes.append(m.regiao)
            self._escuros.append(m.escuro_regiao)
            if len(self._regioes) >= max(10, 2 * self.p.frames_olho_aberto):
                self._fase, self.progresso = "PRONTO", 0.33
            return False
        pontuacao, mudanca = self._pontuacao(m)
        self.ultima_pontuacao = pontuacao
        if self._fase == "PRONTO":
            if pontuacao >= self.p.limiar_regiao:
                self._seguidos += 1
                if self._seguidos >= self.p.frames_olho_fechado:
                    self._fase, self.progresso = "FECHADOS", 0.66
            else:
                self._seguidos = 0
                if pontuacao < self.p.limiar_regiao / 2:  # só olho aberto entra no histórico
                    self._regioes.append(m.regiao)
                    self._mudancas.append(mudanca)
                    self._escuros.append(m.escuro_regiao)
        elif self._fase == "FECHADOS" and pontuacao < self.p.limiar_regiao / 2:
            self.progresso = 1.0                          # fechou e reabriu: piscou
            return True
        return False

    def _mover(self, face, recorte=None) -> bool:
        """Deslizou OU virou o suficiente (o que vier primeiro)."""
        x, _, w, _ = face
        centro = x + w / 2
        giro = None
        if self.p.giro_minimo > 0 and self._olhos is not None and recorte is not None and hasattr(self._olhos, "giro"):
            giro = self._olhos.giro(recorte)
        if self._x_inicial is None:
            self._x_inicial = centro
            self._giro_inicial = giro
            return False
        if self._giro_inicial is None:
            self._giro_inicial = giro
        sentido = -1 if self.gesto is Gesto.MOVER_DIREITA else 1
        deslocamento = sentido * (centro - self._x_inicial) / w
        virada = (sentido * (giro - self._giro_inicial)
                  if giro is not None and self._giro_inicial is not None else 0.0)
        if self.p.direcao_livre:                          # a instrução orienta; qualquer lado vale
            deslocamento, virada = abs(deslocamento), abs(virada)
        self.ultimo_deslocamento, self.ultimo_giro = deslocamento, virada
        parte_giro = virada / self.p.giro_minimo if self.p.giro_minimo > 0 else 0.0
        self.progresso = max(0.0, min(1.0, max(deslocamento / self.p.deslocamento_minimo, parte_giro)))
        return deslocamento >= self.p.deslocamento_minimo or (self.p.giro_minimo > 0
                                                             and virada >= self.p.giro_minimo)
