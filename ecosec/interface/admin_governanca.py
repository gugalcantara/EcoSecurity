"""Telas da governança dos administradores. Toda decisão é do ServicoAdministracao; aqui só se coleta e mostra.

- PainelCodigoCelular     o 3º passo para abrir o painel: o código do celular (ou um de recuperação)
- PainelCadastroCelular   o primeiro acesso de um admin: QR para o aplicativo, primeiro código e os
                          códigos de recuperação, mostrados uma vez
- DialogoAprovacao        ação crítica: o código atual do celular de outro administrador
- pedir_codigo_proprio    ação sensível de quem já está no painel: o código do próprio celular
- mostrar_ancora / pedir_linha_ancora   a âncora da trilha, para guardar e conferir fora do banco
- PaginaEmergencia        no login: os códigos do quórum, em qualquer ordem, sem instruções na tela
- PainelEmergencia        a Administração restrita do acesso de emergência: só consertar o acesso
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QStackedWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ecosec.dominio.motivos import Motivo
from ecosec.interface.estilo import AMBAR, VERDE, VERMELHO, cor_texto_secundario
from ecosec.interface.fluent import (FIF, BodyLabel, CaptionLabel, CheckBox, ComboBox, IconWidget, InfoBar,
                                     InfoBarPosition, LineEdit, MessageBox, MessageBoxBase, PrimaryPushButton,
                                     PushButton, SimpleCardWidget, StrongBodyLabel, SubtitleLabel, TableWidget,
                                     TitleLabel)


def _secundario(texto: str = "") -> CaptionLabel:
    rotulo = CaptionLabel(texto)
    rotulo.setWordWrap(True)
    rotulo.setStyleSheet(f"color:{cor_texto_secundario()};")
    return rotulo


def _corpo(texto: str) -> BodyLabel:
    rotulo = BodyLabel(texto)
    rotulo.setWordWrap(True)
    return rotulo


def _cartao(*widgets, largura: int = 460) -> QWidget:
    fundo = QWidget()
    externo = QVBoxLayout(fundo)
    externo.addStretch(1)
    cartao = SimpleCardWidget()
    cartao.setFixedWidth(largura)
    v = QVBoxLayout(cartao)
    v.setContentsMargins(28, 28, 28, 28)
    v.setSpacing(12)
    for w in widgets:
        v.addLayout(w) if isinstance(w, QHBoxLayout) else v.addWidget(w)
    linha = QHBoxLayout()
    linha.addStretch(1)
    linha.addWidget(cartao)
    linha.addStretch(1)
    externo.addLayout(linha)
    externo.addStretch(2)
    return fundo


def pixmap_qr(texto: str, lado: int = 220) -> QPixmap:
    """QR desenhado aqui mesmo, sem internet (o mesmo codificador do OpenCV dos documentos)."""
    from ecosec.interface.rasterizar_documento import qr
    from ecosec.servicos.documentos import qr_modulos
    imagem = qr(qr_modulos(texto), escala=6, borda=2)
    return QPixmap.fromImage(imagem).scaled(lado, lado, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.FastTransformation)


def segredo_em_grupos(segredo: str) -> str:
    return " ".join(segredo[i:i + 4] for i in range(0, len(segredo), 4))


def campo_codigo(dica: str = "6 dígitos do aplicativo") -> LineEdit:
    campo = LineEdit()
    campo.setPlaceholderText(dica)
    campo.setMaxLength(24)                           # cabe um código de recuperação com hífens
    return campo


# ============================================================ abrir o painel: o código do celular
class PainelCodigoCelular(QWidget):
    confirmado = Signal()
    voltar = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app, self.usuario_id = app, None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        icone = IconWidget(FIF.PHONE)
        icone.setFixedSize(40, 40)
        self.campo = campo_codigo()
        self.campo.returnPressed.connect(self._confirmar)
        self.mensagem = CaptionLabel()
        self.mensagem.setWordWrap(True)
        botao = PrimaryPushButton("Confirmar")
        botao.setIcon(FIF.ACCEPT)
        botao.clicked.connect(self._confirmar)
        voltar = PushButton("Voltar ao início")
        voltar.clicked.connect(self.voltar.emit)
        botoes = QHBoxLayout()
        botoes.addWidget(voltar)
        botoes.addStretch(1)
        botoes.addWidget(botao)
        v.addWidget(_cartao(icone, TitleLabel("Código do celular"),
                            _corpo("Digite o código do aplicativo autenticador."),
                            self.campo, self.mensagem, botoes,
                            _secundario("Sem o celular, use um código de recuperação.")))

    def iniciar(self, usuario_id: int):
        self.usuario_id = usuario_id
        self.campo.clear()
        self.mensagem.setText("")
        self.campo.setFocus()

    def _confirmar(self):
        texto = self.campo.text()
        self.campo.clear()                               # o código não fica na tela
        if not texto.strip():
            return
        motivo, ate = self.app.administracao.conferir_codigo_celular(self.usuario_id, texto)
        if motivo is Motivo.CONCEDIDO:
            self.confirmado.emit()
            return
        self.mensagem.setStyleSheet(f"color:{VERMELHO};")
        if motivo is Motivo.BLOQUEADO and ate is not None:
            self.mensagem.setText(f"Tentativas esgotadas. Tente novamente às {ate:%H:%M}.")
        else:
            self.mensagem.setText(motivo.mensagem)


# ============================================================ primeiro acesso: cadastrar o celular
class PainelCadastroCelular(QWidget):
    concluido = Signal()
    voltar = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app, self.usuario_id, self.novo = app, None, None
        self.pilha = QStackedWidget(self)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.pilha)
        self.pilha.addWidget(self._passo_qr())
        self.pilha.addWidget(self._passo_codigos())

    def _passo_qr(self):
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setFixedSize(230, 230)
        self.segredo = StrongBodyLabel()
        self.segredo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.campo = campo_codigo("Código que o aplicativo mostra agora")
        self.campo.returnPressed.connect(self._confirmar)
        self.mensagem = CaptionLabel()
        self.mensagem.setWordWrap(True)
        botao = PrimaryPushButton("Confirmar celular")
        botao.setIcon(FIF.ACCEPT)
        botao.clicked.connect(self._confirmar)
        voltar = PushButton("Agora não")
        voltar.clicked.connect(self._desistir)
        botoes = QHBoxLayout()
        botoes.addWidget(voltar)
        botoes.addStretch(1)
        botoes.addWidget(botao)
        centro = QHBoxLayout()
        centro.addStretch(1)
        centro.addWidget(self.qr)
        centro.addStretch(1)
        return _cartao(TitleLabel("Cadastre o seu celular"),
                       _corpo("Escaneie o QR com um aplicativo autenticador (Google ou Microsoft Authenticator). "
                              "O código gerado será pedido sempre que você abrir a Administração."),
                       centro,
                       _secundario("Ou digite esta chave no aplicativo (baseada em tempo):"),
                       self.segredo, self.campo, self.mensagem, botoes, largura=520)

    def _passo_codigos(self):
        self.grade = QGridLayout()
        self.grade.setHorizontalSpacing(24)
        self.grade.setVerticalSpacing(6)
        grade = QWidget()
        grade.setLayout(self.grade)
        self.guardei = CheckBox("Guardei estes códigos em local seguro")
        self.botao_concluir = PrimaryPushButton("Concluir")
        self.botao_concluir.setIcon(FIF.ACCEPT)
        self.botao_concluir.setEnabled(False)
        self.guardei.stateChanged.connect(lambda *_: self.botao_concluir.setEnabled(self.guardei.isChecked()))
        self.botao_concluir.clicked.connect(self._concluir)
        copiar = PushButton("Copiar os códigos")
        copiar.setIcon(FIF.COPY)
        copiar.clicked.connect(lambda: QGuiApplication.clipboard().setText("\n".join(self._codigos)))
        botoes = QHBoxLayout()
        botoes.addWidget(copiar)
        botoes.addStretch(1)
        botoes.addWidget(self.botao_concluir)
        aviso = _corpo("Estes códigos são exibidos uma única vez. Cada um pode ser usado uma vez, no lugar do "
                       "celular. Guarde-os fora do computador.")
        aviso.setStyleSheet(f"color:{AMBAR};")
        return _cartao(TitleLabel("Códigos de recuperação"), aviso, grade, self.guardei, botoes, largura=520)

    def iniciar(self, usuario_id: int):
        self.usuario_id = usuario_id
        self.novo = self.app.administracao.novo_celular(usuario_id)
        self._codigos = []
        self.campo.clear()
        self.mensagem.setText("")
        self.pilha.setCurrentIndex(0)
        if self.novo is not None:
            self.qr.setPixmap(pixmap_qr(self.novo.uri))
            self.segredo.setText(segredo_em_grupos(self.novo.segredo))

    def _confirmar(self):
        texto = self.campo.text()
        self.campo.clear()
        codigos = self.app.administracao.confirmar_celular(self.usuario_id, self.novo, texto) if texto.strip() else None
        if codigos is None:
            self.mensagem.setStyleSheet(f"color:{VERMELHO};")
            self.mensagem.setText("Código inválido. Verifique se o relógio do celular está correto.")
            return
        self.novo = None                                  # o segredo não fica mais na memória da tela
        self.qr.clear()
        self.segredo.setText("")
        self._codigos = codigos
        for i, c in enumerate(codigos):
            rotulo = StrongBodyLabel(c)
            rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grade.addWidget(rotulo, i // 2, i % 2)
        self.guardei.setChecked(False)
        self.pilha.setCurrentIndex(1)

    def _limpar(self):
        self.novo, self._codigos = None, []
        self.qr.clear()
        self.segredo.setText("")
        while self.grade.count():
            item = self.grade.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _concluir(self):
        self._limpar()
        self.concluido.emit()

    def _desistir(self):
        self._limpar()
        self.voltar.emit()

    def descartar(self):
        """A tela sumiu: nada de segredo nem de código de recuperação esquecido na memória da tela."""
        self._limpar()


# ============================================================ aprovação por outro administrador
class DialogoAprovacao(MessageBoxBase):
    def __init__(self, acao: str, alvo: str | None, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel("Aprovação de outro administrador"))
        resumo = StrongBodyLabel(acao + (f": {alvo}" if alvo else ""))
        resumo.setWordWrap(True)
        self.viewLayout.addWidget(resumo)
        self.viewLayout.addWidget(_corpo("Esta ação exige a aprovação de outro administrador. Informe o código "
                                         "do aplicativo autenticador dele."))
        self.campo = campo_codigo("Código do celular do outro administrador")
        self.viewLayout.addWidget(self.campo)
        self.yesButton.setText("Aprovar e executar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(500)


def pedir_aprovacao(parent, servico, acao: str, alvo: str | None) -> str | None:
    """Devolve o código digitado; "" na fase de implantação (confirmado sem código); None se desistiu."""
    if not servico.exige_aprovacao:
        caixa = MessageBox("Fase de implantação",
                           f"{acao}{': ' + alvo if alvo else ''}.\n\nSem um segundo administrador, a ação é "
                           "confirmada apenas por você e registrada na trilha.",
                           parent)
        caixa.yesButton.setText("Continuar")
        return "" if caixa.exec() else None
    dialogo = DialogoAprovacao(acao, alvo, parent)
    return dialogo.campo.text() if dialogo.exec() else None


# ============================================================ código do próprio celular e âncora da trilha
class DialogoCodigoProprio(MessageBoxBase):
    def __init__(self, acao: str, explicacao: str, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(acao))
        self.viewLayout.addWidget(_corpo(explicacao))
        self.campo = campo_codigo("Código atual do SEU celular")
        self.viewLayout.addWidget(self.campo)
        self.yesButton.setText("Confirmar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(500)


def pedir_codigo_proprio(parent, acao: str, explicacao: str) -> str | None:
    """O código digitado, ou None se desistiu."""
    dialogo = DialogoCodigoProprio(acao, explicacao, parent)
    return dialogo.campo.text() if dialogo.exec() else None


class DialogoAncora(MessageBoxBase):
    def __init__(self, linha: str, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel("Âncora da trilha"))
        self.viewLayout.addWidget(_corpo("Guarde esta linha fora deste computador. Ela permite conferir depois "
                                         "a integridade da trilha."))
        self.campo = LineEdit()
        self.campo.setText(linha)
        self.campo.setReadOnly(True)
        self.viewLayout.addWidget(self.campo)
        copiar = PushButton("Copiar")
        copiar.setIcon(FIF.COPY)
        copiar.clicked.connect(lambda: QGuiApplication.clipboard().setText(linha))
        self.viewLayout.addWidget(copiar, 0, Qt.AlignmentFlag.AlignLeft)
        self.yesButton.setText("Fechar")
        self.cancelButton.hide()
        self.widget.setMinimumWidth(640)


def mostrar_ancora(parent, linha: str) -> None:
    DialogoAncora(linha, parent).exec()


class DialogoConferirAncora(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel("Conferir uma âncora"))
        self.viewLayout.addWidget(_corpo("Cole a linha da âncora guardada (começa com ECOSEC-TRILHA)."))
        self.campo = LineEdit()
        self.campo.setPlaceholderText("ECOSEC-TRILHA ...")
        self.viewLayout.addWidget(self.campo)
        self.yesButton.setText("Conferir")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(640)


def pedir_linha_ancora(parent) -> str | None:
    dialogo = DialogoConferirAncora(parent)
    return dialogo.campo.text() if dialogo.exec() else None


# ============================================================ acesso de emergência: no login
class PaginaEmergencia(QWidget):
    concedida = Signal(object)                       # servicos.administracao.Emergencia
    voltar = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sessao = None
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        icone = IconWidget(FIF.VPN)
        icone.setFixedSize(40, 40)
        self.contador = StrongBodyLabel()
        self.campo = campo_codigo("Código")
        self.campo.returnPressed.connect(self._informar)
        self.mensagem = CaptionLabel()
        self.mensagem.setWordWrap(True)
        botao = PrimaryPushButton("Enviar")
        botao.clicked.connect(self._informar)
        voltar = PushButton("Voltar ao login")
        voltar.clicked.connect(self._voltar)
        botoes = QHBoxLayout()
        botoes.addWidget(voltar)
        botoes.addStretch(1)
        botoes.addWidget(botao)
        # sem instruções de propósito: quem precisa desta tela já sabe o que fazer
        v.addWidget(_cartao(icone, TitleLabel("Acesso de emergência"), self.contador, self.campo, self.mensagem,
                            botoes, largura=420))

    def iniciar(self, sessao_emergencia):
        self.sessao = sessao_emergencia
        self.campo.clear()
        self.mensagem.setText("")
        self.contador.setText(f"0 de {sessao_emergencia.quorum}")
        self.campo.setFocus()

    def _informar(self):
        texto = self.campo.text()
        self.campo.clear()
        if self.sessao is None or not texto.strip():
            return
        passo = self.sessao.informar(texto)
        self.contador.setText(f"{passo.aceitos} de {passo.quorum}")
        aceito = passo.concedida is not None or passo.mensagem.startswith("Código aceito")
        self.mensagem.setStyleSheet(f"color:{VERDE if aceito else VERMELHO};")
        self.mensagem.setText(passo.mensagem)
        if passo.concedida is not None:
            emergencia, self.sessao = passo.concedida, None
            self.concedida.emit(emergencia)

    def _voltar(self):
        self.sessao = None
        self.voltar.emit()


# ============================================================ acesso de emergência: a Administração restrita
class PainelEmergencia(QWidget):
    recadastrar_rosto = Signal(int)                  # usuario_id
    sair = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app, self.servico, self.sessao = app, app.administracao, None
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 20, 28, 20)
        v.setSpacing(12)
        topo = QHBoxLayout()
        textos = QVBoxLayout()
        textos.addWidget(TitleLabel("Acesso de emergência"))
        self.prazo = CaptionLabel()
        self.prazo.setStyleSheet(f"color:{AMBAR};")
        textos.addWidget(self.prazo)
        topo.addLayout(textos, 1)
        encerrar = PushButton("Encerrar emergência")
        encerrar.setIcon(FIF.POWER_BUTTON)
        encerrar.clicked.connect(self.sair.emit)
        topo.addWidget(encerrar, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(topo)
        v.addWidget(_corpo("Acesso restrito à recuperação de administradores: recadastrar o rosto, refazer o "
                           "celular ou designar um novo. As ações são registradas na trilha."))
        self.tabela = TableWidget()
        self.tabela.setBorderVisible(True)
        self.tabela.setBorderRadius(8)
        self.tabela.setColumnCount(3)
        self.tabela.setHorizontalHeaderLabels(("Matrícula", "Administrador", "Celular"))
        self.tabela.verticalHeader().hide()
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        cabecalho = self.tabela.horizontalHeader()
        cabecalho.setStretchLastSection(False)
        for coluna, modo in ((0, QHeaderView.ResizeMode.ResizeToContents), (1, QHeaderView.ResizeMode.Stretch),
                             (2, QHeaderView.ResizeMode.ResizeToContents)):
            cabecalho.setSectionResizeMode(coluna, modo)
        v.addWidget(self.tabela, 1)
        acoes = QHBoxLayout()
        self.botao_rosto = PushButton("Recadastrar rosto")
        self.botao_rosto.setIcon(FIF.CAMERA)
        self.botao_rosto.clicked.connect(self._recadastrar)
        self.botao_celular = PushButton("Refazer celular")
        self.botao_celular.setIcon(FIF.PHONE)
        self.botao_celular.clicked.connect(self._refazer_celular)
        acoes.addWidget(self.botao_rosto)
        acoes.addWidget(self.botao_celular)
        acoes.addStretch(1)
        self.combo_candidato = ComboBox()
        self.combo_candidato.setMinimumWidth(240)
        self.botao_designar = PushButton("Tornar administrador")
        self.botao_designar.setIcon(FIF.ADD)
        self.botao_designar.clicked.connect(self._designar)
        acoes.addWidget(self.combo_candidato)
        acoes.addWidget(self.botao_designar)
        v.addLayout(acoes)

    def definir(self, sessao):
        self.sessao = sessao
        if sessao is not None:
            self.atualizar()

    def atualizar(self):
        fim = self.sessao.emergencia.fim
        self.prazo.setText(f"Válido até as {fim:%H:%M}.")
        admins = self.servico.administradores_ativos()
        self.tabela.setRowCount(len(admins))
        for i, a in enumerate(admins):
            u = self.servico.usuario(a.usuario_id)
            for j, valor in enumerate((u.matricula, u.nome, "Cadastrado" if a.celular_cadastrado else "Não")):
                item = QTableWidgetItem(valor)
                item.setData(Qt.ItemDataRole.UserRole, u.id)
                self.tabela.setItem(i, j, item)
        self.combo_candidato.clear()
        for u in self.servico.candidatos_a_administrador():
            self.combo_candidato.addItem(f"{u.matricula} · {u.nome}", userData=u.id)
        self.botao_designar.setEnabled(self.combo_candidato.count() > 0)

    def _selecionado(self) -> int | None:
        itens = self.tabela.selectedItems()
        return itens[0].data(Qt.ItemDataRole.UserRole) if itens else None

    def _aviso(self, recusa: str | None, ok: str):
        if recusa:
            InfoBar.warning("Não foi possível", recusa, duration=6000, position=InfoBarPosition.TOP, parent=self)
        else:
            InfoBar.success("Feito", ok, duration=5000, position=InfoBarPosition.TOP, parent=self)
        self.atualizar()

    def _recadastrar(self):
        alvo = self._selecionado()
        if alvo is None:
            return
        recusa = self.servico.autorizar_recadastro_rosto(self.sessao.emergencia, alvo)
        if recusa:
            self._aviso(recusa, "")
            return
        self.recadastrar_rosto.emit(alvo)

    def _refazer_celular(self):
        alvo = self._selecionado()
        if alvo is None:
            return
        recusa = self.servico.refazer_celular(self.sessao.usuario.id, alvo, emergencia=self.sessao.emergencia)
        self._aviso(recusa, "Celular removido. Um novo será cadastrado no próximo acesso.")

    def _designar(self):
        alvo = self.combo_candidato.currentData()
        if alvo is None:
            return
        recusa = self.servico.tornar_administrador(self.sessao.usuario.id, alvo, emergencia=self.sessao.emergencia)
        self._aviso(recusa, "Administrador designado.")
