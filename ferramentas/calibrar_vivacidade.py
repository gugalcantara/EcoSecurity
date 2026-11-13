"""Calibra a prova de vivacidade (S6) com a sua câmera e a sua luz.

    .venv\\Scripts\\python.exe -m ferramentas.calibrar_vivacidade

Protocolo guiado (~30 s), com a pessoa diante da câmera:
  1. PARADO (6 s): mede quanto o detector de olhos oscila sozinho, sem piscar.
     É o que uma foto faria: o limiar precisa ficar acima disso.
  2. PISCAR (10 s): piscadas naturais; mede quanto a textura da faixa dos olhos
     cai em cada uma. O limiar precisa ficar abaixo disso.
  3. DESLIZAR para a esquerda e 4. para a direita (6 s cada), sem girar a
     cabeça: mede quanto o centro do rosto se desloca.
No fim, mostra os valores medidos e os sugeridos para [s6_vivacidade] no
config/ecosec.toml, e grava os números em resultados/calibracao_vivacidade.json.

SINAIS CANDIDATOS da piscada: o Haar de olhos acha "olho" até com o olho
fechado, então a presença dele não serve. Quatro sinais medidos dentro da faixa
e das caixas dos olhos são comparados com os dados da própria pessoa: qual se
afasta na piscada mais do que oscila parado? O melhor vira o detector.

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
    centro: float = 0.0           # centro x da face, em larguras de face
    energia_crua: float | None = None
    escuro: float | None = None
    brilho: float | None = None
    ear: float | None = None
    regiao: float | None = None   # pontuação do detector padrão (região dos olhos) neste quadro, se ele pontuou


# sinal candidato -> sentido na piscada (+1: cai ao fechar o olho; -1: sobe)
SINAIS = {"ear": 1, "energia": 1, "energia_crua": 1, "escuro": 1, "brilho": -1}


def reproduzir_detector(registros: list[Registro], pg) -> dict[str, int]:
    """Passa a gravação pelo DETECTOR REAL da piscada, no modo do contorno (EAR), e conta, por
    etapa, quantas piscadas ele reconheceria. O esperado: ~0 parado (talvez uma
    natural), ~5 piscando, 0 deslizando. (A gravação guarda só números; o modo "regiao" é
    contado ao vivo, na própria janela, porque precisa da imagem do quadro.)"""
    import dataclasses

    from ecosec.visao.gestos import DetectorGesto, Gesto, MedidaOlhos
    from ecosec.visao.pipeline import ResultadoQuadro
    import numpy as np
    pg = dataclasses.replace(pg, sinal_piscada="ear")

    class Gravado:                       # devolve o EAR gravado, quadro a quadro
        valor = None

        def medir(self, _):
            return MedidaOlhos(1, 0.0, ear=self.valor)

    contagem = {}
    for nome, _, _ in ETAPAS:
        olhos, gesto, n = Gravado(), None, 0
        for r in (r for r in registros if r.etapa == nome and r.face and r.ear is not None):
            gesto = gesto or DetectorGesto(Gesto.PISCAR, pg, olhos)
            olhos.valor = r.ear
            caixa = (int(r.centro * 100 - 50), 0, 100, 100)          # centro gravado, em larguras de face
            if gesto.alimentar(ResultadoQuadro(faces=(caixa,), fonte="GRAVADO", largura=640, altura=480,
                                               recorte_cinza=np.zeros((2, 2), np.uint8))):
                n += 1
                gesto = None                                           # rearma, como um gesto novo
        contagem[nome] = n
    return contagem


def picos(valores: list[float | None], minimo: float = 0.3, distancia: int = 4) -> list[float]:
    """Os picos de uma série de pontuações: máximos locais a partir de minimo, com pelo menos distancia quadros
    entre um e outro (uma piscada dura alguns quadros e daria vários máximos seguidos)."""
    achados: list[tuple[int, float]] = []
    for i, v in enumerate(valores):
        if v is None or v < minimo:
            continue
        vizinhos = [x for x in valores[max(0, i - 2):i + 3] if x is not None]
        if v < max(vizinhos):
            continue
        if achados and i - achados[-1][0] < distancia:
            if v > achados[-1][1]:
                achados[-1] = (i, v)
            continue
        achados.append((i, v))
    return [v for _, v in achados]


def analisar_regiao(registros: list[Registro], limiar_atual: float) -> dict | None:
    """O detector padrão da piscada (região dos olhos): o pior valor sem piscar (parado e deslizando), os picos das
    piscadas e o limiar sugerido, no meio do caminho entre o pior valor sem piscar e a piscada mais fraca das cinco
    mais fortes. Função pura; None se o detector não pontuou nenhum quadro."""
    por = {nome: [r.regiao for r in registros if r.etapa == nome and r.face] for nome, _, _ in ETAPAS}
    sem_piscar = [v for nome in ("PARADO", "ESQUERDA", "DIREITA") for v in por[nome] if v is not None]
    das_piscadas = picos(por["PISCAR"])
    if not sem_piscar and not das_piscadas:
        return None
    pior = max(sem_piscar, default=0.0)
    fortes = sorted(das_piscadas, reverse=True)[:5]
    saida = {"pior_sem_piscar": round(pior, 2), "pior_parado": round(max(
        [v for v in por["PARADO"] if v is not None], default=0.0), 2),
        "picos_piscando": [round(v, 2) for v in fortes], "limiar_atual": limiar_atual, "avisos": []}
    if len(fortes) < 3:
        saida["avisos"].append("Menos de 3 picos na etapa de piscar: repita piscando de forma firme, com uma pausa "
                               "de olhos abertos entre uma piscada e outra.")
        return saida
    mais_fraca = fortes[-1]
    if mais_fraca <= pior + 0.1:
        saida["avisos"].append("As piscadas quase não se separam do rosto parado ou deslizando: melhore a luz de "
                               "frente e repita antes de mudar o limiar.")
        return saida
    saida["limiar_sugerido"] = round((pior + mais_fraca) / 2, 2)
    return saida


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
            deslocamentos[nome] = max(sinal * (r.centro - lista[0].centro) for r in lista)
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
            out["avisos"].append(f"O detector pelo contorno (EAR, a reserva) reconheceu só {d.get('PISCAR', 0)} "
                                 "piscadas na etapa 2. Se for usá-lo, veja a "
                                 "linha \"ear\" da tabela: se a variação típica for pequena, reduza "
                                 "queda_ear_minima.")
        if d.get("ESQUERDA", 0) + d.get("DIREITA", 0):
            out["avisos"].append("O detector \"piscou\" enquanto você deslizava: aumente queda_ear_minima "
                                 "ou reduza movimento_maximo_piscada.")
    ear = next((s for s in out["sinais"] if s["sinal"] == "ear" and s.get("medido")), None)
    if ear and ear["piscadas_percebidas"] and ear["limiar_sugerido"]:
        out["sugerido"]["queda_ear_minima"] = round(min(0.5, max(0.15, ear["limiar_sugerido"])), 2)
    medidos = [s for s in out["sinais"] if s.get("medido") and s["piscadas_percebidas"]]
    if medidos:
        melhor = max(medidos, key=lambda s: (min(s["piscadas_percebidas"], 6), s["separacao"] or 0))
        out["melhor_sinal"] = melhor["sinal"]
    if "limiar_regiao" in atual:
        regiao = analisar_regiao(registros, atual["limiar_regiao"])
        if regiao is not None:
            out["regiao"] = regiao
            out["avisos"] += regiao["avisos"]
            if "limiar_sugerido" in regiao and abs(regiao["limiar_sugerido"] - atual["limiar_regiao"]) >= 0.05:
                out["sugerido"]["limiar_regiao"] = regiao["limiar_sugerido"]
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
    if "detector_regiao" in resultado:
        d = resultado["detector_regiao"]
        linhas += ["", "DETECTOR DA PISCADA PADRÃO (região dos olhos, o mesmo do N3), contado ao vivo",
                   f"  parado: {d.get('PARADO', 0)}   piscando: {d.get('PISCAR', 0)}   "
                   f"deslizando: {d.get('ESQUERDA', 0) + d.get('DIREITA', 0)}",
                   "  (esperado: 0 ou 1 parado, ~5 piscando, 0 deslizando; ajuste limiar_regiao se precisar)"]
    if resultado.get("regiao"):
        g = resultado["regiao"]
        picos_texto = ", ".join(f"{v:.2f}" for v in g["picos_piscando"]) or "nenhum"
        linhas += [f"  pontuação: pior parado {g['pior_parado']:.2f}, pior sem piscar (parado ou deslizando) "
                   f"{g['pior_sem_piscar']:.2f}; picos das piscadas: {picos_texto}",
                   f"  limiar_regiao atual {g['limiar_atual']}" + (f", sugerido {g['limiar_sugerido']}"
                                                                     if "limiar_sugerido" in g else "")]
    if resultado.get("detector"):
        d = resultado["detector"]
        linhas += ["", "DETECTOR DA PISCADA PELO CONTORNO (modo \"ear\", reserva) sobre esta gravação",
                   f"  parado: {d.get('PARADO', 0)}   piscando: {d.get('PISCAR', 0)}   "
                   f"deslizando: {d.get('ESQUERDA', 0) + d.get('DIREITA', 0)}",
                   "  (esperado: 0 ou 1 parado, ~5 piscando, 0 deslizando)"]
    if resultado["avisos"]:
        linhas += ["", "AVISOS"] + [f"  • {a}" for a in resultado["avisos"]]
    return "\n".join(linhas)


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
        # o detector PADRÃO (região dos olhos) roda ao vivo: ele precisa da imagem, que não é gravada
        import dataclasses
        from ecosec.visao.gestos import DetectorGesto, Gesto
        self._pg_regiao = dataclasses.replace(self.pg, sinal_piscada="regiao")
        self._medida_atual = type("Medida", (), {"valor": None, "medir": lambda s, _: s.valor})()
        self._novo_gesto = lambda: DetectorGesto(Gesto.PISCAR, self._pg_regiao, self._medida_atual)
        self._gesto_regiao = self._novo_gesto()
        self.piscadas_regiao: dict[str, int] = {}
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
        if face is None or r.recorte_cinza is None:
            return Registro(self.etapa or "", time.monotonic(), False)
        m = self.olhos.medir(r.recorte_cinza)
        self._medida_atual.valor = m
        pontuacao = None
        if self.etapa:
            gesto = self._gesto_regiao
            gesto.ultima_pontuacao = None                          # só vale o que ele pontuar neste quadro
            if gesto.alimentar(r):
                self.piscadas_regiao[self.etapa] = self.piscadas_regiao.get(self.etapa, 0) + 1
                self._gesto_regiao = self._novo_gesto()             # rearma, como um gesto novo
            pontuacao = gesto.ultima_pontuacao
        x, _, w, _ = face
        if m is None:
            return Registro(self.etapa or "", time.monotonic(), True, centro=(x + w / 2) / w, regiao=pontuacao)
        return Registro(self.etapa or "", time.monotonic(), True, m.olhos, m.energia, (x + w / 2) / w,
                        m.energia_crua, m.escuro, m.brilho, m.ear, pontuacao)

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
        if len(self.instantes) < 2:
            return 0.0
        return (len(self.instantes) - 1) / (self.instantes[-1] - self.instantes[0])

    def iniciar(self):
        self.registros, self._fila = [], list(ETAPAS)
        self.piscadas_regiao = {}
        self._gesto_regiao = self._novo_gesto()
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
                 "deslocamento_minimo": self.pg.deslocamento_minimo, "limiar_regiao": self.pg.limiar_regiao}
        resultado = analisar(self.registros, self._fps(), atual, self.pg)
        resultado["detector_regiao"] = dict(self.piscadas_regiao)
        texto = relatorio(resultado)
        self.saida.setPlainText(texto)
        self.instrucao.setText("Pronto. O resultado está abaixo e foi gravado em resultados/calibracao_vivacidade.json.")
        pasta = self.cfg.caminho("resultados")
        pasta.mkdir(parents=True, exist_ok=True)
        resultado["momento"] = datetime.now().isoformat(timespec="seconds")
        # a série (só números) permite reanalisar sem repetir o protocolo
        resultado["serie"] = [{k: v for k, v in r.__dict__.items()} for r in self.registros if r.face]
        (pasta / "calibracao_vivacidade.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
        print(texto)
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
