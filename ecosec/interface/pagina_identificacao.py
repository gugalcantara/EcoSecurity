"""Identificação facial: o sistema diz quem está diante da câmera, comparando o rosto com todos os
cadastros (1:N). Não concede nada: identificar não é autenticar, e o login continua o mesmo.

Quem vê: só o ADMINISTRADOR, numa seção do painel de Administração (: identidade de pessoas é gestão de
acesso, não acervo). O painel já conferiu o rosto e o código do celular; trancar o painel, sair da seção, encerrar
a sessão ou o bloqueio por inatividade desligam a câmera. O serviço recusa quem não é administrador.

A vista mostra o vídeo e, na decisão, os 3 cadastros mais parecidos com a distância, a decisão e o tempo do
primeiro rosto até ela. Quem decide é o serviço (app.identificacao): a tela não compara nada. A matrícula nunca
aparece; o nome de quem não tem cadastro válido também não.

As etapas internas da visão (recorte, face normalizada, padrão LBP) não são mostradas:
expor como o processamento é feito por dentro não cabe na tela de uso.
"""
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ecosec.interface.estilo import AMBAR, VERDE, VERMELHO, cor_texto_secundario
from ecosec.interface.fluent import (FIF, BodyLabel, CaptionLabel, InfoBar, InfoBarPosition, PrimaryPushButton,
                                     ProgressBar, SimpleCardWidget, StrongBodyLabel, SubtitleLabel, TitleLabel)
from ecosec.interface.video import TrabalhadorVideo, VisorVideo


def _numero(valor: float, casas: int = 1) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


