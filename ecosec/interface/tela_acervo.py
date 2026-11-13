"""Consulta ao acervo: a área liberada depois da autenticação.

A tela recebe do serviço a imagem já tratada (tarja e marca aplicadas antes)
e explica, para cada relatório aberto:
  - o que foi ocultado e a partir de que nível ficaria visível;
  - se há marca d'água (e o que isso significa para quem exportar);
  - a regra de exportação do nível: antes do clique, não depois do erro.
"""
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from ecosec.acervo.relatorios import descricao as descricao_relatorio, titulo as titulo_relatorio
from ecosec.dominio.niveis import Exportacao, Nivel
from ecosec.interface.atividade import PrazoInatividade
from ecosec.servicos.acervo import ErroAcervo
from ecosec.interface.componentes import Selo
from ecosec.interface.painel_analitico import PainelAnalitico
from ecosec.interface.estilo import COR_NIVEL, ICONE_NIVEL, VERMELHO, cor_texto_secundario
from ecosec.interface.fluent import (FIF, BodyLabel, CaptionLabel, CardWidget, IconWidget, InfoBar,
                                     InfoBarPosition, PrimaryPushButton, PushButton, ScrollArea, SegmentedWidget, SimpleCardWidget,
                                     StrongBodyLabel, SubtitleLabel, TitleLabel)

log = logging.getLogger(__name__)


def _mensagem(erro: Exception) -> str:
    """Recusa prevista (ErroAcervo): o motivo vai para a tela. Falha interna (banco, trilha):
    mensagem genérica na tela e o detalhe no log. A tela do acervo é vista por qualquer
    logado, inclusive o N1; o texto cru do MySQL exporia nomes de tabelas e detalhes internos."""
    if isinstance(erro, ErroAcervo):
        return str(erro)
    log.error("Falha no acervo", exc_info=erro)
    return "Falha interna. Procure o administrador."


def _para_qimage(bgr) -> QImage:
    rgb = bgr[:, :, ::-1].copy()
    alt, larg, _ = rgb.shape
    return QImage(rgb.data, larg, alt, 3 * larg, QImage.Format.Format_RGB888).copy()


