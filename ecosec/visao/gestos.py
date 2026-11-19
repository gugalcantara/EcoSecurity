"""Fase 5: Classificação e interpretação dos gestos da prova de vivacidade. Aqui só se percebe, quadro a
quadro, se o gesto aconteceu; o sorteio e a decisão ficam na camada S6.

Piscar: o FacemarkLBF ajusta 68 pontos ao rosto, e a razão de aspecto do olho (EAR, Soukupová e Čech,
2016) mede a abertura pelo contorno. A referência é a abertura do olho aberto no início do desafio; a piscada
é o olho fechar uma fração dela (queda_ear_minima) e reabrir. Tudo é medido em tempo, não em quadros: a
mesma piscada ocupa 1 quadro a 10 quadros/s e 3 a 30. O EAR é geometria, não tom de pixel, por isso não
depende da cor da pele. Com o rosto em movimento nada conta, e a referência é refeita.

Mover: vale deslizar o rosto (o centro anda uma fração da largura da face) ou virar a cabeça (o nariz se
afasta do meio dos olhos). Com direcao_livre, qualquer lado vale. Uma foto deslizada também cumpre esse
gesto; quem barra a foto é a piscada, que é obrigatória.

Quadros inconclusivos (rosto fora do quadro, olhos não localizados) não contam para nenhum gesto. A imagem da
câmera não é espelhada: a esquerda da pessoa aparece à direita.
"""
import hashlib
import statistics
import threading
from collections import deque
from dataclasses import dataclass
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
    referencia_ms: float             # tempo de olho aberto e rosto parado para formar a referência
    queda_ear_minima: float          # fechado: EAR <= referência × (1 - queda); reaberto acima da metade disso
    fechado_minimo_ms: float         # olho fechado por menos que isto não é piscada (ruído de um quadro)
    fechado_maximo_ms: float         # fechado por mais que isto não é piscada (mão na frente, olhar para baixo)
    janela_movimento_ms: float       # janela em que se mede o deslocamento do rosto
    movimento_maximo: float          # deslocamento do centro na janela, em larguras típicas do rosto
    deslocamento_minimo: float
    modelo_landmarks: str            # caminho do lbfmodel.yaml (relativo à raiz do projeto)
    modelo_landmarks_sha256: str
    giro_minimo: float = 0.15        # MOVER: nariz x meio dos olhos, em distâncias entre os olhos (0 = desliga)
    direcao_livre: bool = True       # MOVER: qualquer lado vale (a instrução só orienta)

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosGestos":
        from ecosec.configuracao import RAIZ_PROJETO
        v = cfg.secao("s6_vivacidade")
        queda = float(v["queda_ear_minima"])
        if not 0 < queda < 1:
            raise ValueError(f"[s6_vivacidade] queda_ear_minima = {queda}: use uma fração entre 0 e 1.")
        tempos = {k: float(v[k]) for k in ("referencia_ms", "fechado_minimo_ms", "fechado_maximo_ms",
                                            "janela_movimento_ms")}
        if min(tempos.values()) < 0 or tempos["fechado_maximo_ms"] <= tempos["fechado_minimo_ms"]:
            raise ValueError("[s6_vivacidade] tempos da piscada inválidos: nenhum negativo, e fechado_maximo_ms "
                             "acima de fechado_minimo_ms.")
        return cls(v["haar_olhos"], int(v["vizinhos_olhos"]), tempos["referencia_ms"], queda,
                   tempos["fechado_minimo_ms"], tempos["fechado_maximo_ms"], tempos["janela_movimento_ms"],
                   float(v["movimento_maximo_piscada"]), float(v["deslocamento_minimo"]),
                   str(RAIZ_PROJETO / v["modelo_landmarks"]), str(v["modelo_landmarks_sha256"]).lower(),
                   float(v["giro_minimo"]), bool(v["direcao_livre"]))


class ErroModeloLandmarks(RuntimeError):
    """Modelo de landmarks ausente ou diferente do conferido: a vivacidade não roda (e não aprova)."""


_MODELOS: dict = {}
_TRAVA_MODELOS = threading.Lock()


def carregar_landmarks(caminho: str, sha256: str):
    """Carrega o FacemarkLBF de 68 pontos (lbfmodel.yaml, treinado na base HELEN e publicado no projeto
    GSOC2017 da OpenCV). O ajuste dos pontos usa florestas aleatórias e regressão linear, sem rede neural.
    Carrega uma vez (0,7 s, 54 MB) e reaproveita. Confere o SHA-256 antes de carregar: um arquivo trocado
    poderia fazer qualquer coisa "piscar"."""
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
    ear: float | None = None             # abertura média dos olhos por landmarks (o sinal da piscada)


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

    def giro(self, recorte: np.ndarray) -> float | None:
        """Quanto a cabeça está virada: ponta do nariz (ponto 30) menos o meio dos olhos, em x, dividido pela
        distância entre os olhos. ~0 de frente; positivo quando o nariz vai para +x (esquerda da pessoa)."""
        p = self._pontos(recorte)
        if p is None:
            return None
        esquerdo, direito = p[36:42].mean(axis=0), p[42:48].mean(axis=0)
        entre = float(np.linalg.norm(esquerdo - direito))
        return float((p[30][0] - (esquerdo[0] + direito[0]) / 2) / entre) if entre else None

    def _abertura(self, recorte: np.ndarray) -> float | None:
        """EAR médio dos dois olhos. Nada é guardado: tudo vive só neste quadro."""
        p = self._pontos(recorte)
        if p is None:
            return None
        return (ear(p[36:42]) + ear(p[42:48])) / 2

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
        return MedidaOlhos(len(olhos), energia, energia_crua, escuro, brilho, self._abertura(recorte_face_cinza))


