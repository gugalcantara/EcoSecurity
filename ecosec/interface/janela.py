"""Janela principal (FluentWindow). O menu lateral depende do estado:

    Configuração inicial  instalação nova (sem senha de instalação ou sem
                          administrador): só "Administração", pela senha, para
                          fazer o primeiro cadastro, que nasce administrador
    LOGIN                 só o login de entrada; nada do sistema fica visível.
                          É o mesmo login para todos: o sistema reconhece o
                          perfil pelo cadastro
    LOGADO                Início · a aba da camada do perfil (só ela: escopo
                          exclusivo) · Encerrar sessão. O administrador não
                          tem camada: Início e Administração, e nenhuma aba
                          do acervo, nunca. "Camadas de segurança" só entra
                          no menu com [interface] modo_demonstracao = true
    EMERGÊNCIA            pelo acesso de emergência (quórum de admins): só a
                          Administração restrita e Encerrar; termina sozinha
                          no fim do prazo ou na primeira inatividade

Cada página existe uma vez; o estado só mostra ou oculta os itens do menu.

INATIVIDADE: nada fecha no meio de uma atividade. Depois de [sessao]
inatividade_minutos sem uso (mouse, rolagem, teclado; câmera ligada também
conta), a sessão é BLOQUEADA: o menu some, a tela pede a senha e devolve a
pessoa para onde estava. Sair (pelo botão) encerra câmeras e acervos, tranca o
painel e volta ao login.
"""
import sys
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.interface.atividade import PrazoInatividade
from ecosec.interface.estilo import ICONE_NIVEL, alternar_tema, aplicar_tema
from ecosec.interface.fluent import FIF, FluentWindow, InfoBar, InfoBarPosition, NavigationItemPosition
from ecosec.interface.pagina_acesso import PaginaInicio, PaginaNivel
from ecosec.interface.pagina_admin import PaginaAdministracao
from ecosec.interface.pagina_bloqueio import PaginaBloqueio
from ecosec.interface.pagina_camadas import PaginaCamadas
from ecosec.interface.pagina_entrada import PaginaEntrada


ICONE = Path(__file__).parent / "recursos" / "ecosecurity.ico"   # o mesmo desenho de logo.py, em arquivo
# Identidade do aplicativo no Windows. Sem ela, o processo é o python.exe e a barra
# de tarefas agrupa a janela sob o "Python", com o ícone dele.
ID_APLICATIVO = "UNIP.EcoSecurity.APS"


