"""Camada da cena do mapa.

Raiz sem conteúdo: visibilidade e opacidade valem para todos os filhos
(item.setParentItem(camada)), inclusive os que ignoram transformações.
"""
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject


class Camada(QGraphicsObject):
    def __init__(self, chave: str, z: float, opacidade: float = 1.0):
        super().__init__()
        self.chave = chave
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemHasNoContents)
        self.setZValue(z)
        self.setOpacity(opacidade)

    def boundingRect(self) -> QRectF:
        return QRectF()

    def paint(self, *args):
        pass

    def filhos(self):
        return self.childItems()
