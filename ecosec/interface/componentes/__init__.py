"""Componentes reutilizados pelas telas.

FaixaCamadas: mostra as camadas que o nível exige e o estado de cada uma
(pendente, em avaliação, aprovada, negada). A lista vem do serviço, que a tira
da mesma função que a política usa: a tela nunca anuncia uma camada que a
decisão não exige.

ChecklistSenha: as exigências de senha marcadas enquanto se digita. A lista
vem da mesma função que valida o formulário: a tela nunca marca ✓ num item
que o cadastro depois recusaria.

Selo: etiqueta arredondada colorida (situação, papel).

ColunasResponsivas: a tabela se adapta à largura da janela, ocultando as
colunas menos importantes antes de cortar as que importam.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QVBoxLayout, QWidget

from ecosec.interface.estilo import VERDE, VERMELHO, cor_borda, cor_texto_secundario
from ecosec.interface.fluent import BodyLabel, CaptionLabel, themeColor


class FaixaCamadas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._chips: dict = {}

    def definir(self, camadas):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().hide()          # deleteLater só apaga no próximo ciclo
                item.widget().deleteLater()
        self._chips = {}
        for camada in camadas:
            chip = CaptionLabel(f"{camada.codigo}  {camada.nome}")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setToolTip(camada.pergunta)
            chip.setMinimumHeight(30)
            self._chips[camada] = chip
            self._layout.addWidget(chip, 1)
        self.atualizar(frozenset(), None, None)

    def atualizar(self, aprovadas, atual, negada):
        destaque = themeColor().name()
        for camada, chip in self._chips.items():
            if camada == negada:
                fundo, borda, texto, marca = VERMELHO, VERMELHO, "white", "✗ "
            elif camada in aprovadas:
                fundo, borda, texto, marca = VERDE, VERDE, "white", "✓ "
            elif camada == atual:
                fundo, borda, texto, marca = "transparent", destaque, destaque, "● "
            else:
                fundo, borda, texto, marca = "transparent", cor_borda(), cor_texto_secundario(), ""
            chip.setText(f"{marca}{camada.codigo}  {camada.nome}")
            peso = "600" if camada == atual or camada == negada else "normal"
            chip.setStyleSheet(f"QLabel {{ background:{fundo}; border:1px solid {borda}; color:{texto};"
                               f" border-radius:15px; padding:2px 10px; font-weight:{peso}; }}")


class ChecklistSenha(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._linhas: list[CaptionLabel] = []

    def atualizar(self, requisitos: list[tuple[str, bool]]):
        while len(self._linhas) < len(requisitos):
            linha = CaptionLabel(self)
            self._layout.addWidget(linha)
            self._linhas.append(linha)
        for linha, (descricao, cumprido) in zip(self._linhas, requisitos):
            linha.setText(("✓  " if cumprido else "•  ") + descricao)
            cor = VERDE if cumprido else cor_texto_secundario()
            linha.setStyleSheet(f"color:{cor};")
        for sobra in self._linhas[len(requisitos):]:
            sobra.setText("")

    @property
    def tudo_cumprido(self) -> bool:
        return all(l.text().startswith("✓") for l in self._linhas if l.text())


def camadas_avaliadas(vereditos) -> str:
    """Só a camada e o resultado, sem o motivo técnico (que fica na trilha).
    Na tela de login, USUARIO_INEXISTENTE ao lado de SENHA_INCORRETA revelaria
    quais matrículas existem; a mensagem principal já explica em linguagem simples."""
    if not vereditos:
        return ""
    return "Camadas avaliadas: " + "  ".join(f"{v.camada.codigo} {'✓' if v.aprovado else '✗'}" for v in vereditos)


def linha_rotulada(rotulo: str, campo: QWidget, ajuda: str | None = None) -> QWidget:
    """Rótulo acima do campo, com ajuda opcional abaixo: o formato de todos os formulários."""
    caixa = QWidget()
    v = QVBoxLayout(caixa)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    v.addWidget(BodyLabel(rotulo))
    v.addWidget(campo)
    if ajuda:
        dica = CaptionLabel(ajuda)
        dica.setWordWrap(True)
        dica.setStyleSheet(f"color:{cor_texto_secundario()};")
        v.addWidget(dica)
    return caixa


class ColunasResponsivas(QObject):
    """Larguras de tabela que se adaptam à janela.

    Uma coluna é elástica (fica com a sobra; ex.: o nome) e tem largura
    mínima. As demais têm largura fixa (o cabeçalho do Fluent tem espaçamento
    interno que o ajuste automático ignora, e cortava títulos). Quando a tabela
    estreita, ocultam-se primeiro as colunas de `ocultaveis`, na ordem dada,
    em vez de espremer a elástica até cortar o texto que importa."""

    def __init__(self, tabela, larguras: dict[int, int], elastica: int, minima_elastica: int,
                 ocultaveis: tuple[int, ...] = ()):
        super().__init__(tabela)
        self.tabela, self.larguras, self.elastica = tabela, larguras, elastica
        self.minima, self.ocultaveis = minima_elastica, ocultaveis
        cabecalho = tabela.horizontalHeader()
        for coluna, largura in larguras.items():
            cabecalho.setSectionResizeMode(coluna, QHeaderView.ResizeMode.Fixed)
            cabecalho.resizeSection(coluna, largura)
        cabecalho.setSectionResizeMode(elastica, QHeaderView.ResizeMode.Stretch)
        tabela.viewport().installEventFilter(self)
        self.ajustar()

    def eventFilter(self, objeto, evento):
        if evento.type() == QEvent.Type.Resize:
            self.ajustar()
        return False

    def ajustar(self):
        disponivel = self.tabela.viewport().width()
        ocultas = set()
        for coluna in self.ocultaveis:
            visiveis = sum(l for c, l in self.larguras.items() if c not in ocultas)
            if visiveis + self.minima <= disponivel:
                break
            ocultas.add(coluna)
        for coluna in self.larguras:
            self.tabela.setColumnHidden(coluna, coluna in ocultas)


class Selo(QLabel):
    """Etiqueta arredondada ("pill") com a cor de destaque em fundo translúcido.
    QLabel comum, e não um rótulo Fluent: as cores são explícitas e valem nos dois temas."""

    def __init__(self, texto: str, cor: str, parent=None, solido: bool = False):
        super().__init__(texto, parent)
        self.solido = solido
        self.definir(texto, cor)

    def definir(self, texto: str, cor: str):
        """Troca texto e cor. `solido` (selo de risco da ficha): fundo cheio na cor e texto branco ou
        #1A1A1A, o que der mais contraste; a informação não depende de ler texto colorido."""
        self.setText(texto)
        r, g, b = int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16)
        if self.solido:
            fundo, texto_cor = cor, _texto_sobre(r, g, b)
        else:
            fundo, texto_cor = f"rgba({r},{g},{b},0.16)", cor
        self.setStyleSheet(f"QLabel {{ background: {fundo}; color: {texto_cor}; border-radius: 10px; "
                           f"padding: 2px 10px; font-family: 'Segoe UI'; font-weight: 600; font-size: 12px; }}")


def _texto_sobre(r: int, g: int, b: int) -> str:
    """Branco ou #1A1A1A sobre o fundo (r, g, b), pela razão de contraste WCAG 2.1."""
    def linear(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    fundo = 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
    escuro = 0.2126 * linear(0x1A) + 0.7152 * linear(0x1A) + 0.0722 * linear(0x1A)
    return "#FFFFFF" if (1.05 / (fundo + 0.05)) >= ((fundo + 0.05) / (escuro + 0.05)) else "#1A1A1A"
