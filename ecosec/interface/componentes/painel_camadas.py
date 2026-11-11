"""Painel de camadas do mapa.

Cada camada com o símbolo ao lado do nome (o mesmo da legenda, desenhado por `simbologia`), uma caixa de
ligar/desligar (também para as divisas das UFs), opacidade opcional e botões de subir e descer que mudam a
ORDEM de desenho (z-value) no mapa. As linhas aparecem na ordem de desenho: a de cima é desenhada por cima.

Vertical (N3, na coluna lateral, com opacidade) ou horizontal (N2, numa faixa acima do mapa, que quebra a
linha se faltar largura). O painel só conversa com a API pública do mapa (`definir_camada_visivel`,
`definir_opacidade`, `definir_ordem`, `ordem_camadas`, `ordem_mudou`).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ecosec.interface.componentes import simbologia as sb
from ecosec.interface.fluent import FIF, CaptionLabel, CheckBox, FlowLayout, Slider, TransparentToolButton


def simbolos_camada(chave: str, tematica: str = "faixa") -> list[sb.Simbolo]:
    """Símbolos representativos de cada camada (ícone do painel), os mesmos que a legenda desenha. Pendências:
    os extremos da temática atual (faixa: BAIXO e crítico; classe: área e rejeito; fase: identificação e
    remediação)."""
    from ecosec.interface.componentes.legenda_quantis import RAMPA
    cats = sb.categorias(tematica)
    extremos = {"faixa": ("BAIXO", "CRITICO"), "classe": (cats[0], cats[-1]), "fase": (cats[0], cats[2])}[tematica]
    return {
        "pendencias": [sb.simbolo_categoria(tematica, c) for c in extremos],
        "custodias": [sb.simbolo_custodia("DEFINITIVO", sb.COR_OCUPACAO[0])],
        "densidade": [sb.Simbolo("rampa", cores=sb.RAMPA_DENSIDADE)],
        "municipios": [sb.Simbolo("rampa", cores=RAMPA)],
        "limites": [sb.Simbolo("linha", sb.COR_LIMITE_MUNICIPAL, espessura=1.2)],
        "ufs": [sb.Simbolo("linha", sb.COR_DIVISA_UF, espessura=1.4)],
    }.get(chave, [])


class _LinhaCamada(QWidget):
    def __init__(self, painel, chave: str, nome: str, horizontal: bool, com_opacidade: bool, opacidade: float):
        super().__init__()
        self.chave = chave
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.subir = TransparentToolButton(FIF.LEFT_ARROW if horizontal else FIF.UP)
        self.descer = TransparentToolButton(FIF.RIGHT_ARROW if horizontal else FIF.DOWN)
        for botao, texto, passo in ((self.subir, "Subir", -1), (self.descer, "Descer", 1)):
            botao.setFixedSize(22, 24)
            botao.setIconSize(QSize(10, 10))
            botao.setToolTip(f"{texto} {nome} na ordem de desenho"
                             + (" (à esquerda = por cima)" if horizontal else " (em cima = por cima)"))
            botao.setAccessibleName(f"{texto} a camada {nome}")
            botao.clicked.connect(lambda *_, p=passo: painel.mover(chave, p))
        self.icone = QLabel()
        self.icone.setPixmap(sb.icone(simbolos_camada(chave)).pixmap(30, 18))
        self.icone.setFixedSize(30, 18)
        self.icone.setAccessibleName(f"Símbolo de {nome}")
        self.caixa = CheckBox(nome)
        self.caixa.setAccessibleName(f"Camada {nome}")
        self.caixa.setAccessibleDescription("Liga ou desliga a camada no mapa")
        self.caixa.stateChanged.connect(lambda *_: painel.mapa.definir_camada_visivel(chave, self.caixa.isChecked()))
        self.caixa.setMinimumWidth(self.caixa.sizeHint().width())          # o nome nunca é cortado
        self.opacidade = None
        if horizontal:
            for w in (self.icone, self.caixa, self.subir, self.descer):
                h.addWidget(w)
        else:
            h.addWidget(self.subir)
            h.addWidget(self.descer)
            h.addWidget(self.icone)
            h.addWidget(self.caixa, 1)
        if com_opacidade:
            self.opacidade = Slider(Qt.Orientation.Horizontal)
            self.opacidade.setRange(0, 100)
            self.opacidade.setValue(int(100 * opacidade))
            self.opacidade.setFixedWidth(68)
            self.opacidade.setAccessibleName(f"Opacidade de {nome}")
            self.opacidade.valueChanged.connect(lambda valor: painel.mapa.definir_opacidade(chave, valor / 100))
            h.addWidget(self.opacidade)


class PainelCamadas(QWidget):
    def __init__(self, mapa, chaves, horizontal: bool = False, com_opacidade: bool = False, titulo: str = "",
                 parent=None):
        from ecosec.interface.mapa_vetorial import CAMADAS, NOME_CAMADA
        super().__init__(parent)
        self.mapa, self.chaves, self.horizontal = mapa, tuple(chaves), horizontal
        self.setAccessibleName("Camadas do mapa")
        self.linhas: dict[str, _LinhaCamada] = {}
        for chave in self.chaves:
            self.linhas[chave] = _LinhaCamada(self, chave, NOME_CAMADA[chave], horizontal, com_opacidade,
                                              CAMADAS[chave][1])
        self.caixas = {c: linha.caixa for c, linha in self.linhas.items()}
        self.opacidades = {c: linha.opacidade for c, linha in self.linhas.items() if linha.opacidade is not None}
        if horizontal:
            self._layout = FlowLayout(self)
            self._layout.setContentsMargins(0, 0, 0, 0)
            self._layout.setHorizontalSpacing(14)
            self._layout.setVerticalSpacing(2)
            if titulo:
                self._titulo = CaptionLabel(titulo)
                self._titulo.setFixedHeight(24)                            # alinhado ao meio das linhas
                self._titulo.setAlignment(Qt.AlignmentFlag.AlignVCenter)
                self._layout.addWidget(self._titulo)
        else:
            self._layout = QVBoxLayout(self)
            self._layout.setContentsMargins(0, 0, 0, 0)
            self._layout.setSpacing(2)
        self._dispor()
        mapa.ordem_mudou.connect(lambda *_: self._dispor())
        if hasattr(mapa, "tematica_mudou"):
            mapa.tematica_mudou.connect(self._tematica_mudou)

    def _tematica_mudou(self, tematica: str):
        """O ícone das pendências acompanha a temática (o mesmo símbolo do mapa e da legenda)."""
        if "pendencias" in self.linhas:
            self.linhas["pendencias"].icone.setPixmap(
                sb.icone(simbolos_camada("pendencias", tematica)).pixmap(30, 18))

    def ordem(self) -> list[str]:
        """As camadas do painel na ordem de desenho do mapa (a de cima primeiro)."""
        return [c for c in self.mapa.ordem_camadas if c in self.linhas]

    def mover(self, chave: str, passo: int):
        """Troca a camada com a vizinha DO PAINEL (camadas que o painel não mostra ficam onde estão)."""
        sub = self.ordem()
        i = sub.index(chave)
        j = i + passo
        if not 0 <= j < len(sub):
            return
        sub[i], sub[j] = sub[j], sub[i]
        resto = iter(sub)
        self.mapa.definir_ordem([next(resto) if c in self.linhas else c for c in self.mapa.ordem_camadas])

    def _dispor(self):
        ordem = self.ordem()
        if not ordem:
            return
        for linha in self.linhas.values():
            self._layout.removeWidget(linha)
        for i, chave in enumerate(ordem):
            linha = self.linhas[chave]
            self._layout.addWidget(linha)
            linha.subir.setEnabled(i > 0)
            linha.descer.setEnabled(i < len(ordem) - 1)
        self._layout.invalidate()

    def definir_ligadas(self, ligadas):
        """Estado inicial das caixas, sem emitir (o mapa recém-montado já está nesse estado)."""
        from ecosec.interface.mapa_vetorial import CAMADAS
        for chave, caixa in self.caixas.items():
            caixa.blockSignals(True)
            caixa.setChecked(chave in ligadas)
            caixa.blockSignals(False)
            if chave in self.opacidades:
                self.opacidades[chave].setValue(int(100 * CAMADAS[chave][1]))
        self._dispor()
