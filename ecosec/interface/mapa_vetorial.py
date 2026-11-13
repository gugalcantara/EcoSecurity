"""Mapa interativo do acervo, desenhado no próprio Qt (QGraphicsView), sem serviço de mapas nem internet.

Usa as malhas do IBGE (país, UFs e municípios) e organiza o conteúdo em camadas com visibilidade, opacidade e
ordem próprias: divisas, coroplético por UF ou por município, densidade, pendências e custódias. Cada pendência
é um ponto com a simbologia do sistema, que não depende só da cor; em zoom baixo, os pontos próximos viram um
agregado com a contagem. No nível 1 só aparece o coroplético por UF, sem nenhum ponto.

O mapa aceita zoom pela roda e pelo teclado, arrasto, duplo clique e navegação por Tab entre os pontos, e
mostra a legenda e a barra de escala da vista atual. O recorte do filtro e o ano do corte decidem quais pontos
contam; os casos encerrados aparecem vazados. Como as coordenadas são dado reservado, a cena leva a marca
visível com a matrícula e o horário de quem consulta.
"""
from collections import Counter
from math import cos, floor, log10, pi, radians, sin

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QAccessible, QAccessibleEvent, QBrush, QColor, QFont, QImage, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem,
                               QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QToolTip)

from ecosec.acervo import fase as fases
from ecosec.acervo import vocabulario as _vocabulario
from ecosec.interface.componentes import simbologia as sb
from ecosec.interface.componentes.agregacao import agrupar
from ecosec.interface.componentes.animacao import animar_enquadramento, parar_enquadramento
from ecosec.interface.componentes.camada import Camada
from ecosec.interface.componentes.legenda_mapa import Entrada, LegendaMapa

K = 100.0                                    # unidades de cena por grau
COS_LAT = cos(radians(15))                   # projeção: largura na latitude média do país (só a forma do desenho;
                                             # as distâncias da barra de escala usam a latitude do centro)
RAIO_TERRA_KM = 6371.0088                    # raio médio (iugg), o mesmo da haversine
KM_POR_GRAU = pi * RAIO_TERRA_KM / 180       # ≈ 111,195 km por grau de meridiano
COR_FAIXA = sb.COR_FAIXA                     # fonte única: componentes.simbologia
FAIXAS = sb.FAIXAS
ZOOM_MUNICIPIOS = 6.0                        # a partir deste aumento (sobre o país inteiro), os limites municipais
ZOOM_NOMES = 14.0                            # ... e os nomes deles
ESCALAS = ((0.0, "PAIS"), (3.0, "UF"), (12.0, "MUNICIPIO"))
MODOS_RECORTE = ("esconder", "atenuar")
OPACIDADE_ATENUADA = 0.15                    # modo "atenuar": pontos fora do recorte, só como contexto
SIMBOLO = sb.SIMBOLO_CUSTODIA
FATOR_ZOOM_TECLADO = 1.6                     # o mesmo dos botões + e − do painel
ZOOM_MINIMO, ZOOM_MAXIMO = 0.8, 400.0        # do país inteiro (com folga) até ~1 km na tela; o passo para no limite
LIMIAR_CLIQUE_PX = 4                         # Entre apertar e soltar, até aqui é clique; além, arrasto
BARRA_ESCALA_MAX_PX = 140
# camada -> (z, opacidade padrão); z maior = desenhada por cima. A ordem pode mudar (definir_ordem).
CAMADAS = {"ufs": (1, 1.0), "municipios": (2, 0.7), "limites": (3, 1.0), "densidade": (4, 0.55),
           "pendencias": (10, 0.9), "custodias": (20, 1.0)}
# nomes sem ambiguidade: "municipios" é o coroplético (pendências por município); "limites", o contorno
NOME_CAMADA = {"ufs": "Divisas das UFs", "municipios": "Coroplético municipal", "limites": "Limites municipais",
               "densidade": "Densidade (KDE)", "pendencias": "Casos", "custodias": "Custódias"}
INSTRUCOES = ("Roda do mouse ou + e − dão zoom; setas ou arrastar movem o mapa; Tab e Shift+Tab percorrem os "
              "pontos e agregados visíveis do filtro, de oeste para leste; Enter abre a ficha do ponto ou aproxima "
              "o agregado; Esc solta o foco.")
# agregação por zoom: raio em pixels de tela e o aumento a partir do qual nada se agrega (escala de UF)
RAIO_AGREGACAO_PX = 36.0          # 2 × o maior raio externo do agregado (17,8 px)
ZOOM_DESAGREGA = 3.0
ZOOM_MAXIMO_AGREGADO = 1.5 * ZOOM_DESAGREGA      # o clique no agregado aproxima no máximo até aqui (ou 2×)
TEMATICAS = sb.TEMATICAS


def projetar(lon: float, lat: float) -> QPointF:
    return QPointF(lon * K * COS_LAT, -lat * K)


def desprojetar(ponto: QPointF) -> tuple[float, float]:
    """(lon, lat) de um ponto da cena (inverso de projetar)."""
    return ponto.x() / (K * COS_LAT), -ponto.y() / K


def km_por_pixel(escala_cena: float, lat: float) -> float:
    """Distância LESTE-OESTE representada por um pixel na latitude lat: um grau de longitude mede
    KM_POR_GRAU · cos(lat), e um grau ocupa K · COS_LAT unidades de cena (projeção) × escala_cena pixels."""
    return KM_POR_GRAU * cos(radians(lat)) / (K * COS_LAT * escala_cena)


def distancia_redonda(km_max: float) -> float:
    """O maior valor 1, 2 ou 5 × 10ⁿ km que não passa de km_max."""
    if km_max <= 0:
        return 0.0
    potencia = 10 ** floor(log10(km_max))
    return next(m * potencia for m in (5, 2, 1) if m * potencia <= km_max)


def _texto_km(km: float) -> str:
    if km >= 1:
        return f"{km:.0f} km"
    return f"{km * 1000:.0f} m"


def _caminho(aneis) -> QPainterPath:
    caminho = QPainterPath()
    for anel in aneis:
        caminho.addPolygon(QPolygonF([projetar(float(lon), float(lat)) for lon, lat in anel]))
        caminho.closeSubpath()
    return caminho


_cor_ocupacao = sb.cor_ocupacao             # nomes antigos, mantidos
_forma_custodia = sb.forma_custodia


