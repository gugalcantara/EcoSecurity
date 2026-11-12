"""Páginas depois do login de entrada: o início e uma aba por camada.

Início (escopo exclusivo): só o cartão da camada do perfil. As outras
camadas não aparecem nem são mencionadas. O administrador não tem camada: o
Início dele mostra só a Administração.

Aba de camada (PaginaNivel): só aparece no menu para quem tem o perfil daquela
camada. Ao abrir:
- N1 e N2: step-up sem fator novo. O login já provou matrícula, senha e rosto
  1:1; a política reavalia essas evidências para o nível pedido e decide
  (ServicoAutenticacao.abrir_nivel). Desativar alguém vale na próxima aba.
- N3: step-up com fatores novos. Rosto de novo, gesto (vivacidade) e, com a S7
  ligada, a segunda pessoa; matrícula e senha vêm do login.
Sair da aba (trocar de página) encerra o acervo e qualquer tentativa aberta.

Layout: a página inicial rola em vez de espremer, e o botão de cada cartão tem
altura fixa. Em janela estreita, os cartões ficam um embaixo do outro.
"""
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from ecosec.dominio.niveis import Nivel
from ecosec.interface.componentes import Selo, camadas_avaliadas
from ecosec.interface.estilo import COR_DESTAQUE, COR_NIVEL, ICONE_NIVEL, VERDE, VERMELHO, cor_texto_secundario
from ecosec.interface.fluent import (FIF, BodyLabel, CaptionLabel, CardWidget, IconWidget, LargeTitleLabel,
                                     PrimaryPushButton, PushButton, ScrollArea, SimpleCardWidget, StrongBodyLabel,
                                     SubtitleLabel, TitleLabel)
from ecosec.interface.tela_acervo import TelaAcervo
from ecosec.interface.tela_autenticacao import TelaAutenticacao

ALTURA_BOTAO = 40


def ao_abrir(app, nivel: Nivel) -> str:
    """O que é pedido para abrir o nível depois do login (step-up)."""
    if nivel is not Nivel.N3:
        return "Acesso liberado pelo login."
    extra = " e de uma segunda pessoa autorizada" if app.autenticacao.p.acesso.exigir_segunda_pessoa else ""
    return f"Requer nova verificação facial{extra}."


def _rotulo_secao(texto: str) -> CaptionLabel:
    rotulo = CaptionLabel(texto.upper())
    rotulo.setStyleSheet(f"color:{cor_texto_secundario()}; font-weight:600; letter-spacing:1px;")
    return rotulo


