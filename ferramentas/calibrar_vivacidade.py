"""Calibra a prova de vivacidade (S6) com a sua câmera e a sua luz.

    .venv\\Scripts\\python.exe -m ferramentas.calibrar_vivacidade

Protocolo guiado (~30 s), com a pessoa diante da câmera:
  1. PARADO (6 s): mede quanto a abertura do olho oscila sozinha, sem piscar.
     É o que uma foto faria: nenhuma piscada pode aparecer aqui.
  2. PISCAR (10 s): piscadas naturais; mede quanto a abertura cai em cada uma.
  3. DESLIZAR para a esquerda e 4. para a direita (6 s cada), sem girar a
     cabeça: mede quanto o centro do rosto se desloca. Nenhuma piscada pode
     aparecer aqui: é o que uma foto deslizada faria.
No fim, repassa a gravação pelo MESMO detector do N3 (contorno do olho, medido em
tempo), mostra quantas piscadas ele reconheceu em cada etapa, e grava os números em
resultados/calibracao_vivacidade_<data>_<hora>.json, um arquivo por medição: o resumo, os parâmetros em uso
e a série de cada quadro (só números, nenhuma imagem).

SINAIS CANDIDATOS da piscada: além do contorno do olho (EAR), três sinais de
textura e tom dentro das caixas dos olhos são medidos só para comparação. Os de tom
dependem do contraste entre a pálpebra e a íris, que muda com a cor da pele; por isso
o detector usa só o EAR, que é geometria.

LGPD: nenhuma imagem é gravada e ninguém é reconhecido (não há banco nem
modelo facial aqui). Só números: contagens, energias e deslocamentos.
"""
import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from ecosec.configuracao import carregar

ETAPAS = (
    ("PARADO", 6, "Fique parado olhando para a câmera, sem piscar se conseguir."),
    ("PISCAR", 10, "Pisque normalmente, umas 5 vezes, olhando para a câmera."),
    ("ESQUERDA", 6, "Deslize o rosto para a SUA esquerda (sem girar a cabeça) e volte."),
    ("DIREITA", 6, "Deslize o rosto para a SUA direita (sem girar a cabeça) e volte."),
)


@dataclass(frozen=True)
class Registro:
    etapa: str
    tempo: float
    face: bool
    olhos: int = -1               # -1: sem medida (sem face ou recorte vazio)
    energia: float = 0.0
    centro: float = 0.0           # centro x da face, em larguras da face do próprio quadro (gravações antigas)
    energia_crua: float | None = None
    escuro: float | None = None
    brilho: float | None = None
    ear: float | None = None
    # a caixa do rosto, em pixels: o movimento é medido pela largura típica, como no N3
    x: float | None = None
    w: float | None = None


# sinal candidato -> sentido na piscada (+1: cai ao fechar o olho; -1: sobe)
SINAIS = {"ear": 1, "energia": 1, "energia_crua": 1, "escuro": 1, "brilho": -1}


def caixa_do_registro(r: Registro) -> tuple[int, int, int, int]:
    """A caixa do rosto gravada; nas gravações antigas, que só têm o centro, uma caixa de 100 px nele."""
    if r.x is not None and r.w is not None:
        return int(r.x), 0, int(r.w), int(r.w)
    return int(r.centro * 100 - 50), 0, 100, 100


def reproduzir_detector(registros: list[Registro], pg) -> dict[str, int]:
    """Passa a gravação pelo DETECTOR REAL da piscada, com os instantes gravados, e conta, por etapa, quantas
    piscadas ele reconheceria. O esperado: ~0 parado (talvez uma natural), ~5 piscando, 0 deslizando."""
    from ecosec.visao.gestos import DetectorGesto, Gesto, MedidaOlhos
    from ecosec.visao.pipeline import ResultadoQuadro
    import numpy as np

    class Gravado:                       # devolve o EAR gravado, quadro a quadro
        valor = None

        def medir(self, _):
            return MedidaOlhos(1, 0.0, ear=self.valor)

    contagem = {}
    for nome, _, _ in ETAPAS:
        olhos, gesto, n = Gravado(), None, 0
        for r in (r for r in registros if r.etapa == nome and r.face):
            gesto = gesto or DetectorGesto(Gesto.PISCAR, pg, olhos)
            olhos.valor = r.ear
            if gesto.alimentar(ResultadoQuadro(faces=(caixa_do_registro(r),), fonte="GRAVADO", largura=640,
                                               altura=480, recorte_cinza=np.zeros((2, 2), np.uint8),
                                               instante=r.tempo)):
                n += 1
                gesto = None                                           # rearma, como um gesto novo
        contagem[nome] = n
    return contagem


