"""Barra do filtro único (auditoria): o que está filtrado, sempre à vista.

Um chip por restrição ativa, cada um com um × que tira só aquela restrição; a contagem "N dentro · M fora
(de T)"; e "Limpar filtros", desabilitado quando não há filtro. A barra só lê e altera o EstadoFiltro: quem
conta as pendências é a tela, que chama definir_contagem. Os chips quebram linha (FlowLayout) quando
não cabem numa só.
"""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from ecosec.interface.estilo import cor_borda, cor_superficie, cor_texto_secundario
from ecosec.interface.fluent import FIF, BodyLabel, CaptionLabel, FlowLayout, PushButton, TransparentToolButton


def _numero(n: int) -> str:
    return f"{n:,}".replace(",", ".")


class _Chip(QWidget):
    """Uma restrição: rótulo + botão × que a remove."""

    def __init__(self, dimensao: str, valor, rotulo: str, ao_remover, parent=None):
        super().__init__(parent)
        self.dimensao, self.valor, self.rotulo = dimensao, valor, rotulo
        self.setObjectName("chipFiltro")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#chipFiltro {{ background:{cor_superficie()}; border:1px solid {cor_borda()};"
                           f" border-radius:13px; }}")
        self.setAccessibleName(f"Filtro ativo: {rotulo}")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 1, 2, 1)
        h.setSpacing(2)
        self.texto = BodyLabel(rotulo)
        self.botao = TransparentToolButton(FIF.CLOSE)
        self.botao.setFixedSize(22, 22)
        self.botao.setIconSize(QSize(10, 10))
        self.botao.setToolTip(f"Remover {rotulo}")
        self.botao.setAccessibleName(f"Remover filtro {rotulo}")
        self.botao.clicked.connect(lambda *_: ao_remover(dimensao, valor))
        h.addWidget(self.texto)
        h.addWidget(self.botao)


class BarraFiltros(QWidget):
    def __init__(self, estado, parent=None):
        super().__init__(parent)
        self.estado = estado
        self._atividades, self._motivos = {}, {}
        self.chips: list[_Chip] = []
        self.setAccessibleName("Filtros ativos")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.rotulo_vazio = CaptionLabel("Sem filtro")
        self.rotulo_vazio.setStyleSheet(f"color:{cor_texto_secundario()};")
        self.rotulo_vazio.setAccessibleName("Sem filtro")
        self.area_chips = QWidget()
        self.area_chips.setAccessibleName("Chips de filtro")
        self.area_chips.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.fluxo = FlowLayout(self.area_chips)
        self.fluxo.setContentsMargins(0, 0, 0, 0)
        self.fluxo.setHorizontalSpacing(6)
        self.fluxo.setVerticalSpacing(6)
        self.contagem = CaptionLabel()
        self.contagem.setStyleSheet(f"color:{cor_texto_secundario()};")
        self.contagem.setAccessibleName("Contagem do filtro")
        self.botao_limpar = PushButton("Limpar filtros")
        self.botao_limpar.setIcon(FIF.CANCEL)
        self.botao_limpar.setAccessibleName("Limpar filtros")
        self.botao_limpar.clicked.connect(lambda *_: self.estado.limpar())
        h.addWidget(self.rotulo_vazio)
        h.addWidget(self.area_chips, 1)
        h.addWidget(self.contagem, 0, Qt.AlignmentFlag.AlignTop)
        h.addWidget(self.botao_limpar, 0, Qt.AlignmentFlag.AlignTop)
        estado.mudou.connect(self._atualizar)
        self._atualizar(estado.filtro)

    def definir_catalogos(self, atividades: dict | None = None, motivos: dict | None = None):
        """Com os catálogos, os chips de atividade e motivo mostram "código · nome"."""
        self._atividades, self._motivos = atividades or {}, motivos or {}
        self._atualizar(self.estado.filtro)

    def definir_contagem(self, dentro: int, fora: int, total: int):
        self.contagem.setText(f"{_numero(dentro)} dentro · {_numero(fora)} fora (de {_numero(total)})")

    def definir_texto_contagem(self, texto: str):
        """Contagem livre (N1: totais agregados, sem "fora" por registro)."""
        self.contagem.setText(texto)

    def sincronizar(self):
        """Redesenha os chips do filtro corrente (quando o estado foi trocado sem emitir, numa recarga)."""
        self._atualizar(self.estado.filtro)

    def _atualizar(self, filtro):
        for chip in self.chips:
            self.fluxo.removeWidget(chip)
            chip.hide()
            chip.deleteLater()
        self.chips = [_Chip(d, v, r, self.estado.remover, self.area_chips)
                      for d, v, r in filtro.chips(self._atividades, self._motivos)]
        for chip in self.chips:
            self.fluxo.addWidget(chip)
            chip.show()
        vazio = not self.chips
        self.rotulo_vazio.setVisible(vazio)
        self.area_chips.setVisible(not vazio)
        self.botao_limpar.setEnabled(not vazio)
        self.area_chips.updateGeometry()