class CartaoNivel(CardWidget):
    """O cartão da camada da pessoa: o que mostra, como abre e o botão. Só existe o da própria camada."""

    def __init__(self, app, nivel: Nivel, ao_abrir_nivel, parent=None):
        super().__init__(parent)
        self.nivel = nivel
        cor = COR_NIVEL[nivel]
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 20)
        v.setSpacing(8)
        faixa = QWidget()
        faixa.setFixedHeight(4)
        faixa.setStyleSheet(f"background:{cor}; border-radius:2px;")
        v.addWidget(faixa)

        cabeca = QHBoxLayout()
        icone = IconWidget(getattr(FIF, ICONE_NIVEL[nivel]))
        icone.setFixedSize(26, 26)
        cabeca.addWidget(icone)
        titulo = SubtitleLabel(f"Nível {nivel.value}")
        titulo.setTextColor(QColor(cor), QColor(cor))
        cabeca.addWidget(titulo, 1)
        self.selo = Selo("Seu acesso", VERDE)
        cabeca.addWidget(self.selo, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(cabeca)
        v.addWidget(StrongBodyLabel(nivel.titulo))
        publico = CaptionLabel(f"Para: {nivel.publico}")
        publico.setStyleSheet(f"color:{cor_texto_secundario()};")
        v.addWidget(publico)

        v.addSpacing(4)
        v.addWidget(_rotulo_secao("O que mostra"))
        conteudo = BodyLabel(nivel.conteudo + ".")
        conteudo.setWordWrap(True)
        v.addWidget(conteudo)
        quantos = CaptionLabel(f"{len(app.acervo.catalogo(nivel))} relatórios")
        quantos.setStyleSheet(f"color:{cor_texto_secundario()};")
        v.addWidget(quantos)
        v.addStretch(1)

        v.addSpacing(4)
        self.situacao_texto = CaptionLabel()
        self.situacao_texto.setWordWrap(True)
        self.situacao_texto.setText(ao_abrir(app, nivel))
        self.situacao_texto.setStyleSheet(f"color:{cor};")
        self.botao = PrimaryPushButton(f"Abrir o Nível {nivel.value}")
        self.botao.setIcon(FIF.RIGHT_ARROW)
        self.botao.clicked.connect(lambda: ao_abrir_nivel(nivel))
        self.botao.setFixedHeight(ALTURA_BOTAO)              # nunca encolhe, aconteça o que acontecer acima
        v.addWidget(self.situacao_texto)
        v.addWidget(self.botao)


class PaginaInicio(QWidget):
    abrir_nivel = Signal(object)          # Nivel
    abrir_administracao = Signal()
    sair = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.setObjectName("paginaInicio")
        self.app = app
        self.sessao = None
        self.cartoes: list[CartaoNivel] = []
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        rolagem = ScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        rolagem.setWidget(w)
        externo.addWidget(rolagem)
        v = QVBoxLayout(w)
        v.setContentsMargins(36, 24, 36, 28)
        v.setSpacing(8)

        # ---- cabeçalho: quem está logado
        topo = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(4)
        self.saudacao = LargeTitleLabel()
        textos.addWidget(self.saudacao)
        self.linha_selos = QHBoxLayout()
        self.linha_selos.setSpacing(8)
        textos.addLayout(self.linha_selos)
        self.detalhes = CaptionLabel()
        self.detalhes.setStyleSheet(f"color:{cor_texto_secundario()};")
        textos.addWidget(self.detalhes)
        topo.addLayout(textos, 1)
        self.botao_sair = PushButton("Encerrar sessão")
        self.botao_sair.setIcon(FIF.POWER_BUTTON)
        self.botao_sair.setToolTip("Sai do sistema e volta ao login.")
        self.botao_sair.clicked.connect(self.sair.emit)
        topo.addWidget(self.botao_sair, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(topo)
        v.addSpacing(12)

        # ---- o acesso da pessoa (só o da própria camada)
        self.grade = QGridLayout()
        self.grade.setHorizontalSpacing(16)
        self.grade.setVerticalSpacing(16)
        v.addLayout(self.grade)

        # ---- administração (só para o administrador)
        self.cartao_admin = SimpleCardWidget()
        ha = QHBoxLayout(self.cartao_admin)
        ha.setContentsMargins(20, 16, 20, 16)
        ha.setSpacing(14)
        icone = IconWidget(FIF.SETTING)
        icone.setFixedSize(28, 28)
        ha.addWidget(icone)
        textos_admin = QVBoxLayout()
        textos_admin.setSpacing(2)
        textos_admin.addWidget(StrongBodyLabel("Administração"))
        texto_admin = CaptionLabel("Cadastros, perfis, consentimentos, administradores e trilha de auditoria.")
        texto_admin.setWordWrap(True)
        texto_admin.setStyleSheet(f"color:{cor_texto_secundario()};")
        textos_admin.addWidget(texto_admin)
        ha.addLayout(textos_admin, 1)
        botao_admin = PushButton("Abrir a Administração")
        botao_admin.setIcon(FIF.SETTING)
        botao_admin.clicked.connect(self.abrir_administracao.emit)
        ha.addWidget(botao_admin)
        v.addSpacing(10)
        v.addWidget(self.cartao_admin)
        v.addStretch(1)

    def definir_sessao(self, sessao):
        self.sessao = sessao
        for cartao in self.cartoes:
            # deleteLater só destrói quando o laço de eventos volta; até lá o cartão
            # da sessão ANTERIOR seguiria pintado por baixo do novo
            self.grade.removeWidget(cartao)
            cartao.hide()
            cartao.setParent(None)
            cartao.deleteLater()
        self.cartoes = []
        while self.linha_selos.count():
            item = self.linha_selos.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        if sessao is None:
            return
        u = sessao.usuario
        self.saudacao.setText(f"Olá, {u.nome.split()[0]}")
        self.linha_selos.addWidget(Selo(sessao.papel, COR_NIVEL[u.nivel] if u.nivel else COR_DESTAQUE))
        self.linha_selos.addStretch(1)
        minutos = self.app.sessao.inatividade_minutos
        self.detalhes.setText(f"{u.nome} · matrícula {u.matricula}" + (f" · UF {u.uf}" if u.uf else "") +
                              f" · sessão iniciada às {sessao.inicio:%H:%M} · encerra após {minutos:g} min sem uso")
        for nivel in sessao.niveis_com_aba:                  # só a camada do perfil (o admin não tem nenhuma)
            cartao = CartaoNivel(self.app, nivel, self.abrir_nivel.emit)
            cartao.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            self.grade.addWidget(cartao, 0, len(self.cartoes))
            self.cartoes.append(cartao)
        self.cartao_admin.setVisible(sessao.administrador)


class PaginaNivel(QWidget):
    voltar_inicio = Signal()

    def __init__(self, app, nivel: Nivel, parent=None):
        super().__init__(parent)
        self.setObjectName(f"paginaNivel{nivel.value}")
        self.app, self.nivel = app, nivel
        self.sessao = None
        self._saindo = False
        self.pilha = QStackedWidget(self)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.pilha)
        self.pilha.addWidget(self._tela_aviso())                       # 0
        self.autenticacao = TelaAutenticacao(app)
        self.autenticacao.voltar.connect(self.voltar_inicio.emit)
        self.autenticacao.concedido.connect(self._step_up_concedido)
        self.pilha.addWidget(self.autenticacao)                        # 1
        self.acervo = TelaAcervo(app)
        self.acervo.encerrada.connect(self._acervo_encerrado)
        self.pilha.addWidget(self.acervo)                              # 2

    def _tela_aviso(self):
        fundo = QWidget()
        externo = QVBoxLayout(fundo)
        externo.addStretch(1)
        cartao = SimpleCardWidget()
        cartao.setMaximumWidth(520)
        v = QVBoxLayout(cartao)
        v.setContentsMargins(28, 28, 28, 28)
        v.setSpacing(12)
        self.aviso_titulo = TitleLabel()
        self.aviso_texto = BodyLabel()
        self.aviso_texto.setWordWrap(True)
        self.aviso_detalhe = CaptionLabel()
        self.aviso_detalhe.setWordWrap(True)
        self.aviso_detalhe.setStyleSheet(f"color:{cor_texto_secundario()};")
        botoes = QHBoxLayout()
        repetir = PrimaryPushButton("Tentar de novo")
        repetir.setIcon(FIF.SYNC)
        repetir.clicked.connect(self._abrir)
        voltar = PushButton("Voltar ao início")
        voltar.clicked.connect(self.voltar_inicio.emit)
        botoes.addWidget(repetir)
        botoes.addWidget(voltar)
        botoes.addStretch(1)
        for item in (self.aviso_titulo, self.aviso_texto, self.aviso_detalhe):
            v.addWidget(item)
        v.addLayout(botoes)
        linha = QHBoxLayout()
        linha.addStretch(1)
        linha.addWidget(cartao, 3)
        linha.addStretch(1)
        externo.addLayout(linha)
        externo.addStretch(2)
        return fundo

    def definir_sessao(self, sessao):
        self.encerrar()
        self.sessao = sessao

    # ------------------------------------------------------------ abrir
    def showEvent(self, evento):
        super().showEvent(evento)
        if self.sessao is not None and self.pilha.currentIndex() != 2 and self.autenticacao.sessao is None:
            self._abrir()

    def _abrir(self):
        if self.sessao is None:
            return
        identidade = self.sessao.identidade
        if self.nivel is Nivel.N3:
            self.pilha.setCurrentIndex(1)
            self.autenticacao.iniciar_nivel(Nivel.N3, identidade)
            return
        decisao = self.app.autenticacao.abrir_nivel(identidade, self.nivel)
        if decisao.concedido:
            self._liberar(self.app.administracao.usuario(identidade.usuario_id))
            return
        self.aviso_titulo.setText(f"Nível {self.nivel.value}: acesso negado")
        self.aviso_titulo.setStyleSheet(f"color:{VERMELHO};")
        self.aviso_texto.setText(decisao.mensagem)
        self.aviso_detalhe.setText(camadas_avaliadas(decisao.vereditos) if self.autenticacao.modo_demonstracao
                                   else "")
        self.pilha.setCurrentIndex(0)

    def _step_up_concedido(self, sessao_autenticacao):
        if self.sessao is not None:              # o step-up do N3 acabou de conferir o rosto
            self.sessao.verificacao.registrar(datetime.now())
        self._liberar(sessao_autenticacao.usuario_autenticado)

    def _liberar(self, usuario):
        if usuario is None:
            return
        self.acervo.sessao = self.sessao
        self.acervo.iniciar(usuario, self.nivel)
        self.pilha.setCurrentIndex(2)

    def _acervo_encerrado(self):
        if not self._saindo:                # o próprio usuário encerrou: volta ao início
            self.pilha.setCurrentIndex(0)
            self.voltar_inicio.emit()

    # ------------------------------------------------------------ sair
    def encerrar(self):
        self._saindo = True
        try:
            self.autenticacao.encerrar()
            if self.pilha.currentIndex() == 2:
                self.acervo.encerrar()
            self.pilha.setCurrentIndex(0)
        finally:
            self._saindo = False

    def hideEvent(self, evento):
        # trocar de página encerra o acervo; minimizar a janela (evento espontâneo) não. A tela de
        # bloqueio por inatividade também não: N1 e N2 voltam como estavam (o N3 a janela fecha)
        bloqueio = getattr(self.window(), "bloqueada", False)
        if not evento.spontaneous() and not bloqueio:
            self.encerrar()
        super().hideEvent(evento)

