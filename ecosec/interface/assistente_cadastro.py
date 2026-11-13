"""Assistente de cadastro: Preparação -> Termo -> Dados -> Rosto -> Concluído.

Regras que a tela garante (as de negócio estão no ServicoCadastro):
- Preparação: o administrador confirma os requisitos (pessoa presente, maior
  de 18, luz e câmera livres) antes de qualquer coisa. Evita começar um
  cadastro que vai falhar no meio.
- Termo: resumo em linguagem simples, texto completo e duas marcações
  (finalidade a, obrigatória; b, opcional). "Concordo" só habilita depois de o
  texto ser lido até o fim, da finalidade (a) marcada e da assinatura com
  nome e sobrenome. "Não concordo" encerra sem coletar nada.
- Dados: a própria pessoa digita a senha (o administrador não deve conhecê-la);
  os erros aparecem ao lado do formulário.
- Rosto: a câmera só liga quando a pessoa clica em "Iniciar captura".
- Cancelar depois do aceite pede confirmação; qualquer saída (cancelar, trocar
  de página, fechar a janela) passa por encerrar(), que apaga as faces.
"""
import math
import time

from PySide6.QtCore import QMarginsF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout,
                               QWidget)

from ecosec.dominio.entidades import UFS
from ecosec.dominio.perfis import Perfil
from ecosec.interface.componentes import ChecklistSenha, linha_rotulada
from ecosec.interface.estilo import AMBAR, COR_NIVEL, VERDE, VERMELHO, cor_texto_secundario
from ecosec.interface.fluent import (FIF, BodyLabel, CaptionLabel, CheckBox, ComboBox, DisplayLabel, InfoBar,
                                     InfoBarPosition, LineEdit, MessageBox, PasswordLineEdit, PrimaryPushButton,
                                     ProgressBar, PushButton, ScrollArea, SimpleCardWidget, StrongBodyLabel,
                                     SubtitleLabel, TitleLabel, themeColor)
from ecosec.interface.video import TrabalhadorVideo, VisorVideo
from ecosec.servicos.cadastro import DadosCadastro, ErroCadastro

PASSOS = ("Preparação", "Termo", "Dados", "Rosto", "Concluído")
# o que cada perfil faz, para quem cadastra escolher (só o próprio escopo de cada um)
DESCRICAO_PERFIL = {
    Perfil.EXTERNO: "Fora do quadro do governo. Não acessa o acervo. Administradores têm este perfil.",
    Perfil.SERVIDOR: "Estatísticas agregadas, sem localização; regiões sensíveis suprimidas. Exportação livre.",
    Perfil.DIRETOR: "Registros da própria UF, com a cadeia de responsabilidade. Exporta com marca d'água.",
    Perfil.MINISTRO: "Visão nacional da custódia, matriz de criticidade e fila do orçamento público. Só visualização.",
}
# o termo é apresentado como folha de documento: clara nos dois temas, serifada
# e com largura de leitura (linhas longas demais cansam e fazem pular linha)
LARGURA_FOLHA = 860
COR_FOLHA, COR_TINTA = "#fbfbf8", "#1b1b1b"
FONTE_DOCUMENTO = "Georgia"
PREPARACAO, TERMO, DADOS, ROSTO, FIM = range(5)

REQUISITOS = (
    "A pessoa a ser cadastrada está presente, diante da câmera.",
    "A pessoa tem 18 anos ou mais (art. 14 da LGPD).",
    "O rosto está bem iluminado e a câmera não está em uso por outro programa.",
)


def _texto_secundario(texto: str) -> CaptionLabel:
    rotulo = CaptionLabel(texto)
    rotulo.setWordWrap(True)
    rotulo.setStyleSheet(f"color:{cor_texto_secundario()};")
    return rotulo


