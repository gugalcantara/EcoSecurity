"""Simbologia do mapa: fonte única de cores, tamanhos e desenho dos símbolos.

Os mesmos tons de identidade (verde, âmbar, laranja, vermelho),
escurecidos até contraste ≥ 3:1 (WCAG 1.4.11, luminância relativa) contra o fundo do mapa, com codificação
redundante: raio crescente por faixa (BAIXO e ALTO têm quase a mesma luminância; o tamanho os separa no
daltonismo) e ANEL escuro só no crítico.

Quem desenha usa as funções daqui: o ponto do mapa (`_Ponto.paint`), a legenda dinâmica e os ícones do painel
de camadas chamam o mesmo `desenhar_ponto`. Assim a legenda nunca diverge do mapa e as constantes de
cor deixam de estar duplicadas.

Temáticas de simbologia dos pontos (faixa de risco, classe, fase) e o símbolo do
AGREGADO por zoom. Classe: as cores de identidade das classes nos gráficos (`COR_IDENTIDADE_CLASSE`),
escurecidas até 3:1, e uma FORMA por classe (quadrado, círculo, triângulo de mesma área), para não depender da
cor. Fase: tons da paleta já usada nos painéis, escurecidos até 3:1, e preenchimento progressivo (um terço,
dois terços, cheio; a ENCERRADA só com o contorno, como toda encerrada no mapa). Agregado: disco BRANCO com a
contagem em #1A1A1A (17:1) e um anel em setores proporcionais à composição pelo atributo ativo (cada categoria
presente com pelo menos 20°), mais o anel escuro quando há crítico na temática de faixa. Não se confunde com o
ponto de risco, que é um disco cheio de cor sem número.

Sem dependência de segurança nem de repositórios; só QtGui (e o `acervo.fase`, puro, para os códigos de fase).
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass
from math import cos, log10, pi, radians, sin, sqrt

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF)

from ecosec.acervo import fase as _fase
from ecosec.acervo import vocabulario as _vocabulario

FAIXAS = ("BAIXO", "MEDIO", "ALTO", "CRITICO")
FUNDO_MAPA = "#EEF3EE"                    # preenchimento do país, onde os pontos são desenhados
CONTRASTE_MINIMO = 3.0                    # WCAG 2.1, 1.4.11 (objetos gráficos)
CONTRASTE_ALVO = 3.3                      # folga sobre o mínimo (arredondamento de cor e antisserrilhado)
COR_TEXTO = "#1A1A1A"                     # texto da legenda: 17:1 sobre o branco (antes, na cor da faixa: 2,44:1)
COR_TEXTO_SECUNDARIO = "#4A4A4A"
COR_ANEL = "#1A1A1A"
COR_CONTORNO_PONTO = "#FFFFFF"

# tons de identidade (gráfico de risco, planilha e ficha, sobre o fundo do tema)
COR_IDENTIDADE = {"BAIXO": "#2EA36B", "MEDIO": "#D99A1E", "ALTO": "#E36A2E", "CRITICO": "#D2384F"}
# raio do disco em pixels de tela (o anel do crítico fica por fora)
RAIO_FAIXA = {"BAIXO": 3.0, "MEDIO": 4.0, "ALTO": 5.0, "CRITICO": 5.5}
ANEL_FAIXA = {"BAIXO": False, "MEDIO": False, "ALTO": False, "CRITICO": True}
FOLGA_ANEL, ESPESSURA_ANEL = 2.0, 1.6
ESPESSURA_CONTORNO, ESPESSURA_VAZADO = 1.2, 2.0
FOLGA_FOCO = 3.5                          # anel de foco do teclado, por fora do símbolo

# ocupação das custódias: verde abaixo de 70%, âmbar de 70% a 90%, vermelho acima de 90%
LIMITES_OCUPACAO = (0.7, 0.9)
COR_OCUPACAO = (COR_IDENTIDADE["BAIXO"], COR_IDENTIDADE["MEDIO"], COR_IDENTIDADE["CRITICO"])
ROTULOS_OCUPACAO = ("< 70%", "70 a 90%", "> 90%")
SIMBOLO_CUSTODIA = {"DEFINITIVO": "◇", "INTERMEDIARIO": "□", "NORM": "△", "INICIAL": "○"}
COR_CONTORNO_CUSTODIA = "#1A1A1A"

# contornos
COR_DIVISA_UF, COR_LIMITE_MUNICIPAL = "#9AA89A", "#B8C4B8"
COR_CONTORNO_PAIS = "#7A8A7A"

# DENSIDADE: rampa sequencial AZUL, sem colidir com os tons de risco (verde, âmbar, laranja, vermelho)
# nem com a rampa laranja-vermelha do coroplético
RAMPA_DENSIDADE = ("#DCE4F7", "#9DB8E6", "#5580CC", "#24519E", "#0B2C66")


# ---------------------------------------------------------------- contraste (WCAG 2.1)
def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminancia(cor: str | QColor) -> float:
    """Luminância relativa (WCAG 2.1): 0 = preto, 1 = branco."""
    q = QColor(cor)
    return 0.2126 * _linear(q.redF()) + 0.7152 * _linear(q.greenF()) + 0.0722 * _linear(q.blueF())


def contraste(a: str | QColor, b: str | QColor) -> float:
    """Razão de contraste (L1 + 0,05) / (L2 + 0,05), de 1 a 21."""
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def escurecer_ate(cor: str, fundo: str = FUNDO_MAPA, alvo: float = CONTRASTE_ALVO) -> str:
    """O mesmo matiz e a mesma saturação (HLS), com a luminosidade reduzida em passos de 0,005 até o contraste
    com o fundo chegar ao alvo. Cor que já passa volta igual."""
    q = QColor(cor)
    h, l, s = colorsys.rgb_to_hls(q.redF(), q.greenF(), q.blueF())
    while l > 0:
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        candidata = "#{:02X}{:02X}{:02X}".format(*(round(v * 255) for v in (r, g, b)))
        if contraste(candidata, fundo) >= alvo:
            return candidata
        l -= 0.005
    return "#000000"


# cor dos pontos no mapa (e na legenda): BAIXO #2A9562, MEDIO #AC7A18, ALTO #DD5D1E, CRITICO #D2384F
COR_FAIXA = {faixa: escurecer_ate(cor) for faixa, cor in COR_IDENTIDADE.items()}

# ---------------------------------------------------------------- temáticas
TEMATICAS = ("faixa", "classe", "fase")
NOME_TEMATICA = {"faixa": "Faixa de risco", "classe": "Classe", "fase": "Fase"}

# CLASSE: tons de identidade das classes (os mesmos dos gráficos de estoque e dos painéis)
AREA, CLASSE_I, RADIOATIVO = "AREA CONTAMINADA", "CLASSE I NBR 10004", "REJEITO RADIOATIVO CNEN"
CLASSES = (AREA, CLASSE_I, RADIOATIVO)
COR_IDENTIDADE_CLASSE = {AREA: "#4e79a7", CLASSE_I: "#f28e2b", RADIOATIVO: "#e15759"}
COR_CLASSE = {c: escurecer_ate(cor) for c, cor in COR_IDENTIDADE_CLASSE.items()}
MARCA_CLASSE = {AREA: "quadrado", CLASSE_I: "circulo", RADIOATIVO: "triangulo"}
ROTULO_CLASSE = {c: _vocabulario.rotulo(c, "classe") for c in CLASSES}            # vocabulário
GLIFO_CLASSE = {AREA: "■", CLASSE_I: "●", RADIOATIVO: "▲"}
RAIO_CLASSE = 4.5                          # raio equivalente: as três formas têm a mesma área

# FASE (acervo.fase): tons da paleta dos painéis, escurecidos até 3:1
FASES = _fase.FASES
COR_IDENTIDADE_FASE = {_fase.IDENTIFICACAO: "#9c755f", _fase.INVESTIGACAO: "#76b7b2", _fase.REMEDIACAO: "#59a14f",
                       _fase.ENCERRADA: "#bab0ac"}
COR_FASE = {f: escurecer_ate(cor) for f, cor in COR_IDENTIDADE_FASE.items()}
PREENCHIMENTO_FASE = {_fase.IDENTIFICACAO: 1 / 3, _fase.INVESTIGACAO: 2 / 3, _fase.REMEDIACAO: 1.0,
                      _fase.ENCERRADA: 0.0}
GLIFO_FASE = {_fase.IDENTIFICACAO: "◔", _fase.INVESTIGACAO: "◑", _fase.REMEDIACAO: "●", _fase.ENCERRADA: "○"}
RAIO_FASE = 5.0
ESPESSURA_CONTORNO_FASE = 1.4

# AGREGADO
COR_FUNDO_AGREGADO = "#FFFFFF"
LARGURA_ANEL_AGREGADO = 4.0
SETOR_MINIMO_GRAUS = 20.0                  # toda categoria presente aparece no anel, por menor que seja


def cor_ocupacao(ocupacao: float) -> str:
    return COR_OCUPACAO[0] if ocupacao < LIMITES_OCUPACAO[0] else (
        COR_OCUPACAO[1] if ocupacao <= LIMITES_OCUPACAO[1] else COR_OCUPACAO[2])


def cor_densidade(t: float) -> QColor:
    """Cor da rampa de densidade em t ∈ [0, 1] (interpolação linear entre as paradas)."""
    t = max(0.0, min(1.0, t))
    n = len(RAMPA_DENSIDADE) - 1
    i = min(n - 1, int(t * n))
    f = t * n - i
    a, b = QColor(RAMPA_DENSIDADE[i]), QColor(RAMPA_DENSIDADE[i + 1])
    return QColor(round(a.red() + (b.red() - a.red()) * f), round(a.green() + (b.green() - a.green()) * f),
                  round(a.blue() + (b.blue() - a.blue()) * f))


def tabela_densidade():
    """Tabela de 256 cores RGB (numpy uint8, 256 × 3) para colorir a grade da KDE."""
    import numpy as np
    return np.array([[c.red(), c.green(), c.blue()] for c in (cor_densidade(i / 255) for i in range(256))],
                    np.uint8)


# ---------------------------------------------------------------- símbolos
@dataclass(frozen=True)
class Simbolo:
    """Descrição de um símbolo, desenhado igual no mapa, na legenda e no painel de camadas.

    forma: "ponto" (pendência), "agregado" (pendências agregadas por zoom), "custodia" (◇ □ △ ○), "rampa" (cores
    em sequência), "linha" (contorno), "caixas" (amostras de cor lado a lado) ou "nenhum" (só texto).
    marca: desenho do ponto ("circulo", "quadrado" ou "triangulo", de mesma área para o mesmo raio).
    preenchimento: fração do disco pintada (fase: 1/3, 2/3 ou 1), a partir do meio-dia, no sentido horário.
    Agregado: `cores` e `pesos` dos setores do anel, `texto` com a contagem."""
    forma: str
    cor: str = "#000000"
    raio: float = 5.0
    anel: bool = False
    vazado: bool = False
    atenuado: bool = False
    tipo: str = ""                         # custódia
    cores: tuple = ()                      # rampa / caixas / setores do agregado
    espessura: float = 1.0                 # linha
    marca: str = "circulo"                 # ponto
    preenchimento: float = 1.0             # ponto (fase)
    pesos: tuple = ()                      # agregado
    texto: str = ""                        # agregado

    @property
    def extensao(self) -> float:
        """Meia largura da marca, sem contorno (o vértice do triângulo de mesma área vai além do círculo)."""
        return self.raio * FATOR_MARCA.get(self.marca, 1.0)

    @property
    def raio_externo(self) -> float:
        """Até onde o desenho vai (com o contorno e o anel), em pixels."""
        if self.forma == "agregado":
            return self.raio + (FOLGA_ANEL + ESPESSURA_ANEL / 2 if self.anel else 0.5)
        if self.forma != "ponto":
            return self.raio
        borda = (ESPESSURA_VAZADO if self.vazado else ESPESSURA_CONTORNO) / 2
        return self.extensao + (FOLGA_ANEL + ESPESSURA_ANEL / 2 if self.anel else borda)


# distância do centro ao ponto mais afastado de cada marca com a mesma área do círculo de raio r: quadrado de lado
# r·√π (meia diagonal r·√π·√2 / 2); triângulo equilátero de circunraio r·√(4π / (3√3))
FATOR_MARCA = {"circulo": 1.0, "quadrado": sqrt(pi) * sqrt(2) / 2, "triangulo": sqrt(4 * pi / (3 * sqrt(3)))}


# Na temática de faixa, o caso ENCERRADO não tem faixa de risco atual (o score
# para de crescer no encerramento): contorno cinza de tamanho único, sem anel, e fora das faixas na legenda
COR_ENCERRADO = "#6B6B6B"                  # 4,6:1 sobre #EEF3EE
ENCERRADO = "ENCERRADO"                    # categoria do agregado e da legenda na temática de faixa


def simbolo_faixa(faixa: str, vazado: bool = False, atenuado: bool = False) -> Simbolo:
    if vazado:
        return Simbolo("ponto", COR_ENCERRADO, RAIO_FAIXA["MEDIO"], False, True, atenuado)
    return Simbolo("ponto", COR_FAIXA[faixa], RAIO_FAIXA[faixa], ANEL_FAIXA[faixa], vazado, atenuado)


def categorias(tematica: str) -> tuple:
    """Categorias da temática, na ordem da legenda (faixa: da pior para a melhor; fase: na ordem do processo)."""
    return {"faixa": tuple(reversed(FAIXAS)), "classe": CLASSES, "fase": FASES}[tematica]


def rotulo_categoria(tematica: str, categoria: str) -> str:
    """Rótulo de exibição da categoria (vocabulário): "Crítico", "Área contaminada", "Remediação"."""
    if categoria == ENCERRADO:
        return "Encerrados"
    if tematica == "classe":
        return ROTULO_CLASSE[categoria]
    if tematica == "fase":
        return _vocabulario.rotulo(categoria, "fase")
    return _vocabulario.rotulo(categoria, "faixa")


def cor_categoria(tematica: str, categoria: str) -> str:
    if categoria == ENCERRADO:
        return COR_ENCERRADO
    return {"faixa": COR_FAIXA, "classe": COR_CLASSE, "fase": COR_FASE}[tematica][categoria]


def glifo_categoria(tematica: str, categoria: str) -> str:
    return {"faixa": {}, "classe": GLIFO_CLASSE, "fase": GLIFO_FASE}[tematica].get(categoria, "●")


def simbolo_categoria(tematica: str, categoria: str, vazado: bool = False, atenuado: bool = False) -> Simbolo:
    """O símbolo do ponto na temática (o mesmo objeto que a legenda desenha). Na fase, a ENCERRADA é vazada."""
    if tematica == "classe":
        return Simbolo("ponto", COR_CLASSE[categoria], RAIO_CLASSE, vazado=vazado, atenuado=atenuado,
                       marca=MARCA_CLASSE[categoria])
    if tematica == "fase":
        preenchimento = PREENCHIMENTO_FASE[categoria]
        return Simbolo("ponto", COR_FASE[categoria], RAIO_FASE, vazado=preenchimento == 0.0, atenuado=atenuado,
                       preenchimento=preenchimento or 1.0)
    return simbolo_faixa(categoria, vazado, atenuado)


def raio_agregado(n: int) -> float:
    """Raio do disco do agregado em pixels: cresce devagar com a contagem (2: 9,7; 100: 13,4; teto 15)."""
    return min(15.0, 9.0 + 2.2 * log10(max(2, n)))


def texto_contagem(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def setores(pesos) -> list[float]:
    """Ângulos (graus) dos setores do anel, proporcionais aos pesos, com SETOR_MINIMO_GRAUS para toda categoria
    presente (a soma é sempre 360)."""
    pesos = [float(p) for p in pesos]
    total = sum(pesos)
    if total <= 0:
        return []
    angulos = [p / total * 360 for p in pesos]
    pequenos = {i for i, a in enumerate(angulos) if a < SETOR_MINIMO_GRAUS}
    if not pequenos:
        return angulos
    sobra = 360 - SETOR_MINIMO_GRAUS * len(pequenos)
    resto = sum(a for i, a in enumerate(angulos) if i not in pequenos)
    return [SETOR_MINIMO_GRAUS if i in pequenos else a / resto * sobra for i, a in enumerate(angulos)]


def simbolo_agregado(contagem: dict, tematica: str = "faixa", texto: str | None = None) -> Simbolo:
    """Agregado com `contagem` {categoria: n} na temática: setores do anel na ordem de `categorias(tematica)`;
    anel escuro quando há crítico na temática de faixa (a mesma codificação do ponto crítico)."""
    ordem = categorias(tematica) + ((ENCERRADO,) if tematica == "faixa" else ())
    presentes = [c for c in ordem if contagem.get(c)]
    n = sum(contagem[c] for c in presentes)
    return Simbolo("agregado", COR_TEXTO, raio_agregado(n),
                   anel=tematica == "faixa" and bool(contagem.get("CRITICO")),
                   cores=tuple(cor_categoria(tematica, c) for c in presentes),
                   pesos=tuple(contagem[c] for c in presentes),
                   texto=texto_contagem(n) if texto is None else texto)


def simbolo_agregado_legenda(tematica: str = "faixa") -> Simbolo:
    """Exemplo para a legenda e o painel: todas as categorias da temática em partes iguais, com "N"."""
    return simbolo_agregado({c: 1 for c in categorias(tematica)}, tematica, texto="N")


def simbolo_custodia(tipo: str, cor: str = COR_OCUPACAO[0]) -> Simbolo:
    return Simbolo("custodia", cor, 8.0, tipo=tipo)


def forma_custodia(tipo: str, r: float = 8.0) -> QPainterPath:
    caminho = QPainterPath()
    if tipo == "DEFINITIVO":
        caminho.addPolygon(QPolygonF([QPointF(0, -r), QPointF(r, 0), QPointF(0, r), QPointF(-r, 0)]))
    elif tipo == "NORM":
        caminho.addPolygon(QPolygonF([QPointF(0, -r), QPointF(r, r * 0.8), QPointF(-r, r * 0.8)]))
    elif tipo == "INICIAL":
        caminho.addEllipse(QPointF(0, 0), r * 0.85, r * 0.85)
    else:
        caminho.addRect(-r * 0.8, -r * 0.8, 1.6 * r, 1.6 * r)
    caminho.closeSubpath()
    return caminho


def caminho_marca(marca: str, centro: QPointF, r: float) -> QPainterPath:
    """Contorno da marca de mesma área do círculo de raio `r` (quadrado; triângulo com a ponta para cima)."""
    caminho = QPainterPath()
    if marca == "quadrado":
        meio = r * sqrt(pi) / 2
        caminho.addRect(QRectF(centro.x() - meio, centro.y() - meio, 2 * meio, 2 * meio))
    elif marca == "triangulo":
        externo = r * FATOR_MARCA["triangulo"]
        cx, cy = centro.x(), centro.y()
        caminho.addPolygon(QPolygonF([QPointF(cx, cy - externo), QPointF(cx + externo * 0.8660254, cy + externo / 2),
                                      QPointF(cx - externo * 0.8660254, cy + externo / 2)]))
        caminho.closeSubpath()
    else:
        caminho.addEllipse(centro, r, r)
    return caminho


def _anel_de_foco(painter: QPainter, centro: QPointF, externo: float):
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("#FFFFFF"), 3.0))
    painter.drawEllipse(centro, externo, externo)
    painter.setPen(QPen(QColor("#0B2C66"), 1.8))
    painter.drawEllipse(centro, externo, externo)


def desenhar_ponto(painter: QPainter, simbolo: Simbolo, centro: QPointF = QPointF(0, 0), foco: bool = False):
    """Marca na cor da categoria com contorno branco (ou só o contorno, se vazada; ou parcialmente preenchida,
    na fase) e, no crítico, um anel escuro por fora. `foco`: anel duplo (branco e escuro) do foco do teclado,
    visível sobre qualquer fundo. O agregado também passa por aqui (`desenhar_agregado`)."""
    if simbolo.forma == "agregado":
        desenhar_agregado(painter, simbolo, centro, foco)
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    cor = QColor(simbolo.cor)
    r = simbolo.raio
    contorno = caminho_marca(simbolo.marca, centro, r)
    if simbolo.vazado:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(cor, ESPESSURA_VAZADO))
        painter.drawPath(contorno)
    elif simbolo.preenchimento < 1.0:
        # fase: fundo branco, a fração pintada a partir do meio-dia (sentido horário) e o contorno na cor
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(COR_CONTORNO_PONTO)))
        painter.drawPath(contorno)
        fatia = QPainterPath(centro)
        fatia.arcTo(QRectF(centro.x() - r, centro.y() - r, 2 * r, 2 * r), 90.0, -360.0 * simbolo.preenchimento)
        fatia.closeSubpath()
        painter.setBrush(QBrush(cor))
        painter.drawPath(fatia.intersected(contorno))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(cor, ESPESSURA_CONTORNO_FASE))
        painter.drawPath(contorno)
    else:
        painter.setBrush(QBrush(cor))
        painter.setPen(QPen(QColor(COR_CONTORNO_PONTO), ESPESSURA_CONTORNO))
        painter.drawPath(contorno)
    if simbolo.anel:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(COR_ANEL), ESPESSURA_ANEL))
        painter.drawEllipse(centro, r + FOLGA_ANEL, r + FOLGA_ANEL)
    if foco:
        _anel_de_foco(painter, centro, simbolo.raio_externo + FOLGA_FOCO)
    painter.restore()


def desenhar_agregado(painter: QPainter, simbolo: Simbolo, centro: QPointF = QPointF(0, 0), foco: bool = False):
    """Disco branco, anel em setores (composição pelo atributo ativo, do meio-dia no sentido horário, com
    divisórias brancas), anel escuro opcional e a contagem no centro."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    r = simbolo.raio
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(COR_FUNDO_AGREGADO)))
    painter.drawEllipse(centro, r, r)
    meio = r - LARGURA_ANEL_AGREGADO / 2
    caixa = QRectF(centro.x() - meio, centro.y() - meio, 2 * meio, 2 * meio)
    angulos = setores(simbolo.pesos)
    inicio = 90.0
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for cor, span in zip(simbolo.cores, angulos):
        caneta = QPen(QColor(cor), LARGURA_ANEL_AGREGADO)
        caneta.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(caneta)
        painter.drawArc(caixa, round(inicio * 16), -round(span * 16))
        inicio -= span
    if len(angulos) > 1:                           # setores vizinhos de tom parecido ficam separados
        painter.setPen(QPen(QColor(COR_FUNDO_AGREGADO), 1.2))
        inicio = 90.0
        for span in angulos:
            a = radians(inicio)
            interno = r - LARGURA_ANEL_AGREGADO
            painter.drawLine(QPointF(centro.x() + interno * cos(a), centro.y() - interno * sin(a)),
                             QPointF(centro.x() + r * cos(a), centro.y() - r * sin(a)))
            inicio -= span
    if simbolo.anel:
        painter.setPen(QPen(QColor(COR_ANEL), ESPESSURA_ANEL))
        painter.drawEllipse(centro, r + FOLGA_ANEL, r + FOLGA_ANEL)
    if simbolo.texto:
        fonte = QFont("Segoe UI")
        fonte.setPixelSize(10 if len(simbolo.texto) <= 2 else 9 if len(simbolo.texto) == 3 else 8)
        fonte.setWeight(QFont.Weight.Bold)
        painter.setFont(fonte)
        painter.setPen(QColor(simbolo.cor))
        interno = r - LARGURA_ANEL_AGREGADO + 1
        painter.drawText(QRectF(centro.x() - interno, centro.y() - interno, 2 * interno, 2 * interno),
                         Qt.AlignmentFlag.AlignCenter, simbolo.texto)
    if foco:
        _anel_de_foco(painter, centro, simbolo.raio_externo + FOLGA_FOCO)
    painter.restore()


