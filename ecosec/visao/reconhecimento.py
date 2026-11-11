"""Fases 4 e 5: Extração (LBPH) e Classificação (distância + confirmação).

Extração, Local Binary Patterns Histograms:
  1. Para cada pixel, compara os 8 vizinhos com o centro: vizinho >= centro
     vira 1, menor vira 0. Os 8 bits formam um código (0-255) que descreve a
     textura local: borda, canto, mancha, região lisa.
  2. A face é dividida numa grade 8×8; cada célula vira um histograma dos
     códigos. Os 64 histogramas concatenados são a "assinatura" da face.
  Por comparar vizinhos entre si, o LBP é pouco sensível a mudanças uniformes
  de iluminação: clarear a imagem toda não muda quem é maior que quem.

Classificação: distância qui-quadrado entre assinaturas. Menor = mais
parecido. O limiar é decidido pela camada de segurança (S4), não aqui.

Dois modos:
- identificar (1:N): o vizinho mais próximo de toda a galeria.
- verificar (1:1): a menor distância às amostras da identidade alegada. Um
  predict() comum devolveria o vizinho de toda a galeria; se ele fosse outra
  pessoa, o dono legítimo seria negado sem motivo.

Atualização incremental: `update()` acrescenta uma pessoa nova sem
retreinar as outras.

Persistência sem arquivo temporário: o modelo é serializado em memória
(cv2.FileStorage em modo memory), comprimido e cifrado antes de tocar o disco.
A versão anterior gravava o YAML em texto puro numa pasta temporária por um
instante: dado biométrico em claro no disco, que sobraria se o programa
travasse naquele momento.

Remoção de uma pessoa (LGPD art. 18, VI): o LBPH não tem "remover". O modelo é
reescrito sem os histogramas daquele rótulo; as demais pessoas continuam com
exatamente as mesmas distâncias.
"""
import os
import threading
import zlib
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from cryptography.fernet import Fernet, InvalidToken


@dataclass(frozen=True)
class ParametrosLBPH:
    radius: int
    neighbors: int
    grid: tuple[int, int]

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosLBPH":
        p = cfg.secao("lbph")
        return cls(int(p["radius"]), int(p["neighbors"]), tuple(p["grid"]))


class ErroModelo(RuntimeError):
    pass