def declarar_aplicativo_windows() -> None:
    """Precisa vir antes da primeira janela."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ID_APLICATIVO)


def icone_aplicativo() -> QIcon:
    if ICONE.exists():
        return QIcon(str(ICONE))
    from ecosec.interface.logo import pixmap_logo
    return QIcon(pixmap_logo(256))                  # reserva: o mesmo logo, desenhado na hora


class Estado(str, Enum):
    CONFIGURACAO = "CONFIGURACAO"
    LOGIN = "LOGIN"
    LOGADO = "LOGADO"


class JanelaPrincipal(FluentWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.sessao = None                       # SessaoAplicacao do logado
        self.bloqueada = False                   # sessão viva, mas atrás da tela de bloqueio
        self._pagina_antes_do_bloqueio = None
        self._fim_emergencia = QTimer(self)
        self._fim_emergencia.setSingleShot(True)
        self._fim_emergencia.timeout.connect(self._emergencia_expirou)
        self.setWindowTitle(f"{app.cfg['aplicacao.nome']} · {app.cfg['aplicacao.subtitulo']}")
        self.setWindowIcon(icone_aplicativo())
        # Sem o efeito Mica do Windows 11: ele deixa o fundo transparente para o
        # sistema pintar, e onde não há Mica (Windows 10, capturas de tela) o
        # fundo fica branco sob o texto claro do tema escuro. A janela pinta o
        # próprio fundo conforme o tema.
        self.setMicaEffectEnabled(False)

        self.pagina_entrada = PaginaEntrada(app, self)
        self.pagina_inicio = PaginaInicio(app, self)
        self.paginas_nivel = {n: PaginaNivel(app, n, self) for n in Nivel}
        s7_ligada = app.autenticacao.p.acesso.exigir_segunda_pessoa
        self.pagina_camadas = PaginaCamadas(self, desligadas=() if s7_ligada else {CamadaSeguranca.S7_CUSTODIA})
        self.modo_demonstracao = self.pagina_entrada.autenticacao.modo_demonstracao
        self.pagina_admin = PaginaAdministracao(app, self)
        self.pagina_bloqueio = PaginaBloqueio(self)
        self.pagina_bloqueio.desbloquear.connect(self._tentar_desbloqueio)
        self.pagina_bloqueio.sair.connect(lambda: self.encerrar_sessao("SAIDA"))
        self.pagina_entrada.entrou.connect(self._entrou)
        self.pagina_entrada.emergencia.connect(self._entrou_emergencia)
        self.pagina_admin.sair_emergencia.connect(lambda: self.encerrar_sessao("EMERGENCIA_ENCERRADA"))
        self.pagina_inicio.abrir_nivel.connect(lambda n: self.switchTo(self.paginas_nivel[n]))
        self.pagina_inicio.sair.connect(lambda: self.encerrar_sessao("SAIDA"))
        self.pagina_inicio.abrir_administracao.connect(lambda: self.switchTo(self.pagina_admin))
        for pagina in [*self.paginas_nivel.values(), self.pagina_admin]:
            pagina.voltar_inicio.connect(lambda: self.switchTo(self.pagina_inicio))
        self.pagina_admin.cadastro_concluido.connect(self._talvez_fim_da_configuracao)

        # login e bloqueio nunca aparecem no menu (ocultos em _aplicar_estado); o ícone é o do app
        self.addSubInterface(self.pagina_entrada, icone_aplicativo(), "Login")
        self.addSubInterface(self.pagina_bloqueio, icone_aplicativo(), "Bloqueio")
        self.addSubInterface(self.pagina_inicio, FIF.HOME, "Início")
        for nivel, pagina in self.paginas_nivel.items():
            self.addSubInterface(pagina, getattr(FIF, ICONE_NIVEL[nivel]), f"Nível {nivel.value}")
        # ícones distintos dos três níveis (pessoas, certificado, cadeado)
        self.addSubInterface(self.pagina_camadas, FIF.LIBRARY, "Camadas de segurança")
        self.addSubInterface(self.pagina_admin, FIF.SETTING, "Administração", position=NavigationItemPosition.BOTTOM)
        self.navigationInterface.addItem("sair", FIF.POWER_BUTTON, "Encerrar sessão",
                                         onClick=lambda: self.encerrar_sessao("SAIDA"), selectable=False,
                                         position=NavigationItemPosition.BOTTOM)
        self.navigationInterface.addItem("tema", FIF.CONSTRACT, "Tema claro/escuro", onClick=alternar_tema,
                                         selectable=False, position=NavigationItemPosition.BOTTOM)

        # inatividade real (mouse, rolagem, teclado; câmera ligada conta como uso): bloqueia, não encerra
        self._inatividade = PrazoInatividade(app.sessao.inatividade_minutos, ocupado=self._ocupado, parent=self)
        self._inatividade.vencido.connect(self.bloquear_sessao)

        self.resize(1240, 820)
        tela = QApplication.primaryScreen().availableGeometry()
        self.move(tela.center() - self.rect().center())
        self._aplicar_estado()

    # estado
    @property
    def estado(self) -> Estado:
        adm = self.app.administracao
        if not adm.configurado or not adm.administrador_vinculado:
            return Estado.CONFIGURACAO          # instalação nova: ninguém consegue fazer login ainda
        return Estado.LOGADO if self.sessao is not None else Estado.LOGIN

    def _mostrar_no_menu(self, pagina_ou_chave, visivel: bool):
        chave = pagina_ou_chave if isinstance(pagina_ou_chave, str) else pagina_ou_chave.objectName()
        self.navigationInterface.widget(chave).setVisible(visivel)

    def _menu_do_acervo(self, logado: bool):
        """Só a aba da camada do perfil (escopo exclusivo). O administrador e a emergência não têm nenhuma."""
        visiveis = set(self.sessao.niveis_com_aba) if logado and not self.sessao.em_emergencia else set()
        for nivel, pagina in self.paginas_nivel.items():
            self._mostrar_no_menu(pagina, nivel in visiveis)
        self._mostrar_no_menu(self.pagina_inicio, logado and not self.sessao.em_emergencia)
        self._mostrar_no_menu(self.pagina_camadas, logado and not self.sessao.em_emergencia
                              and self.modo_demonstracao)

    def _aplicar_estado(self, destino=None):
        estado = self.estado
        logado = estado is Estado.LOGADO and not self.bloqueada    # bloqueada: nada do sistema no menu
        self._mostrar_no_menu(self.pagina_entrada, False)          # o login nunca é item de menu
        self._mostrar_no_menu(self.pagina_bloqueio, False)
        self._menu_do_acervo(logado)
        self._mostrar_no_menu(self.pagina_admin, estado is Estado.CONFIGURACAO
                              or (logado and self.sessao.administrador))
        self._mostrar_no_menu("sair", logado)
        if self.bloqueada:
            destino = self.pagina_bloqueio
        elif destino is None:
            destino = {Estado.CONFIGURACAO: self.pagina_admin, Estado.LOGIN: self.pagina_entrada,
                       Estado.LOGADO: self.pagina_inicio}[estado]
            if estado is Estado.LOGADO and self.sessao.em_emergencia:
                destino = self.pagina_admin
        self.switchTo(destino)
        if logado:
            self._inatividade.iniciar()
        else:
            self._inatividade.parar()

    # bloqueio por inatividade
    def _ocupado(self) -> bool:
        """Câmera ligada (login, step-up, conferência, captura do cadastro) é uso, não inatividade."""
        telas = [p.autenticacao for p in self.paginas_nivel.values()] + [self.pagina_admin.tela_rosto]
        return any(t.trabalhador is not None for t in telas) or self.pagina_admin.camera_ligada()

    def bloquear_sessao(self):
        if self.sessao is None or self.bloqueada:
            return
        if self.sessao.em_emergencia:                    # sem senha que a devolva: a emergência termina
            self.encerrar_sessao("EMERGENCIA_INATIVIDADE")
            return
        atual = self.stackedWidget.currentWidget()
        self._pagina_antes_do_bloqueio = atual
        self.bloqueada = True
        self.paginas_nivel[Nivel.N3].encerrar()          # exigiu prova de vida: senha não reabre
        self.pagina_admin.bloquear()                     # exige o rosto de novo (e desliga a identificação)
        self.app.sessao.registrar(self.sessao, "BLOQUEIO_INATIVIDADE")
        self.pagina_bloqueio.mostrar(self.sessao.usuario.nome, self.sessao.usuario.matricula,
                                     self.app.sessao.inatividade_minutos)
        self._aplicar_estado()

    def _tentar_desbloqueio(self, senha: str):
        if self.sessao is None or not self.bloqueada:
            return
        motivo = self.app.autenticacao.desbloquear(self.sessao.identidade, senha)
        if motivo is Motivo.CONCEDIDO:
            self.bloqueada = False
            antes = self._pagina_antes_do_bloqueio
            self._pagina_antes_do_bloqueio = None
            self._aplicar_estado(destino=antes if antes is not None and antes is not self.pagina_bloqueio else None)
        elif motivo in (Motivo.BLOQUEADO, Motivo.USUARIO_INATIVO, Motivo.ERRO_INTERNO):
            self.encerrar_sessao("SAIDA")
            InfoBar.error("Sessão encerrada", motivo.mensagem, duration=8000, position=InfoBarPosition.TOP,
                          parent=self)
        else:
            self.pagina_bloqueio.mostrar_erro("Senha incorreta.")

    # sessão
    def _talvez_fim_da_configuracao(self):
        if self.sessao is None and self.estado is Estado.LOGIN:
            self._aplicar_estado()
            InfoBar.success("Configuração inicial concluída", "Entre pelo login.", duration=8000,
                            position=InfoBarPosition.TOP, parent=self)

    def _entrou(self, sessao_entrada):
        sessao = self.app.sessao.abrir(sessao_entrada)
        if sessao is None:
            return
        self.sessao = sessao
        self.pagina_inicio.definir_sessao(sessao)
        for pagina in self.paginas_nivel.values():
            pagina.definir_sessao(sessao)
        self.pagina_admin.definir_sessao(sessao)
        self._aplicar_estado()

    def _entrou_emergencia(self, emergencia):
        sessao = self.app.sessao.abrir_emergencia(emergencia)
        if sessao is None:
            return
        self.sessao = sessao
        self.pagina_admin.definir_sessao(sessao)        # só a Administração recebe a sessão de emergência
        restante = (emergencia.fim - self.app.administracao.relogio()).total_seconds()
        self._fim_emergencia.start(max(1, int(restante * 1000)))
        self._aplicar_estado()
        InfoBar.warning("Acesso de emergência", f"Válido até as {emergencia.fim:%H:%M}.", duration=8000,
                        position=InfoBarPosition.TOP, parent=self)

    def _emergencia_expirou(self):
        if self.sessao is not None and self.sessao.em_emergencia:
            self.encerrar_sessao("EMERGENCIA_EXPIRADA")
            InfoBar.info("Acesso de emergência encerrado", "O prazo terminou. Entre pelo login.", duration=8000,
                         position=InfoBarPosition.TOP, parent=self)

    def encerrar_sessao(self, motivo: str = "SAIDA"):
        if self.sessao is None:
            return
        self._fim_emergencia.stop()
        for pagina in self.paginas_nivel.values():
            pagina.definir_sessao(None)              # encerra acervos e tentativas abertas
        self.pagina_admin.definir_sessao(None)       # tranca o painel, descarta cadastro em andamento
        self.pagina_inicio.definir_sessao(None)
        self.app.sessao.encerrar(self.sessao, motivo)
        self.sessao = None
        self.bloqueada = False
        self._pagina_antes_do_bloqueio = None
        self._aplicar_estado()

    def closeEvent(self, evento):
        # nenhuma câmera ligada e nenhuma face na memória depois de fechar
        self.encerrar_sessao("SAIDA")
        self.pagina_entrada.encerrar()
        self.pagina_admin.bloquear()
        self._inatividade.parar()
        super().closeEvent(evento)


def mostrar_erro_abertura(mensagem: str) -> int:
    """O sistema não abre em modo degradado: explica o que fazer e encerra."""
    from PySide6.QtWidgets import QMessageBox
    declarar_aplicativo_windows()
    qt = QApplication.instance() or QApplication(sys.argv)
    qt.setWindowIcon(icone_aplicativo())
    aplicar_tema("claro")
    caixa = QMessageBox(QMessageBox.Icon.Critical, "EcoSecurity: não foi possível abrir com segurança",
                        mensagem)
    caixa.setWindowIcon(icone_aplicativo())
    caixa.exec()
    return 1


def executar(app) -> int:
    declarar_aplicativo_windows()
    qt = QApplication.instance() or QApplication(sys.argv)
    qt.setApplicationName("EcoSecurity")
    qt.setWindowIcon(icone_aplicativo())        # vale para todas as janelas e diálogos
    aplicar_tema(app.cfg["aplicacao.tema"])
    janela = JanelaPrincipal(app)
    janela.show()
    return qt.exec()