def desenhar(painter: QPainter, simbolo: Simbolo, caixa: QRectF):
    """Desenha `simbolo` centrado em `caixa` (legenda e ícones)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    centro = caixa.center()
    if simbolo.forma == "ponto":
        if simbolo.atenuado:
            painter.setOpacity(0.35)
        desenhar_ponto(painter, simbolo, centro)
    elif simbolo.forma == "agregado":
        escala = min(1.0, (min(caixa.width(), caixa.height()) - 1) / (2 * simbolo.raio_externo))
        painter.translate(centro)
        painter.scale(escala, escala)
        desenhar_agregado(painter, simbolo, QPointF(0, 0))
    elif simbolo.forma == "custodia":
        escala = min(1.0, (min(caixa.width(), caixa.height()) - 2) / 16)
        painter.translate(centro)
        painter.scale(escala, escala)
        painter.setBrush(QBrush(QColor(simbolo.cor)))
        painter.setPen(QPen(QColor(COR_CONTORNO_CUSTODIA), 1.4))
        painter.drawPath(forma_custodia(simbolo.tipo))
    elif simbolo.forma == "rampa":
        faixa = QRectF(caixa.left(), centro.y() - 5, caixa.width(), 10)
        gradiente = QLinearGradient(faixa.topLeft(), faixa.topRight())
        for i, c in enumerate(simbolo.cores):
            gradiente.setColorAt(i / max(1, len(simbolo.cores) - 1), QColor(c))
        painter.setBrush(QBrush(gradiente))
        painter.setPen(QPen(QColor("#7A7A7A"), 0.8))
        painter.drawRect(faixa)
    elif simbolo.forma == "caixas":
        n = max(1, len(simbolo.cores))
        largura = caixa.width() / n
        for i, c in enumerate(simbolo.cores):
            painter.setBrush(QBrush(QColor(c)))
            painter.setPen(QPen(QColor("#7A7A7A"), 0.8))
            painter.drawRect(QRectF(caixa.left() + i * largura, centro.y() - 5, largura, 10))
    elif simbolo.forma == "linha":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(simbolo.cor), simbolo.espessura))
        r = QRectF(0, 0, min(caixa.width(), 18), min(caixa.height(), 12))
        r.moveCenter(centro)
        painter.drawRect(r)
    painter.restore()


def icone(simbolos, largura: int = 30, altura: int = 18) -> QIcon:
    """Ícone do painel de camadas com um ou mais símbolos lado a lado (os mesmos da legenda)."""
    simbolos = list(simbolos)
    pixmap = QPixmap(largura * 2, altura * 2)              # 2× para ficar nítido em telas densas
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    passo = largura / max(1, len(simbolos))
    for i, simbolo in enumerate(simbolos):
        desenhar(painter, simbolo, QRectF(i * passo, 0, passo, altura))
    painter.end()
    return QIcon(pixmap)
