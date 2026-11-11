"""Árvore Custódia → Pendência → Documento do N3.

Carga preguiçosa: cada expansão é uma chamada ao serviço (que passa pela matriz e,
para documentos, pela trilha). Nada é pré-carregado. Raízes: uma por custódia
(símbolo do tipo e ocupação no ano da linha do tempo) e IN SITU (sem custódia),
agrupada por UF. Clicar num nó enquadra o item no mapa; duplo clique num
documento abre o visualizador.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidgetItem

from ecosec.interface.fluent import TreeWidget

PAPEL = Qt.ItemDataRole.UserRole
SIMBOLO = {"DEFINITIVO": "◇", "INTERMEDIARIO": "□", "NORM": "△", "INICIAL": "○"}
CARREGANDO = "CARREGANDO"


class ArvoreCustodia(TreeWidget):
    abrir_documento = Signal(str, int)                # (código da pendência, id do documento)
    focar = Signal(str, object)                       # ("CUSTODIA" | "PENDENCIA" | "UF", objeto)

    def __init__(self, tela, parent=None):
        super().__init__(parent)
        self.tela, self.painel = tela, None
        self.chamadas = 0                             # quantas vezes o serviço foi consultado (para os testes)
        self.setHeaderLabels(["ITEM", "SITUACAO"])
        self.setColumnWidth(0, 205)
        self.itemExpanded.connect(self._carregar)
        self.itemClicked.connect(self._clicado)
        self.itemDoubleClicked.connect(self._duplo)

    def _no(self, pai, texto, situacao, papel, expansivel: bool):
        item = QTreeWidgetItem([texto, situacao])
        item.setData(0, PAPEL, papel)
        item.setToolTip(0, texto)
        if expansivel:
            item.addChild(QTreeWidgetItem([CARREGANDO]))          # marcador: torna o nó expansível
        (pai.addChild if pai is not None else self.addTopLevelItem)(item)
        return item

    def montar(self, painel, ano: int, tipos_visiveis, dentro: frozenset | None = None):
        """`dentro`: códigos do recorte do filtro (None = sem recorte). Os filhos de cada nó só mostram
        pendências do recorte; o IN SITU agrupa só as UFs que sobram. A ocupação das custódias é a do ano."""
        self.painel = painel
        self.ano = ano
        self.dentro = dentro
        self.clear()
        self.chamadas += 1
        for c, ocupacao in self.tela.app.acervo.custodias(painel, self.tela.usuario, ano):
            if c.tipo in tipos_visiveis:
                self._no(None, f"{SIMBOLO[c.tipo]} {c.nome}", f"{ocupacao:.0%}", ("CUSTODIA", c), True)
        self._no(None, "IN SITU (SEM CUSTODIA)", "", ("IN_SITU", None), True)

    def _carregar(self, item):
        if item.childCount() != 1 or item.child(0).data(0, PAPEL) is not None:
            return                                                # já carregado
        item.takeChildren()
        tipo, objeto = item.data(0, PAPEL)
        acervo = self.tela.app.acervo
        self.chamadas += 1
        if tipo == "CUSTODIA":
            guardadas = acervo.pendencias_da_custodia(self.painel, self.tela.usuario, objeto.nome, self.ano)
            for p in self._do_recorte(guardadas):
                self._no(item, f"{p.codigo} {p.substancia}", p.situacao, ("PENDENCIA", p), True)
        elif tipo == "IN_SITU":
            por_uf = {}
            for p in self._do_recorte(acervo.pendencias_da_custodia(self.painel, self.tela.usuario, None, self.ano)):
                por_uf.setdefault(p.uf, []).append(p)
            for uf in sorted(por_uf):
                no = self._no(item, f"UF {uf}", f"{len(por_uf[uf])} ativas", ("UF", uf), False)
                for p in por_uf[uf]:
                    self._no(no, f"{p.codigo} {p.substancia}", p.situacao, ("PENDENCIA", p), True)
        elif tipo == "PENDENCIA":
            for d in acervo.documentos(self.painel, self.tela.usuario, objeto.codigo):
                self._no(item, f"{d.tipo} {d.numero}", f"{d.data:%d/%m/%Y}", ("DOCUMENTO", d), False)

    def _do_recorte(self, pendencias) -> list:
        dentro = getattr(self, "dentro", None)
        return [p for p in pendencias if dentro is None or p.codigo in dentro]

    def _clicado(self, item, _coluna):
        papel = item.data(0, PAPEL)
        if papel and papel[0] in ("CUSTODIA", "PENDENCIA", "UF"):
            self.focar.emit(*papel)

    def _duplo(self, item, _coluna):
        papel = item.data(0, PAPEL)
        if papel and papel[0] == "DOCUMENTO":
            self.abrir_documento.emit(papel[1].pendencia_codigo, papel[1].id)
