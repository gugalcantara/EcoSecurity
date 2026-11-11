"""Tela de bloqueio por inatividade.

Depois de [sessao] inatividade_minutos sem uso, a sessão não é encerrada: a
tela é bloqueada. A pessoa digita a própria senha e volta exatamente para onde
estava. Nada fecha no meio de uma atividade; só uma inatividade real bloqueia.

Enquanto bloqueada, o menu some e nada do conteúdo fica visível. O Nível 3 e o
painel de administração, que exigem o rosto, se fecham no bloqueio: ao voltar,
pedem o rosto de novo. Erros de senha aqui contam para a contenção da conta.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ecosec.interface.componentes import linha_rotulada
from ecosec.interface.estilo import cor_texto_secundario
from ecosec.interface.fluent import (FIF, BodyLabel, CaptionLabel, PasswordLineEdit, PrimaryPushButton,
                                     PushButton, SimpleCardWidget, StrongBodyLabel, TitleLabel)
from ecosec.interface.logo import pixmap_logo


class PaginaBloqueio(QWidget):
    desbloquear = Signal(str)            # a senha digitada
    sair = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("paginaBloqueio")
        fundo = QVBoxLayout(self)
        fundo.addStretch(1)
        cartao = SimpleCardWidget()
        cartao.setFixedWidth(440)
        v = QVBoxLayout(cartao)
        v.setContentsMargins(32, 30, 32, 28)
        v.setSpacing(12)
        icone = QLabel()
        icone.setPixmap(pixmap_logo(48))
        icone.setFixedSize(48, 48)
        v.addWidget(icone, 0, Qt.AlignmentFlag.AlignHCenter)
        titulo = TitleLabel("Sessão bloqueada")
        v.addWidget(titulo, 0, Qt.AlignmentFlag.AlignHCenter)
        self.quem = StrongBodyLabel()
        v.addWidget(self.quem, 0, Qt.AlignmentFlag.AlignHCenter)
        self.explicacao = BodyLabel()
        self.explicacao.setWordWrap(True)
        self.explicacao.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.explicacao.setStyleSheet(f"color:{cor_texto_secundario()};")
        v.addWidget(self.explicacao)
        self.campo = PasswordLineEdit()
        self.campo.setPlaceholderText("Sua senha")
        self.campo.returnPressed.connect(self._enviar)
        v.addWidget(linha_rotulada("Senha", self.campo))
        self.erro = CaptionLabel()
        self.erro.setWordWrap(True)
        v.addWidget(self.erro)
        self.botao = PrimaryPushButton("Desbloquear")
        self.botao.setIcon(FIF.ACCEPT)
        self.botao.clicked.connect(self._enviar)
        v.addWidget(self.botao)
        sair = PushButton("Sair e trocar de usuário")
        sair.setIcon(FIF.POWER_BUTTON)
        sair.clicked.connect(self.sair.emit)
        v.addWidget(sair)
        linha = QHBoxLayout()
        linha.addStretch(1)
        linha.addWidget(cartao)
        linha.addStretch(1)
        fundo.addLayout(linha)
        fundo.addStretch(2)

    def mostrar(self, nome: str, matricula: str, minutos: float):
        self.quem.setText(f"{nome} · matrícula {matricula}")
        self.explicacao.setText(f"Ficou {minutos:g} minutos sem uso. Para continuar de onde parou, digite a "
                                "sua senha. A custódia e a Administração, se estavam abertas, pedem o rosto de "
                                "novo.")
        self.erro.setText("")
        self.campo.clear()
        self.campo.setFocus()

    def mostrar_erro(self, texto: str):
        self.erro.setText(texto)
        self.erro.setStyleSheet("color:#D2384F;")
        self.campo.clear()
        self.campo.setFocus()

    def _enviar(self):
        senha = self.campo.text()
        self.campo.clear()                     # a senha não fica na tela
        if senha:
            self.desbloquear.emit(senha)
