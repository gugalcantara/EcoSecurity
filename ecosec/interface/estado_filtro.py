"""Filtro atual do painel, compartilhado entre as telas."""
from PySide6.QtCore import QObject, Signal

from ecosec.acervo.filtro import Filtro


class EstadoFiltro(QObject):
    mudou = Signal(object)                   # o Filtro novo

    def __init__(self, filtro: Filtro | None = None, parent=None):
        super().__init__(parent)
        self._filtro = filtro if filtro is not None else Filtro()

    @property
    def filtro(self) -> Filtro:
        return self._filtro

    def substituir(self, filtro: Filtro) -> bool:
        """Troca o filtro inteiro. Devolve True se mudou (e então emitiu)."""
        if filtro == self._filtro:
            return False
        self._filtro = filtro
        self.mudou.emit(filtro)
        return True

    def definir(self, **mudancas) -> bool:
        return self.substituir(self._filtro.com(**mudancas))

    def remover(self, dimensao: str, valor=None) -> bool:
        return self.substituir(self._filtro.sem(dimensao, valor))

    def limpar(self) -> bool:
        return self.substituir(Filtro())
