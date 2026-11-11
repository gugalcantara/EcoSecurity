"""Aba "Glossário", em todos os níveis.

A regra de negócio de cada termo que a tela mostra: classes, situação, score e faixas de risco, indicadores, fases e
etapas, quem paga, motivos, atividades, campos da ficha, prazos, níveis de acesso e a supressão de grupos pequenos.

O conteúdo vem só de `acervo/vocabulario.py` (a fonte única dos rótulos): nenhum número, nome, endereço ou valor do
acervo passa por aqui, por isso a mesma aba serve ao N1, ao N2 e ao N3 sem consulta ao serviço e sem trilha.

Desenho: à esquerda, o índice das seções (clicar rola até a seção); à direita, uma seção por cartão, cada termo numa
linha com o nome em negrito, a definição e, quando há, a conta (indicadores), a unidade, o código interno e a norma.
A busca filtra por nome, definição, código ou norma, sem diferenciar acento nem caixa.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from ecosec.acervo import vocabulario
from ecosec.interface.estilo import cor_borda, cor_texto_secundario
from ecosec.interface.fluent import (BodyLabel, CaptionLabel, ListWidget, ScrollArea, SearchLineEdit, SimpleCardWidget,
                                     StrongBodyLabel, SubtitleLabel, TitleLabel)


def _rotulo(classe, texto: str, secundario: bool = False, quebra: bool = True):
    rotulo = classe(texto)
    rotulo.setWordWrap(quebra)
    rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if secundario:
        rotulo.setStyleSheet(f"color:{cor_texto_secundario()};")
    return rotulo


class LinhaTermo(QWidget):
    """Um termo: nome em negrito (com o rótulo longo quando há), a definição e a linha de referência."""

    def __init__(self, termo: vocabulario.Termo, parent=None):
        super().__init__(parent)
        self.termo = termo
        self.setObjectName("linhaTermo")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 10, 16, 10)
        v.setSpacing(3)
        topo = QHBoxLayout()
        topo.setSpacing(10)
        self.nome = _rotulo(StrongBodyLabel, termo.rotulo, quebra=False)
        topo.addWidget(self.nome)
        complemento = termo.longo
        if complemento.startswith(termo.rotulo):          # "Resíduo perigoso (Classe I)": só o que acrescenta
            complemento = complemento[len(termo.rotulo):].strip(" ()")
        if complemento and complemento != termo.rotulo:
            self.complemento = _rotulo(CaptionLabel, complemento, secundario=True, quebra=False)
            topo.addWidget(self.complemento)
        topo.addStretch(1)
        v.addLayout(topo)
        self.definicao = _rotulo(BodyLabel, termo.definicao)
        v.addWidget(self.definicao)
        extras = []
        if termo.formula:
            extras.append(f"Cálculo: {termo.formula}.")
        if termo.unidade:
            extras.append(f"Unidade: {termo.unidade}.")
        referencia = " · ".join(x for x in ((f"Código {termo.codigo}" if termo.mostrar_codigo else ""),
                                            termo.referencia) if x)
        if referencia:
            extras.append(referencia)
        self.extras = _rotulo(CaptionLabel, "\n".join(extras), secundario=True) if extras else None
        if self.extras is not None:
            v.addWidget(self.extras)
        self.setAccessibleName(termo.rotulo)
        self.setAccessibleDescription(termo.definicao)
        self._texto_busca = vocabulario.texto_de_busca(termo)

    def aceita(self, alvo: str) -> bool:
        return not alvo or alvo in self._texto_busca

    def textos(self) -> list[str]:
        return [self.nome.text(), self.definicao.text(), self.extras.text() if self.extras else ""]


class CartaoSecao(QWidget):
    """Título e descrição da seção, e um cartão com as linhas dos termos separadas por um fio."""

    def __init__(self, secao: vocabulario.Secao, parent=None):
        super().__init__(parent)
        self.secao = secao
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 14)
        v.setSpacing(4)
        self.titulo = SubtitleLabel(secao.titulo)
        v.addWidget(self.titulo)
        v.addWidget(_rotulo(CaptionLabel, secao.descricao, secundario=True))
        self.cartao = SimpleCardWidget()
        vc = QVBoxLayout(self.cartao)
        vc.setContentsMargins(0, 4, 0, 4)
        vc.setSpacing(0)
        self.linhas: list[LinhaTermo] = []
        self.fios: list[QFrame] = []
        for i, termo in enumerate(secao.termos):
            if i:
                fio = QFrame()
                fio.setFixedHeight(1)
                fio.setStyleSheet(f"background:{cor_borda()}; border:none; margin:0 16px;")
                vc.addWidget(fio)
                self.fios.append(fio)
            linha = LinhaTermo(termo)
            vc.addWidget(linha)
            self.linhas.append(linha)
        v.addWidget(self.cartao)
        self.setAccessibleName(f"Seção {secao.titulo}")

    def filtrar(self, alvo: str) -> int:
        """Mostra só as linhas que aceitam a busca; devolve quantas ficaram. Os fios acompanham a linha de baixo."""
        visiveis = 0
        for i, linha in enumerate(self.linhas):
            mostra = linha.aceita(alvo)
            linha.setVisible(mostra)
            if i:
                self.fios[i - 1].setVisible(mostra and visiveis > 0)
            visiveis += mostra
        self.setVisible(visiveis > 0)
        return visiveis


class PainelGlossario(QWidget):
    def __init__(self, camada=None, parent=None):
        """`camada`: o nível da tela; o termo de nível fica só o dela (escopo exclusivo)."""
        super().__init__(parent)
        self.setObjectName("painelGlossario")
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 8, 4, 0)
        v.setSpacing(6)
        cabeca = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(TitleLabel("Glossário"))
        textos.addWidget(_rotulo(CaptionLabel, "O que cada termo da tela significa e a regra de negócio por trás "
                                               "dele. Só definições: nenhum dado do acervo.", secundario=True))
        cabeca.addLayout(textos, 1)
        coluna_busca = QVBoxLayout()
        self.busca = SearchLineEdit()
        self.busca.setPlaceholderText("Buscar termo, código ou norma…")
        self.busca.setMinimumWidth(320)
        self.busca.setAccessibleName("Buscar no glossário")
        self.busca.textChanged.connect(self.filtrar)
        self.contagem = CaptionLabel()
        self.contagem.setStyleSheet(f"color:{cor_texto_secundario()};")
        self.contagem.setAlignment(Qt.AlignmentFlag.AlignRight)
        coluna_busca.addWidget(self.busca)
        coluna_busca.addWidget(self.contagem)
        cabeca.addLayout(coluna_busca)
        v.addLayout(cabeca)
        corpo = QHBoxLayout()
        corpo.setSpacing(16)
        self.indice = ListWidget()
        self.indice.setFixedWidth(250)
        self.indice.setAccessibleName("Seções do glossário")
        self.indice.currentRowChanged.connect(self._ir_para)
        corpo.addWidget(self.indice)
        self.rolagem = ScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rolagem.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        conteudo = QWidget()
        conteudo.setObjectName("conteudoGlossario")
        conteudo.setStyleSheet("#conteudoGlossario { background: transparent; }")
        vc = QVBoxLayout(conteudo)
        vc.setContentsMargins(0, 0, 12, 12)
        vc.setSpacing(0)
        self.secoes: list[CartaoSecao] = []
        for secao in vocabulario.glossario(camada):
            cartao = CartaoSecao(secao)
            vc.addWidget(cartao)
            self.secoes.append(cartao)
        self.vazio = _rotulo(BodyLabel, "Nenhum termo encontrado. Tente outra palavra, um código (ex.: KPI-03, MP-08) "
                                        "ou uma norma (ex.: CONAMA).", secundario=True)
        self.vazio.hide()
        vc.addWidget(self.vazio)
        vc.addStretch(1)
        self.rolagem.setWidget(conteudo)
        corpo.addWidget(self.rolagem, 1)
        v.addLayout(corpo, 1)
        self.filtrar("")

    # ------------------------------------------------------------ busca e índice
    def filtrar(self, texto: str = ""):
        alvo = vocabulario.sem_acento(texto.strip())
        total = sum(cartao.filtrar(alvo) for cartao in self.secoes)
        self.indice.blockSignals(True)
        self.indice.clear()
        self._no_indice = [c for c in self.secoes if not c.isHidden()]
        for cartao in self._no_indice:
            self.indice.addItem(f"{cartao.secao.titulo}  ({sum(not l.isHidden() for l in cartao.linhas)})")
        self.indice.blockSignals(False)
        self.vazio.setVisible(total == 0)
        n = sum(len(cartao.linhas) for cartao in self.secoes)
        self.contagem.setText(f"{total} de {n} termos" if alvo else f"{n} termos em {len(self.secoes)} seções")

    def _ir_para(self, linha: int):
        if 0 <= linha < len(self._no_indice):
            alvo = self._no_indice[linha]
            QTimer.singleShot(0, lambda: self.rolagem.verticalScrollBar().setValue(alvo.y()))

    # ------------------------------------------------------------ para os testes
    def termos_visiveis(self) -> list:
        return [l.termo for c in self.secoes if not c.isHidden() for l in c.linhas if not l.isHidden()]

    def textos(self) -> list[str]:
        return [t for c in self.secoes for t in (c.secao.titulo, c.secao.descricao)] + \
            [t for c in self.secoes for l in c.linhas for t in l.textos()]
