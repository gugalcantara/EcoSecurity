"""Fase 1, Aquisição: quadros da webcam em tempo real.

Thread dedicada + fila de tamanho 1. Por quê:

    câmera  ──30 fps──▶  [fila]  ──?? fps──▶  reconhecimento

Se o reconhecimento for mais lento que a câmera, uma fila comum acumula
quadros: depois de 10 s a tela mostraria o que aconteceu há 3 s, e a decisão
seria tomada sobre o passado. Com tamanho 1, o quadro antigo é descartado
quando chega um novo: quem consome recebe sempre o mais recente, e a latência
nunca cresce.

Sem Qt aqui (a visão não conhece a interface): é uma thread comum do Python.

Backend de captura: no Windows o padrão do OpenCV é o Media Foundation (MSMF),
que leva ~8 s para abrir a webcam e ~14 s para trocar a resolução (medido:
~22 s até o 1º quadro). O DirectShow faz o mesmo em ~1,5 s. Se o backend
pedido não abrir a câmera, tenta-se o padrão antes de desistir.
"""
import queue
import threading
import time

import cv2
import numpy as np

BACKENDS = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}


class ErroCamera(RuntimeError):
    """Câmera indisponível ou parada. Quem recebe deve negar/encerrar (falha segura)."""


class Camera:
    def __init__(self, indice: int, largura: int, altura: int, timeout_leitura: float,
                 frames_aquecimento: int = 0, abrir=None, backend: str = "auto"):
        if backend not in BACKENDS:
            raise ValueError(f"[captura] backend desconhecido: {backend!r} (use {', '.join(BACKENDS)})")
        self._indice = indice
        self._largura, self._altura = largura, altura
        self._timeout = timeout_leitura
        self._aquecimento = frames_aquecimento
        self._backend = BACKENDS[backend]
        self._abrir = abrir or self._abrir_webcam  # injetável: os testes usam uma câmera falsa
        self._fila: queue.Queue = queue.Queue(maxsize=1)
        self._rodando = threading.Event()
        self._thread: threading.Thread | None = None
        self._captura = None
        self.quadros_lidos = 0
        self.quadros_descartados = 0             # evidência funcionando

    @classmethod
    def de_configuracao(cls, cfg) -> "Camera":
        c = cfg.secao("captura")
        return cls(c["indice_camera"], c["largura"], c["altura"], c["timeout_leitura"],
                   c["frames_aquecimento"], backend=c.get("backend", "auto"))

    def _abrir_webcam(self, indice: int):
        captura = cv2.VideoCapture(indice, self._backend)
        if captura.isOpened() or self._backend == cv2.CAP_ANY:
            return captura
        captura.release()
        return cv2.VideoCapture(indice)          # backend pedido indisponível: o padrão

    def iniciar(self) -> None:
        captura = self._abrir(self._indice)
        if not captura.isOpened():
            captura.release()
            raise ErroCamera("Webcam indisponível. Feche outros programas que a usem "
                             "(Teams, navegador) e tente de novo.")
        captura.set(cv2.CAP_PROP_FRAME_WIDTH, self._largura)
        captura.set(cv2.CAP_PROP_FRAME_HEIGHT, self._altura)
        for _ in range(self._aquecimento):
            captura.read()
        self._captura = captura
        self._rodando.set()
        self._thread = threading.Thread(target=self._laco, name="captura", daemon=True)
        self._thread.start()

    def _laco(self):
        try:
            while self._rodando.is_set():
                ok, quadro = self._captura.read()
                if not ok:
                    time.sleep(0.01)
                    continue
                self.quadros_lidos += 1
                try:
                    self._fila.get_nowait()        # descarta o antigo, se houver
                    self.quadros_descartados += 1
                except queue.Empty:
                    pass
                self._fila.put_nowait(quadro)      # só esta thread põe: nunca está cheia aqui
        finally:
            self._captura.release()

    def ler(self) -> np.ndarray:
        """O quadro mais recente. Levanta ErroCamera se nada chegar no prazo."""
        if not self._rodando.is_set():
            raise ErroCamera("A câmera não foi iniciada.")
        try:
            return self._fila.get(timeout=self._timeout)
        except queue.Empty:
            raise ErroCamera(f"A câmera parou de enviar imagens por {self._timeout:.0f} s.") from None

    def parar(self) -> None:
        self._rodando.clear()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def __enter__(self):
        self.iniciar()
        return self

    def __exit__(self, *_):
        self.parar()