class VistaIdentificacao(QWidget):
    """Vídeo, decisão e os 3 mais parecidos."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.sessao = None
        self.trabalhador: TrabalhadorVideo | None = None
        self._operador = None
        self._congelado = False               # decidido: o vídeo fica no quadro que gerou a decisão
        # distâncias, limiar, candidatos e tempo só aparecem com [interface] modo_demonstracao = true
        self.modo_demonstracao = bool(app.cfg["interface.modo_demonstracao"])
        self._montar()

    # layout
    def _montar(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 16, 24, 16)
        raiz.setSpacing(12)
        raiz.addWidget(TitleLabel("Identificação facial"))
        intro = CaptionLabel("Identifica a pessoa diante da câmera entre os cadastros. Não concede acesso.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{cor_texto_secundario()};")
        raiz.addWidget(intro)

        corpo = QHBoxLayout()
        corpo.setSpacing(16)
        self.visor = VisorVideo()
        corpo.addWidget(self.visor, 3)
        corpo.addWidget(self._painel_decisao(), 2)
        raiz.addLayout(corpo, 1)

    def _painel_decisao(self):
        painel = SimpleCardWidget()
        painel.setMinimumWidth(330)
        painel.setMaximumWidth(440)
        v = QVBoxLayout(painel)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(8)
        self.mensagem = SubtitleLabel()
        self.mensagem.setWordWrap(True)
        self.barra = ProgressBar()
        self.barra.setRange(0, 100)
        self.titulo_decisao = TitleLabel()
        self.texto_decisao = BodyLabel()
        self.texto_decisao.setWordWrap(True)
        self.titulo_candidatos = StrongBodyLabel("Os 3 cadastros mais parecidos")
        self.linhas_candidatos = [BodyLabel() for _ in range(3)]
        explicacao = CaptionLabel("Distância LBPH: quanto menor, mais parecido. Só é identificado quem fica abaixo "
                                  "do limiar em vários quadros seguidos.")
        explicacao.setVisible(self.modo_demonstracao)
        explicacao.setWordWrap(True)
        explicacao.setStyleSheet(f"color:{cor_texto_secundario()};")
        self.tempo = CaptionLabel()
        self.botao_repetir = PrimaryPushButton("Identificar de novo")
        self.botao_repetir.setIcon(FIF.SYNC)
        self.botao_repetir.clicked.connect(self._nova_sessao)
        aviso = CaptionLabel("As identificações são registradas na trilha de auditoria.")
        aviso.setWordWrap(True)
        aviso.setStyleSheet(f"color:{cor_texto_secundario()};")
        for item in (self.mensagem, self.barra, self.titulo_decisao, self.texto_decisao, self.titulo_candidatos,
                     *self.linhas_candidatos, explicacao, self.tempo, self.botao_repetir, aviso):
            v.addWidget(item)
        v.addStretch(1)
        return painel

    # fluxo
    def iniciar(self, operador_id: int):
        """operador_id: quem está logado (vai para a trilha como quem pediu a identificação)."""
        self._operador = operador_id
        self._nova_sessao()

    def _nova_sessao(self):
        if self._operador is None:
            return
        self._parar_video()
        try:
            self.sessao = self.app.identificacao.nova_sessao(self._operador)
        except Exception as erro:  # noqa: BLE001, o serviço recusou (só o administrador identifica)
            self.sessao = None
            self.visor.limpar(str(erro))
            return
        self._congelado = False               # de novo ao vivo
        self._limpar()
        self.visor.limpar("Ligando a câmera…")
        self._exibir(self.sessao.andamento)
        self._ligar_video()

    def _limpar(self):
        for item in (self.titulo_decisao, self.texto_decisao, self.titulo_candidatos, *self.linhas_candidatos,
                     self.tempo):
            item.hide()
        self.barra.setValue(0)

    def _ao_quadro(self, imagem, resultado, andamento):
        if self.sessao is None or self._congelado:
            return                            # um quadro atrasado na fila do sinal não troca o congelado
        self.visor.mostrar(imagem, resultado)
        if andamento is None:
            return
        self._exibir(andamento)

    def _exibir(self, a):
        self.mensagem.setText(a.mensagem)
        self.barra.setValue(int(a.progresso * 100))
        if not a.concluida:
            return
        self._congelado = True                # o visor guarda o último quadro mostrado: o da decisão
        self._parar_video()
        limiar = _numero(a.limiar, 0)
        if a.identificado:
            titulo, cor = "Identificado", VERDE
            texto = (f"{a.nome} · distância {_numero(a.distancia)} (limiar {limiar})" if self.modo_demonstracao
                     else a.nome)
            self.mensagem.setText(f"Identificado como {a.nome}")
        elif a.sem_rosto:
            titulo, cor = "Sem rosto", AMBAR
            texto = f"{a.mensagem} Centralize o rosto e tente de novo."
            self.mensagem.setText(titulo)
        else:
            titulo, cor = "Não reconhecido", VERMELHO
            self.mensagem.setText(titulo)
            if a.distancia is None:
                texto = "Nenhum cadastro para comparar."
            elif self.modo_demonstracao:
                texto = f"Menor distância vista: {_numero(a.distancia)} · limiar {limiar}"
            else:
                texto = "Nenhum cadastro corresponde a este rosto."
        self.titulo_decisao.setText(titulo)
        self.titulo_decisao.setStyleSheet(f"color:{cor};")
        self.texto_decisao.setText(texto)
        self.titulo_decisao.show()
        self.texto_decisao.show()
        candidatos = a.candidatos if self.modo_demonstracao else ()
        self.titulo_candidatos.setVisible(bool(candidatos))
        for i, linha in enumerate(self.linhas_candidatos):
            if i < len(candidatos):
                c = a.candidatos[i]
                linha.setText(f"{i + 1}. {c.nome or 'Não reconhecido'} · distância {_numero(c.distancia)}")
                dentro = c.nome is not None and c.distancia <= a.limiar
                linha.setStyleSheet(f"color:{VERDE};" if dentro else "")
                linha.show()
            else:
                linha.hide()
        if a.segundos is not None and self.modo_demonstracao:
            self.tempo.setText(f"Tempo do primeiro rosto até a decisão: {_numero(a.segundos)} s")
            self.tempo.show()

    def _ao_falhar(self, mensagem):
        self._parar_video()
        self.visor.limpar("Câmera indisponível")
        InfoBar.error("Câmera", mensagem, duration=6000, position=InfoBarPosition.TOP, parent=self)

    # vídeo
    def _ligar_video(self):
        if self.trabalhador is not None or self.sessao is None:
            return
        self.trabalhador = TrabalhadorVideo(self.app.nova_camera(), self.app.novo_pipeline(),
                                            processar=self.sessao.processar, parent=self)
        self.trabalhador.quadro.connect(self._ao_quadro)
        self.trabalhador.falhou.connect(self._ao_falhar)
        self.trabalhador.start()

    def _parar_video(self):
        if self.trabalhador is not None:
            trabalhador, self.trabalhador = self.trabalhador, None
            trabalhador.quadro.disconnect(self._ao_quadro)
            trabalhador.parar()
            trabalhador.deleteLater()

    def encerrar(self):
        self._parar_video()
        self.sessao = None
        self._operador = None
        self._congelado = False
        self._limpar()
        self.visor.limpar()