# sem relógio no quadro (os testes montam quadros à mão): os quadros contam como a 30 quadros/s
INTERVALO_SEM_RELOGIO = 1 / 30
# a referência acompanha só o último segundo e meio de olho aberto (deriva lenta da luz e da pose)
MEMORIA_REFERENCIA_S = 1.5


class DetectorGesto:
    """Acompanha UM gesto. alimentar devolve True quando ele se completa."""

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
        self._quadros = 0               # para o relógio dos quadros sem instante
        self._posicoes: deque = deque()                 # (instante, centro x em pixels, largura) recentes
        self._reiniciar_referencia()
        self._x_inicial = None          # MOVER
        self.progresso = 0.0            # 0..1 para a tela
        self.ultima_medida: MedidaOlhos | None = None    # para a ferramenta de calibração
        self.ultimo_movimento = 0.0     # deslocamento na janela, em larguras típicas (para a calibração)
        self.ultimo_deslocamento = 0.0

    def _reiniciar_referencia(self):
        """PISCAR: ABERTOS (forma a referência) -> PRONTO -> FECHADOS -> (reabriu)."""
        self._fase = "ABERTOS"
        self._abertos: deque = deque()                  # (instante, EAR) de olho aberto
        self._inicio_fechado = None

    @property
    def referencia(self) -> float | None:
        return statistics.median(e for _, e in self._abertos) if self._abertos else None

    def _instante(self, r: ResultadoQuadro) -> float:
        self._quadros += 1
        return r.instante if r.instante is not None else self._quadros * INTERVALO_SEM_RELOGIO

    def alimentar(self, r: ResultadoQuadro) -> bool:
        face = r.face_unica
        if face is None or r.recorte_cinza is None:
            return False                                  # inconclusivo
        if self.gesto is Gesto.PISCAR:
            return self._piscar(self._olhos.medir(r.recorte_cinza), face, self._instante(r))
        return self._mover(face, r.recorte_cinza)

    def _moveu(self, face, t: float) -> bool:
        """O centro do rosto andou mais que movimento_maximo na janela, em larguras TÍPICAS do rosto (a mediana
        das larguras da janela). Dividir pela largura de cada quadro faria a caixa que cresce ou encolhe, com o
        rosto parado, parecer movimento."""
        x, _, w, _ = face
        janela = self.p.janela_movimento_ms / 1000
        self._posicoes.append((t, x + w / 2, w))
        while self._posicoes and t - self._posicoes[0][0] > janela:
            self._posicoes.popleft()
        centros = [c for _, c, _ in self._posicoes]
        largura = statistics.median(l for _, _, l in self._posicoes) or 1
        self.ultimo_movimento = (max(centros) - min(centros)) / largura
        return self.ultimo_movimento > self.p.movimento_maximo

    def _piscar(self, m: MedidaOlhos | None, face, t: float) -> bool:
        self.ultima_medida = m
        if self._moveu(face, t):                          # rosto em movimento: nada conta, a referência é refeita
            self._reiniciar_referencia()
            self.progresso = 0.0
            return False
        if m is None or m.ear is None:
            return False                                  # sem pontos: inconclusivo
        while self._abertos and t - self._abertos[0][0] > MEMORIA_REFERENCIA_S:
            self._abertos.popleft()
        if self._fase == "ABERTOS":
            self._abertos.append((t, m.ear))
            if len(self._abertos) >= 3 and t - self._abertos[0][0] >= self.p.referencia_ms / 1000:
                self._fase, self.progresso = "PRONTO", 0.33
            return False
        referencia = self.referencia
        fechado = referencia * (1 - self.p.queda_ear_minima)
        reaberto = referencia * (1 - self.p.queda_ear_minima / 2)
        if self._fase == "PRONTO":
            if m.ear <= fechado:
                self._fase, self.progresso, self._inicio_fechado = "FECHADOS", 0.66, t
            elif m.ear >= reaberto:
                self._abertos.append((t, m.ear))          # a referência acompanha a deriva lenta
            return False
        duracao_ms = (t - self._inicio_fechado) * 1000
        if m.ear < reaberto:
            if duracao_ms > self.p.fechado_maximo_ms:      # fechado tempo demais: não é piscada
                self._reiniciar_referencia()
                self.progresso = 0.0
            return False
        self._fase = "PRONTO"                             # reabriu
        self._abertos.append((t, m.ear))
        if duracao_ms < self.p.fechado_minimo_ms:          # um quadro de ruído, não uma piscada
            self.progresso = 0.33
            return False
        self.progresso = 1.0
        return True

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
