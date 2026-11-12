"""Login de entrada: a primeira (e, antes dele, a única) tela da aplicação.

Matrícula, senha e rosto 1:1, os fatores do nível 2. Antes do login nada do
sistema fica visível: nem os níveis, nem o acervo, nem o menu. Quem não deveria
estar ali não aprende a estrutura do que está protegido.

Layout de tela de login: à esquerda, a marca e como funciona o acesso; à
direita, um cartão com matrícula e senha. A câmera só aparece dentro do cartão
quando chega a vez do rosto. A lógica é a mesma da TelaAutenticacao (sessão,
vídeo, falha segura); TelaLogin só rearruma o layout.

O nome não substitui a matrícula (não é único e é público; ver a ajuda
"Esqueci minha matrícula" na própria tela).

Acesso de emergência: uma porta discreta, que
aparece no resultado só quando um administrador acertou matrícula e senha e o
rosto ou a câmera falhou, e só se o quórum for possível. Ela abre uma tela sem
instruções que pede os códigos dos administradores. A segurança está nos
códigos, não em esconder a porta (princípio de Kerckhoffs).
"""
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from ecosec.interface.componentes import FaixaCamadas
from ecosec.interface.fluent import FIF, CaptionLabel, PushButton, SimpleCardWidget, TitleLabel
from ecosec.interface.tela_autenticacao import TelaAutenticacao
from ecosec.interface.video import VisorVideo
from ecosec.servicos.autenticacao import Etapa

ICONE_GRANDE = Path(__file__).parent / "recursos" / "ecosecurity.png"
# abaixo desta largura, o painel da marca sai e fica só o cartão de login
LARGURA_COM_MARCA = 980
VERDE_ESCURO, VERDE = "#0E4D36", "#1F9D6B"

PASSOS = (
    ("1", "Matrícula e senha", "Os dados do seu cadastro."),
    ("2", "Rosto", "Verificação pela câmera."),
    ("3", "Acesso", "Conforme o seu perfil."),
)


class PainelMarca(QFrame):
    """Faixa da marca, à esquerda: o que é o sistema e como funciona o acesso."""

    def __init__(self, nome: str, parent=None):
        super().__init__(parent)
        self.setObjectName("painelMarca")
        self.setMaximumWidth(420)
        self.setStyleSheet(f"#painelMarca {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                           f"stop:0 {VERDE}, stop:1 {VERDE_ESCURO}); }}"
                           "#painelMarca QLabel { color: white; background: transparent; "
                           "font-family: 'Segoe UI'; }")
        v = QVBoxLayout(self)
        v.setContentsMargins(44, 56, 44, 36)
        v.setSpacing(10)
        icone = QLabel()
        if ICONE_GRANDE.exists():
            icone.setPixmap(QPixmap(str(ICONE_GRANDE)).scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                                               Qt.TransformationMode.SmoothTransformation))
        v.addWidget(icone)
        v.addSpacing(8)
        titulo = QLabel(nome)
        titulo.setStyleSheet("font-size: 34px; font-weight: 700;")
        v.addWidget(titulo)
        subtitulo = QLabel("Controle de acesso multinível por reconhecimento facial")
        subtitulo.setWordWrap(True)
        subtitulo.setStyleSheet("font-size: 15px; color: rgba(255,255,255,0.85);")
        v.addWidget(subtitulo)
        v.addSpacing(28)
        for numero, titulo_passo, texto in PASSOS:
            linha = QHBoxLayout()
            linha.setSpacing(14)
            circulo = QLabel(numero)
            circulo.setFixedSize(30, 30)
            circulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            circulo.setStyleSheet("background: rgba(255,255,255,0.18); border-radius: 15px; font-weight: 700;")
            linha.addWidget(circulo, 0, Qt.AlignmentFlag.AlignTop)
            coluna = QVBoxLayout()
            coluna.setSpacing(2)
            rotulo = QLabel(titulo_passo)
            rotulo.setStyleSheet("font-size: 14px; font-weight: 600;")
            explicacao = QLabel(texto)
            explicacao.setWordWrap(True)
            explicacao.setStyleSheet("font-size: 12px; color: rgba(255,255,255,0.78);")
            coluna.addWidget(rotulo)
            coluna.addWidget(explicacao)
            linha.addLayout(coluna, 1)
            v.addLayout(linha)
            v.addSpacing(12)
        v.addStretch(1)
        rodape = QLabel("Trabalho acadêmico · UNIP · 2026/2")
        rodape.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.6);")
        v.addWidget(rodape)

    def minimumSizeHint(self):
        # a marca não segura a largura da janela: estreita demais, ela simplesmente sai
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        return QSize(420, super().sizeHint().height())