class ReconhecedorLBPH:
    def __init__(self, parametros: ParametrosLBPH):
        self.p = parametros
        self._modelo = self._novo()
        self._treinado = False
        self._lock = threading.Lock()     # o vídeo consulta numa thread; o cadastro grava em outra

    def _novo(self):
        gx, gy = self.p.grid
        return cv2.face.LBPHFaceRecognizer_create(radius=self.p.radius, neighbors=self.p.neighbors,
                                                  grid_x=gx, grid_y=gy)

    @property
    def treinado(self) -> bool:
        return self._treinado

    def rotulos(self) -> set[int]:
        with self._lock:
            if not self._treinado:
                return set()
            return set(int(r) for r in self._modelo.getLabels().ravel())

    def adicionar(self, faces: list[np.ndarray], rotulo: int) -> None:
        if not faces:
            raise ValueError("Nenhuma face para adicionar ao modelo.")
        rotulos = np.full(len(faces), rotulo, dtype=np.int32)
        with self._lock:
            if self._treinado:
                self._modelo.update(faces, rotulos)          # Sem retreinar os outros
            else:
                self._modelo.train(faces, rotulos)
                self._treinado = True

    def identificar(self, face: np.ndarray) -> tuple[int, float] | None:
        """1:N, (rótulo mais próximo, distância), ou None sem modelo."""
        with self._lock:
            if not self._treinado:
                return None
            rotulo, distancia = self._modelo.predict(face)
        return int(rotulo), float(distancia)

    def verificar(self, face: np.ndarray, rotulo_alegado: int) -> float | None:
        """1:1, menor distância às amostras do alegado, ou None se ele não está no modelo."""
        with self._lock:
            if not self._treinado:
                return None
            coletor = cv2.face.StandardCollector_create()
            self._modelo.predict_collect(face, coletor)
            resultados = coletor.getResults(False)
        distancias = [d for r, d in resultados if r == rotulo_alegado]
        return float(min(distancias)) if distancias else None

    # ------------------------------------------------------------ persistência cifrada
    def salvar_cifrado(self, caminho: Path, chave: bytes) -> None:
        """O modelo contém os histogramas das faces: é dado biométrico. Vai para
        o disco cifrado com Fernet (AES-128 + HMAC), nunca em texto."""
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if not self._treinado:
                raise ErroModelo("Modelo vazio: nada a salvar.")
            dados = self._serializar()
        temporario = caminho.with_suffix(".tmp")
        temporario.write_bytes(Fernet(chave).encrypt(dados))
        os.replace(temporario, caminho)              # troca atômica: nunca meio arquivo

    def _serializar(self) -> bytes:
        """Modelo -> bytes, inteiramente em memória."""
        fs = cv2.FileStorage(".yml", cv2.FILE_STORAGE_WRITE | cv2.FILE_STORAGE_MEMORY | cv2.FILE_STORAGE_BASE64)
        cv2.Algorithm.write(self._modelo, fs)       # o write(arquivo) do LBPH só aceita caminho
        return zlib.compress(fs.releaseAndGetString().encode("utf-8"), 9)

    def _desserializar(self, dados: bytes) -> None:
        texto = zlib.decompress(dados).decode("utf-8")
        fs = cv2.FileStorage(texto, cv2.FILE_STORAGE_READ | cv2.FILE_STORAGE_MEMORY)
        modelo = self._novo()
        cv2.Algorithm.read(modelo, fs.root())
        self._modelo = modelo
        self._treinado = modelo.getLabels() is not None and len(modelo.getLabels()) > 0

    @classmethod
    def carregar_cifrado(cls, caminho: Path, chave: bytes, parametros: ParametrosLBPH) -> "ReconhecedorLBPH":
        try:
            dados = Fernet(chave).decrypt(Path(caminho).read_bytes())
        except InvalidToken:
            raise ErroModelo("Modelo não decifra com esta chave (chave trocada ou arquivo adulterado).") from None
        reconhecedor = cls(parametros)
        reconhecedor._desserializar(dados)
        return reconhecedor

    # ------------------------------------------------------------ eliminação (LGPD)
    def remover(self, rotulo: int) -> bool:
        """Elimina do modelo todos os histogramas de uma pessoa. True se havia algum."""
        with self._lock:
            if not self._treinado:
                return False
            rotulos = self._modelo.getLabels().ravel()
            if rotulo not in rotulos:
                return False
            manter = rotulos != rotulo
            if not manter.any():                       # era a única pessoa: modelo vazio
                self._modelo, self._treinado = self._novo(), False
                return True
            histogramas = [h for h, fica in zip(self._modelo.getHistograms(), manter) if fica]
            fs = cv2.FileStorage(".yml", cv2.FILE_STORAGE_WRITE | cv2.FILE_STORAGE_MEMORY | cv2.FILE_STORAGE_BASE64)
            # mesma estrutura que o LBPH grava (radius ... labelsInfo)
            for chave, valor in (("radius", self.p.radius), ("neighbors", self.p.neighbors),
                                 ("grid_x", self.p.grid[0]), ("grid_y", self.p.grid[1])):
                fs.write(chave, int(valor))
            fs.write("threshold", float(self._modelo.getThreshold()))
            fs.startWriteStruct("histograms", cv2.FileNode_SEQ)
            for h in histogramas:
                fs.write("", h)
            fs.endWriteStruct()
            fs.write("labels", rotulos[manter].astype(np.int32).reshape(-1, 1))
            fs.startWriteStruct("labelsInfo", cv2.FileNode_SEQ)
            fs.endWriteStruct()
            texto = fs.releaseAndGetString()
            leitor = cv2.FileStorage(texto, cv2.FILE_STORAGE_READ | cv2.FILE_STORAGE_MEMORY)
            novo = self._novo()
            cv2.Algorithm.read(novo, leitor.root())
            self._modelo = novo
            return True


class ConfirmadorQuadros:
    """Pós-processamento: decide só após N quadros seguidos coerentes.

    Coerente = mesma identidade e distância dentro do limiar. Um quadro
    divergente zera a contagem. Um acerto isolado pode ser sorte; cinco
    seguidos, dificilmente.
    """

    def __init__(self, quadros: int, limiar: float):
        self.n = quadros
        self.limiar = limiar
        self._rotulo = None
        self._distancias: list[float] = []

    def alimentar(self, rotulo: int | None, distancia: float | None) -> tuple[int, float] | None:
        coerente = (rotulo is not None and distancia is not None and distancia <= self.limiar)
        if not coerente:
            self.reiniciar()
        elif rotulo != self._rotulo:
            self._rotulo, self._distancias = rotulo, [distancia]
        else:
            self._distancias.append(distancia)
        if self._rotulo is not None and len(self._distancias) >= self.n:
            return self._rotulo, sum(self._distancias) / len(self._distancias)
        return None

    @property
    def confirmados(self) -> int:
        return len(self._distancias)

    def reiniciar(self):
        self._rotulo, self._distancias = None, []