def deslocamento_maximo(lista: list[Registro], sentido: int) -> float:
    """O maior deslocamento do centro desde o primeiro quadro da etapa, em larguras típicas do rosto."""
    if all(r.x is not None and r.w is not None for r in lista):
        largura = statistics.median(r.w for r in lista) or 1
        inicio = lista[0].x + lista[0].w / 2
        return max(sentido * (r.x + r.w / 2 - inicio) / largura for r in lista)
    return max(sentido * (r.centro - lista[0].centro) for r in lista)


def _variacao(valor: float, referencia: float, sentido: int) -> float:
    """Quanto o valor se afastou da referência NO SENTIDO da piscada (fração)."""
    return sentido * (referencia - valor) / referencia if referencia else 0.0


def _eventos(valores: list[float], limiar: float) -> list[float]:
    """Pico de cada trecho seguido acima do limiar (cada trecho = uma piscada candidata)."""
    picos, atual = [], None
    for v in valores + [float("-inf")]:
        if v > limiar:
            atual = v if atual is None else max(atual, v)
        elif atual is not None:
            picos.append(atual)
            atual = None
    return picos


def comparar_sinais(parado: list[Registro], piscar: list[Registro]) -> list[dict]:
    """Para cada sinal: pior oscilação parado, piscadas percebidas e a separação entre elas."""
    linhas = []
    for nome, sentido in SINAIS.items():
        base = [getattr(r, nome) for r in parado if getattr(r, nome) is not None]
        serie = [getattr(r, nome) for r in piscar if getattr(r, nome) is not None]
        if len(base) < 5 or len(serie) < 5:
            linhas.append({"sinal": nome, "medido": False})
            continue
        referencia = statistics.median(base)
        ruido = max(_variacao(v, referencia, sentido) for v in base)
        limiar = max(0.03, ruido * 1.3)
        picos = _eventos([_variacao(v, referencia, sentido) for v in serie], limiar)
        tipico = statistics.median(picos) if picos else 0.0
        linhas.append({"sinal": nome, "medido": True, "referencia": round(referencia, 3),
                       "pior_oscilacao_parado": round(ruido, 3), "piscadas_percebidas": len(picos),
                       "variacao_tipica": round(tipico, 3),
                       "separacao": round(tipico / ruido, 2) if ruido > 0 else None,
                       "limiar_sugerido": round((ruido + tipico) / 2, 3) if picos else None})
    return linhas


def analisar(registros: list[Registro], fps: float, atual: dict, pg=None) -> dict:
    """Função pura: números medidos e valores sugeridos (com o porquê)."""
    por = {nome: [r for r in registros if r.etapa == nome and r.face] for nome, _, _ in ETAPAS}
    out = {"fps": round(fps, 1), "atual": atual, "medido": {}, "sugerido": {}, "avisos": []}
    parado, piscar = por["PARADO"], por["PISCAR"]

    com_pontos = [r for r in parado + piscar if r.ear is not None]
    out["medido"]["quadros_com_landmarks"] = round(len(com_pontos) / len(parado + piscar), 2) if parado + piscar else 0
    if parado + piscar and len(com_pontos) / len(parado + piscar) < 0.8:
        out["avisos"].append("Os pontos do rosto não foram ajustados em boa parte dos quadros: rosto de frente, "
                             "inteiro na imagem e com luz à frente.")

    deslocamentos = {}
    for nome, sinal in (("ESQUERDA", 1), ("DIREITA", -1)):
        lista = por[nome]
        if len(lista) >= 2:
            deslocamentos[nome] = deslocamento_maximo(lista, sinal)
    out["medido"]["deslocamento_maximo"] = {k: round(v, 2) for k, v in deslocamentos.items()}
    if len(deslocamentos) == 2:
        menor = min(deslocamentos.values())
        if menor < 0.1:
            out["avisos"].append("Quase não houve deslocamento lateral. O gesto é deslizar o rosto, com o corpo "
                                 "acompanhando; com a cabeça girada, a face deixa de ser detectada.")
        # só sugere reduzir: exigir mais deslocamento não traz segurança (deslizar uma foto custa
        # o mesmo) e só dificulta para quem se move menos
        alvo = round(max(0.12, menor * 0.7), 2)
        if alvo < atual["deslocamento_minimo"]:
            out["sugerido"]["deslocamento_minimo"] = alvo
    out["sinais"] = comparar_sinais(parado, piscar)
    if pg is not None and any(r.ear is not None for r in registros):
        out["detector"] = reproduzir_detector(registros, pg)
        d = out["detector"]
        if d.get("PISCAR", 0) < 3:
            out["avisos"].append(f"O detector reconheceu só {d.get('PISCAR', 0)} piscadas na etapa 2. Pisque de "
                                 "forma firme, com a luz de frente e o rosto parado, e repita.")
        if d.get("ESQUERDA", 0) + d.get("DIREITA", 0):
            out["avisos"].append("O detector \"piscou\" enquanto você deslizava: anote e mande esta gravação, "
                                 "porque uma foto deslizada não pode virar piscada.")
    ear = next((s for s in out["sinais"] if s["sinal"] == "ear" and s.get("medido")), None)
    if ear and ear["piscadas_percebidas"] and ear["limiar_sugerido"]:
        out["sugerido"]["queda_ear_minima"] = round(min(0.5, max(0.15, ear["limiar_sugerido"])), 2)
    medidos = [s for s in out["sinais"] if s.get("medido") and s["piscadas_percebidas"]]
    if medidos:
        melhor = max(medidos, key=lambda s: (min(s["piscadas_percebidas"], 6), s["separacao"] or 0))
        out["melhor_sinal"] = melhor["sinal"]
    if fps and fps < 8:
        out["avisos"].append(f"Só {fps:.1f} quadros/s: piscadas rápidas podem cair entre dois quadros.")
    return out