class _Ponto(QGraphicsEllipseItem):
    """Pendência: símbolo da faixa (simbologia), tamanho fixo na tela, realça ao passar o mouse, avisa no clique
    e no Enter (o mesmo caminho), recebe foco do teclado (anel duplo)."""

    def __init__(self, pendencia, faixa: str, ao_clicar, rotulo_atividade: str = ""):
        super().__init__()
        self.pendencia, self.faixa, self._ao_clicar = pendencia, faixa, ao_clicar
        self.filtrado, self.no_ano = True, True        # no recorte do filtro / ativo (ou existente) no ano do mapa
        self.atenuado = False
        self.vazado = False                             # encerrada no corte: só o contorno
        self.focado = False
        self.agrupado = False                           # escondido dentro de um agregado
        self.tematica = "faixa"
        self.fase = fases.fase(pendencia)               # no corte do mapa (definir_ano atualiza)
        self.simbolo = sb.simbolo_faixa(faixa)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._ajustar_geometria()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(FAIXAS.index(faixa))                    # crítico por cima
        self.setData(0, f"FAIXA:{faixa}")
        self._rotulo_atividade = rotulo_atividade
        self.nome_acessivel = ""
        self._dica = ""
        self._atualizar_textos()

    def _atualizar_textos(self):
        """Nome acessível e dica com os rótulos do vocabulário: "Caso PD-0001, risco crítico, UF SP"."""
        p = self.pendencia
        fase = sb.rotulo_categoria("fase", self.fase).lower()
        risco = "encerrado" if self.vazado else f"risco {sb.rotulo_categoria('faixa', self.faixa).lower()}"
        extra = {"classe": f", classe {sb.rotulo_categoria('classe', p.classe_risco)}",
                 "fase": f", fase {fase}"}.get(self.tematica, "")
        self.nome_acessivel = f"Caso {p.codigo}, {risco}, UF {p.uf}{extra}"
        self._dica = (f"{p.codigo} · {_vocabulario.frase(p.substancia)}\n{self._rotulo_atividade or p.atividade}\n"
                      f"{p.municipio}/{p.uf} · {risco} · {_vocabulario.rotulo(p.situacao, 'situacao_caso')}\n"
                      f"{sb.rotulo_categoria('classe', p.classe_risco)} · fase {fase}\n"
                      "clique ou Enter para a ficha")
        if not self.atenuado:
            self.setToolTip(self._dica)

    @property
    def categoria(self) -> str:
        """Categoria do ponto na temática atual (faixa, classe ou fase)."""
        return {"classe": self.pendencia.classe_risco, "fase": self.fase}.get(self.tematica, self.faixa)

    def categoria_em(self, tematica: str) -> str:
        return {"classe": self.pendencia.classe_risco, "fase": self.fase}.get(tematica, self.faixa)

    def _atualizar_simbolo(self):
        self.simbolo = sb.simbolo_categoria(self.tematica, self.categoria, vazado=self.vazado)
        self._ajustar_geometria()
        self.update()

    def definir_tematica(self, tematica: str):
        if tematica != self.tematica:
            self.tematica = tematica
            self._atualizar_simbolo()
            self._atualizar_textos()

    def definir_fase(self, codigo: str):
        if codigo != self.fase:
            self.fase = codigo
            if self.tematica == "fase":
                self._atualizar_simbolo()
            self._atualizar_textos()

    @property
    def instrucao(self) -> str:
        return "Enter abre a ficha."

    @property
    def anel(self) -> bool:
        return self.simbolo.anel

    @property
    def raio(self) -> float:
        return self.simbolo.raio

    @property
    def cor(self) -> str:
        return self.simbolo.cor

    @property
    def descricao_acessivel(self) -> str:
        p = self.pendencia
        return (f"{p.municipio}/{p.uf}, {_vocabulario.frase(p.substancia)}, "
                f"{_vocabulario.rotulo(p.situacao, 'situacao_caso')}"
                + (", encerrado no corte (contorno cinza)" if self.vazado else ""))

    @property
    def conta(self) -> bool:
        """Entra nas contagens (legenda, dicas, coroplético, densidade): no ano do mapa E no recorte."""
        return self.filtrado and self.no_ano

    def _ajustar_geometria(self):
        r = self.simbolo.raio_externo + (sb.FOLGA_FOCO + 2.0 if self.focado else 0.0)
        if self.rect().width() != 2 * r:
            self.setRect(-r, -r, 2 * r, 2 * r)

    def paint(self, painter, opcao, widget=None):
        sb.desenhar_ponto(painter, self.simbolo, QPointF(0, 0), self.focado)

    def definir_vazado(self, vazado: bool):
        """Encerrada: contorno na cor da faixa, sem preenchimento (continua clicável e com a dica)."""
        if vazado == self.vazado:
            return
        self.vazado = vazado
        self._atualizar_simbolo()
        self._atualizar_textos()

    def definir_foco(self, focado: bool):
        if focado == self.focado:
            return
        self.focado = focado
        self._ajustar_geometria()
        self.update()

    def definir_agrupado(self, agrupado: bool):
        """Dentro de um agregado: escondido (continua contando na legenda, nas dicas e no filtro)."""
        if agrupado != self.agrupado:
            self.agrupado = agrupado
            self.setVisible((self.conta or self.atenuado) and not agrupado)

    def atualizar_visibilidade(self, modo: str = "esconder"):
        atenuado = modo == "atenuar" and self.no_ano and not self.filtrado
        self.setVisible((self.conta or atenuado) and not (self.agrupado and self.conta))
        if atenuado == self.atenuado:
            return
        self.atenuado = atenuado
        # atenuado: só contexto, sem clique, sem realce, sem dica e por baixo dos pontos do recorte
        self.setOpacity(OPACIDADE_ATENUADA if atenuado else 1.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton if atenuado else Qt.MouseButton.AllButtons)
        self.setAcceptHoverEvents(not atenuado)
        self.setToolTip("" if atenuado else self._dica)
        self.setCursor(Qt.CursorShape.ArrowCursor if atenuado else Qt.CursorShape.PointingHandCursor)
        self.setZValue(FAIXAS.index(self.faixa) - (len(FAIXAS) if atenuado else 0))
        if atenuado:
            self.setScale(1.0)

    def ativar(self):
        """Abre a ficha: o mesmo caminho do clique (o sinal pendencia_escolhida do mapa)."""
        self._ao_clicar(self.pendencia)

    def hoverEnterEvent(self, evento):
        self.setScale(1.8)
        super().hoverEnterEvent(evento)

    def hoverLeaveEvent(self, evento):
        self.setScale(1.0)
        super().hoverLeaveEvent(evento)

    def clicar(self) -> bool:
        """Clique (do mapa, ao soltar): o mesmo caminho do Enter."""
        self.ativar()
        return True


class _Agregado(QGraphicsItem):
    """Pendências do filtro próximas na tela: disco branco com a contagem e anel em setores pela
    composição no atributo da temática. Tamanho fixo na tela; clique ou Enter aproximam até os membros; dica com
    a contagem por faixa (e pela categoria da temática); recebe o foco do teclado como o ponto."""

    def __init__(self, membros, tematica: str, ao_ativar):
        super().__init__()
        self.membros = list(membros)
        self.n = len(self.membros)
        self.tematica = tematica
        self._ao_ativar = ao_ativar
        self.focado = False
        # Na temática de faixa, os encerrados (contorno cinza) não têm faixa atual: ficam fora da contagem
        # por faixa e do "pior risco", e entram no anel como uma categoria cinza própria
        self.por_faixa = Counter(m.faixa for m in self.membros if not m.vazado)
        self.encerrados = sum(m.vazado for m in self.membros)
        self.pior = max(self.por_faixa, key=FAIXAS.index) if self.por_faixa else sb.ENCERRADO
        self.por_categoria = Counter(sb.ENCERRADO if tematica == "faixa" and m.vazado else m.categoria_em(tematica)
                                     for m in self.membros)
        self.simbolo = sb.simbolo_agregado(self.por_categoria, tematica)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(len(FAIXAS) + 1)                 # por cima dos pontos soltos da camada
        self.setData(0, "AGREGADO")
        pior = sb.rotulo_categoria("faixa", self.pior).lower()
        self.nome_acessivel = (f"Agrupamento de {self.n} casos, pior risco {pior}" if self.por_faixa
                               else f"Agrupamento de {self.n} casos encerrados")
        linhas = [f"{self.n} casos agrupados" + (f" · pior risco {pior}" if self.por_faixa else ""),
                  "ativos por faixa de risco:"]
        linhas += [f"  {sb.rotulo_categoria('faixa', f)}: {self.por_faixa[f]}" for f in reversed(FAIXAS)
                   if self.por_faixa[f]]
        if self.encerrados:
            linhas.append(f"  encerrados (sem faixa): {self.encerrados}")
        if tematica != "faixa":
            linhas.append(f"por {sb.NOME_TEMATICA[tematica].lower()}:")
            linhas += [f"  {sb.rotulo_categoria(tematica, c)}: {self.por_categoria[c]}"
                       for c in sb.categorias(tematica) if self.por_categoria[c]]
        linhas.append("clique ou Enter para aproximar")
        self.setToolTip("\n".join(linhas))

    @property
    def descricao_acessivel(self) -> str:
        return ("por faixa: " + ", ".join(f"{sb.rotulo_categoria('faixa', f).lower()} {self.por_faixa[f]}"
                                          for f in reversed(FAIXAS) if self.por_faixa[f])
                + (f", encerrados {self.encerrados}" if self.encerrados else ""))

    @property
    def instrucao(self) -> str:
        return "Enter aproxima o mapa até o agregado."

    def boundingRect(self) -> QRectF:
        r = self.simbolo.raio_externo + (sb.FOLGA_FOCO + 2.0 if self.focado else 0.0)
        return QRectF(-r, -r, 2 * r, 2 * r)

    def shape(self) -> QPainterPath:
        caminho = QPainterPath()
        caminho.addEllipse(QPointF(0, 0), self.simbolo.raio, self.simbolo.raio)
        return caminho

    def paint(self, painter, opcao, widget=None):
        sb.desenhar_agregado(painter, self.simbolo, QPointF(0, 0), self.focado)

    def retangulo_membros(self) -> QRectF:
        """Retângulo (cena) que contém as posições de todos os membros."""
        xs = [m.pos().x() for m in self.membros]
        ys = [m.pos().y() for m in self.membros]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def definir_foco(self, focado: bool):
        if focado != self.focado:
            self.prepareGeometryChange()
            self.focado = focado
            self.update()

    def ativar(self):
        self._ao_ativar(self)

    def hoverEnterEvent(self, evento):
        self.setScale(1.15)
        super().hoverEnterEvent(evento)

    def hoverLeaveEvent(self, evento):
        self.setScale(1.0)
        super().hoverLeaveEvent(evento)

    def clicar(self) -> bool:
        # adiado: aproximar recria os agregados, e este item não pode sumir dentro do evento do mouse
        QTimer.singleShot(0, self.ativar)
        return True


