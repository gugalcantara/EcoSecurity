"""Página de teste da câmera, na configuração inicial."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ecosec.interface.estilo import cor_texto_secundario
from ecosec.interface.fluent import FIF, BodyLabel, CaptionLabel, PrimaryPushButton, PushButton, TitleLabel
from ecosec.interface.video import TrabalhadorVideo, VisorVideo


def orientacao(resultado) -> str:
    """O que a pessoa vê abaixo do vídeo: a mesma orientação do login, ou que a imagem está adequada."""
    if resultado.dica:
        return resultado.dica + "."
    return "Imagem adequada para o reconhecimento." if resultado.qualidade_aprovada else ""


class PaginaTesteCamera(QWidget):
    continuar = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.setObjectName("paginaTesteCamera")
        self.app = app
        self.trabalhador: TrabalhadorVideo | None = None
        self._montar()

    def _montar(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 16, 24, 16)
        raiz.setSpacing(12)
        raiz.addWidget(TitleLabel("Testar a câmera"))
        intro = CaptionLabel("Confira a sua imagem antes da configuração. Ninguém é reconhecido e nada é gravado.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{cor_texto_secundario()};")
        raiz.addWidget(intro)
        self.visor = VisorVideo()
        raiz.addWidget(self.visor, 1)
        self.situacao = BodyLabel()                       # a orientação do quadro ou o erro da câmera
        self.situacao.setWordWrap(True)
        raiz.addWidget(self.situacao)
        botoes = QHBoxLayout()
        self.botao_camera = PrimaryPushButton("Ligar a câmera")
        self.botao_camera.setIcon(FIF.CAMERA)
        self.botao_camera.clicked.connect(self._alternar)
        self.botao_continuar = PushButton("Continuar")
        self.botao_continuar.setIcon(FIF.RIGHT_ARROW)
        self.botao_continuar.clicked.connect(self._continuar)
        botoes.addWidget(self.botao_camera)
        botoes.addWidget(self.botao_continuar)
        botoes.addStretch(1)
        raiz.addLayout(botoes)

    # câmera
    @property
    def ligada(self) -> bool:
        return self.trabalhador is not None

    def _alternar(self):
        if self.ligada:
            self._desligar()
        else:
            self._ligar()

    def _ligar(self):
        self.trabalhador = TrabalhadorVideo(self.app.nova_camera(), self.app.novo_pipeline(), parent=self)
        self.trabalhador.quadro.connect(self._ao_quadro)
        self.trabalhador.falhou.connect(self._ao_falhar)
        self.trabalhador.start()
        self.botao_camera.setText("Desligar a câmera")
        self.situacao.setText("Ligando a câmera…")

    def _desligar(self, texto: str = "Câmera desligada"):
        if self.trabalhador is not None:
            trabalhador, self.trabalhador = self.trabalhador, None
            trabalhador.quadro.disconnect(self._ao_quadro)
            trabalhador.parar()
            trabalhador.deleteLater()
        self.botao_camera.setText("Ligar a câmera")
        self.visor.limpar(texto)
        self.situacao.setText("")

    def _ao_quadro(self, imagem, resultado, _retorno):
        self.visor.mostrar(imagem, resultado)
        self.situacao.setText(orientacao(resultado))

    def _ao_falhar(self, mensagem: str):
        self._desligar("Câmera indisponível")
        self.situacao.setText(mensagem)

    def _continuar(self):
        self._desligar()
        self.continuar.emit()

    def encerrar(self):
        """Desliga a câmera (troca de página ou janela fechando)."""
        self._desligar()

    def hideEvent(self, evento):
        if not evento.spontaneous():                      # trocou de página: a câmera não fica ligada sem ninguém
            self.encerrar()
        super().hideEvent(evento)
