"""Estado compartilhado do painel do N1 (EstadoN1).

As seções do painel não se chamam diretamente: todas observam o mesmo EstadoN1 (UF em foco, seleção, classe e
ano), que só emite um sinal quando o valor muda, o que evita eco entre seções que se atualizam umas às outras.
"""
from PySide6.QtCore import QObject, Signal


class EstadoN1(QObject):
    foco_mudou = Signal(object)              # UF sob o mouse, ou None
    selecao_mudou = Signal(frozenset)        # UFs fixadas por clique ou pela legenda
    classe_mudou = Signal(object)            # classe escolhida nas barras, ou None (todas)
    ano_mudou = Signal(int)
    SINAIS = {"foco": "foco_mudou", "selecao": "selecao_mudou", "classe": "classe_mudou", "ano": "ano_mudou"}

    def __init__(self):
        super().__init__()
        self.foco, self.selecao, self.classe, self.ano = None, frozenset(), None, 2026

    def definir(self, **mudancas):
        for nome, valor in mudancas.items():
            if getattr(self, nome) != valor:                    # só emite quando muda (sem eco)
                setattr(self, nome, valor)
                getattr(self, self.SINAIS[nome]).emit(valor)