def relatorio(resultado: dict) -> str:
    linhas = [f"Quadros por segundo: {resultado['fps']}", "", "MEDIDO"]
    for chave, valor in resultado["medido"].items():
        linhas.append(f"  {chave}: {valor}")
    linhas += ["", "SUGERIDO para [s6_vivacidade] em config/ecosec.toml (atual entre parênteses)"]
    for chave, valor in resultado["sugerido"].items():
        linhas.append(f"  {chave} = {valor}    ({resultado['atual'].get(chave)})")
    if not resultado["sugerido"]:
        linhas.append("  (nada a sugerir: veja os avisos)")
    if resultado.get("sinais"):
        linhas += ["", "SINAIS CANDIDATOS DA PISCADA (pisque ~5 vezes na etapa 2)",
                   "  sinal          piscadas  variação típica  pior parado  separação"]
        for s in resultado["sinais"]:
            if not s.get("medido"):
                linhas.append(f"  {s['sinal']:<14} sem dados")
                continue
            linhas.append(f"  {s['sinal']:<14} {s['piscadas_percebidas']:>8}  {s['variacao_tipica']:>15.0%}  "
                          f"{s['pior_oscilacao_parado']:>11.0%}  {s['separacao'] or '-':>9}")
        if resultado.get("melhor_sinal"):
            linhas.append(f"  melhor sinal nesta medição: {resultado['melhor_sinal']}")
    if resultado.get("detector"):
        d = resultado["detector"]
        linhas += ["", "DETECTOR DA PISCADA (o mesmo do N3) sobre esta gravação",
                   f"  parado: {d.get('PARADO', 0)}   piscando: {d.get('PISCAR', 0)}   "
                   f"deslizando: {d.get('ESQUERDA', 0) + d.get('DIREITA', 0)}",
                   "  (esperado: 0 ou 1 parado, ~5 piscando, 0 deslizando)"]
    if resultado["avisos"]:
        linhas += ["", "AVISOS"] + [f"  • {a}" for a in resultado["avisos"]]
    return "\n".join(linhas)


def quadros_por_segundo(instantes: list[float]) -> float:
    """Quadros por segundo nos instantes recentes. 0 enquanto não há intervalo medido: no Windows, o relógio
    monotônico anda em passos de ~15 ms, e dois quadros podem chegar com o mesmo instante."""
    if len(instantes) < 2 or instantes[-1] <= instantes[0]:
        return 0.0
    return (len(instantes) - 1) / (instantes[-1] - instantes[0])


def nome_arquivo(momento: datetime) -> str:
    """Um arquivo por medição: a data e a hora no nome, para uma medição não apagar a anterior."""
    return f"calibracao_vivacidade_{momento:%Y-%m-%d_%H%M%S}.json"


def parametros_gravaveis(pg) -> dict:
    """Os parâmetros da vivacidade em uso na medição (números e textos), para reanalisar a série depois."""
    import dataclasses
    return {k: v for k, v in dataclasses.asdict(pg).items() if isinstance(v, (bool, int, float, str))}


