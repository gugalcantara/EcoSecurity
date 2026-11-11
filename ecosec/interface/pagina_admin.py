"""Área administrativa: senha de instalação (1ª execução) -> bloqueada -> [rosto] -> [celular] -> painel.

Três situações:
- Configuração inicial (instalação nova, sem administrador): a senha de
  INSTALAÇÃO abre o painel, para fazer o primeiro cadastro, que só pode ter o
  perfil de administrador e vira o primeiro admin. Depois dele, o
  sistema abre pelo login.
- Administradores (login único, cada um com a sua matrícula): só um admin
  logado vê esta página. Abri-la confere o rosto de novo, na hora, e pede o
  código do celular (no primeiro acesso, cadastra o celular). O administrador
  não tem camada: nenhum dado do acervo aparece para ele. Aqui ele gere pessoas
  e perfis, exclui cadastros, lê a trilha (com o detalhe do acervo mascarado),
  os relatórios do sistema e faz a identificação facial 1:N. Ações
  críticas pedem o código do celular de OUTRO admin.
- Acesso de emergência: sem rosto nem celular (foi isso que falhou); abre
  direto o painel restrito, que só conserta o acesso.

Sair da página bloqueia o painel de novo e encerra qualquer cadastro em
andamento (com descarte das faces). O painel também se tranca sozinho depois
de alguns minutos sem uso ([administracao] no config). Um painel aberto e
esquecido é uma porta destrancada para a próxima pessoa que sentar ao
computador.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QStackedWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ecosec.dominio.entidades import UFS
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import CRITICOS, Perfil
from ecosec.interface.admin_governanca import (PainelCadastroCelular, PainelCodigoCelular, PainelEmergencia,
                                               mostrar_ancora, pedir_aprovacao, pedir_codigo_proprio,
                                               pedir_linha_ancora)
from ecosec.interface.assistente_cadastro import AssistenteCadastro
from ecosec.interface.atividade import PrazoInatividade
from ecosec.interface.componentes import ChecklistSenha, ColunasResponsivas, linha_rotulada
from ecosec.interface.estilo import COR_NIVEL, VERDE, VERMELHO, cor_texto_secundario, qcor
from ecosec.interface.fluent import (FIF, BodyLabel, CaptionLabel, ComboBox, IconWidget, InfoBar, InfoBarPosition,
                                     MessageBox, MessageBoxBase, PasswordLineEdit, PrimaryPushButton, PushButton,
                                     SegmentedWidget, SimpleCardWidget, StrongBodyLabel, SubtitleLabel, TableWidget,
                                     TitleLabel)
from ecosec.interface.logo import pixmap_logo
from ecosec.interface.pagina_identificacao import VistaIdentificacao
from ecosec.interface.tela_autenticacao import TelaAutenticacao

COLUNAS_TRILHA = ("#", "Momento", "Evento", "Resultado", "Motivo", "Camadas", "Nível", "Usuário",
                  "Matrícula informada", "Detalhe")

COLUNAS = ("Matrícula", "Nome", "Perfil", "UF", "Situação", "Consentimento", "Amostras", "Rosto no modelo",
           "Criado em", "Administrador")
# telas da pilha (o assistente de cadastro entra e sai dela, sem índice fixo)
DEFINIR, BLOQUEADA, PAINEL, ROSTO, CODIGO, CELULAR, EMERGENCIA = range(7)


def _cartao_central(*widgets) -> QWidget:
    fundo = QWidget()
    externo = QVBoxLayout(fundo)
    externo.addStretch(1)
    cartao = SimpleCardWidget()
    cartao.setFixedWidth(440)
    v = QVBoxLayout(cartao)
    v.setContentsMargins(28, 28, 28, 28)
    v.setSpacing(14)
    for w in widgets:
        v.addWidget(w)
    linha = QHBoxLayout()
    linha.addStretch(1)
    linha.addWidget(cartao)
    linha.addStretch(1)
    externo.addLayout(linha)
    externo.addStretch(2)
    return fundo


class DialogoPerfil(MessageBoxBase):
    """Escolher o perfil novo de um cadastro (e a UF, para o diretor)."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel("Atribuir perfil"))
        texto = BodyLabel(f"{usuario.nome} ({usuario.matricula}) tem hoje o perfil {usuario.perfil.rotulo}. "
                          "Ministro pede o código de outro administrador. O administrador não recebe perfil com "
                          "camada: tire o papel antes.")
        texto.setWordWrap(True)
        self.viewLayout.addWidget(texto)
        self.combo = ComboBox()
        for perfil in Perfil:
            self.combo.addItem(perfil.rotulo, userData=perfil)
        self.combo.setCurrentIndex(list(Perfil).index(usuario.perfil))
        self.combo_uf = ComboBox()
        for uf in sorted(UFS):
            self.combo_uf.addItem(uf, userData=uf)
        self.combo_uf.setPlaceholderText("UF do diretor")
        self.combo_uf.setCurrentIndex(sorted(UFS).index(usuario.uf) if usuario.uf else -1)
        self.combo.currentIndexChanged.connect(self._mudou)
        self.viewLayout.addWidget(linha_rotulada("Perfil", self.combo))
        self.viewLayout.addWidget(linha_rotulada("UF", self.combo_uf, "Só para o diretor."))
        self.yesButton.setText("Atribuir")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(460)
        self._mudou()

    def _mudou(self, *_):
        self.combo_uf.setEnabled(self.combo.currentData().exige_uf)

    def escolha(self) -> tuple[Perfil, str | None]:
        perfil = self.combo.currentData()
        return perfil, (self.combo_uf.currentData() if perfil.exige_uf else None)