class AssistenteCadastro(QWidget):
    finalizado = Signal(object)          # Usuario criado (ou o recadastrado), ou None se cancelado

    def __init__(self, app, parent=None, *, recadastro=None, perfis=tuple(Perfil)):
        """recadastro (um Usuario): só troca o rosto, pelo acesso de emergência. O termo e a senha
        continuam os mesmos: da Preparação vai direto ao Rosto. perfis: os que o formulário oferece (na
        configuração inicial, só o Externo: o primeiro cadastro vira o primeiro administrador)."""
        super().__init__(parent)
        self.app = app
        self.servico = app.cadastro
        self.recadastro = recadastro
        self.perfis = tuple(perfis)
        self.aceite = None
        self.dados: DadosCadastro | None = None
        self.coleta = None
        self.usuario = None
        self.trabalhador: TrabalhadorVideo | None = None
        self._montar()

    # layout
    def _montar(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 12, 24, 16)
        raiz.setSpacing(10)
        topo = QHBoxLayout()
        topo.addWidget(TitleLabel(f"Recadastrar rosto · {self.recadastro.nome}" if self.recadastro
                                  else "Novo cadastro"), 1)
        self.botao_cancelar = PushButton("Cancelar cadastro")
        self.botao_cancelar.setIcon(FIF.CLOSE)
        self.botao_cancelar.clicked.connect(self.cancelar)
        topo.addWidget(self.botao_cancelar)
        raiz.addLayout(topo)

        indicador = QHBoxLayout()
        self.rotulos_passos = []
        for i, nome in enumerate(PASSOS, 1):
            rotulo = StrongBodyLabel(f"{i}  {nome}")
            self.rotulos_passos.append(rotulo)
            indicador.addWidget(rotulo)
            if i < len(PASSOS):
                indicador.addWidget(CaptionLabel("  ›  "))
        indicador.addStretch(1)
        raiz.addLayout(indicador)

        self.pilha = QStackedWidget()
        for construtor in (self._passo_preparacao, self._passo_termo, self._passo_dados, self._passo_rosto,
                           self._passo_fim):
            self.pilha.addWidget(construtor())
        raiz.addWidget(self.pilha, 1)
        self._ir(PREPARACAO)

    def _ir(self, indice):
        self.pilha.setCurrentIndex(indice)
        if indice == TERMO:
            self._iniciar_leitura()
        for i, rotulo in enumerate(self.rotulos_passos):
            cor = QColor(VERDE if i < indice else (themeColor().name() if i == indice else cor_texto_secundario()))
            rotulo.setTextColor(cor, cor)

    # passo 1: preparação
    def _passo_preparacao(self):
        w = SimpleCardWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(12)
        v.addWidget(SubtitleLabel("Antes de começar"))
        v.addWidget(BodyLabel("Etapas: termo de consentimento, dados e senha, captura do rosto e matrícula."))
        v.addSpacing(6)
        v.addWidget(StrongBodyLabel("Confirme os requisitos:"))
        self.requisitos = []
        for texto in REQUISITOS:
            caixa = CheckBox(texto)
            caixa.stateChanged.connect(self._requisitos_mudaram)
            self.requisitos.append(caixa)
            v.addWidget(caixa)
        v.addSpacing(6)
        aviso = BodyLabel("A senha é digitada pela própria pessoa cadastrada.")
        aviso.setWordWrap(True)
        aviso.setStyleSheet(f"color:{AMBAR};")
        v.addWidget(aviso)
        v.addStretch(1)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        self.botao_comecar = PrimaryPushButton("Começar")
        self.botao_comecar.setIcon(FIF.RIGHT_ARROW)
        self.botao_comecar.setEnabled(False)
        self.botao_comecar.setToolTip("Marque os três requisitos para começar.")
        self.botao_comecar.clicked.connect(self._comecar)
        botoes.addWidget(self.botao_comecar)
        v.addLayout(botoes)
        return w

    def _comecar(self):
        if self.recadastro is None:
            self._ir(TERMO)
            return
        try:
            self.coleta = self.servico.nova_coleta_recadastro(self.recadastro.id)
        except ErroCadastro as erro:
            InfoBar.error("Recadastro", str(erro), duration=6000, position=InfoBarPosition.TOP, parent=self)
            return
        self._preparar_sessao()
        self._ir(ROSTO)

    def _requisitos_mudaram(self, *_):
        prontos = all(c.isChecked() for c in self.requisitos)
        self.botao_comecar.setEnabled(prontos)
        self.botao_comecar.setToolTip("" if prontos else "Marque os três requisitos para começar.")

    # passo 2: termo
    def _passo_termo(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # o termo é uma folha de documento que ocupa a página, e a rolagem é a da
        # página inteira
        self.rolagem_termo = ScrollArea()
        self.rolagem_termo.setWidgetResizable(True)
        self.rolagem_termo.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        conteudo = QWidget()
        conteudo.setStyleSheet("background: transparent;")
        self.rolagem_termo.setWidget(conteudo)
        externo = QHBoxLayout(conteudo)        # folha centralizada; em janela estreita, ela encolhe
        externo.setContentsMargins(0, 0, 12, 0)
        pagina = QWidget()
        pagina.setMaximumWidth(LARGURA_FOLHA)
        externo.addStretch(1)
        externo.addWidget(pagina, 100)
        externo.addStretch(1)
        coluna = QVBoxLayout(pagina)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(14)

        folha = QFrame()
        folha.setObjectName("folhaTermo")
        folha.setStyleSheet(f"#folhaTermo {{ background:{COR_FOLHA}; border-radius:6px; }}")
        vf = QVBoxLayout(folha)
        vf.setContentsMargins(56, 44, 56, 44)
        self.texto_termo = QLabel()
        self.texto_termo.setTextFormat(Qt.TextFormat.RichText)
        self.texto_termo.setWordWrap(True)
        self.texto_termo.setFont(QFont(FONTE_DOCUMENTO, 11))
        self.texto_termo.setStyleSheet(f"color:{COR_TINTA}; background:transparent;")
        self.texto_termo.setText(self.servico.termo_html(""))
        vf.addWidget(self.texto_termo)
        coluna.addWidget(folha)

        # manifestação do titular: no FIM do documento, como se assina um papel
        manifestacao = SimpleCardWidget()
        vm = QVBoxLayout(manifestacao)
        vm.setContentsMargins(24, 18, 24, 18)
        vm.setSpacing(10)
        vm.addWidget(SubtitleLabel("Manifestação do titular"))
        self.check_lido = CheckBox("Li e compreendi integralmente este Termo")
        self.check_lido.setEnabled(False)
        # rótulos curtos (a caixa de marcação não quebra linha): a redação
        # completa de cada finalidade está na Cláusula 3ª, logo acima
        self.check_finalidade_a = CheckBox("(a) Autorizo a autenticação pela minha imagem facial (obrigatória)")
        self.check_finalidade_b = CheckBox("(b) Autorizo o uso estatístico, sem identificação nominal (opcional)")
        self.campo_assinatura = LineEdit()
        self.campo_assinatura.setPlaceholderText("Nome completo da pessoa titular da imagem")
        for sinal in (self.check_lido.stateChanged, self.check_finalidade_a.stateChanged,
                      self.check_finalidade_b.stateChanged):
            sinal.connect(self._atualizar_aceite)
        self.campo_assinatura.textChanged.connect(self._atualizar_aceite)
        for item in (self.check_lido, self.check_finalidade_a, self.check_finalidade_b):
            vm.addWidget(item)
        vm.addWidget(linha_rotulada("Assinatura eletrônica", self.campo_assinatura,
                                    "O nome e as autorizações passam a integrar o termo aceito (Cláusula 11ª)."))
        self.motivo_aceite = CaptionLabel()
        self.motivo_aceite.setWordWrap(True)
        self.motivo_aceite.setStyleSheet(f"color:{AMBAR};")
        vm.addWidget(self.motivo_aceite)
        coluna.addWidget(manifestacao)
        coluna.addStretch(1)
        v.addWidget(self.rolagem_termo, 1)

        # barra fixa: sempre visível, com o relógio de leitura
        barra = QHBoxLayout()
        recusar = PushButton("Não concordo")
        recusar.setToolTip("Encerra o cadastro sem coletar nenhuma imagem.")
        recusar.clicked.connect(self._recusar)
        self.relogio_leitura = CaptionLabel()
        self.relogio_leitura.setStyleSheet(f"color:{cor_texto_secundario()};")
        self.botao_aceitar = PrimaryPushButton("Concordo e assino")
        self.botao_aceitar.setIcon(FIF.EDIT)
        self.botao_aceitar.setEnabled(False)
        self.botao_aceitar.clicked.connect(self._aceitar)
        barra.addWidget(recusar)
        barra.addStretch(1)
        barra.addWidget(self.relogio_leitura)
        barra.addSpacing(12)
        barra.addWidget(self.botao_aceitar)
        v.addLayout(barra)

        self._inicio_leitura = None
        self._temporizador_leitura = QTimer(self)
        self._temporizador_leitura.setInterval(1000)
        self._temporizador_leitura.timeout.connect(self._tique_leitura)
        self._atualizar_aceite()
        return w

    def _iniciar_leitura(self):
        if self._inicio_leitura is None:              # conta uma vez só, desde a 1ª exibição
            self._inicio_leitura = time.monotonic()
            self._temporizador_leitura.start()
        self._tique_leitura()

    def _restante_leitura(self) -> int:
        if self._inicio_leitura is None:
            return self.servico.leitura_minima_segundos
        return max(0, math.ceil(self.servico.leitura_minima_segundos - (time.monotonic() - self._inicio_leitura)))

    def _tique_leitura(self):
        restante = self._restante_leitura()
        if restante > 0:
            self.relogio_leitura.setText(f"Leitura mínima: o aceite é liberado em {restante} s")
        else:
            self._temporizador_leitura.stop()
            self.relogio_leitura.setText("")
            self.check_lido.setEnabled(True)
        self._atualizar_aceite()

    def _pendencias_do_aceite(self) -> list[str]:
        pendentes = []
        if self._restante_leitura() > 0:
            pendentes.append("aguardar o tempo mínimo de leitura")
        if not self.check_lido.isChecked():
            pendentes.append("marcar «Li e compreendi integralmente este Termo»")
        if not self.check_finalidade_a.isChecked():
            pendentes.append("marcar a finalidade (a), obrigatória")
        if len(self.campo_assinatura.text().split()) < 2:
            pendentes.append("assinar com o nome completo (nome e sobrenome)")
        return pendentes

    def _atualizar_aceite(self, *_):
        pendentes = self._pendencias_do_aceite()
        self.botao_aceitar.setEnabled(not pendentes)
        self.motivo_aceite.setText("Para assinar, falta: " + "; ".join(pendentes) + "." if pendentes else "")

    def _recusar(self):
        self.encerrar()
        InfoBar.info("Cadastro encerrado", "Sem consentimento, nenhuma imagem foi capturada.",
                     duration=4000, position=InfoBarPosition.TOP, parent=self.window())
        self.finalizado.emit(None)

    def _aceitar(self):
        if self.aceite is not None or self._pendencias_do_aceite():   # duplo clique / estado inválido
            return
        try:
            self.aceite = self.servico.registrar_aceite(self.campo_assinatura.text(),
                                                        autoriza_pesquisa=self.check_finalidade_b.isChecked())
        except ErroCadastro as erro:
            InfoBar.error("Termo", str(erro), duration=4000, position=InfoBarPosition.TOP, parent=self)
            return
        self._temporizador_leitura.stop()
        self.campo_nome.setText(self.aceite.titular_nome)
        self._ir(DADOS)

    # passo 3: dados
    def _passo_dados(self):
        w = SimpleCardWidget()
        grade = QGridLayout(w)
        grade.setContentsMargins(24, 20, 24, 20)
        grade.setHorizontalSpacing(24)
        grade.setVerticalSpacing(12)
        aviso = BodyLabel("A senha deve ser digitada pela pessoa cadastrada, sem que outros a vejam.")
        aviso.setWordWrap(True)
        aviso.setStyleSheet(f"color:{AMBAR};")
        grade.addWidget(aviso, 0, 0, 1, 2)
        self.campo_nome = LineEdit()
        self.campo_nome.setReadOnly(True)
        self.combo_perfil = ComboBox()
        for perfil in self.perfis:
            self.combo_perfil.addItem(perfil.rotulo, userData=perfil)
        self.combo_perfil.currentIndexChanged.connect(self._perfil_mudou)
        self.combo_uf = ComboBox()
        for uf in sorted(UFS):
            self.combo_uf.addItem(uf, userData=uf)
        # sem UF pré-escolhida: um padrão ("AC") daria ao diretor a região
        # errada sem ninguém perceber; vazio, a validação obriga a escolher
        self.combo_uf.setPlaceholderText("Selecione a UF")
        self.combo_uf.setCurrentIndex(-1)
        self.campo_senha = PasswordLineEdit()
        self.campo_confirmacao = PasswordLineEdit()
        self.checklist = ChecklistSenha()
        self.campo_senha.textChanged.connect(self._senha_mudou)
        self.campo_confirmacao.textChanged.connect(self._senha_mudou)
        self.descricao_perfil = CaptionLabel()
        self.descricao_perfil.setWordWrap(True)

        grade.addWidget(linha_rotulada("Nome (da assinatura do termo)", self.campo_nome), 1, 0)
        grade.addWidget(linha_rotulada("Perfil de acesso", self.combo_perfil,
                                       "O mínimo que a função exige."),
                        2, 0)
        grade.addWidget(self.descricao_perfil, 3, 0)
        grade.addWidget(linha_rotulada("UF sob responsabilidade", self.combo_uf,
                                       "Apenas para o perfil Diretor."), 4, 0)
        grade.addWidget(linha_rotulada("Senha", self.campo_senha,
                                       "Não use data de nascimento nem a matrícula."), 1, 1)
        grade.addWidget(linha_rotulada("Confirme a senha", self.campo_confirmacao), 2, 1)
        grade.addWidget(self.checklist, 3, 1, 2, 1, Qt.AlignmentFlag.AlignTop)

        self.erros_dados = BodyLabel()
        self.erros_dados.setWordWrap(True)
        self.erros_dados.setStyleSheet(f"color:{VERMELHO};")
        grade.addWidget(self.erros_dados, 5, 0, 1, 2)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        continuar = PrimaryPushButton("Continuar para a captura")
        continuar.setIcon(FIF.CAMERA)
        continuar.clicked.connect(self._confirmar_dados)
        botoes.addWidget(continuar)
        grade.addLayout(botoes, 6, 0, 1, 2)
        grade.setRowStretch(7, 1)
        self._perfil_mudou()
        return w

    def _perfil(self) -> Perfil:
        return self.combo_perfil.currentData() or self.perfis[0]

    def _perfil_mudou(self, *_):
        perfil = self._perfil()
        self.combo_uf.setEnabled(perfil.exige_uf)
        self.descricao_perfil.setText(DESCRICAO_PERFIL[perfil])
        cor = COR_NIVEL[perfil.camada] if perfil.camada else cor_texto_secundario()
        self.descricao_perfil.setStyleSheet(f"color:{cor};")
        self._senha_mudou()

    def _senha_mudou(self, *_):
        requisitos = self.servico.requisitos_senha(self.campo_senha.text(), self._perfil())
        confere = bool(self.campo_senha.text()) and self.campo_senha.text() == self.campo_confirmacao.text()
        self.checklist.atualizar(requisitos + [("confirmação igual à senha", confere)])

    def _confirmar_dados(self):
        perfil = self._perfil()
        self.dados = DadosCadastro(self.campo_nome.text(), None,
                                   self.combo_uf.currentData() if perfil.exige_uf else None,
                                   self.campo_senha.text(), self.campo_confirmacao.text(), perfil=perfil)
        erros = self.servico.validar(self.dados)
        if erros:
            # ao lado do formulário (fica visível enquanto a pessoa corrige)
            self.erros_dados.setText("Corrija antes de continuar:\n• " + "\n• ".join(erros))
            return
        self.erros_dados.setText("")
        self.coleta = self.servico.nova_coleta(self.aceite)
        self._preparar_sessao()
        self._ir(ROSTO)

    # passo 4: rosto
    def _passo_rosto(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        self.visor = VisorVideo()
        h.addWidget(self.visor, 3)
        painel = SimpleCardWidget()
        painel.setMinimumWidth(320)
        painel.setMaximumWidth(400)
        v = QVBoxLayout(painel)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(10)
        self.sessao_titulo = SubtitleLabel()
        self.sessao_instrucao = BodyLabel()
        self.sessao_instrucao.setWordWrap(True)
        dicas = _texto_secundario("Rosto dentro da moldura · sem óculos escuros, boné ou máscara · uma pessoa "
                                  "por vez · movimentos lentos.")
        self.barra_coleta = ProgressBar()
        self.contagem = StrongBodyLabel()
        self.orientacao = BodyLabel()
        self.orientacao.setWordWrap(True)
        self.recusas = _texto_secundario("")
        self.botao_captura = PrimaryPushButton("Iniciar captura")
        self.botao_captura.setIcon(FIF.CAMERA)
        self.botao_captura.clicked.connect(self._acao_captura)
        explicacao = _texto_secundario("As imagens não são gravadas: são descartadas após o treinamento.")
        for item in (self.sessao_titulo, self.sessao_instrucao, dicas, self.barra_coleta, self.contagem,
                     self.orientacao, self.recusas, self.botao_captura, explicacao):
            v.addWidget(item)
        v.addStretch(1)
        h.addWidget(painel, 2)
        return w

    def _preparar_sessao(self):
        estado = self.coleta.estado()
        self.sessao_titulo.setText(f"Sessão {estado.sessao} de {estado.total_sessoes}")
        if estado.sessao == 1:
            self.sessao_instrucao.setText("Olhe para a câmera e mova a cabeça devagar.")
        else:
            self.sessao_instrucao.setText("Mude a iluminação ou a posição e repita os movimentos.")
        self.barra_coleta.setRange(0, estado.meta)
        self.barra_coleta.setValue(0)
        self.contagem.setText(f"0 de {estado.meta} imagens")
        self.orientacao.setText("")
        self.recusas.setText("")
        self.botao_captura.setText("Iniciar captura" if estado.sessao == 1 else f"Iniciar sessão {estado.sessao}")
        self.botao_captura.setIcon(FIF.CAMERA)
        self.botao_captura.setEnabled(True)
        self.visor.limpar("Clique em «Iniciar captura» para ligar a câmera")

    def _acao_captura(self):
        estado = self.coleta.estado()
        if estado.concluida:
            self._concluir()
        elif estado.sessao_completa:
            self.coleta.avancar_sessao()
            self._preparar_sessao()
        else:
            self.botao_captura.setEnabled(False)
            self.botao_captura.setText("Capturando…")
            self._ligar_video()

    def _ao_quadro(self, imagem, resultado, estado):
        if self.coleta is None:
            return
        self.visor.mostrar(imagem, resultado)
        self.barra_coleta.setValue(estado.aceitas)
        self.contagem.setText(f"{estado.aceitas} de {estado.meta} imagens")
        self.orientacao.setText(estado.orientacao or "")
        if estado.recusas:
            principais = sorted(estado.recusas.items(), key=lambda kv: -kv[1])[:3]
            self.recusas.setText("Recusadas: " + "; ".join(f"{n}× {m.lower()}" for m, n in principais))
        if estado.sessao_completa:
            self._parar_video()
            self.visor.limpar("Sessão concluída")
            self.botao_captura.setEnabled(True)
            if estado.concluida:
                self.botao_captura.setText("Concluir cadastro")
                self.botao_captura.setIcon(FIF.ACCEPT)
            else:
                self.botao_captura.setText("Próxima sessão")
                self.botao_captura.setIcon(FIF.RIGHT_ARROW)

    def _ao_falhar(self, mensagem):
        self._parar_video()
        self.visor.limpar("Câmera indisponível")
        self.botao_captura.setEnabled(True)
        self.botao_captura.setText("Tentar de novo")
        InfoBar.error("Câmera", mensagem, duration=6000, position=InfoBarPosition.TOP, parent=self)

    def _ligar_video(self):
        self.trabalhador = TrabalhadorVideo(self.app.nova_camera(), self.app.novo_pipeline(),
                                            processar=self.coleta.oferecer, parent=self)
        self.trabalhador.quadro.connect(self._ao_quadro)
        self.trabalhador.falhou.connect(self._ao_falhar)
        self.trabalhador.start()

    def _parar_video(self):
        if self.trabalhador is not None:
            trabalhador, self.trabalhador = self.trabalhador, None
            trabalhador.quadro.disconnect(self._ao_quadro)
            trabalhador.parar()
            trabalhador.deleteLater()

    def _concluir(self):
        self.botao_captura.setEnabled(False)
        if self.recadastro is not None:
            self._concluir_recadastro()
            return
        try:
            usuario = self.servico.concluir(self.dados, self.aceite, self.coleta)
        except Exception as erro:  # noqa: BLE001, qualquer falha: avisar, faces já descartadas
            InfoBar.error("Cadastro não concluído", f"{erro} As imagens foram descartadas; "
                          "recomece o cadastro.", duration=8000, position=InfoBarPosition.TOP, parent=self)
            self.encerrar()
            self.finalizado.emit(None)
            return
        self.coleta = None
        self.usuario = usuario
        self.fim_matricula.setText(usuario.matricula)
        pesquisa = "autorizou" if self.aceite.autoriza_pesquisa else "não autorizou"
        self.fim_resumo.setText(f"{usuario.nome} · Perfil {usuario.perfil.rotulo}"
                                + (f" · UF {usuario.uf}" if usuario.uf else "")
                                + f"\nTermo v{self.aceite.versao_termo}: {pesquisa} o uso nas estatísticas (b).")
        self.botao_cancelar.setEnabled(False)
        self._ir(FIM)

    def _concluir_recadastro(self):
        coleta, self.coleta = self.coleta, None
        try:
            self.servico.substituir_rosto(self.recadastro.id, coleta)       # descarta as faces sempre
        except Exception as erro:  # noqa: BLE001, avisar; o rosto anterior continua valendo se nada mudou
            InfoBar.error("Recadastro não concluído", f"{erro} As imagens foram descartadas.", duration=8000,
                          position=InfoBarPosition.TOP, parent=self)
            self.encerrar()
            self.finalizado.emit(None)
            return
        self.usuario = self.recadastro
        self.fim_titulo.setText("Rosto recadastrado")
        self.fim_rotulo_matricula.setText("Matrícula (não muda):")
        self.fim_matricula.setText(self.recadastro.matricula)
        self.fim_resumo.setText(f"{self.recadastro.nome}: rosto recadastrado. Vale a partir do próximo login.")
        self.botao_pdf.hide()
        self.botao_cancelar.setEnabled(False)
        self._ir(FIM)

    # passo 5: fim
    def _passo_fim(self):
        w = SimpleCardWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(32, 32, 32, 32)
        v.setSpacing(12)
        self.fim_titulo = SubtitleLabel("Cadastro concluído")
        v.addWidget(self.fim_titulo)
        self.fim_rotulo_matricula = BodyLabel("Matrícula gerada pelo sistema:")
        v.addWidget(self.fim_rotulo_matricula)
        self.fim_matricula = DisplayLabel()
        self.fim_matricula.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.fim_matricula)
        self.fim_resumo = BodyLabel()
        self.fim_resumo.setWordWrap(True)
        v.addWidget(self.fim_resumo)
        v.addWidget(_texto_secundario("Entregue a matrícula à pessoa. A senha não pode ser recuperada."))
        botoes = QHBoxLayout()
        self.botao_pdf = PushButton("Salvar via do titular (PDF)")
        self.botao_pdf.setIcon(FIF.SAVE)
        self.botao_pdf.setToolTip("Via do termo assinado.")
        self.botao_pdf.clicked.connect(self._salvar_pdf)
        copiar = PushButton("Copiar matrícula")
        copiar.setIcon(FIF.COPY)
        copiar.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.fim_matricula.text()))
        concluir = PrimaryPushButton("Concluir")
        concluir.setIcon(FIF.ACCEPT)
        concluir.clicked.connect(lambda: self.finalizado.emit(self.usuario))
        botoes.addWidget(copiar)
        botoes.addWidget(self.botao_pdf)
        botoes.addStretch(1)
        botoes.addWidget(concluir)
        v.addStretch(1)
        v.addLayout(botoes)
        return w

    def _salvar_pdf(self):
        if self.aceite is None or self.usuario is None:     # a via só existe depois de assinada e concluída
            return
        nome_arquivo = f"termo_consentimento_{self.usuario.matricula}.pdf"
        caminho, _ = QFileDialog.getSaveFileName(self, "Salvar via do titular", nome_arquivo, "PDF (*.pdf)")
        if caminho:
            self.gerar_via_pdf(caminho)
            InfoBar.success("Via do titular salva", caminho, duration=4000, position=InfoBarPosition.TOP,
                            parent=self)

    def gerar_via_pdf(self, caminho: str):
        documento = QTextDocument()
        documento.setDefaultFont(QFont(FONTE_DOCUMENTO, 11))
        documento.setHtml(self.servico.via_do_titular_html(self.aceite, self.usuario.matricula))
        # QPdfWriter escreve o PDF direto, sem
        # consultar o subsistema de impressão do Windows (lento, depende de drivers)
        pdf = QPdfWriter(caminho)
        pdf.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        pdf.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)    # o Qt já aplica 2 cm
        pdf.setTitle(f"Termo de consentimento: {self.aceite.titular_nome}")
        pdf.setCreator("EcoSecurity")
        documento.print_(pdf)               # sem tamanho de página no documento, o Qt numera as páginas

    # saídas
    def cancelar(self):
        if self.aceite is not None or self.coleta is not None:
            caixa = MessageBox("Cancelar o cadastro?", "O aceite do termo e as imagens já capturadas serão "
                               "descartados. Nada fica gravado.", self.window())
            caixa.yesButton.setText("Cancelar cadastro")
            caixa.cancelButton.setText("Continuar")
            if not caixa.exec():
                return
        self.encerrar()
        self.finalizado.emit(None)

    def encerrar(self):
        """Idempotente. Para o vídeo e APAGA as faces coletadas (LGPD)."""
        self._parar_video()
        if self.coleta is not None:
            self.coleta.descartar()
            self.coleta = None