class JanelaCalibracao(QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        from ecosec.interface.video import TrabalhadorVideo, VisorVideo
        from ecosec.visao.aquisicao import Camera
        from ecosec.visao.gestos import DetectorOlhos, ParametrosGestos, carregar_landmarks
        from ecosec.visao.pipeline import PipelineVisao
        self.cfg = cfg
        self.pg = ParametrosGestos.de_configuracao(cfg)
        self.olhos = DetectorOlhos(self.pg.haar_olhos, self.pg.vizinhos_olhos,
                                   carregar_landmarks(self.pg.modelo_landmarks, self.pg.modelo_landmarks_sha256))
        self.registros: list[Registro] = []
        self.instantes: list[float] = []
        self.etapa, self.fim_etapa = None, 0.0
        self.setWindowTitle("EcoSecurity · calibrar a vivacidade")
        self.visor = VisorVideo()
        self.instrucao = QLabel("Clique em «Iniciar» com o rosto de frente, bem iluminado.")
        self.instrucao.setWordWrap(True)
        self.instrucao.setStyleSheet("font-size:18px; font-weight:600;")
        self.ao_vivo = QLabel()
        self.ao_vivo.setStyleSheet("font-family:Consolas; font-size:13px;")
        self.saida = QPlainTextEdit()
        self.saida.setReadOnly(True)
        self.botao = QPushButton("Iniciar")
        self.botao.clicked.connect(self.iniciar)
        lado = QVBoxLayout()
        for w in (self.instrucao, self.ao_vivo, self.botao, self.saida):
            lado.addWidget(w)
        corpo = QHBoxLayout()
        corpo.addWidget(self.visor, 3)
        corpo.addLayout(lado, 2)
        central = QWidget()
        central.setLayout(corpo)
        self.setCentralWidget(central)
        self.resize(1100, 600)
        self.video = TrabalhadorVideo(Camera.de_configuracao(cfg), PipelineVisao.de_configuracao(cfg),
                                      processar=self._medir, parent=self)
        self.video.quadro.connect(self._quadro)
        self.video.falhou.connect(lambda m: self.instrucao.setText(f"Câmera: {m}"))
        self.video.start()
        self.relogio = QTimer(self)
        self.relogio.timeout.connect(self._tique)
        self.relogio.start(200)

    def _medir(self, r):                                   # thread do vídeo
        face = r.face_unica
        instante = r.instante if r.instante is not None else time.monotonic()
        if face is None or r.recorte_cinza is None:
            return Registro(self.etapa or "", instante, False)
        m = self.olhos.medir(r.recorte_cinza)
        x, _, w, _ = face
        if m is None:
            return Registro(self.etapa or "", instante, True, centro=(x + w / 2) / w, x=x, w=w)
        return Registro(self.etapa or "", instante, True, m.olhos, m.energia, (x + w / 2) / w,
                        m.energia_crua, m.escuro, m.brilho, m.ear, x, w)

    def _quadro(self, imagem, resultado, registro):        # thread da interface
        self.visor.mostrar(imagem, resultado)
        self.instantes = (self.instantes + [time.monotonic()])[-30:]
        if registro is None:
            return
        if self.etapa:
            self.registros.append(registro)
        abertura = f"{registro.ear:.3f}" if registro.ear is not None else "-"
        self.ao_vivo.setText(f"face: {'sim' if registro.face else 'NÃO'}   abertura dos olhos (EAR): {abertura}\n"
                             f"quadros/s: {self._fps():.1f}")

    def _fps(self) -> float:
        return quadros_por_segundo(self.instantes)

    def iniciar(self):
        self.registros, self._fila = [], list(ETAPAS)
        self.botao.setEnabled(False)
        self.saida.clear()
        self._proxima()

    def _proxima(self):
        if not self._fila:
            self.etapa = None
            self._concluir()
            return
        self.etapa, duracao, texto = self._fila.pop(0)
        self.fim_etapa = time.monotonic() + duracao
        self._texto_etapa = texto

    def _tique(self):
        if not self.etapa:
            return
        restante = self.fim_etapa - time.monotonic()
        if restante <= 0:
            self._proxima()
            return
        self.instrucao.setText(f"{self._texto_etapa}  ({restante:.0f} s)")

    def _concluir(self):
        atual = {"vizinhos_olhos": self.pg.vizinhos_olhos, "queda_ear_minima": self.pg.queda_ear_minima,
                 "deslocamento_minimo": self.pg.deslocamento_minimo}
        resultado = analisar(self.registros, self._fps(), atual, self.pg)
        texto = relatorio(resultado)
        self.saida.setPlainText(texto)
        pasta = self.cfg.caminho("resultados")
        pasta.mkdir(parents=True, exist_ok=True)
        agora = datetime.now()
        resultado["momento"] = agora.isoformat(timespec="seconds")
        resultado["parametros"] = parametros_gravaveis(self.pg)
        # a série (só números) permite reanalisar sem repetir o protocolo
        resultado["serie"] = [{k: v for k, v in r.__dict__.items()} for r in self.registros if r.face]
        arquivo = pasta / nome_arquivo(agora)
        arquivo.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        self.instrucao.setText(f"Pronto. O resultado está abaixo e foi gravado em resultados/{arquivo.name}.")
        print(texto)
        print(f"\nGravado em {arquivo}")
        self.botao.setText("Repetir")
        self.botao.setEnabled(True)

    def closeEvent(self, evento):
        self.video.parar()
        self.video.wait(3000)
        super().closeEvent(evento)


def main():
    app = QApplication(sys.argv)
    janela = JanelaCalibracao(carregar())
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