class _Regiao(QGraphicsPathItem):
    """UF ou município: realça ao passar o mouse e mostra o resumo na dica. Avisa hover e clique."""

    def __init__(self, caminho, cor_borda: str, espessura: float, preenchimento: QColor, realce: QColor,
                 chave=None, ao_passar=None, ao_clicar=None):
        super().__init__(caminho)
        self.chave, self._ao_passar, self._ao_clicar = chave, ao_passar, ao_clicar
        self._normal, self._realce = QBrush(preenchimento), QBrush(realce)
        caneta = QPen(QColor(cor_borda), espessura)
        caneta.setCosmetic(True)                       # espessura em pixels, qualquer que seja o zoom
        self.setPen(caneta)
        self.setBrush(self._normal)
        self.setAcceptHoverEvents(True)

    def definir_preenchimento(self, cor: QColor, realce: QColor | None = None):
        self._normal = QBrush(cor)
        self._realce = QBrush(realce or cor.lighter(115))
        self.setBrush(self._normal)

    def hoverEnterEvent(self, evento):
        self.setBrush(self._realce)
        if self._ao_passar:
            self._ao_passar(self.chave)
        super().hoverEnterEvent(evento)

    def hoverLeaveEvent(self, evento):
        self.setBrush(self._normal)
        if self._ao_passar:
            self._ao_passar(None)
        super().hoverLeaveEvent(evento)

    def clicar(self) -> bool:
        """UF do coroplético (N1): avisa o clique; município e divisa sem aviso deixam o clique passar."""
        if self._ao_clicar:
            self._ao_clicar(self.chave)
        return bool(self._ao_clicar)