class CartaoRelatorio(CardWidget):
    """Um relatório do catálogo: código, título e descrição. Clicar abre."""

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.codigo = item.codigo
        cor = COR_NIVEL[Nivel(item.nivel_minimo)]
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 12, 0)
        h.setSpacing(10)
        self.faixa = QWidget()
        self.faixa.setFixedWidth(4)
        self.faixa.setStyleSheet(f"background:{cor}; border-radius:2px;")
        h.addWidget(self.faixa)
        v = QVBoxLayout()
        v.setContentsMargins(0, 10, 0, 10)
        v.setSpacing(2)
        cabeca = QHBoxLayout()
        cabeca.setSpacing(6)
        codigo = CaptionLabel(item.codigo)
        codigo.setStyleSheet(f"color:{cor}; font-weight:600;")
        cabeca.addWidget(codigo)
        cabeca.addStretch(1)
        self.selo_aberto = Selo("aberto", cor)
        self.selo_aberto.hide()
        cabeca.addWidget(self.selo_aberto)
        v.addLayout(cabeca)
        titulo = StrongBodyLabel(titulo_relatorio(item))
        titulo.setWordWrap(True)
        v.addWidget(titulo)
        descricao = CaptionLabel(descricao_relatorio(item))
        descricao.setWordWrap(True)
        descricao.setStyleSheet(f"color:{cor_texto_secundario()};")
        v.addWidget(descricao)
        h.addLayout(v, 1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def marcar(self, aberto: bool):
        self.selo_aberto.setVisible(aberto)


class TelaAcervo(QWidget):
    encerrada = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.usuario, self.nivel, self.entrega = None, None, None
        self.sessao = None                       # SessaoAplicacao: risco do contexto e última conferência do rosto
        self.cartoes_relatorio: list[CartaoRelatorio] = []
        # N3: fecha só depois de um tempo sem uso (nunca no meio de uma consulta)
        self._minutos_n3 = float(app.cfg["sessao.inatividade_n3_minutos"])
        self._prazo_n3 = PrazoInatividade(self._minutos_n3, parent=self)
        self._prazo_n3.vencido.connect(self._fechar_por_inatividade)
        self._relogio = QTimer(self)                  # só atualiza o texto do prazo
        self._relogio.timeout.connect(self._tique)
        self._montar()

    # layout
    def _montar(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 16, 24, 16)
        raiz.setSpacing(12)
        topo = QHBoxLayout()
        topo.setSpacing(12)
        self.icone = IconWidget(FIF.FOLDER)
        self.icone.setFixedSize(32, 32)
        topo.addWidget(self.icone, 0, Qt.AlignmentFlag.AlignVCenter)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        self.titulo = TitleLabel()
        self.subtitulo = CaptionLabel()
        self.subtitulo.setStyleSheet(f"color:{cor_texto_secundario()};")
        textos.addWidget(self.titulo)
        textos.addWidget(self.subtitulo)
        topo.addLayout(textos, 1)
        self.tempo = StrongBodyLabel()
        topo.addWidget(self.tempo, 0, Qt.AlignmentFlag.AlignVCenter)
        sair = PushButton("Fechar o nível")
        sair.setIcon(FIF.CLOSE)
        sair.setToolTip("Fecha este nível e volta ao Início.")
        sair.clicked.connect(self.encerrar)
        topo.addWidget(sair, 0, Qt.AlignmentFlag.AlignVCenter)
        raiz.addLayout(topo)
        # ---- sessão de risco (MFA adaptativo): a pessoa sabe por que algo está bloqueado
        self.aviso_risco = CaptionLabel()
        self.aviso_risco.setWordWrap(True)
        self.aviso_risco.hide()
        raiz.addWidget(self.aviso_risco)

        # ---- relatórios desenhados ou painel analítico (N2 e N3)
        self.modo = SegmentedWidget()
        self.modo.addItem("relatorios", "Relatórios", onClick=lambda: self.mostrar_modo("relatorios"))
        self.modo.addItem("painel", "Painel analítico", onClick=lambda: self.mostrar_modo("painel"))
        linha_modo = QHBoxLayout()
        linha_modo.addWidget(self.modo)
        linha_modo.addStretch(1)
        raiz.addLayout(linha_modo)

        corpo = QHBoxLayout()
        corpo.setSpacing(16)
        # ---- catálogo: cartões agrupados pelo nível de origem
        esquerda = self.esquerda = QWidget()
        esquerda.setMinimumWidth(220)          # encolhe em janela estreita, sem passar disso
        esquerda.setMaximumWidth(300)
        ve = QVBoxLayout(esquerda)
        ve.setContentsMargins(0, 0, 0, 0)
        ve.setSpacing(6)
        ve.addWidget(SubtitleLabel("Relatórios"))
        dica = CaptionLabel("Relatórios disponíveis para o seu perfil.")
        dica.setWordWrap(True)
        dica.setStyleSheet(f"color:{cor_texto_secundario()};")
        ve.addWidget(dica)
        rolagem_lista = ScrollArea()
        rolagem_lista.setWidgetResizable(True)
        rolagem_lista.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        # sem rolagem horizontal: o conteúdo fica com a largura da coluna e os textos quebram linha
        rolagem_lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        conteudo_lista = QWidget()
        conteudo_lista.setStyleSheet("background: transparent;")
        rolagem_lista.setWidget(conteudo_lista)
        self.coluna_lista = QVBoxLayout(conteudo_lista)
        self.coluna_lista.setContentsMargins(0, 4, 6, 4)
        self.coluna_lista.setSpacing(8)
        ve.addWidget(rolagem_lista, 1)
        corpo.addWidget(esquerda)

        # ---- visualização
        pagina_relatorios = QWidget()
        centro = QVBoxLayout(pagina_relatorios)
        centro.setContentsMargins(0, 0, 0, 0)
        self.aviso = BodyLabel()
        self.aviso.setWordWrap(True)
        centro.addWidget(self.aviso)
        self.vazio = SimpleCardWidget()                     # antes de escolher: o que esperar
        vv = QVBoxLayout(self.vazio)
        vv.setContentsMargins(28, 28, 28, 28)
        vv.setSpacing(10)
        icone_vazio = IconWidget(FIF.DOCUMENT)
        icone_vazio.setFixedSize(40, 40)
        vv.addWidget(icone_vazio)
        titulo_vazio = SubtitleLabel("Escolha um relatório à esquerda")
        titulo_vazio.setWordWrap(True)
        vv.addWidget(titulo_vazio)
        self.vazio_texto = BodyLabel()
        self.vazio_texto.setWordWrap(True)
        vv.addWidget(self.vazio_texto)
        vv.addStretch(1)
        centro.addWidget(self.vazio, 1)
        self.rolagem = ScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.imagem = QLabel(alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.imagem.setStyleSheet("background: transparent;")
        self.rolagem.setWidget(self.imagem)
        centro.addWidget(self.rolagem, 1)
        self.painel_analitico = None                # criado na 1ª abertura: dezenas de widgets a menos na tela
        self.pilha_centro = QStackedWidget()
        self.pilha_centro.addWidget(pagina_relatorios)
        corpo.addWidget(self.pilha_centro, 1)

        # ---- o que foi feito com esta visualização
        direita = self.direita = SimpleCardWidget()
        direita.setMinimumWidth(220)
        direita.setMaximumWidth(290)
        vd = QVBoxLayout(direita)
        vd.setContentsMargins(16, 16, 16, 16)
        vd.setSpacing(10)
        vd.addWidget(SubtitleLabel("Nesta visualização"))
        self.info_supressao = BodyLabel()
        self.info_supressao.setWordWrap(True)
        vd.addWidget(self.info_supressao)
        vd.addStretch(1)
        self.botao_exportar = PrimaryPushButton("Exportar PNG")
        self.botao_exportar.setIcon(FIF.SAVE)
        self.botao_exportar.clicked.connect(self.exportar)
        vd.addWidget(self.botao_exportar)
        corpo.addWidget(direita)
        raiz.addLayout(corpo, 1)

    # sessão
    def iniciar(self, usuario, nivel: Nivel):
        self.usuario, self.nivel, self.entrega = usuario, Nivel(nivel), None
        cor = COR_NIVEL[self.nivel]
        self.icone.setIcon(getattr(FIF, ICONE_NIVEL[self.nivel]))
        self.titulo.setText(f"Nível {self.nivel.value} · {self.nivel.titulo}")
        self.titulo.setTextColor(QColor(cor), QColor(cor))
        regiao = f" · região {usuario.uf}" if self.nivel is Nivel.N2 and usuario.nivel is Nivel.N2 else ""
        self.subtitulo.setText(f"Acervo de passivos perigosos · {usuario.nome} · matrícula "
                               f"{usuario.matricula}{regiao}")
        self._montar_catalogo()
        self._limpar_visualizacao()
        risco = self.sessao.identidade.risco if self.sessao is not None else None
        if risco is not None and risco.nivel != "BAIXO":
            self.aviso_risco.setText("Sessão só para consulta: exportações e conteúdo sigiloso estão bloqueados."
                                     if risco.so_consulta else "Sessão iniciada com verificação adicional.")
            self.aviso_risco.setStyleSheet(f"color:{VERMELHO if risco.so_consulta else '#D99A1E'}; font-weight:600;")
            self.aviso_risco.show()
        else:
            self.aviso_risco.hide()
        if self.painel_analitico is not None:
            self.painel_analitico.limpar()
        self.modo.setVisible(True)                    # o N1 também tem painel: o resumo agregado (só totais)
        self.mostrar_modo("relatorios")
        self.botao_exportar.setVisible(self.nivel.exportacao is not Exportacao.BLOQUEADA)
        self.tempo.setText("")
        if self.nivel is Nivel.N3:
            self._prazo_n3.iniciar()
            self._relogio.start(1000)
            self._tique()

    def mostrar_modo(self, modo: str):
        """Relatórios (catálogo + imagem tratada) ou painel analítico (carregado na 1ª vez: uma
        consulta registrada na trilha por abertura do nível)."""
        painel = modo == "painel"
        if painel and self.painel_analitico is None:
            self.painel_analitico = PainelAnalitico(self)
            # mínimo explícito: o QStackedWidget soma os mínimos de TODAS as páginas, e os filtros do
            # painel não podem impedir a janela de estreitar (a página de relatórios se adapta)
            self.painel_analitico.setMinimumSize(320, 240)
            self.pilha_centro.addWidget(self.painel_analitico)
        if painel and not self.painel_analitico.carregado:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.painel_analitico.carregar()
            except Exception as erro:  # noqa: BLE001 (recusa ou falha: nada é exibido)
                InfoBar.error("Painel indisponível", _mensagem(erro), duration=6000, position=InfoBarPosition.TOP,
                              parent=self)
                painel, modo = False, "relatorios"
            finally:
                QApplication.restoreOverrideCursor()
        self.modo.setCurrentItem(modo)
        self.pilha_centro.setCurrentWidget(self.painel_analitico if painel else self.pilha_centro.widget(0))
        self.esquerda.setVisible(not painel)
        self.direita.setVisible(not painel)

    def _montar_catalogo(self):
        while self.coluna_lista.count():
            item = self.coluna_lista.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        self.cartoes_relatorio = []
        grupo = None
        for item in self.app.acervo.catalogo(self.nivel):
            if item.nivel_minimo != grupo:
                grupo = item.nivel_minimo
                nivel = Nivel(grupo)
                cabecalho = CaptionLabel(f"DO NÍVEL {grupo} · {nivel.titulo.upper()}")
                cabecalho.setWordWrap(True)
                cabecalho.setStyleSheet(f"color:{COR_NIVEL[nivel]}; font-weight:600; letter-spacing:1px;")
                self.coluna_lista.addWidget(cabecalho)
            cartao = CartaoRelatorio(item)
            cartao.clicked.connect(lambda codigo=item.codigo: self.abrir(codigo))
            self.cartoes_relatorio.append(cartao)
            self.coluna_lista.addWidget(cartao)
        self.coluna_lista.addStretch(1)

    def _limpar_visualizacao(self):
        self.entrega = None
        self.imagem.clear()
        self.aviso.setText("")
        self.aviso.hide()
        self.rolagem.hide()
        self.vazio.show()
        for cartao in self.cartoes_relatorio:
            cartao.marcar(False)
        if self.nivel is not None:
            self.vazio_texto.setText(
                f"{len(self.cartoes_relatorio)} relatórios disponíveis no Nível {self.nivel.value}. "
                "Selecione um na lista.")
        self.info_supressao.setText("Nenhum relatório aberto.")
        self.botao_exportar.setEnabled(False)
        self.botao_exportar.setToolTip("Abra um relatório para poder exportá-lo.")

    def _tique(self):
        restante = self._prazo_n3.restante_ms()
        if restante < 0:
            return
        urgente = restante < 60_000
        if urgente:
            self.tempo.setText(f"Sem uso: fecha em {restante // 1000 + 1} s")
        else:
            self.tempo.setText(f"Custódia: fecha após {self._minutos_n3:g} min sem uso")
        self.tempo.setToolTip("O Nível 3 fecha após um período sem uso.")
        # cor pela API do Fluent: limpar o estilo apagaria a cor do tema (texto preto no fundo escuro)
        self.tempo.setTextColor(QColor(VERMELHO if urgente else "#1A1A1A"), QColor(VERMELHO if urgente else "#FFFFFF"))

    def _fechar_por_inatividade(self):
        if self.usuario is None:
            return
        InfoBar.info("Nível 3 fechado", f"Fechado após {self._minutos_n3:g} minutos sem uso.", duration=8000,
                     position=InfoBarPosition.TOP, parent=self.window())
        self.encerrar()

    # relatórios
    def abrir(self, codigo: str):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.entrega = self.app.acervo.abrir(codigo, self.usuario, self.nivel)
        except Exception as erro:  # noqa: BLE001 (recusa ou falha: nada é exibido)
            self._limpar_visualizacao()
            InfoBar.error("Não foi possível abrir", _mensagem(erro), duration=6000, position=InfoBarPosition.TOP,
                          parent=self)
            return
        finally:
            QApplication.restoreOverrideCursor()
        e = self.entrega
        self.vazio.hide()
        self.aviso.show()
        self.rolagem.show()
        for cartao in self.cartoes_relatorio:
            cartao.marcar(cartao.codigo == codigo)
        self.aviso.setText(f"{e.item.codigo} · {titulo_relatorio(e.item)}. {descricao_relatorio(e.item)}")
        self._mostrar_imagem()
        resumo = e.resumo_supressao()
        self.info_supressao.setText(("Ocultado para o seu nível:\n• " + "\n• ".join(resumo)) if resumo
                                    else "Nada foi ocultado para o seu nível.")
        self.botao_exportar.setEnabled(e.exportacao is not Exportacao.BLOQUEADA)
        self.botao_exportar.setToolTip("Salva exatamente o que está na tela, em PNG.")

    def _mostrar_imagem(self):
        if self.entrega is None:
            return
        pixmap = QPixmap.fromImage(_para_qimage(self.entrega.imagem))
        largura = max(400, self.rolagem.viewport().width() - 12)
        self.imagem.setPixmap(pixmap.scaledToWidth(min(largura, pixmap.width()),
                                                   Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self._mostrar_imagem()

    def exportar(self):
        if self.entrega is None:
            return
        sugestao = f"{self.entrega.item.codigo}_{self.usuario.matricula}.png"
        caminho, _ = QFileDialog.getSaveFileName(self, "Exportar relatório", sugestao, "Imagem PNG (*.png)")
        if not caminho:
            return
        entrega, usuario = self.entrega, self.usuario
        try:
            destino = self.exportar_com_verificacao(
                lambda verificado_em: self.app.acervo.exportar(entrega, usuario, Path(caminho), risco=self.risco,
                                                               verificado_em=verificado_em))
        except Exception as erro:  # noqa: BLE001
            InfoBar.error("Exportação recusada", _mensagem(erro), duration=6000, position=InfoBarPosition.TOP,
                          parent=self)
            return
        if destino is None:
            InfoBar.warning("Exportação cancelada", "Verificação facial não concluída.", duration=5000,
                            position=InfoBarPosition.TOP, parent=self)
            return
        InfoBar.success("Exportado", f"{destino.name} salvo.", duration=5000,
                        position=InfoBarPosition.TOP, parent=self)

    @property
    def risco(self) -> str:
        return self.sessao.risco if self.sessao is not None else "BAIXO"

    def exportar_com_verificacao(self, operacao):
        """Step-up: se o serviço pedir o rosto (dados nominais, conferência antiga), a câmera confere e repete."""
        from ecosec.interface.verificacao import executar_com_verificacao
        return executar_com_verificacao(self, self.app, self.sessao, operacao)

    def encerrar(self):
        self._relogio.stop()
        self._prazo_n3.parar()
        self.usuario, self.entrega = None, None
        self.imagem.clear()
        if self.painel_analitico is not None:
            self.painel_analitico.limpar()
        self.encerrada.emit()