class TelaLogin(TelaAutenticacao):
    """A mesma condução da TelaAutenticacao, com layout de cartão de login."""
    pedir_emergencia = Signal(int)                   # usuario_id do administrador barrado pela câmera

    def __init__(self, app, parent=None, **extra):
        super().__init__(app, parent, **extra)
        self._admin_barrado = None
        self.botao_emergencia.clicked.connect(lambda: self._admin_barrado and
                                              self.pedir_emergencia.emit(self._admin_barrado))

    def _montar(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 24, 24, 24)
        raiz.setSpacing(14)
        raiz.addStretch(1)
        self.cartao = SimpleCardWidget()
        self.cartao.setMinimumWidth(380)
        self.cartao.setMaximumWidth(460)
        v = QVBoxLayout(self.cartao)
        v.setContentsMargins(32, 28, 32, 28)
        v.setSpacing(10)
        topo = QHBoxLayout()
        self.titulo = TitleLabel()
        topo.addWidget(self.titulo, 1)
        self.botao_cancelar = PushButton("Cancelar")
        self.botao_cancelar.setIcon(FIF.CLOSE)
        self.botao_cancelar.clicked.connect(self.cancelar)
        topo.addWidget(self.botao_cancelar, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(topo)
        self.publico = CaptionLabel()
        self.publico.setWordWrap(True)
        v.addWidget(self.publico)
        self.visor = VisorVideo()                       # só aparece na etapa do rosto
        self.visor.setFixedHeight(250)
        self.visor.hide()
        v.addWidget(self.visor)
        self.pilha = QStackedWidget()
        self.pilha.addWidget(self._painel_credenciais())
        self.pilha.addWidget(self._painel_progresso())
        self.pilha.addWidget(self._painel_resultado())
        v.addWidget(self.pilha)
        self.cred_titulo.hide()                         # o título do cartão já diz o que é
        self.publico.hide()                             # a frase do painel de credenciais já orienta
        # a pilha reserva a altura do maior painel: os que não estão à vista deixam de pedir
        # espaço, e o cartão acompanha a etapa (sem isso, a janela crescia na etapa do rosto)
        self.pilha.currentChanged.connect(self._ajustar_pilha)
        self._ajustar_pilha(0)
        centro = QHBoxLayout()
        centro.addStretch(1)
        centro.addWidget(self.cartao, 3)
        centro.addStretch(1)
        raiz.addLayout(centro)
        # as camadas do login, abaixo do cartão (só no modo demonstração)
        self.faixa = FaixaCamadas()
        faixa = QHBoxLayout()
        faixa.addStretch(1)
        faixa.addWidget(self.faixa, 3)
        faixa.addStretch(1)
        raiz.addLayout(faixa)
        raiz.addStretch(2)

    def _ajustar_pilha(self, atual: int):
        for i in range(self.pilha.count()):
            politica = QSizePolicy.Policy.Preferred if i == atual else QSizePolicy.Policy.Ignored
            self.pilha.widget(i).setSizePolicy(politica, politica)
        self.pilha.adjustSize()

    def _exibir(self, a):
        super()._exibir(a)
        self.visor.setVisible(a.etapa in (Etapa.ROSTO, Etapa.DESAFIO))
        self.botao_cancelar.setVisible(a.etapa is not Etapa.CREDENCIAIS and a.etapa is not Etapa.CONCLUIDA)
        if a.etapa is Etapa.CONCLUIDA and a.decisao is not None and a.decisao.concedido:
            QTimer.singleShot(600, self._entrar)          # concedido: entra sozinho, sem clique extra
        self._oferecer_emergencia(a)

    def _oferecer_emergencia(self, a):
        """Matrícula e senha certas, rosto ou câmera falhando, e quem tentou é administrador."""
        barrado = None
        if a.etapa is Etapa.CONCLUIDA and self.sessao is not None and a.decisao is not None and not a.decisao.concedido:
            usuario = self.sessao.credenciais_sem_rosto
            if usuario is not None and self.app.administracao.pode_oferecer_emergencia(usuario.id):
                barrado = usuario.id
        self._admin_barrado = barrado
        self.botao_emergencia.setVisible(barrado is not None)


class PaginaEntrada(QWidget):
    entrou = Signal(object)              # a SessaoAutenticacao de entrada, concedida
    emergencia = Signal(object)          # servicos.administracao.Emergencia concedida pelo quórum

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.setObjectName("paginaEntrada")
        self.app = app
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.marca = PainelMarca(app.cfg["aplicacao.nome"])
        h.addWidget(self.marca)
        self.lados = QStackedWidget()
        self.autenticacao = TelaLogin(app, pode_voltar=False)
        self.autenticacao.concedido.connect(self.entrou.emit)
        self.autenticacao.pedir_emergencia.connect(self._abrir_emergencia)
        self.lados.addWidget(self.autenticacao)
        from ecosec.interface.admin_governanca import PaginaEmergencia
        self.tela_emergencia = PaginaEmergencia()
        self.tela_emergencia.concedida.connect(self._emergencia_concedida)
        self.tela_emergencia.voltar.connect(self._voltar_ao_login)
        self.lados.addWidget(self.tela_emergencia)
        h.addWidget(self.lados, 1)

    def iniciar(self):
        self.lados.setCurrentWidget(self.autenticacao)
        self.autenticacao.iniciar(self.app.autenticacao.nova_entrada, "Entrar",
                                  "Informe a sua matrícula e senha.")

    def _abrir_emergencia(self, usuario_id: int):
        sessao = self.app.administracao.nova_emergencia(usuario_id)
        if sessao is None:
            return
        self.autenticacao.encerrar()
        self.tela_emergencia.iniciar(sessao)
        self.lados.setCurrentWidget(self.tela_emergencia)

    def _emergencia_concedida(self, emergencia):
        self.lados.setCurrentWidget(self.autenticacao)
        self.emergencia.emit(emergencia)

    def _voltar_ao_login(self):
        self.iniciar()

    def showEvent(self, evento):
        super().showEvent(evento)
        if self.autenticacao.sessao is None and self.lados.currentWidget() is self.autenticacao:
            self.iniciar()                            # cada vez que a página aparece, um login novo

    def resizeEvent(self, evento):
        self.marca.setVisible(evento.size().width() >= LARGURA_COM_MARCA)
        super().resizeEvent(evento)

    def encerrar(self):
        self.autenticacao.encerrar()
        self.tela_emergencia.sessao = None