class MapaVetorial(QGraphicsView):
    pendencia_escolhida = Signal(object)            # a Pendencia clicada (ou ativada com Enter)
    zoom_mudou = Signal(float)                       # aumento atual sobre o país inteiro
    uf_em_foco = Signal(object)                      # coroplético: UF sob o mouse (None ao sair)
    uf_clicada = Signal(str)                         # coroplético: UF clicada
    recorte_mudou = Signal(int, int)                 # (dentro, fora) do recorte, entre os ativos no ano
    na_vista_mudou = Signal(int)                     # pontos do recorte dentro da vista (legenda)
    ponto_focado = Signal(object)                    # Pendencia (ou o agregado) com o foco do teclado; None ao soltar
    ordem_mudou = Signal(list)                       # chaves das camadas, de cima para baixo
    tematica_mudou = Signal(str)                     # "faixa", "classe" ou "fase"
    agregacao_mudou = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cena = QGraphicsScene(self)
        self.setScene(self.cena)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Mapa dos casos")
        self.setAccessibleDescription(INSTRUCOES)
        self.marca_dagua = ""
        self.pontos: list[_Ponto] = []
        self.agregados: list[_Agregado] = []
        self._agregar = True                         # padrão no N2 e no N3 (montar volta a ligar)
        self._tematica = "faixa"
        self._corte = None
        self._versao = 0                             # muda a cada recorte, ano ou temática: refaz os agregados
        self._chave_agregados = None
        self.municipios: dict[tuple[str, str], _Regiao] = {}     # polígonos do coroplético municipal
        self.limites: dict[tuple[str, str], _Regiao] = {}        # contornos municipais (por zoom)
        self.nomes: list[QGraphicsSimpleTextItem] = []
        self.ufs: dict[str, _Regiao] = {}
        self.custodias: list[QGraphicsPathItem] = []
        self.camadas: dict[str, Camada] = {}
        self.legenda_dinamica = True
        self.municipios_forcados = False             # camada "Coroplético municipal" ligada pelo usuário
        self.legenda = LegendaMapa(self)
        self.zoom_com_ctrl = False                   # N1: a roda sozinha fica com a página; Ctrl + roda dá zoom
        self._aperto = None                          # onde o botão esquerdo apertou (clique ou arrasto, no soltar)
        self._escala_pais = 1.0
        self._limites_pais = QRectF()
        self._faixa_de = None
        self._foco: _Ponto | None = None
        self._densidade_item: QGraphicsPixmapItem | None = None
        self._escala_densidade = 0.0
        self._centro_densidade = QPointF()
        self._entradas: list[Entrada] = []
        self._dentro: frozenset[str] | None = None   # recorte do filtro (None = todas)
        self._modo_recorte = "esconder"
        self._contagem_municipal: dict[tuple[str, str], int] = {}
        self._faixa_municipal: tuple[int, int] | None = None     # (mínimo, máximo) do coroplético municipal
        self._dicas_uf: dict[str, str] = {}
        self._na_vista = 0
        self._derivadas = False
        self._legenda = QTimer(self)
        self._legenda.setSingleShot(True)
        self._legenda.setInterval(120)
        self._legenda.timeout.connect(self._recalcular_legenda)
        self._densidade = QTimer(self)
        self._densidade.setSingleShot(True)
        self._densidade.setInterval(200)
        self._densidade.timeout.connect(self._recalcular_densidade)

    # montagem
    def _nova_cena(self):
        self.soltar_foco()
        self.cena.clear()
        self.pontos, self.municipios, self.limites, self.nomes, self.ufs, self.custodias = [], {}, {}, [], {}, []
        self.agregados, self._chave_agregados, self._corte = [], None, None
        self._versao += 1
        self._densidade_item = None
        self._escala_densidade = 0.0
        self._dentro, self._modo_recorte = None, "esconder"
        self._contagem_municipal, self._dicas_uf, self._na_vista = {}, {}, 0
        self._faixa_municipal = None
        self._derivadas = False                      # só a cena de pontos (montar) tem camadas derivadas
        self.municipios_forcados = False
        self.camadas = {}
        for chave, (z, opacidade) in CAMADAS.items():
            camada = Camada(chave, z, opacidade)
            self.cena.addItem(camada)
            self.camadas[chave] = camada
        self.camadas["municipios"].setVisible(False)

    def _contorno(self, pais):
        caneta = QPen(QColor(sb.COR_CONTORNO_PAIS), 1.2)
        caneta.setCosmetic(True)
        contorno = self.cena.addPath(_caminho([pais]), caneta, QBrush(QColor(sb.FUNDO_MAPA)))
        contorno.setZValue(0)
        self._limites_pais = contorno.boundingRect()
        self._ajustar_area()

    def _ajustar_area(self):
        """A área do mapa é o país com uma vista inteira de folga de cada lado, medida no recuo máximo
        (ZOOM_MINIMO). Proporcional à janela, não fixa: no recuo máximo o país vai até a borda da vista, e o
        arrasto anda em qualquer zoom e em qualquer formato de janela."""
        escala = self._escala_pais * ZOOM_MINIMO            # pixels por unidade de cena no recuo máximo
        dx, dy = self.viewport().width() / escala, self.viewport().height() / escala
        self.cena.setSceneRect(self._limites_pais.adjusted(-dx, -dy, dx, dy))

    def montar(self, pais, divisas_uf: dict, municipios: dict, pendencias, faixa_de, custodias=(),
               rotulos_atividade: dict | None = None):
        """municipios: {uf: [Municipio]} (sinteticos.geografia); `faixa_de(p)` -> BAIXO..CRITICO;
        custodias: Custodia (com .tipo) ou tuplas antigas (nome, lon, lat, ocupação)."""
        self._nova_cena()
        self.legenda_dinamica = True
        self.setAccessibleName("Mapa dos casos")
        self.setAccessibleDescription(INSTRUCOES)
        self._agregar, self._tematica = True, "faixa"     # padrão a cada montagem (o painel acompanha)
        self._faixa_de = faixa_de
        self._contorno(pais)
        for uf, aneis in divisas_uf.items():
            regiao = _Regiao(_caminho(aneis), sb.COR_DIVISA_UF, 1.0, QColor(0, 0, 0, 0), QColor(52, 120, 180, 28), uf)
            regiao.setParentItem(self.camadas["ufs"])
            self.ufs[uf] = regiao
        for uf, lista in municipios.items():
            for m in lista:
                caminho = _caminho(m.aneis)
                # coroplético: preenchimento por quintil (a camada fica escondida até ser ligada)
                regiao = _Regiao(caminho, sb.COR_LIMITE_MUNICIPAL, 0.8, QColor(0, 0, 0, 0), QColor(210, 56, 79, 30),
                                 (uf, m.nome))
                regiao.setData(0, "MUNICIPIO")
                regiao.setParentItem(self.camadas["municipios"])
                self.municipios[(uf, m.nome)] = regiao
                # limite: só o contorno, aparece a partir de ZOOM_MUNICIPIOS
                limite = _Regiao(caminho, sb.COR_LIMITE_MUNICIPAL, 0.8, QColor(0, 0, 0, 0), QColor(210, 56, 79, 30),
                                 (uf, m.nome))
                limite.setParentItem(self.camadas["limites"])
                limite.setVisible(False)
                self.limites[(uf, m.nome)] = limite
                nome = QGraphicsSimpleTextItem(m.nome)
                nome.setFont(QFont("Segoe UI", 8))
                nome.setBrush(QBrush(QColor("#445044")))
                nome.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                nome.setPos(regiao.boundingRect().center())
                nome.setZValue(5)
                nome.setVisible(False)
                nome.setParentItem(self.camadas["limites"])
                self.nomes.append(nome)
        for p in pendencias:
            ponto = _Ponto(p, faixa_de(p), self.pendencia_escolhida.emit,
                           (rotulos_atividade or {}).get(p.atividade, ""))
            ponto.setPos(projetar(p.longitude, p.latitude))
            ponto.setParentItem(self.camadas["pendencias"])
            self.pontos.append(ponto)
        for c in custodias:
            nome, lon, lat, ocupacao = c[0], c[1], c[2], c[3]
            tipo = getattr(c, "tipo", "INTERMEDIARIO")
            icone = QGraphicsPathItem(sb.forma_custodia(tipo))
            icone.setBrush(QBrush(QColor(sb.cor_ocupacao(ocupacao))))
            icone.setPen(QPen(QColor(sb.COR_CONTORNO_CUSTODIA), 1.4))
            icone.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            icone.setPos(projetar(lon, lat))
            icone.setToolTip(f"{SIMBOLO[tipo]} {nome}\ncustódia {tipo.lower()} · ocupação {ocupacao:.0%}")
            icone.setData(0, f"CUSTODIA:{tipo}")
            icone.setData(1, nome)
            icone.setParentItem(self.camadas["custodias"])
            self.custodias.append(icone)
        self.camadas["densidade"].setVisible(False)
        self._derivadas = True
        self._atualizar_derivadas()                 # dicas e coroplético a partir dos pontos que contam
        self.ir_para_brasil()
        self.tematica_mudou.emit(self._tematica)
        self.agregacao_mudou.emit(self._agregar)

    def coropletico(self, pais, divisas_uf: dict, cores: dict, dicas: dict):
        """N1: só os polígonos das UFs pintados (cores {uf: QColor}); nenhum ponto na cena."""
        self._nova_cena()
        self._contorno(pais)
        for uf, aneis in divisas_uf.items():
            cor = cores.get(uf, QColor("#EEEEEE"))
            regiao = _Regiao(_caminho(aneis), "#5E6B5E", 1.0, cor, cor.darker(112), uf,
                             self.uf_em_foco.emit, self.uf_clicada.emit)
            regiao.setToolTip(dicas.get(uf, uf))
            regiao.setCursor(Qt.CursorShape.PointingHandCursor)
            regiao.setParentItem(self.camadas["ufs"])
            self.ufs[uf] = regiao
        self.legenda_dinamica = False
        self.setAccessibleName("Mapa coroplético por UF")
        zoom = ("Ctrl + roda dá zoom; arrastar move o mapa; + e − também dão zoom." if self.zoom_com_ctrl
                else "Roda do mouse ou + e − dão zoom; arrastar move o mapa.")
        self.setAccessibleDescription(f"Só totais por UF, sem pontos nem localização. {zoom} Os valores de cada UF "
                                      "estão na dica e na legenda de quintis.")
        self.ir_para_brasil()

    def pintar_ufs(self, cores: dict, dicas: dict | None = None):
        for uf, regiao in self.ufs.items():
            cor = cores.get(uf, QColor("#EEEEEE"))
            regiao.definir_preenchimento(cor, cor.darker(112))
            if dicas and uf in dicas:
                regiao.setToolTip(dicas[uf])

    def realcar_ufs(self, ufs: set | None):
        """Legenda de quintis: as UFs fora do conjunto ficam a 25% (None = todas normais)."""
        for uf, regiao in self.ufs.items():
            regiao.setOpacity(1.0 if not ufs or uf in ufs else 0.25)

    # camadas
    def definir_opacidade(self, chave: str, valor: float):
        if chave in self.camadas:
            self.camadas[chave].setOpacity(max(0.0, min(1.0, valor)))

    def definir_camada_visivel(self, chave: str, visivel: bool):
        if chave not in self.camadas:
            return
        if chave == "municipios":
            self.municipios_forcados = visivel
            self.camadas["municipios"].setVisible(visivel)
            self._colorir_municipios(visivel)
            self._atualizar_detalhe(emitir=False)
            return
        self.camadas[chave].setVisible(visivel)
        if chave == "densidade" and visivel:
            self._escala_densidade = 0.0
            self._recalcular_densidade()
        self._legenda.start()

    def camada_visivel(self, chave: str) -> bool:
        """Ligada pelo usuário (a de limites pode estar ligada e ainda não desenhada, longe demais)."""
        if chave == "municipios":
            return self.municipios_forcados
        return chave in self.camadas and self.camadas[chave].isVisible()

    def camada_desenhada(self, chave: str) -> bool:
        """Ligada E com algo desenhado nesta escala (os limites municipais só aparecem perto)."""
        if chave == "limites":
            return self.camada_visivel("limites") and bool(self.limites) and self.aumento >= ZOOM_MUNICIPIOS
        conteudo = {"ufs": self.ufs, "custodias": self.custodias, "pendencias": self.pontos,
                    "municipios": self.municipios}
        if chave in conteudo and not conteudo[chave]:
            return False                                # N2 sem custódias, N1 sem pontos: nada a explicar
        return self.camada_visivel(chave)

    @property
    def ordem_camadas(self) -> list[str]:
        """Chaves das camadas, de CIMA para baixo (z decrescente)."""
        return sorted(self.camadas, key=lambda c: -self.camadas[c].zValue())

    def definir_ordem(self, ordem) -> list[str]:
        """Ordem de desenho, de cima para baixo: a primeira chave recebe o maior z. Chaves que faltarem
        ficam por baixo, na ordem atual. O contorno do país (z 0) continua no fundo."""
        ordem = [c for c in ordem if c in self.camadas]
        ordem += [c for c in self.ordem_camadas if c not in ordem]
        for i, chave in enumerate(ordem):
            self.camadas[chave].setZValue(len(ordem) - i)
        self._legenda.start()
        self.ordem_mudou.emit(list(ordem))
        return ordem

    def _atualizar_derivadas(self):
        """Camadas derivadas: dicas das UFs e dos municípios e coroplético municipal contam só os
        pontos que entram nas contagens (ativos no ano do mapa e no recorte do filtro)."""
        if not self._derivadas:                       # coroplético do N1: as dicas vêm de fora (pintar_ufs)
            return
        por_uf, criticas, por_municipio = Counter(), Counter(), Counter()
        for ponto in self.pontos:
            if ponto.conta:
                p = ponto.pendencia
                por_uf[p.uf] += 1
                criticas[p.uf] += ponto.faixa == "CRITICO" and not ponto.vazado
                por_municipio[(p.uf, p.municipio)] += 1
        for uf, regiao in self.ufs.items():
            dica = f"{uf}: {_vocabulario.casos(por_uf[uf])}, {criticas[uf]} críticos"
            if self._dicas_uf.get(uf) != dica:
                regiao.setToolTip(dica)
                self._dicas_uf[uf] = dica
        anterior, self._contagem_municipal = self._contagem_municipal, dict(por_municipio)
        for chave, regiao in self.municipios.items():
            n = por_municipio[chave]
            if anterior.get(chave, -1) != n or not regiao.toolTip():
                dica = f"{chave[1]}/{chave[0]}: {_vocabulario.casos(n)}"
                regiao.setToolTip(dica)
                self.limites[chave].setToolTip(dica)
        if self.municipios_forcados:
            self._colorir_municipios(True)

    def _colorir_municipios(self, ligar: bool):
        from ecosec.interface.componentes.legenda_quantis import RAMPA, quintis
        if not ligar:
            for regiao in self.municipios.values():
                regiao.definir_preenchimento(QColor(0, 0, 0, 0), QColor(210, 56, 79, 30))
            return
        contagens = {k: n for k, n in self._contagem_municipal.items() if n}
        _, classe = quintis(contagens)
        self._faixa_municipal = (min(contagens.values()), max(contagens.values())) if contagens else None
        for chave, regiao in self.municipios.items():
            if chave in classe:
                cor = QColor(RAMPA[classe[chave]])
                cor.setAlpha(200)
                regiao.definir_preenchimento(cor, cor.darker(115))
            else:
                regiao.definir_preenchimento(QColor(0, 0, 0, 0), QColor(210, 56, 79, 30))
        self._legenda.start()

    def filtrar_custodias(self, tipos) -> int:
        """Mostra só as custódias dos tipos escolhidos (◇ □ △ ○). Devolve quantas ficaram visíveis."""
        tipos = set(tipos)
        visiveis = 0
        for icone in self.custodias:
            mostrar = icone.data(0).split(":")[1] in tipos
            icone.setVisible(mostrar)
            visiveis += mostrar
        self._legenda.start()
        return visiveis

    def atualizar_custodias(self, ocupacoes: dict):
        """Cor e dica de cada custódia pela ocupação {nome: fração} (linha do tempo do N3)."""
        for icone in self.custodias:
            nome = icone.data(1)
            if nome in ocupacoes:
                tipo = icone.data(0).split(":")[1]
                icone.setBrush(QBrush(QColor(sb.cor_ocupacao(ocupacoes[nome]))))
                icone.setToolTip(f"{SIMBOLO[tipo]} {nome}\ncustódia {tipo.lower()} · ocupação {ocupacoes[nome]:.0%}")

    def definir_ano(self, corte, so_ativas: bool = True) -> int:
        """Linha do tempo: só as pendências ATIVAS na data corte (None = todas), dentro do recorte do filtro.
        Com `so_ativas=False` (situação ENCERRADAS ou TODAS no filtro), basta a pendência existir no corte: o
        recorte decide sozinho, e as encerradas no corte aparecem vazadas. Devolve quantas entram nas
        contagens."""
        mudou_corte = corte != self._corte
        self._corte = corte
        for ponto in self.pontos:
            p = ponto.pendencia
            if mudou_corte:
                ponto.definir_fase(fases.fase(p, corte))
            if so_ativas:
                ponto.no_ano = corte is None or p.ativa(corte)
                ponto.definir_vazado(False)
            else:
                ponto.no_ano = corte is None or p.data_identificacao <= corte
                ponto.definir_vazado(p.data_encerramento is not None if corte is None else not p.ativa(corte))
        return self._reaplicar()

    # navegação
    @property
    def aumento(self) -> float:
        return self.transform().m11() / self._escala_pais if self._escala_pais else 1.0

    @property
    def escala(self) -> str:
        return [nome for limite, nome in ESCALAS if self.aumento >= limite][-1]

    def _enquadrar(self, retangulo: QRectF):
        animar_enquadramento(self, retangulo, ao_terminar=self._atualizar_detalhe)

    def ir_para_brasil(self):
        parar_enquadramento(self)                     # senão o próximo quadro da animação desfaz o recuo
        self.resetTransform()
        self.fitInView(self._limites_pais, Qt.AspectRatioMode.KeepAspectRatio)
        self._escala_pais = self.transform().m11() or 1.0
        self._ajustar_area()                          # a folga depende da escala do país
        self.centerOn(self._limites_pais.center())
        self._atualizar_detalhe()

    def ir_para_uf(self, uf: str):
        if uf in self.ufs:
            self._enquadrar(self.ufs[uf].boundingRect().adjusted(-30, -30, 30, 30))

    def ir_para_municipio(self, uf: str, municipio: str):
        regiao = self.municipios.get((uf, municipio))
        if regiao is not None:
            self._enquadrar(regiao.boundingRect().adjusted(-8, -8, 8, 8))

    def ir_para_ponto(self, lon: float, lat: float, largura: float = 120.0):
        centro = projetar(lon, lat)
        r = QRectF(0, 0, largura, largura * 0.7)
        r.moveCenter(centro)
        self._enquadrar(r)

    def aproximar(self, fator: float = 1.5):
        """Zoom de fator; um passo que passaria do limite para exatamente nele, para o mapa não parecer
        emperrado. Já além do limite (um enquadramento), não anda mais para fora."""
        atual = self.aumento
        alvo = atual * fator
        if fator > 1:
            alvo = min(alvo, max(ZOOM_MAXIMO, atual))
        else:
            alvo = max(alvo, min(ZOOM_MINIMO, atual))
        if abs(alvo / atual - 1) > 1e-9:
            parar_enquadramento(self)                 # a roda do mouse vence o enquadramento em curso
            self.scale(alvo / atual, alvo / atual)
            self._atualizar_detalhe()

    def _zoom_teclado(self, fator: float):
        """+ e −: zoom no centro da vista (o cursor pode estar em qualquer lugar); com um ponto focado, o ponto
        continua no centro."""
        ancora = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.aproximar(fator)
        self.setTransformationAnchor(ancora)
        if self._foco is not None:
            self.centerOn(self._foco)

    def wheelEvent(self, evento):
        if self.zoom_com_ctrl and not evento.modifiers() & Qt.KeyboardModifier.ControlModifier:
            evento.ignore()                           # a roda sozinha sobe para a página, que rola
            return
        self.aproximar(1.25 ** (evento.angleDelta().y() / 120))

    def mouseDoubleClickEvent(self, evento):
        self.aproximar(2.0)

    def mousePressEvent(self, evento):
        """Os itens não reagem ao apertar: o aperto inicia o arrasto em qualquer lugar; o clique sai do
        soltar (mouseReleaseEvent)."""
        self._aperto = evento.position() if evento.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(evento)

    def mouseReleaseEvent(self, evento):
        super().mouseReleaseEvent(evento)
        aperto, self._aperto = self._aperto, None
        if (aperto is not None and evento.button() == Qt.MouseButton.LeftButton
                and (evento.position() - aperto).manhattanLength() <= LIMIAR_CLIQUE_PX):
            self._clicar(aperto.toPoint())
        self._legenda.start()
        if self.camada_visivel("densidade"):
            self._densidade.start()

    def _clicar(self, pos):
        """O item de cima, onde o botão apertou, que reage ao clique (ponto, agregado ou UF do coroplético); os
        que não reagem (divisas, municípios, ponto atenuado) deixam o clique passar para o de baixo."""
        for item in self.items(pos):
            if (item.isVisible() and item.acceptedMouseButtons() & Qt.MouseButton.LeftButton
                    and hasattr(item, "clicar") and item.clicar()):
                return

    def scrollContentsBy(self, dx: int, dy: int):
        """Rolagem por arrasto, setas do teclado ou barras: a vista mudou, a legenda (e a densidade) também."""
        super().scrollContentsBy(dx, dy)
        if dx or dy:
            self._legenda.start()
            if self.camada_visivel("densidade"):
                self._densidade.start()

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        if self.aumento <= 1.05:                      # ainda no país inteiro: acompanha o tamanho da janela
            self.ir_para_brasil()
        else:
            self._ajustar_area()                      # a folga acompanha o tamanho da vista
        self.legenda.posicionar(QRectF(self.viewport().geometry()))

    def _atualizar_detalhe(self, emitir: bool = True):
        """Nível de detalhe: limites municipais e nomes só quando perto (o país inteiro ficaria poluído)."""
        mostrar_limites = self.aumento >= ZOOM_MUNICIPIOS
        mostrar_nomes = self.aumento >= ZOOM_NOMES
        for regiao in self.limites.values():
            regiao.setVisible(mostrar_limites)
        for nome in self.nomes:
            nome.setVisible(mostrar_nomes)
        self._recalcular_agregados()
        if self.camada_visivel("densidade"):
            self._densidade.start()
        self._legenda.start()
        if emitir:
            self.zoom_mudou.emit(self.aumento)

    # teclado e acessibilidade
    def event(self, evento):
        if (evento.type() == QEvent.Type.KeyPress and evento.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
                and not evento.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            avancar = evento.key() == Qt.Key.Key_Tab and not evento.modifiers() & Qt.KeyboardModifier.ShiftModifier
            if self.focar_proximo(avancar):
                evento.accept()
                return True
        return super().event(evento)

    def keyPressEvent(self, evento):
        tecla = evento.key()
        if tecla in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._zoom_teclado(FATOR_ZOOM_TECLADO)
        elif tecla in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self._zoom_teclado(1 / FATOR_ZOOM_TECLADO)
        elif tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._foco is not None:
            self._foco.ativar()
        elif tecla == Qt.Key.Key_Escape and self._foco is not None:
            self.soltar_foco()
        else:
            super().keyPressEvent(evento)
            return
        evento.accept()

    def focusInEvent(self, evento):
        super().focusInEvent(evento)
        self.viewport().update()

    def focusOutEvent(self, evento):
        super().focusOutEvent(evento)
        if evento.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason):
            self.soltar_foco()
        self.viewport().update()

    def pontos_focaveis(self) -> list:
        """Pontos soltos que contam e agregados cujo símbolo cruza a vista, de OESTE para LESTE (empate: norte
        primeiro, depois o código): ordem estável, que não depende da ordem de desenho."""
        vista = self.mapToScene(self.viewport().rect()).boundingRect()
        itens = self.cena.items(vista, Qt.ItemSelectionMode.IntersectsItemBoundingRect,
                                Qt.SortOrder.DescendingOrder, self.viewportTransform())
        focaveis = [i for i in itens if ((isinstance(i, _Ponto) and i.conta) or isinstance(i, _Agregado))
                    and i.isVisible() and i.parentItem() is not None and i.parentItem().isVisible()]
        return sorted(focaveis, key=lambda i: (round(i.pos().x(), 6), round(i.pos().y(), 6),
                                               i.pendencia.codigo if isinstance(i, _Ponto) else ""))

    def focar_proximo(self, avancar: bool = True) -> bool:
        """Tab / Shift+Tab. Devolve False quando a lista acaba (o foco sai do mapa: sem armadilha de teclado)."""
        lista = self.pontos_focaveis()
        if not lista:
            self.soltar_foco()
            return False
        if self._foco in lista:
            i = lista.index(self._foco) + (1 if avancar else -1)
            if not 0 <= i < len(lista):
                self.soltar_foco()
                return False
        else:
            i = 0 if avancar else len(lista) - 1
        self.focar(lista[i])
        return True

    def focar(self, ponto):
        """Foco do teclado num ponto solto ou num agregado (o mesmo anel duplo, o mesmo anúncio)."""
        if self._foco is not None and self._foco is not ponto:
            self._foco.definir_foco(False)
        self._foco = ponto
        ponto.definir_foco(True)
        self._anunciar(f"{ponto.nome_acessivel}. {ponto.descricao_acessivel}. {ponto.instrucao}")
        if self.isVisible():
            QToolTip.showText(self.viewport().mapToGlobal(self.mapFromScene(ponto.scenePos())), ponto.toolTip(),
                              self.viewport())
        self.ponto_focado.emit(getattr(ponto, "pendencia", ponto))

    def soltar_foco(self):
        if self._foco is None:
            return
        self._foco.definir_foco(False)
        self._foco = None
        QToolTip.hideText()
        self._anunciar(INSTRUCOES)
        self.ponto_focado.emit(None)

    @property
    def ponto_em_foco(self):
        """O item com o foco do teclado: um ponto solto, um agregado ou None."""
        return self._foco

    def _anunciar(self, descricao: str):
        self.setAccessibleDescription(descricao)
        try:
            QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.DescriptionChanged))
        except Exception:  # noqa: BLE001, sem leitor de tela ativo, nada a avisar
            pass

    # filtros
    def aplicar_recorte(self, dentro: frozenset[str] | None, modo: str = "esconder") -> int:
        """Recorte do filtro: dentro = códigos das pendências que passam (None = todas).

        Um ponto conta (legenda, dicas, coroplético, densidade, clique) se e somente se estiver ativo no ano do
        mapa (definir_ano) E no recorte. Modo "esconder" (padrão): os de fora somem. Modo "atenuar":
        os de fora ativos no ano ficam visíveis a 15% de opacidade, por baixo, sem clique e sem contar.
        Devolve quantos pontos contam; emite `recorte_mudou(dentro, fora)`."""
        if modo not in MODOS_RECORTE:
            raise ValueError(f"modo de recorte desconhecido: {modo!r}")
        self._dentro = None if dentro is None else frozenset(dentro)
        self._modo_recorte = modo
        for ponto in self.pontos:
            ponto.filtrado = self._dentro is None or ponto.pendencia.codigo in self._dentro
        return self._reaplicar()

    def _reaplicar(self) -> int:
        """Visibilidade de cada ponto e tudo que deriva dela (dicas, coroplético, densidade, legenda)."""
        for ponto in self.pontos:
            ponto.atualizar_visibilidade(self._modo_recorte)
        if isinstance(self._foco, _Ponto) and not self._foco.conta:
            self.soltar_foco()
        self._versao += 1
        self._recalcular_agregados()
        self._atualizar_derivadas()
        self._escala_densidade = 0.0
        if self.camada_visivel("densidade"):
            self._densidade.start()
        self._legenda.start()
        dentro, fora = self._dentro_fora()
        self.recorte_mudou.emit(dentro, fora)
        return dentro

    def _dentro_fora(self) -> tuple[int, int]:
        ativos = [ponto for ponto in self.pontos if ponto.no_ano]
        dentro = sum(ponto.filtrado for ponto in ativos)
        return dentro, len(ativos) - dentro

    @property
    def recorte(self) -> frozenset[str] | None:
        return self._dentro

    @property
    def modo_recorte(self) -> str:
        return self._modo_recorte

    @property
    def contagens(self) -> dict[str, int]:
        """Para a barra de filtros. Entre os ativos no ano: dentro (no recorte), fora (fora dele) e
        total = dentro + fora; na_vista = pontos do recorte cujo símbolo cruza a vista (como na legenda)."""
        dentro, fora = self._dentro_fora()
        return {"dentro": dentro, "fora": fora, "total": dentro + fora, "na_vista": self._na_vista}

    def pontos_visiveis(self) -> list:
        """Pontos que contam (ativos no ano E no recorte); no modo "atenuar" não inclui os atenuados."""
        return [ponto for ponto in self.pontos if ponto.conta]

    @property
    def contagem_municipal(self) -> dict[tuple[str, str], int]:
        return dict(self._contagem_municipal)

    def dica_uf(self, uf: str) -> str:
        return self.ufs[uf].toolTip() if uf in self.ufs else ""

    def filtrar(self, faixas=None, ufs=None, atividade: str | None = None) -> int:
        """Filtro antigo (faixa, UF, atividade), agora por cima de aplicar_recorte. Devolve quantos contam."""
        if not faixas and not ufs and not atividade:
            return self.aplicar_recorte(None)
        dentro = frozenset(
            ponto.pendencia.codigo for ponto in self.pontos
            if (not faixas or ponto.faixa in faixas) and (not ufs or ponto.pendencia.uf in ufs)
            and (not atividade or ponto.pendencia.atividade == atividade))
        return self.aplicar_recorte(dentro)

    # agregação por zoom e temática
    @property
    def agregacao(self) -> bool:
        return self._agregar

    def definir_agregacao(self, ligada: bool):
        """Liga ou desliga "Agrupar pontos" (ligado por padrão no N2 e no N3)."""
        ligada = bool(ligada)
        if ligada != self._agregar:
            self._agregar = ligada
            self._recalcular_agregados()
            self._legenda.start()
            self.agregacao_mudou.emit(ligada)

    @property
    def tematica(self) -> str:
        return self._tematica

    def definir_tematica(self, tematica: str):
        """Atributo da simbologia dos pontos e agregados: "faixa" (padrão), "classe" ou "fase"."""
        if tematica not in TEMATICAS:
            raise ValueError(f"temática desconhecida: {tematica!r}")
        if tematica == self._tematica:
            return
        self._tematica = tematica
        for ponto in self.pontos:
            ponto.definir_tematica(tematica)
        if isinstance(self._foco, _Ponto):
            self._anunciar(f"{self._foco.nome_acessivel}. {self._foco.descricao_acessivel}. {self._foco.instrucao}")
        self._versao += 1
        self._recalcular_agregados()
        self._recalcular_legenda()
        self.tematica_mudou.emit(tematica)

    def raio_agregacao(self) -> float:
        """Raio em pixels usado agora (0 = nada se agrega: desligado, sem pontos ou na escala de UF ou mais)."""
        if not self._agregar or not self._derivadas or self.aumento >= ZOOM_DESAGREGA - 1e-6:
            return 0.0
        return RAIO_AGREGACAO_PX

    def _recalcular_agregados(self):
        """Refaz os agregados se o zoom, o recorte, o ano, a temática ou o liga/desliga mudaram. Agrega só os
        pontos que contam (no ano e no filtro); a grade em pixels fica ancorada na origem da cena."""
        if not self._derivadas:
            return
        escala = self.transform().m11()
        raio = self.raio_agregacao()
        chave = (round(escala, 9) if raio else None, raio, self._versao)
        if chave == self._chave_agregados:
            return
        self._chave_agregados = chave
        if isinstance(self._foco, _Agregado):
            self.soltar_foco()
        for agregado in self.agregados:
            self.cena.removeItem(agregado)
        self.agregados = []
        agrupados = set()
        if raio:
            candidatos = [pt for pt in self.pontos if pt.conta]
            grupos = agrupar([(pt.pos().x() * escala, pt.pos().y() * escala) for pt in candidatos], raio)
            camada = self.camadas["pendencias"]
            soltos = [candidatos[g[0]] for g in grupos if len(g) == 1]
            novos = [_Agregado([candidatos[i] for i in g], self._tematica, self.aproximar_agregado)
                     for g in grupos if len(g) > 1]
            for agregado, posicao in zip(novos, self._ancoras(novos, soltos, escala)):
                agregado.setPos(posicao)
                agregado.setParentItem(camada)
                self.agregados.append(agregado)
                agrupados.update(id(m) for m in agregado.membros)
        for ponto in self.pontos:
            ponto.definir_agrupado(id(ponto) in agrupados)
        if isinstance(self._foco, _Ponto) and self._foco.agrupado:
            self.soltar_foco()

    def _ancoras(self, agregados, soltos, escala: float) -> list[QPointF]:
        """Onde desenhar cada agregado: na SEMENTE (o membro mais denso). Duas sementes ficam a mais de
        RAIO_AGREGACAO_PX uma da outra e o agregado tem raio externo de no máximo metade disso, então nada se
        sobrepõe. Exceção: se uma custódia (desenhada por cima, na ordem padrão) cobrir a contagem, o agregado vai
        para o membro mais perto da semente que fique livre da custódia sem encostar em outro agregado ou ponto
        solto; se nenhum servir, fica na semente. Sempre na posição de um membro."""
        def px(item):
            return item.pos().x() * escala, item.pos().y() * escala

        def dist(a, b):
            return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

        custodias = [px(c) for c in self.custodias]
        posicoes = [px(a.membros[0]) for a in agregados]
        raios = [a.simbolo.raio_externo for a in agregados]
        outros = [(px(pt), pt.simbolo.raio_externo) for pt in soltos]
        for k, agregado in enumerate(agregados):
            folga = raios[k] + 9.0                    # custódia: até 8 px de meia largura, mais 1 px
            if not custodias or min(dist(posicoes[k], c) for c in custodias) >= folga:
                continue
            semente = posicoes[k]

            def livre(p):
                return (min(dist(p, c) for c in custodias) >= folga
                        and all(dist(p, posicoes[j]) >= raios[k] + raios[j] for j in range(len(agregados)) if j != k)
                        and all(dist(p, q) >= raios[k] + r for q, r in outros))

            candidatos = [px(m) for m in sorted(agregado.membros[1:], key=lambda m: dist(px(m), semente))]
            # sem membro livre: encostado por fora da custódia que atrapalha, na direção mais perto da semente
            cx, cy = min(custodias, key=lambda c: dist(c, semente))
            tangentes = [(cx + (folga + 0.5) * cos(radians(a)), cy + (folga + 0.5) * sin(radians(a)))
                         for a in range(0, 360, 15)]
            candidatos += sorted(tangentes, key=lambda p: dist(p, semente))
            posicoes[k] = next((p for p in candidatos if livre(p)), semente)
        return [QPointF(x / escala, y / escala) for x, y in posicoes]

    def aproximar_agregado(self, agregado: _Agregado):
        """Clique ou Enter no agregado: enquadra os membros, aproximando pelo menos 2× e no máximo até
        ZOOM_MAXIMO_AGREGADO (ou 2×, se já estiver além), para o agregado sempre se desfazer ou se dividir."""
        membros = agregado.retangulo_membros()
        vp = self.viewport().rect()
        atual = self.transform().m11()
        cabe = min(vp.width() / max(membros.width(), 1e-6), vp.height() / max(membros.height(), 1e-6)) * 0.8
        teto = max(2 * atual, self._escala_pais * ZOOM_MAXIMO_AGREGADO)
        alvo = max(2 * atual, min(cabe, teto))
        retangulo = QRectF(0, 0, vp.width() / alvo, vp.height() / alvo)
        retangulo.moveCenter(membros.center())
        self._enquadrar(retangulo)

    def resumo_agregacao(self) -> dict[str, int]:
        """Para conferência: agregados e pontos soltos desenhados, pontos que contam e a soma das contagens."""
        soltos = sum(pt.conta and pt.isVisible() for pt in self.pontos)
        agregados = sum(a.isVisible() for a in self.agregados)
        em_agregados = sum(a.n for a in self.agregados)
        return {"agregados": agregados, "soltos": soltos, "desenhados": agregados + soltos,
                "pontos": len(self.pontos_visiveis()), "soma": em_agregados + soltos}

    # densidade (KDE)
    def _recalcular_densidade(self):
        """KDE gaussiana ponderada pela pontuação de criticidade, numa grade do tamanho da vista (metade da
        resolução). O raio do kernel é fixo em pixels de tela: acompanha o zoom. Rampa azul."""
        if not self.camada_visivel("densidade") or not self.pontos:
            return
        vista = self.mapToScene(self.viewport().rect()).boundingRect()
        if (self._escala_densidade and 0.5 < self.transform().m11() / self._escala_densidade < 2.0
                and (vista.center() - self._centro_densidade).manhattanLength() < vista.width() * 0.25):
            return
        largura, altura = max(1, self.viewport().width() // 2), max(1, self.viewport().height() // 2)
        grade = np.zeros((altura, largura), np.float32)
        for ponto in self.pontos:
            if not ponto.conta:                       # atenuados (fora do recorte) não pesam na densidade
                continue
            pos = ponto.pos()
            x = int((pos.x() - vista.left()) / vista.width() * largura)
            y = int((pos.y() - vista.top()) / vista.height() * altura)
            if 0 <= x < largura and 0 <= y < altura:
                grade[y, x] += 1 + FAIXAS.index(ponto.faixa)          # peso: faixa de criticidade
        grade = cv2.GaussianBlur(grade, (0, 0), 14)
        maximo = float(grade.max())
        camada = self.camadas["densidade"]
        if self._densidade_item is not None:
            self.cena.removeItem(self._densidade_item)
            self._densidade_item = None
        if maximo <= 0:
            return
        norma = np.clip(grade / maximo, 0, 1)
        cores = sb.tabela_densidade()[(norma * 255).astype(np.uint8)]           # RGB
        rgba = np.ascontiguousarray(np.dstack([cores, (np.sqrt(norma) * 230).astype(np.uint8)]))
        imagem = QImage(rgba.data, largura, altura, 4 * largura, QImage.Format.Format_RGBA8888).copy()
        item = QGraphicsPixmapItem(QPixmap.fromImage(imagem))
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setPos(vista.topLeft())
        item.setScale(vista.width() / largura)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setData(0, "DENSIDADE")
        item.setParentItem(camada)
        self._densidade_item = item
        self._escala_densidade = self.transform().m11()
        self._centro_densidade = vista.center()

    # legenda dinâmica
    def _recalcular_legenda(self):
        if not self.legenda_dinamica:
            self._entradas = []
            self.legenda.definir([])
            return
        contagem = self._contar_na_vista()
        na_vista = sum(contagem[f"FAIXA:{faixa}"] for faixa in FAIXAS) + contagem["VAZADO"]
        entradas = [Entrada("", "ESCALA", "Legenda", f"vista: {self.escala.lower()}", titulo=True)]
        secoes = {"pendencias": self._legenda_pendencias, "custodias": self._legenda_custodias,
                  "densidade": self._legenda_densidade, "municipios": self._legenda_coropletico,
                  "limites": self._legenda_limites, "ufs": self._legenda_ufs}
        for chave in self.ordem_camadas:                       # a camada de cima primeiro, como no desenho
            if chave in secoes and self.camada_desenhada(chave):
                entradas += secoes[chave](contagem, na_vista)
        self._entradas = entradas
        self.legenda.definir(entradas)
        self.legenda.posicionar(QRectF(self.viewport().geometry()))
        if na_vista != self._na_vista:
            self._na_vista = na_vista
            self.na_vista_mudou.emit(na_vista)
        self.viewport().update()

    def _legenda_pendencias(self, contagem: Counter, na_vista: int) -> list[Entrada]:
        """Com a situação Todos, os encerrados aparecem no mapa. Na temática de faixa
        eles têm linha própria (contorno cinza) e não entram nas faixas, que contam só os ativos (a faixa de um caso
        encerrado não é risco atual); o título soma ativos e encerrados. Na de classe, o encerrado continua na sua
        classe (a classe vale para ele) e a linha diz isso; na de fase, a Encerrada já é uma fase."""
        t = self._tematica
        titulo = "Casos na vista" + ("" if t == "faixa" else f", por {sb.NOME_TEMATICA[t].lower()}")
        entradas = [Entrada("pendencias", "PENDÊNCIAS NA VISTA", titulo, str(na_vista), titulo=True)]
        prefixo = {"faixa": "FAIXA", "classe": "CLASSE", "fase": "FASE"}[t]
        if t == "faixa" and contagem["VAZADO"]:
            ativos = sum(contagem[f"FAIXA:{faixa}"] for faixa in FAIXAS)
            entradas.append(Entrada("pendencias", "ATIVOS POR FAIXA", "Ativos, por faixa de risco", str(ativos)))
        for categoria in sb.categorias(t):
            n = contagem[f"{prefixo}:{categoria}"]
            if n:
                chave = f"● {categoria}" if t == "faixa" else f"{prefixo}:{categoria}"
                entradas.append(Entrada("pendencias", chave, sb.rotulo_categoria(t, categoria), str(n),
                                        sb.simbolo_categoria(t, categoria)))
        if contagem["VAZADO"] and t != "fase":           # na fase, a ENCERRADA já é uma categoria
            entradas.append(Entrada("pendencias", "○ ENCERRADAS",
                                    "Encerrados (fora das faixas)" if t == "faixa" else "Encerrados (já nas classes)",
                                    str(contagem["VAZADO"]),
                                    sb.simbolo_faixa("MEDIO", vazado=True) if t == "faixa"
                                    else sb.Simbolo("ponto", sb.COR_ENCERRADO, sb.RAIO_FAIXA["MEDIO"], vazado=True)))
        if contagem["AGREGADO"]:
            entradas.append(Entrada("pendencias", "AGREGADO", "Agrupamento (número = casos)",
                                    f"{contagem['AGREGADO']} na vista", sb.simbolo_agregado_legenda(t)))
            cinza = " (cinza = encerrados)" if t == "faixa" and contagem["VAZADO"] else ""
            entradas.append(Entrada("pendencias", "ANEL DO AGREGADO",
                                    f"anel: composição por {sb.NOME_TEMATICA[t].lower()}{cinza}"))
        if self._dentro is not None:
            dentro, fora = self._dentro_fora()
            atenuar = self._modo_recorte == "atenuar"
            entradas.append(Entrada("pendencias", "FILTRO NO MAPA TODO", "Filtro, no mapa todo", "", titulo=True))
            entradas.append(Entrada("pendencias", "DENTRO DO FILTRO", "Dentro do filtro", str(dentro)))
            entradas.append(Entrada("pendencias", "FORA DO FILTRO",
                                    "Fora do filtro (atenuado)" if atenuar else "Fora do filtro (oculto)", str(fora),
                                    sb.Simbolo("ponto", sb.COR_TEXTO_SECUNDARIO, sb.RAIO_FAIXA["MEDIO"], atenuado=True)
                                    if atenuar else None))
        return entradas

    def _legenda_custodias(self, contagem: Counter, na_vista: int) -> list[Entrada]:
        total = sum(contagem[f"CUSTODIA:{tipo}"] for tipo in SIMBOLO)
        entradas = [Entrada("custodias", "CUSTÓDIAS NA VISTA", "Custódias na vista", str(total), titulo=True)]
        for tipo in SIMBOLO:
            n = contagem[f"CUSTODIA:{tipo}"]
            if n:
                entradas.append(Entrada("custodias", f"{SIMBOLO[tipo]} {tipo}",
                                        _vocabulario.ROTULO_CUSTODIA.get(tipo, tipo), str(n),
                                        sb.simbolo_custodia(tipo, "#FFFFFF")))
        entradas.append(Entrada("custodias", "OCUPAÇÃO", "Ocupação (cor)", ", ".join(sb.ROTULOS_OCUPACAO),
                                sb.Simbolo("caixas", cores=sb.COR_OCUPACAO)))
        return entradas

    def _legenda_densidade(self, contagem: Counter, na_vista: int) -> list[Entrada]:
        return [Entrada("densidade", "▒ DENSIDADE", "Densidade (score de risco)", "baixa a alta",
                        sb.Simbolo("rampa", cores=sb.RAMPA_DENSIDADE))]

    def _legenda_coropletico(self, contagem: Counter, na_vista: int) -> list[Entrada]:
        from ecosec.interface.componentes.legenda_quantis import RAMPA
        faixa = self._faixa_municipal
        valor = (f"{faixa[0]} a {faixa[1]}" if faixa and faixa[0] != faixa[1] else str(faixa[0]) if faixa
                 else "nenhuma")
        return [Entrada("municipios", "PENDÊNCIAS POR MUNICÍPIO", "Casos por município", valor,
                        sb.Simbolo("rampa", cores=RAMPA))]

    def _legenda_limites(self, contagem: Counter, na_vista: int) -> list[Entrada]:
        return [Entrada("limites", "LIMITE MUNICIPAL", "Limite municipal", "",
                        sb.Simbolo("linha", sb.COR_LIMITE_MUNICIPAL, espessura=1.2))]

    def _legenda_ufs(self, contagem: Counter, na_vista: int) -> list[Entrada]:
        return [Entrada("ufs", "DIVISA DE UF", "Divisa de UF", "", sb.Simbolo("linha", sb.COR_DIVISA_UF, espessura=1.4))]

    def _contar_na_vista(self) -> Counter:
        """Itens da legenda cujo símbolo cruza a vista. Pontos e custódias ignoram o zoom
        (ItemIgnoresTransformations): sem a transformação do dispositivo, o retângulo deles seria tomado em
        unidades de cena e, em zoom alto, pontos fora da tela entrariam na conta."""
        vista = self.mapToScene(self.viewport().rect()).boundingRect()
        vt = self.viewportTransform()
        contagem = Counter()
        for item in self.cena.items(vista, Qt.ItemSelectionMode.IntersectsItemBoundingRect,
                                    Qt.SortOrder.DescendingOrder, vt):
            chave = item.data(0)
            if (not chave or isinstance(item, _Ponto) or not item.isVisible() or item.parentItem() is None
                    or not item.parentItem().isVisible()):
                continue
            contagem[chave] += 1                                   # custódias e agregados
        # pontos: contam pela posição do próprio símbolo, desenhado solto ou escondido num agregado; os
        # atenuados (fora do recorte) não contam
        if self.pontos and self.camadas["pendencias"].isVisible():
            retangulo = QRectF(self.viewport().rect())
            for ponto in self.pontos:
                if not ponto.conta or not ponto.deviceTransform(vt).mapRect(ponto.boundingRect()).intersects(
                        retangulo):
                    continue
                if ponto.vazado:                           # encerrado: fora das faixas (sem risco atual)
                    contagem["VAZADO"] += 1
                else:
                    contagem[f"FAIXA:{ponto.faixa}"] += 1
                contagem[f"CLASSE:{ponto.pendencia.classe_risco}"] += 1
                contagem[f"FASE:{ponto.fase}"] += 1
        return contagem

    @property
    def entradas_legenda(self) -> list[Entrada]:
        return list(self._entradas)

    @property
    def linhas_legenda(self) -> list[tuple[str, str]]:
        """(chave, valor) de cada entrada (ex.: ("● CRITICO", "120"))."""
        return [(e.chave, e.valor) for e in self._entradas]

    # barra de escala
    def barra_escala(self) -> tuple[float, float, float]:
        """(km, pixels, latitude do centro) da barra: o maior comprimento redondo que cabe em
        BARRA_ESCALA_MAX_PX (ou 1/4 da largura), medido na latitude do centro da vista."""
        escala_cena = self.transform().m11()
        if escala_cena <= 0:
            return 0.0, 0.0, 0.0
        centro = self.mapToScene(self.viewport().rect().center())
        lat = desprojetar(QPointF(centro))[1]
        lat = max(-85.0, min(85.0, lat))
        kpp = km_por_pixel(escala_cena, lat)
        maximo = min(BARRA_ESCALA_MAX_PX, max(40, self.viewport().width() // 4))
        km = distancia_redonda(maximo * kpp)
        return km, km / kpp if kpp else 0.0, lat

    def _desenhar_barra_escala(self, painter: QPainter, largura: int, altura: int):
        km, px, _ = self.barra_escala()
        if km <= 0 or px < 8:
            return
        fonte = QFont("Segoe UI")
        fonte.setPixelSize(11)
        painter.setFont(fonte)
        texto = _texto_km(km)
        largura_texto = painter.fontMetrics().horizontalAdvance(texto)
        caixa = QRectF(0, 0, max(px, largura_texto) + 20, 34)
        caixa.moveBottomRight(QPointF(largura - 10, altura - 10))
        painter.setPen(QPen(QColor(0, 0, 0, 70)))
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawRoundedRect(caixa, 4, 4)
        x0 = caixa.left() + (caixa.width() - px) / 2
        y = caixa.bottom() - 9
        metade = px / 2
        painter.setPen(QPen(QColor(sb.COR_TEXTO), 1))
        painter.setBrush(QColor(sb.COR_TEXTO))
        painter.drawRect(QRectF(x0, y - 4, metade, 4))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRect(QRectF(x0 + metade, y - 4, metade, 4))
        painter.setPen(QColor(sb.COR_TEXTO))
        painter.drawText(QRectF(caixa.left(), caixa.top() + 3, caixa.width(), 14), Qt.AlignmentFlag.AlignHCenter,
                         texto)

    # marca d'água, escala e foco (na tela)
    def drawForeground(self, painter: QPainter, retangulo: QRectF):
        painter.save()
        painter.resetTransform()                      # em pixels da tela, não da cena
        largura, altura = self.viewport().width(), self.viewport().height()
        if self.marca_dagua:
            painter.save()
            painter.setPen(QColor(120, 120, 120, 38))
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
            painter.translate(largura / 2, altura / 2)
            painter.rotate(-28)
            passo_x, passo_y = 420, 120
            for y in range(-altura, altura, passo_y):
                for x in range(-largura, largura, passo_x):
                    painter.drawText(x + (y // passo_y % 2) * passo_x // 2, y, self.marca_dagua)
            painter.restore()
        if not self._limites_pais.isEmpty():
            self._desenhar_barra_escala(painter, largura, altura)
        if self.hasFocus() and self._foco is None:     # foco do teclado no mapa (sem ponto focado)
            painter.setPen(QPen(QColor("#0B2C66"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(1, 1, largura - 2, altura - 2))
        painter.restore()
