"""Estado compartilhado do filtro único: o mediador entre as vistas.

Guarda o `Filtro` corrente (ecosec.acervo.filtro) e avisa por `mudou` quem desenha (mapa, planilha,
gráfico, barra de chips). As vistas não conversam entre si: mudam o estado e reagem ao sinal. Como em
EstadoN1, só emite quando o filtro de fato muda (sem eco entre vistas que se atualizam mutuamente).
"""
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
