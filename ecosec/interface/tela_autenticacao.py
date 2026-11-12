"""Tela de autenticação: conduz uma SessaoAutenticacao e mostra o andamento.

Toda decisão é do serviço. A tela:
  - coleta matrícula e senha (níveis 2 e 3) e entrega ao serviço;
  - liga o vídeo, cujos quadros a thread de vídeo passa ao serviço;
  - mostra o que o serviço devolve (Andamento): camadas, distância × limiar,
    tempo restante, gesto pedido e, no fim, a decisão.

Mostrar a distância ao lado do limiar é didático: vê-la cair enquanto o rosto
se estabiliza deixa claro que o LBPH mede distância: menor é melhor.

A mesma tela conduz o login de entrada, o step-up do N3 e a conferência do
administrador: quem a usa entrega uma fábrica de sessões (para "Tentar de
novo" criar outra igual) e os textos do cabeçalho.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.interface.componentes import FaixaCamadas, camadas_avaliadas, linha_rotulada
from ecosec.interface.estilo import COR_NIVEL, VERDE, VERMELHO, cor_texto_secundario
from ecosec.interface.fluent import (FIF, BodyLabel, CaptionLabel, IconWidget, InfoBar, InfoBarPosition,
                                     LineEdit, MessageBox, PasswordLineEdit, PrimaryPushButton, ProgressBar,
                                     PushButton, SimpleCardWidget, StrongBodyLabel, SubtitleLabel, TitleLabel,
                                     TransparentPushButton)
from ecosec.interface.video import TrabalhadorVideo, VisorVideo
from ecosec.servicos.autenticacao import Etapa


ESQUECI_MATRICULA = ("A matrícula consta no termo de consentimento entregue no cadastro. "
                     "Se não o tiver, procure o administrador.")


class TelaAutenticacao(QWidget):
    concedido = Signal(object)               # a SessaoAutenticacao concluída com acesso concedido
    voltar = Signal()

    def __init__(self, app, parent=None, *, pode_voltar: bool = True):
        super().__init__(parent)
        self.app = app
        self.sessao = None
        self.nivel = None
        self._fabrica = None
        self._pode_voltar = pode_voltar
        self.trabalhador: TrabalhadorVideo | None = None
        self._estado_anterior = None
        # Distância, limiar e camadas avaliadas explicam o método, mas orientam quem tenta
        # enganar o sistema. Só aparecem com [interface] modo_demonstracao = true.
        self.modo_demonstracao = bool(self.app.cfg["interface.modo_demonstracao"])
        self._montar()
        self.faixa.setVisible(self.modo_demonstracao)
        self.res_detalhe.setVisible(self.modo_demonstracao)

    # ============================================================ layout
    def _montar(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 16, 24, 16)
        raiz.setSpacing(12)

        topo = QHBoxLayout()
        self.titulo = TitleLabel()
        self.publico = CaptionLabel()
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(self.titulo)
        textos.addWidget(self.publico)
        topo.addLayout(textos, 1)
        self.botao_cancelar = PushButton("Cancelar")
        self.botao_cancelar.setIcon(FIF.CLOSE)
        self.botao_cancelar.clicked.connect(self.cancelar)
        topo.addWidget(self.botao_cancelar, 0, Qt.AlignmentFlag.AlignTop)
        raiz.addLayout(topo)

        self.faixa = FaixaCamadas()
        raiz.addWidget(self.faixa)

        corpo = QHBoxLayout()
        corpo.setSpacing(16)
        self.visor = VisorVideo()
        corpo.addWidget(self.visor, 3)

        self.painel = SimpleCardWidget()
        self.painel.setMinimumWidth(330)
        self.painel.setMaximumWidth(420)
        self.pilha = QStackedWidget(self.painel)
        caixa = QVBoxLayout(self.painel)
        caixa.setContentsMargins(20, 20, 20, 20)
        caixa.addWidget(self.pilha)
        self.pilha.addWidget(self._painel_credenciais())
        self.pilha.addWidget(self._painel_progresso())
        self.pilha.addWidget(self._painel_resultado())
        corpo.addWidget(self.painel, 2)
        raiz.addLayout(corpo, 1)

    def _painel_credenciais(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(14)
        self.cred_titulo = SubtitleLabel("Identificação")
        self.cred_texto = BodyLabel()
        self.cred_texto.setWordWrap(True)
        self.campo_matricula = LineEdit()
        self.campo_matricula.setPlaceholderText("Ex.: R7K2M94")
        self.campo_matricula.setMaxLength(20)
        self.campo_senha = PasswordLineEdit()
        self.campo_senha.setPlaceholderText("Sua senha")
        self.campo_senha.returnPressed.connect(self._enviar_credenciais)
        self.campo_matricula.returnPressed.connect(self.campo_senha.setFocus)
        self.botao_continuar = PrimaryPushButton("Continuar")
        self.botao_continuar.setIcon(FIF.RIGHT_ARROW)
        self.botao_continuar.clicked.connect(self._enviar_credenciais)
        self.botao_esqueci = TransparentPushButton("Esqueci minha matrícula")
        self.botao_esqueci.clicked.connect(lambda: MessageBox("Esqueci minha matrícula", ESQUECI_MATRICULA,
                                                              self.window()).exec())
        for item in (self.cred_titulo, self.cred_texto, linha_rotulada("Matrícula", self.campo_matricula),
                     linha_rotulada("Senha", self.campo_senha), self.botao_continuar, self.botao_esqueci):
            v.addWidget(item)
        v.addStretch(1)
        return w

    def _painel_progresso(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)
        self.prog_etapa = CaptionLabel()
        self.prog_mensagem = SubtitleLabel()
        self.prog_mensagem.setWordWrap(True)
        self.prog_barra = ProgressBar()
        self.prog_barra.setRange(0, 100)
        self.prog_distancia = StrongBodyLabel()
        self.prog_ajuda = CaptionLabel("Distância LBPH: quanto menor, mais parecido. "
                                       "O acesso exige ficar abaixo do limiar do nível.")
        self.prog_ajuda.setWordWrap(True)
        self.prog_ajuda.setStyleSheet(f"color:{cor_texto_secundario()};")
        self.prog_tempo = CaptionLabel()
        self.prog_distancia.setVisible(self.modo_demonstracao)
        self.prog_ajuda.setVisible(self.modo_demonstracao)
        for item in (self.prog_etapa, self.prog_mensagem, self.prog_barra, self.prog_distancia,
                     self.prog_ajuda, self.prog_tempo):
            v.addWidget(item)
        v.addStretch(1)
        return w

    def _painel_resultado(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)
        self.res_icone = IconWidget()
        self.res_icone.setFixedSize(56, 56)
        self.res_titulo = TitleLabel()
        self.res_texto = BodyLabel()
        self.res_texto.setWordWrap(True)
        self.res_detalhe = CaptionLabel()
        self.res_detalhe.setWordWrap(True)
        self.res_detalhe.setStyleSheet(f"color:{cor_texto_secundario()};")
        self.botao_entrar = PrimaryPushButton("Continuar")
        self.botao_entrar.setIcon(FIF.ACCEPT)
        self.botao_entrar.clicked.connect(self._entrar)
        self.botao_repetir = PrimaryPushButton("Tentar novamente")
        self.botao_repetir.setIcon(FIF.SYNC)
        self.botao_repetir.clicked.connect(self._repetir)
        self.botao_voltar = PushButton("Voltar ao início")
        self.botao_voltar.clicked.connect(self._sair)
        # só o login de entrada o mostra, e só no caso combinado (ver TelaLogin)
        self.botao_emergencia = TransparentPushButton("Acesso de emergência")
        self.botao_emergencia.hide()
        for item in (self.res_icone, self.res_titulo, self.res_texto, self.res_detalhe,
                     self.botao_entrar, self.botao_repetir, self.botao_voltar, self.botao_emergencia):
            v.addWidget(item)
        v.addStretch(1)
        return w

    # ============================================================ fluxo
    def iniciar(self, fabrica, titulo: str, subtitulo: str, cor: str | None = None):
        """`fabrica()` cria a SessaoAutenticacao (de novo a cada "Tentar novamente")."""
        self._parar_video()
        self._fabrica, self._cabecalho = fabrica, (titulo, subtitulo, cor)
        self.sessao = fabrica()
        self.nivel = self.sessao.nivel
        self.titulo.setText(titulo)
        # setTextColor, e não folha de estilo: limpar a folha deixa o rótulo Fluent
        # preto no tema escuro; sem cor própria, volta às cores do tema
        claro, escuro = (QColor(cor), QColor(cor)) if cor else (QColor(0, 0, 0), QColor(255, 255, 255))
        self.titulo.setTextColor(claro, escuro)
        self.publico.setText(subtitulo)
        self.faixa.definir(self.sessao.andamento.camadas)
        self.visor.limpar("A câmera liga depois da identificação"
                          if self.sessao.andamento.etapa is Etapa.CREDENCIAIS else "Ligando a câmera…")
        self.botao_cancelar.setEnabled(True)
        self.botao_voltar.setVisible(self._pode_voltar)
        self._estado_anterior = None
        self._exibir(self.sessao.andamento)

    def iniciar_nivel(self, nivel: int, identidade=None):
        """Acesso a um nível (com `identidade`, step-up a partir do login de entrada)."""
        nivel = Nivel(nivel)
        self.iniciar(lambda: self.app.autenticacao.nova_sessao(nivel, identidade=identidade),
                     f"Nível {nivel.value} · {nivel.titulo}",
                     f"{nivel.publico} · reconhecimento {nivel.modo.value}", COR_NIVEL[nivel])

    def _repetir(self):
        if self._fabrica is not None:
            self.iniciar(self._fabrica, *self._cabecalho)

    def _enviar_credenciais(self):
        if self.sessao is None or self.sessao.andamento.etapa is not Etapa.CREDENCIAIS:
            return
        matricula, senha = self.campo_matricula.text(), self.campo_senha.text()
        self.campo_senha.clear()                      # a senha não fica na tela
        if not matricula.strip() or not senha:
            InfoBar.warning("Campos vazios", "Informe a matrícula e a senha.", duration=3000,
                            position=InfoBarPosition.TOP, parent=self)
            return
        self.botao_continuar.setEnabled(False)
        try:
            andamento = self.sessao.informar_credenciais(matricula, senha)   # bcrypt: ~0,25 s
        finally:
            self.botao_continuar.setEnabled(True)
        self._exibir(andamento)

    def _ao_quadro(self, imagem, resultado, andamento):
        if self.sessao is None:
            return
        self.visor.mostrar(imagem, resultado)
        if andamento is not None:
            self._exibir(andamento)

    def _ao_falhar(self, mensagem):
        if self.sessao and self.sessao.andamento.etapa is not Etapa.CONCLUIDA:
            self.sessao.cancelar()                    # falha segura: tentativa encerrada
        self._parar_video()
        self.visor.limpar("Câmera indisponível")
        InfoBar.error("Câmera", mensagem, duration=6000, position=InfoBarPosition.TOP, parent=self)
        self._exibir(self.sessao.andamento)

    def _exibir(self, a):
        negada = a.decisao.camada_que_negou if a.decisao else None
        self.faixa.atualizar(a.aprovadas, a.atual, negada)
        # o vídeo manda um Andamento a cada quadro; o formulário só é preparado
        # quando a etapa muda: senão apagaria o que a pessoa está digitando
        mudou = (a.etapa, a.pessoa) != self._estado_anterior
        self._estado_anterior = (a.etapa, a.pessoa)
        if a.etapa is Etapa.CREDENCIAIS:
            if mudou:
                self.pilha.setCurrentIndex(0)
                segunda = a.pessoa == 2
                self.cred_titulo.setText("Segunda pessoa (regra dos dois)" if segunda else "Identificação")
                self.cred_texto.setText(a.mensagem)
                self.campo_matricula.clear()
                self.campo_matricula.setFocus()
        elif a.etapa in (Etapa.ROSTO, Etapa.DESAFIO):
            self._ligar_video()
            self.pilha.setCurrentIndex(1)
            self._exibir_progresso(a)
        else:
            self._parar_video()
            self._exibir_resultado(a)

    def _exibir_progresso(self, a):
        pessoa = "Segunda pessoa · " if a.pessoa == 2 else ""
        if a.etapa is Etapa.DESAFIO:
            self.prog_etapa.setText(f"{pessoa}Gesto {a.desafio_indice} de {a.desafio_total}")
        else:
            self.prog_etapa.setText(f"{pessoa}Reconhecimento facial")
        self.prog_mensagem.setText(a.mensagem)
        self.prog_barra.setValue(int(a.progresso * 100))
        if a.distancia is not None and a.limiar is not None:
            dentro = a.distancia <= a.limiar
            cor = VERDE if dentro else VERMELHO
            self.prog_distancia.setText(f"Distância {a.distancia:.1f}  ·  limiar {a.limiar:.1f}")
            self.prog_distancia.setStyleSheet(f"color:{cor};")
        else:
            self.prog_distancia.setText(f"Limiar do nível: {a.limiar:.1f}" if a.limiar else "")
            self.prog_distancia.setStyleSheet("")
        self.prog_tempo.setText(f"Tempo restante: {a.segundos_restantes:.0f} s"
                                if a.segundos_restantes is not None else "")

    def _exibir_resultado(self, a):
        self.pilha.setCurrentIndex(2)
        self.botao_cancelar.setEnabled(False)
        concedido = bool(a.decisao and a.decisao.concedido)
        self.res_icone.setIcon(FIF.ACCEPT_MEDIUM if concedido else FIF.CANCEL_MEDIUM)
        self.res_titulo.setText("Acesso concedido" if concedido else
                                ("Tentativa cancelada" if a.cancelada else "Acesso negado"))
        self.res_titulo.setStyleSheet(f"color:{VERDE if concedido else VERMELHO};")
        texto = (a.mensagem if not a.cancelada else
                 "Tentativa encerrada.")
        if a.bloqueado_ate is not None:
            if a.decisao and a.decisao.motivo is Motivo.BLOQUEADO:
                texto += f" Liberado a partir das {a.bloqueado_ate:%H:%M}."
            else:                                     # foi esta tentativa que bloqueou
                texto += f" Matrícula bloqueada até as {a.bloqueado_ate:%H:%M}."
        self.res_texto.setText(texto)
        if a.decisao:
            self.res_detalhe.setText(camadas_avaliadas(a.decisao.vereditos))
        self.botao_entrar.setVisible(concedido)
        self.botao_repetir.setVisible(not concedido)
        self.visor.limpar("Acesso concedido" if concedido else "Câmera desligada")

    # ============================================================ vídeo
    def _ligar_video(self):
        if self.trabalhador is not None:
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

    # ============================================================ saídas
    def cancelar(self):
        if self.sessao is not None and self.sessao.andamento.etapa is not Etapa.CONCLUIDA:
            self._exibir(self.sessao.cancelar())
        else:
            self._sair()

    def encerrar(self):
        """Chamado quando a tela some (troca de página, fechar janela)."""
        if self.sessao is not None and self.sessao.andamento.etapa is not Etapa.CONCLUIDA:
            self.sessao.cancelar()
        self._parar_video()
        self.sessao = None

    def hideEvent(self, evento):
        # sumiu da tela (troca de aba): nenhuma tentativa fica aberta sem ninguém
        # olhando. Minimizar a janela (evento espontâneo) não cancela.
        if not evento.spontaneous():
            self.encerrar()
        super().hideEvent(evento)

    def _entrar(self):
        sessao = self.sessao
        concedida = sessao is not None and sessao.andamento.decisao is not None and sessao.andamento.decisao.concedido
        self.encerrar()
        if concedida:
            self.concedido.emit(sessao)

    def _sair(self):
        self.encerrar()
        self.voltar.emit()