class PaginaAdministracao(QWidget):
    cadastro_concluido = Signal()        # a janela reavalia o estado (a configuração inicial pode ter acabado)
    voltar_inicio = Signal()
    sair_emergencia = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.setObjectName("paginaAdministracao")
        self.app = app
        self.servico = app.administracao
        self.sessao = None               # SessaoAplicacao do logado (None na configuração inicial)
        self.assistente: AssistenteCadastro | None = None
        self.pilha = QStackedWidget(self)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.pilha)
        self.pilha.addWidget(self._tela_definir())     # DEFINIR
        self.pilha.addWidget(self._tela_bloqueada())   # BLOQUEADA
        self.pilha.addWidget(self._tela_painel())      # PAINEL
        self.tela_rosto = TelaAutenticacao(app)
        self.tela_rosto.concedido.connect(lambda _s: self._apos_rosto())
        self.tela_rosto.voltar.connect(self.voltar_inicio.emit)
        self.pilha.addWidget(self.tela_rosto)          # ROSTO
        self.tela_codigo = PainelCodigoCelular(app)
        self.tela_codigo.confirmado.connect(self._abrir_painel)
        self.tela_codigo.voltar.connect(self.voltar_inicio.emit)
        self.pilha.addWidget(self.tela_codigo)         # CODIGO
        self.tela_celular = PainelCadastroCelular(app)
        self.tela_celular.concluido.connect(self._abrir_painel)
        self.tela_celular.voltar.connect(self.voltar_inicio.emit)
        self.pilha.addWidget(self.tela_celular)        # CELULAR
        self.tela_emergencia = PainelEmergencia(app)
        self.tela_emergencia.recadastrar_rosto.connect(self._recadastrar_rosto)
        self.tela_emergencia.sair.connect(self.sair_emergencia.emit)
        self.pilha.addWidget(self.tela_emergencia)     # EMERGENCIA
        # tranca por inatividade REAL (mouse, rolagem, teclado); a câmera do cadastro ou da identificação ligada
        # conta como uso
        self._inatividade = PrazoInatividade(
            app.cfg["administracao.bloqueio_inatividade_minutos"], ocupado=self.camera_ligada, parent=self)
        self._inatividade.vencido.connect(self._trancar_por_inatividade)
        self.bloquear()

    def definir_sessao(self, sessao):
        self.sessao = sessao
        self.tela_emergencia.definir(sessao if sessao is not None and sessao.em_emergencia else None)
        self.bloquear()

    def camera_ligada(self) -> bool:
        return ((self.assistente is not None and self.assistente.trabalhador is not None)
                or self.identificacao.trabalhador is not None)

    def _em_emergencia(self) -> bool:
        return self.sessao is not None and self.sessao.em_emergencia

    def _modo_administrador(self) -> bool:
        """Login único: um administrador logado. O painel pede o rosto e o código do celular."""
        return (self.servico.administrador_vinculado and self.sessao is not None and self.sessao.administrador
                and not self._em_emergencia())

    def _iniciar_conferencia(self):
        self.pilha.setCurrentIndex(ROSTO)
        self.tela_rosto.iniciar(lambda: self.app.autenticacao.nova_verificacao_admin(self.sessao.identidade),
                                "Conferência do administrador",
                                "O login já identificou você como administrador. Para abrir o painel, o "
                                "rosto é conferido de novo, na hora, e depois é pedido o código do celular.")

    def _apos_rosto(self):
        """Rosto conferido: falta o celular. Sem celular cadastrado, este é o primeiro acesso: cadastra."""
        uid = self.sessao.usuario.id
        if self.servico.celular_cadastrado(uid):
            self.pilha.setCurrentIndex(CODIGO)
            self.tela_codigo.iniciar(uid)
        else:
            self.pilha.setCurrentIndex(CELULAR)
            self.tela_celular.iniciar(uid)

    def showEvent(self, evento):
        super().showEvent(evento)
        if self._modo_administrador() and self.pilha.currentIndex() == ROSTO and self.tela_rosto.sessao is None:
            self._iniciar_conferencia()

    def _trancar_por_inatividade(self):
        if self.pilha.currentIndex() in (DEFINIR, BLOQUEADA, ROSTO, CODIGO, CELULAR, EMERGENCIA):
            return
        self.bloquear()
        if self._modo_administrador() and self.isVisible():
            self._iniciar_conferencia()
        InfoBar.info("Painel trancado", "Tempo sem uso esgotado. Confirme de novo para continuar.",
                     duration=5000, position=InfoBarPosition.TOP, parent=self)

    # ============================================================ 1ª execução
    def _tela_definir(self):
        icone = QLabel()
        icone.setPixmap(pixmap_logo(48))
        icone.setFixedSize(48, 48)
        texto = BodyLabel("Primeira execução: defina a senha de INSTALAÇÃO. Ela abre a configuração inicial e "
                          "serve uma única vez para indicar o primeiro administrador; depois disso, cada admin "
                          "entra com a própria matrícula, o rosto e o celular. Use uma senha forte: ela não fica "
                          "guardada, só um código que permite conferi-la.")
        texto.setWordWrap(True)
        self.def_senha = PasswordLineEdit()
        self.def_confirmacao = PasswordLineEdit()
        self.def_checklist = ChecklistSenha()
        self.def_senha.textChanged.connect(self._def_mudou)
        self.def_confirmacao.textChanged.connect(self._def_mudou)
        botao = PrimaryPushButton("Definir senha")
        botao.clicked.connect(self._definir)
        self.def_senha.returnPressed.connect(self.def_confirmacao.setFocus)    # como no login
        self.def_confirmacao.returnPressed.connect(self._definir)
        self._def_mudou()
        return _cartao_central(icone, TitleLabel("Configurar a instalação"), texto,
                               linha_rotulada("Nova senha", self.def_senha),
                               linha_rotulada("Confirme a senha", self.def_confirmacao),
                               self.def_checklist, botao)

    def _def_mudou(self, *_):
        senha = self.def_senha.text()
        confere = bool(senha) and senha == self.def_confirmacao.text()
        self.def_checklist.atualizar(self.servico.requisitos_senha(senha) +
                                     [("confirmação igual à senha", confere)])

    def _definir(self):
        erros = self.servico.definir_senha_inicial(self.def_senha.text(), self.def_confirmacao.text())
        self.def_senha.clear()
        self.def_confirmacao.clear()
        if erros:
            InfoBar.warning("Senha recusada", "\n".join(erros), duration=6000,
                            position=InfoBarPosition.TOP, parent=self)
            return
        InfoBar.success("Instalação configurada", "Use a senha definida para entrar.",
                        duration=4000, position=InfoBarPosition.TOP, parent=self)
        self.bloquear()

    # ============================================================ bloqueada
    def _tela_bloqueada(self):
        icone = IconWidget(FIF.PEOPLE)
        icone.setFixedSize(48, 48)
        self.bloq_titulo = TitleLabel()
        self.bloq_texto = BodyLabel()
        self.bloq_texto.setWordWrap(True)
        self.campo_admin = PasswordLineEdit()
        self.campo_admin.setPlaceholderText("Senha de instalação")
        self.campo_admin.returnPressed.connect(self._entrar)
        botao = PrimaryPushButton("Entrar")
        botao.setIcon(FIF.RIGHT_ARROW)
        botao.clicked.connect(self._entrar)
        return _cartao_central(icone, self.bloq_titulo, self.bloq_texto,
                               linha_rotulada("Senha", self.campo_admin), botao)

    def _textos_bloqueada(self):
        """Na configuração inicial a tela diz o que falta: sem isso, ela parece um login
        de administrador comum, e os níveis "somem" sem explicação."""
        if self.servico.administrador_vinculado:
            self.bloq_titulo.setText("Área administrativa")
            self.bloq_texto.setText("O painel abre pelo login de um administrador: a matrícula e a senha dele, "
                                    "o rosto conferido na hora e o código do celular.")
        else:
            self.bloq_titulo.setText("Configuração inicial")
            self.bloq_texto.setText("Instalação nova: ainda não há administrador. Entre com a senha de instalação "
                                    "e faça o seu cadastro (Novo cadastro, perfil Externo): ele vira o primeiro "
                                    "administrador. Depois, o sistema abre pelo login (matrícula, senha e rosto).")

    def _entrar(self):
        motivo = self.servico.autenticar(self.campo_admin.text())
        self.campo_admin.clear()
        if motivo is Motivo.CONCEDIDO:
            if self.servico.administrador_vinculado:       # depois do vínculo, a senha não abre o painel
                InfoBar.error("Use o login", "Com um administrador definido, o painel abre pelo login de cada "
                              "administrador.", duration=5000, position=InfoBarPosition.TOP, parent=self)
            else:
                self._abrir_painel()                       # configuração inicial: só a senha
        elif motivo is Motivo.ERRO_INTERNO:
            InfoBar.error("Banco indisponível", "Não foi possível conferir a senha. Verifique o "
                          "serviço do MySQL.", duration=6000, position=InfoBarPosition.TOP, parent=self)
        elif motivo is Motivo.BLOQUEADO:
            InfoBar.error("Bloqueado", "Tentativas seguidas demais. Aguarde alguns minutos.",
                          duration=5000, position=InfoBarPosition.TOP, parent=self)
        else:
            InfoBar.warning("Senha incorreta", "Confira a senha do administrador.",
                            duration=3000, position=InfoBarPosition.TOP, parent=self)

    def _abrir_painel(self):
        self.pilha.setCurrentIndex(PAINEL)
        self.atualizar_tabela()
        self._inatividade.iniciar()

    def bloquear(self):
        self._inatividade.parar()
        self.tela_rosto.encerrar()
        self.tela_celular.descartar()
        self.identificacao.encerrar()
        self._encerrar_assistente()
        self._textos_bloqueada()
        if self._em_emergencia():
            self.pilha.setCurrentIndex(EMERGENCIA)        # a emergência não tem rosto nem celular a conferir
            self.tela_emergencia.atualizar()
        elif self._modo_administrador():
            self.pilha.setCurrentIndex(ROSTO)              # ao reaparecer, a conferência do rosto recomeça
        else:
            self.pilha.setCurrentIndex(BLOQUEADA if self.servico.configurado else DEFINIR)

    # ============================================================ painel
    def _tela_painel(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 20, 28, 20)
        v.setSpacing(14)
        topo = QHBoxLayout()
        textos = QVBoxLayout()
        textos.addWidget(TitleLabel("Administração"))
        self.resumo = CaptionLabel()
        textos.addWidget(self.resumo)
        topo.addLayout(textos, 1)
        novo = PrimaryPushButton("Novo cadastro")
        novo.setIcon(FIF.ADD)
        novo.clicked.connect(self._novo_cadastro)
        sair = PushButton("Bloquear painel")
        sair.setIcon(FIF.CLOSE)
        sair.clicked.connect(self.bloquear)
        topo.addWidget(novo, 0, Qt.AlignmentFlag.AlignTop)
        topo.addWidget(sair, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(topo)

        if self.app.modo_persistencia == "memoria":
            aviso = CaptionLabel("Modo de desenvolvimento: os cadastros ficam em memória e somem ao "
                                 "fechar o programa. A persistência chega com o MySQL.")
            aviso.setStyleSheet(f"color:{COR_NIVEL[Nivel.N2]};")
            v.addWidget(aviso)

        # abas: usuários | trilha de auditoria
        self.abas = SegmentedWidget()
        self.pilha_abas = QStackedWidget()
        aba_usuarios = QWidget()
        vu = QVBoxLayout(aba_usuarios)
        vu.setContentsMargins(0, 0, 0, 0)
        vu.setSpacing(12)
        self.pilha_abas.addWidget(aba_usuarios)
        self.pilha_abas.addWidget(self._aba_trilha())
        self.pilha_abas.addWidget(self._aba_relatorios())
        self.identificacao = VistaIdentificacao(self.app)          # A identificação 1:N é do administrador
        self.pilha_abas.addWidget(self.identificacao)
        self.abas.addItem("usuarios", "Usuários", self._abrir_usuarios)
        self.abas.addItem("trilha", "Trilha de auditoria", self._abrir_trilha)
        self.abas.addItem("relatorios", "Relatórios do sistema", self._abrir_relatorios)
        self.abas.addItem("identificacao", "Identificação facial", self._abrir_identificacao)
        self.abas.setCurrentItem("usuarios")
        v.addWidget(self.abas, 0, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(self.pilha_abas, 1)

        self.tabela = TableWidget()
        self.tabela.setBorderVisible(True)
        self.tabela.setBorderRadius(8)
        self.tabela.setColumnCount(len(COLUNAS))
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.verticalHeader().hide()
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # o nome fica com a sobra; em janela estreita, somem primeiro "Criado em"
        # e "Amostras" (o painel do titular mostra os dois), nunca o nome
        self.colunas = ColunasResponsivas(self.tabela, {0: 110, 2: 150, 3: 60, 4: 100, 5: 140, 6: 100, 7: 145,
                                                        8: 150, 9: 150},
                                          elastica=1, minima_elastica=220, ocultaveis=(8, 6))
        self.tabela.itemSelectionChanged.connect(self._selecao_mudou)
        vu.addWidget(self.tabela, 1)

        acoes = QHBoxLayout()
        self.botao_ativo = PushButton("Desativar")
        self.botao_ativo.clicked.connect(self._alternar_ativo)
        self.botao_revogar = PushButton("Revogar consentimento")
        self.botao_revogar.setIcon(FIF.REMOVE_FROM)
        self.botao_revogar.clicked.connect(self._revogar)
        self.botao_titular = PushButton("Dados do titular")
        self.botao_titular.setIcon(FIF.DOCUMENT)
        self.botao_titular.setToolTip("Relatório do que o sistema guarda sobre a pessoa (LGPD art. 18, I e II)")
        self.botao_titular.clicked.connect(self._dados_do_titular)
        self.botao_perfil = PushButton("Atribuir perfil")
        self.botao_perfil.setIcon(FIF.PEOPLE)
        self.botao_perfil.setToolTip("Dar ou trocar o perfil (Externo, Servidor, Diretor ou Ministro). Ministro pede o "
                                     "código de outro administrador.")
        self.botao_perfil.clicked.connect(self._atribuir_perfil)
        self.botao_excluir = PushButton("Excluir")
        self.botao_excluir.setIcon(FIF.DELETE)
        self.botao_excluir.setToolTip("Exclusão lógica e irreversível: revoga o consentimento e elimina o rosto. "
                                      "A trilha e o termo aceito ficam, como prova.")
        self.botao_excluir.clicked.connect(self._excluir)
        explicacao = CaptionLabel("Desativar suspende o acesso sem apagar histórico. Revogar o "
                                  "consentimento ou excluir desativa o cadastro e ELIMINA o rosto do modelo: só "
                                  "um novo cadastro, com novo termo, devolve o acesso.")
        explicacao.setWordWrap(True)
        explicacao.setStyleSheet(f"color:{cor_texto_secundario()};")
        acoes.addWidget(self.botao_perfil)
        acoes.addWidget(self.botao_ativo)
        acoes.addWidget(self.botao_revogar)
        acoes.addWidget(self.botao_excluir)
        acoes.addWidget(self.botao_titular)
        acoes.addWidget(explicacao, 1)
        vu.addLayout(acoes)

        # papel de administrador: as ações que pedem o código do celular de OUTRO admin
        papeis = QHBoxLayout()
        self.botao_tornar_admin = PushButton("Tornar administrador")
        self.botao_tornar_admin.setIcon(FIF.ADD)
        self.botao_tornar_admin.clicked.connect(self._tornar_admin)
        self.botao_tirar_admin = PushButton("Tirar o papel de administrador")
        self.botao_tirar_admin.setIcon(FIF.REMOVE)
        self.botao_tirar_admin.clicked.connect(self._tirar_admin)
        self.botao_refazer_celular = PushButton("Refazer celular")
        self.botao_refazer_celular.setIcon(FIF.PHONE)
        self.botao_refazer_celular.setToolTip("Apaga o celular e os códigos de recuperação do administrador; ele "
                                              "cadastra um novo no próximo acesso ao painel.")
        self.botao_refazer_celular.clicked.connect(self._refazer_celular)
        self.explicacao_papeis = CaptionLabel()
        self.explicacao_papeis.setWordWrap(True)
        self.explicacao_papeis.setStyleSheet(f"color:{cor_texto_secundario()};")
        papeis.addWidget(self.botao_tornar_admin)
        papeis.addWidget(self.botao_tirar_admin)
        papeis.addWidget(self.botao_refazer_celular)
        papeis.addWidget(self.explicacao_papeis, 1)
        vu.addLayout(papeis)
        self._selecao_mudou()
        return w

    # ============================================================ trilha
    def _aba_trilha(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        topo = QHBoxLayout()
        explicacao = CaptionLabel("Cada evento guarda o hash SHA-256 do anterior. Alterar ou apagar qualquer "
                                  "registro rompe a corrente, e a verificação aponta onde. A conta da "
                                  "aplicação não tem permissão para alterar esta tabela.")
        explicacao.setWordWrap(True)
        explicacao.setStyleSheet(f"color:{cor_texto_secundario()};")
        verificar = PrimaryPushButton("Verificar integridade")
        verificar.setIcon(FIF.CERTIFICATE)
        verificar.clicked.connect(self._verificar_trilha)
        atualizar = PushButton("Atualizar")
        atualizar.setIcon(FIF.SYNC)
        atualizar.clicked.connect(self._abrir_trilha)
        ancorar = PushButton("Gerar âncora")
        ancorar.setIcon(FIF.PIN)
        ancorar.setToolTip("Gera a linha com o último registro da trilha, para guardar fora do computador. "
                           "Pede o código do seu celular e fica registrado na trilha.")
        ancorar.clicked.connect(self._gerar_ancora)
        conferir = PushButton("Conferir âncora")
        conferir.setIcon(FIF.SEARCH)
        conferir.clicked.connect(self._conferir_ancora)
        topo.addWidget(explicacao, 1)
        topo.addWidget(atualizar)
        topo.addWidget(conferir)
        topo.addWidget(ancorar)
        topo.addWidget(verificar)
        v.addLayout(topo)
        self.resultado_trilha = StrongBodyLabel()
        v.addWidget(self.resultado_trilha)
        self.tabela_trilha = TableWidget()
        self.tabela_trilha.setBorderVisible(True)
        self.tabela_trilha.setBorderRadius(8)
        self.tabela_trilha.setColumnCount(len(COLUNAS_TRILHA))
        self.tabela_trilha.setHorizontalHeaderLabels(COLUNAS_TRILHA)
        self.tabela_trilha.verticalHeader().hide()
        self.tabela_trilha.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela_trilha.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.colunas_trilha = ColunasResponsivas(
            self.tabela_trilha, {0: 50, 1: 130, 2: 140, 3: 115, 4: 210, 5: 110, 6: 55, 7: 70, 8: 145},
            elastica=9, minima_elastica=160, ocultaveis=(5, 7, 6))
        v.addWidget(self.tabela_trilha, 1)
        return w

    def _abrir_usuarios(self):
        self.identificacao.encerrar()
        self.pilha_abas.setCurrentIndex(0)

    def _abrir_identificacao(self):
        """A câmera liga só aqui, com o painel já aberto pelo rosto e pelo celular; o serviço confere o perfil."""
        self.pilha_abas.setCurrentIndex(3)
        self.abas.setCurrentItem("identificacao")
        if self.sessao is not None and self.sessao.administrador and not self._em_emergencia():
            self.identificacao.iniciar(self.sessao.usuario.id)

    def _abrir_trilha(self):
        self.identificacao.encerrar()
        self.pilha_abas.setCurrentIndex(1)
        self.abas.setCurrentItem("trilha")
        try:
            registros = self.servico.trilha_visivel()           # o detalhe do acervo vem mascarado
        except Exception as erro:  # noqa: BLE001
            InfoBar.error("Banco indisponível", str(erro), duration=6000, position=InfoBarPosition.TOP, parent=self)
            return
        self.tabela_trilha.setRowCount(len(registros))
        for i, r in enumerate(registros):
            e = r.evento
            valores = (str(r.id), f"{e.momento:%d/%m %H:%M:%S}", e.evento, e.resultado, e.motivo, e.camadas,
                       str(e.nivel_solicitado or ""), str(e.usuario_id or ""), e.matricula_informada or "",
                       e.detalhe or "")
            for j, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if j == 3:
                    item.setForeground(qcor({"CONCEDIDO": VERDE, "NEGADO": VERMELHO}.get(e.resultado, "#8A8A8A")))
                self.tabela_trilha.setItem(i, j, item)

    def _verificar_trilha(self):
        try:
            resultado = self.servico.verificar_trilha()
        except Exception as erro:  # noqa: BLE001
            InfoBar.error("Banco indisponível", str(erro), duration=6000, position=InfoBarPosition.TOP, parent=self)
            return
        self.resultado_trilha.setText(str(resultado))
        self.resultado_trilha.setStyleSheet(f"color:{VERDE if resultado.integra else VERMELHO};")
        if not resultado.integra:
            for linha in range(self.tabela_trilha.rowCount()):
                if self.tabela_trilha.item(linha, 0).text() == str(resultado.id_rompido):
                    self.tabela_trilha.selectRow(linha)
                    self.tabela_trilha.scrollToItem(self.tabela_trilha.item(linha, 0))

    def pedir_codigo_proprio(self, acao: str, explicacao: str) -> str | None:
        """Separado para os testes trocarem (o diálogo é modal)."""
        return pedir_codigo_proprio(self.window(), acao, explicacao)

    def mostrar_ancora(self, linha: str) -> None:
        mostrar_ancora(self.window(), linha)

    def pedir_linha_ancora(self) -> str | None:
        return pedir_linha_ancora(self.window())

    def _gerar_ancora(self):
        codigo = self.pedir_codigo_proprio(
            "Gerar a âncora da trilha",
            "A âncora é a linha com o último registro da trilha, para guardar fora deste computador. Para "
            "gerá-la, digite o código que o SEU celular mostra agora. A geração fica registrada na trilha.")
        if codigo is None:
            return
        ancorada, recusa = self.servico.gerar_ancora(self._eu(), codigo)
        if recusa:
            InfoBar.warning("Âncora não gerada", recusa, duration=7000, position=InfoBarPosition.TOP, parent=self)
        else:
            self.mostrar_ancora(ancorada.texto())
        self._abrir_trilha()

    def _conferir_ancora(self):
        linha = self.pedir_linha_ancora()
        if linha is None:
            return
        conferencia, recusa = self.servico.conferir_ancora_painel(self._eu(), linha)
        if recusa:
            InfoBar.warning("Âncora não conferida", recusa, duration=7000, position=InfoBarPosition.TOP, parent=self)
            return
        self._abrir_trilha()
        self.resultado_trilha.setText(str(conferencia))
        self.resultado_trilha.setStyleSheet(f"color:{VERDE if conferencia.valida else VERMELHO};")

    # ============================================================ relatórios do sistema
    def _aba_relatorios(self):
        from ecosec.servicos.relatorios_sistema import RELATORIOS
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        topo = QHBoxLayout()
        self.combo_relatorio = ComboBox()
        for codigo, titulo in RELATORIOS.items():
            self.combo_relatorio.addItem(f"{codigo}  {titulo}", userData=codigo)
        self.combo_relatorio.setMinimumWidth(320)
        self.combo_relatorio.currentIndexChanged.connect(lambda *_: self._mostrar_relatorio())
        topo.addWidget(self.combo_relatorio)
        atualizar = PushButton("Atualizar")
        atualizar.setIcon(FIF.SYNC)
        atualizar.clicked.connect(self._mostrar_relatorio)
        topo.addWidget(atualizar)
        topo.addStretch(1)
        rastrear = PushButton("Rastrear arquivo vazado")
        rastrear.setIcon(FIF.SEARCH)
        rastrear.setToolTip("Lê a marca d'água de um PNG exportado e diz quem o exportou e quando.")
        rastrear.clicked.connect(self._rastrear_arquivo)
        topo.addWidget(rastrear)
        self.botao_revisao = PrimaryPushButton("Registrar revisão")
        self.botao_revisao.setIcon(FIF.CERTIFICATE)
        self.botao_revisao.setToolTip("Depois de o grupo conferir o S-10: grava na trilha que a revisão foi feita, "
                                      "com quem pediu e quem aprovou.")
        self.botao_revisao.clicked.connect(self._registrar_revisao)
        topo.addWidget(self.botao_revisao)
        v.addLayout(topo)
        self.explicacao_relatorio = CaptionLabel()
        self.explicacao_relatorio.setWordWrap(True)
        self.explicacao_relatorio.setStyleSheet(f"color:{cor_texto_secundario()};")
        v.addWidget(self.explicacao_relatorio)
        self.tabela_relatorio = TableWidget()
        self.tabela_relatorio.setBorderVisible(True)
        self.tabela_relatorio.setBorderRadius(8)
        self.tabela_relatorio.verticalHeader().hide()
        self.tabela_relatorio.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.tabela_relatorio, 1)
        return w

    def _abrir_relatorios(self):
        self.pilha_abas.setCurrentIndex(2)
        self.abas.setCurrentItem("relatorios")
        self._mostrar_relatorio()

    def _mostrar_relatorio(self):
        codigo = self.combo_relatorio.currentData()
        self.botao_revisao.setVisible(codigo == "S-10" and self.sessao is not None)
        try:
            tabela = self.app.relatorios_sistema.gerar(codigo)
        except Exception as erro:  # noqa: BLE001
            InfoBar.error("Banco indisponível", str(erro), duration=6000, position=InfoBarPosition.TOP, parent=self)
            return
        self.explicacao_relatorio.setText(tabela.explicacao + (" Nenhum registro ainda." if not tabela.linhas else ""))
        self.tabela_relatorio.clear()
        self.tabela_relatorio.setColumnCount(len(tabela.colunas))
        self.tabela_relatorio.setHorizontalHeaderLabels(tabela.colunas)
        self.tabela_relatorio.setRowCount(len(tabela.linhas))
        for i, linha in enumerate(tabela.linhas):
            for j, valor in enumerate(linha):
                item = QTableWidgetItem(str(valor))
                if valor in ("NEGADO", "ADULTERADA", "NÃO", "Revogado"):
                    item.setForeground(qcor(VERMELHO))
                elif valor in ("CONCEDIDO", "ÍNTEGRA"):
                    item.setForeground(qcor(VERDE))
                self.tabela_relatorio.setItem(i, j, item)
        cabecalho = self.tabela_relatorio.horizontalHeader()
        cabecalho.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        cabecalho.setStretchLastSection(True)

    def _rastrear_arquivo(self):
        import cv2
        import numpy as np
        caminho, _ = QFileDialog.getOpenFileName(self, "Arquivo a rastrear", "", "Imagem (*.png *.jpg *.jpeg)")
        if not caminho:
            return
        imagem = cv2.imdecode(np.frombuffer(Path(caminho).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        marca = None if imagem is None else self.app.acervo.identificar_marca(imagem)
        if marca is None:
            InfoBar.warning("Sem marca legível", "Este arquivo não traz marca d'água do EcoSecurity (ou ela foi "
                            "destruída por recorte). Nenhum palpite é dado.", duration=7000,
                            position=InfoBarPosition.TOP, parent=self)
            return
        usuario = self.servico.usuario(marca.usuario_id)
        quem = f"{usuario.nome} ({usuario.matricula})" if usuario else f"usuário nº {marca.usuario_id}"
        InfoBar.success("Origem identificada", f"Exportado por {quem} em "
                        f"{marca.momento.astimezone():%d/%m/%Y às %H:%M}.", duration=10000,
                        position=InfoBarPosition.TOP, parent=self)

    def atualizar_tabela(self):
        try:
            linhas = self.servico.listar()
        except Exception as erro:  # noqa: BLE001
            InfoBar.error("Banco indisponível", str(erro), duration=6000,
                          position=InfoBarPosition.TOP, parent=self)
            return
        self.tabela.setRowCount(len(linhas))
        for i, linha in enumerate(linhas):
            u = linha.usuario
            papel = ("" if not linha.administrador else
                     "Sim" if linha.celular else "Sim, sem celular")
            valores = (u.matricula, u.nome, u.perfil.rotulo, u.uf or "",
                       "Ativo" if u.ativo else "Inativo", "Vigente" if linha.consentimento_vigente else "Revogado",
                       str(linha.amostras), "Sim" if linha.no_modelo else "NÃO",
                       f"{u.criado_em:%d/%m/%Y %H:%M}" if u.criado_em else "", papel)
            for j, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                item.setData(Qt.ItemDataRole.UserRole, u.id)
                if j == 2 and u.perfil.camada is not None:
                    item.setForeground(qcor(COR_NIVEL[u.perfil.camada]))
                if j in (3, 6):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if j == 4:
                    item.setForeground(qcor(VERDE if u.ativo else VERMELHO))
                if (j == 5 and not linha.consentimento_vigente) or (j == 7 and not linha.no_modelo):
                    item.setForeground(qcor(VERMELHO))
                self.tabela.setItem(i, j, item)
        por_perfil = {p: sum(1 for l in linhas if l.usuario.perfil is p) for p in Perfil}
        self.resumo.setText(f"{len(linhas)} cadastrados · " +
                            " · ".join(f"{p.rotulo}: {q}" for p, q in por_perfil.items() if q))
        if self.sessao is None:
            texto = "Os papéis de administrador são geridos depois do login de um administrador."
        elif self.servico.exige_aprovacao:
            texto = ("Ações de papel e a revogação pedem o código do celular de OUTRO administrador. O sistema "
                     f"não fica com menos de {self.servico.governanca.minimo_administradores} administradores.")
        else:
            texto = ("Fase de implantação: com menos de 2 administradores, você designa o próximo sozinho "
                     "(fica na trilha). Depois, toda ação crítica pede um segundo administrador.")
        self.explicacao_papeis.setText(texto)
        self._selecao_mudou()

    def _selecionado(self):
        itens = self.tabela.selectedItems()
        if not itens:
            return None
        return self.servico.usuario(itens[0].data(Qt.ItemDataRole.UserRole))

    def _selecao_mudou(self):
        usuario = self._selecionado()
        self.botao_ativo.setEnabled(usuario is not None)
        self.botao_revogar.setEnabled(usuario is not None)
        self.botao_titular.setEnabled(usuario is not None)
        if usuario is not None:
            self.botao_ativo.setText("Desativar" if usuario.ativo else "Reativar")
            self.botao_ativo.setIcon(FIF.PAUSE if usuario.ativo else FIF.PLAY)
        logado = self.sessao is not None and not self._em_emergencia()
        e_admin = usuario is not None and self.servico.eh_administrador(usuario.id)
        candidato = usuario is not None and usuario.id in {u.id for u in self.servico.candidatos_a_administrador()}
        for botao, visivel in ((self.botao_tornar_admin, logado), (self.botao_tirar_admin, logado),
                               (self.botao_refazer_celular, logado), (self.botao_perfil, logado),
                               (self.botao_excluir, logado)):
            botao.setVisible(visivel)
        outro = usuario is not None and usuario.id != self._eu()
        self.botao_perfil.setEnabled(logado and outro)
        self.botao_excluir.setEnabled(logado and outro)
        self.botao_tornar_admin.setEnabled(logado and candidato)
        self.botao_tirar_admin.setEnabled(logado and e_admin)
        self.botao_refazer_celular.setEnabled(logado and e_admin)

    # ------------------------------------------------------------ ações críticas (aprovação de outro admin)
    def pedir_aprovacao(self, acao: str, alvo: str | None) -> str | None:
        """Separado para os testes trocarem (o diálogo é modal)."""
        return pedir_aprovacao(self.window(), self.servico, acao, alvo)

    def _critica(self, acao: str, usuario, executar, sucesso: str) -> None:
        """Pede o código de outro admin (ou a confirmação, na implantação), executa e informa."""
        alvo = f"{usuario.nome} ({usuario.matricula})" if usuario is not None else None
        codigo = self.pedir_aprovacao(acao, alvo)
        if codigo is None:
            return
        recusa = executar(codigo or None)
        if recusa:
            InfoBar.warning("Não foi feito", recusa, duration=7000, position=InfoBarPosition.TOP, parent=self)
        else:
            InfoBar.success("Feito", sucesso, duration=5000, position=InfoBarPosition.TOP, parent=self)
        self.atualizar_tabela()

    def _eu(self) -> int | None:
        return self.sessao.usuario.id if self.sessao is not None else None

    def _tornar_admin(self):
        u = self._selecionado()
        if u is not None:
            self._critica("Tornar administrador", u,
                          lambda c: self.servico.tornar_administrador(self._eu(), u.id, c),
                          f"{u.nome} agora é administrador. No primeiro acesso ao painel, cadastra o celular.")

    def _tirar_admin(self):
        u = self._selecionado()
        if u is not None:
            self._critica("Tirar o papel de administrador", u,
                          lambda c: self.servico.remover_administrador(self._eu(), u.id, c),
                          f"{u.nome} não é mais administrador. O cadastro continua ativo.")

    def _refazer_celular(self):
        u = self._selecionado()
        if u is not None:
            self._critica("Refazer o celular", u, lambda c: self.servico.refazer_celular(self._eu(), u.id, c),
                          f"Celular de {u.nome} apagado. Ele cadastra um novo no próximo acesso ao painel.")

    def escolher_perfil(self, usuario) -> tuple[Perfil, str | None] | None:
        """O perfil novo e a UF (diretor). Separado para os testes trocarem (o diálogo é modal)."""
        dialogo = DialogoPerfil(usuario, self.window())
        return dialogo.escolha() if dialogo.exec() else None

    def _atribuir_perfil(self):
        u = self._selecionado()
        if u is None:
            return
        escolha = self.escolher_perfil(u)
        if escolha is None:
            return
        perfil, uf = escolha
        sucesso = f"{u.nome} agora tem o perfil {perfil.rotulo}."
        if perfil in CRITICOS:
            self._critica(f"Atribuir o perfil {perfil.rotulo}", u,
                          lambda c: self.servico.atribuir_perfil(self._eu(), u.id, perfil, uf, c), sucesso)
            return
        recusa = self.servico.atribuir_perfil(self._eu(), u.id, perfil, uf)
        if recusa:
            InfoBar.warning("Não foi feito", recusa, duration=7000, position=InfoBarPosition.TOP, parent=self)
        else:
            InfoBar.success("Feito", sucesso, duration=5000, position=InfoBarPosition.TOP, parent=self)
        self.atualizar_tabela()

    def _excluir(self):
        u = self._selecionado()
        if u is None:
            return
        caixa = MessageBox("Excluir o cadastro",
                           f"Excluir {u.nome} ({u.matricula})? O cadastro é desativado, o consentimento revogado e "
                           "o modelo do rosto, ELIMINADO. Não há como desfazer. A trilha e o termo aceito ficam, "
                           "como prova.", self.window())
        if not caixa.exec():
            return
        self._critica("Excluir o cadastro", u, lambda c: self.servico.excluir_usuario(self._eu(), u.id, c),
                      f"Cadastro de {u.nome} excluído; o rosto foi eliminado do modelo.")

    def _registrar_revisao(self):
        self._critica("Registrar a revisão de acessos (S-10)", None,
                      lambda c: self.servico.registrar_revisao(self._eu(), c),
                      "Revisão registrada na trilha, com quem pediu e quem aprovou.")

    def _alternar_ativo(self):
        usuario = self._selecionado()
        if usuario is None:
            return
        if usuario.ativo and self.servico.eh_administrador(usuario.id) and self.sessao is not None:
            # desativar um ADMIN tira dele o papel: é ação crítica
            self._critica("Desativar o cadastro de um administrador", usuario,
                          lambda c: self.servico.definir_ativo(usuario.id, False, self._eu(), c),
                          f"Cadastro de {usuario.nome} desativado e papel de administrador retirado.")
            return
        recusa = self.servico.definir_ativo(usuario.id, not usuario.ativo, self._eu())
        if recusa:
            InfoBar.warning("Não foi possível", recusa, duration=5000, position=InfoBarPosition.TOP, parent=self)
        self.atualizar_tabela()

    def _revogar(self):
        usuario = self._selecionado()
        if usuario is None:
            return
        caixa = MessageBox("Revogar consentimento",
                           f"Revogar o consentimento de {usuario.nome} ({usuario.matricula})? O cadastro "
                           "será desativado e o modelo do rosto, ELIMINADO. Não há como desfazer: "
                           "só um novo cadastro, com novo termo, devolve o acesso.", self.window())
        if not caixa.exec():
            return
        if self.sessao is None or not self.servico.administrador_vinculado:     # configuração inicial
            recusa = self.servico.revogar_consentimento(usuario.id)
        else:
            codigo = self.pedir_aprovacao("Revogar o consentimento e eliminar o rosto",
                                          f"{usuario.nome} ({usuario.matricula})")
            if codigo is None:
                return
            recusa = self.servico.revogar_consentimento(usuario.id, self._eu(), codigo or None)
        if recusa:
            InfoBar.warning("Atenção", recusa, duration=5000, position=InfoBarPosition.TOP, parent=self)
        else:
            InfoBar.success("Consentimento revogado", "Cadastro desativado e rosto eliminado do modelo.",
                            duration=4000,
                            position=InfoBarPosition.TOP, parent=self)
        self.atualizar_tabela()

    def _dados_do_titular(self):
        usuario = self._selecionado()
        if usuario is None:
            return
        caminho, _ = QFileDialog.getSaveFileName(self, "Salvar relatório do titular",
                                                 f"titular_{usuario.matricula}.txt", "Texto (*.txt)")
        if not caminho:
            return
        Path(caminho).write_text(self.servico.dados_do_titular(usuario.id), encoding="utf-8")
        InfoBar.success("Relatório salvo", caminho, duration=4000, position=InfoBarPosition.TOP, parent=self)

    # ============================================================ cadastro
    def _novo_cadastro(self):
        self._encerrar_assistente()
        # configuração inicial: o primeiro cadastro, Externo, vira o primeiro administrador
        perfis = tuple(Perfil) if self.servico.administrador_vinculado else (Perfil.EXTERNO,)
        self.assistente = AssistenteCadastro(self.app, perfis=perfis)
        self.assistente.finalizado.connect(self._cadastro_finalizado)
        self.pilha.addWidget(self.assistente)
        self.pilha.setCurrentWidget(self.assistente)

    def _recadastrar_rosto(self, usuario_id: int):
        """Só pelo acesso de emergência (o painel restrito já registrou a autorização na trilha)."""
        self._encerrar_assistente()
        self.assistente = AssistenteCadastro(self.app, recadastro=self.servico.usuario(usuario_id))
        self.assistente.finalizado.connect(self._cadastro_finalizado)
        self.pilha.addWidget(self.assistente)
        self.pilha.setCurrentWidget(self.assistente)

    def _cadastro_finalizado(self, usuario):
        recadastro = self.assistente is not None and self.assistente.recadastro is not None
        self._encerrar_assistente()
        if self._em_emergencia():
            self.pilha.setCurrentIndex(EMERGENCIA)
            self.tela_emergencia.atualizar()
            if usuario is not None:
                InfoBar.success("Rosto recadastrado", f"{usuario.nome} já pode entrar pelo login.",
                                duration=5000, position=InfoBarPosition.TOP, parent=self)
            return
        self.pilha.setCurrentIndex(PAINEL)
        if usuario is not None and not recadastro and not self.servico.administrador_vinculado:
            recusa = self.servico.vincular_primeiro_administrador(usuario.id)
            if recusa:
                InfoBar.warning("Primeiro administrador", recusa, duration=7000, position=InfoBarPosition.TOP,
                                parent=self)
        self.atualizar_tabela()
        if usuario is not None and not recadastro:
            self.cadastro_concluido.emit()
            InfoBar.success("Cadastro concluído", f"{usuario.nome}, matrícula {usuario.matricula}",
                            duration=5000, position=InfoBarPosition.TOP, parent=self)

    def _encerrar_assistente(self):
        if self.assistente is not None:
            assistente, self.assistente = self.assistente, None
            assistente.encerrar()                         # apaga as faces, para a câmera
            self.pilha.removeWidget(assistente)
            assistente.deleteLater()

    def hideEvent(self, evento):
        # trocar de página tranca o painel; minimizar a janela (evento
        # "espontâneo", vindo do sistema) não: senão cancelaria um cadastro
        if not evento.spontaneous():
            self.bloquear()
        super().hideEvent(evento)
