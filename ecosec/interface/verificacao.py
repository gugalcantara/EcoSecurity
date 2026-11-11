"""Step-up antes de uma operação crítica: a câmera confere o rosto de novo, na hora.

Modelo de verificação contínua: o login provou quem entrou; exportar nomes e
endereços prova que é a mesma pessoa que está diante do computador agora. A
biometria funciona como verificação de presença, não como senha.

Fluxo: o serviço recusa com VerificacaoNecessaria -> este diálogo abre a câmera
(TelaAutenticacao, finalidade OPERACAO: rosto 1:1 contra a identidade do login,
com contenção própria MATRÍCULA#OPR) -> concedido, a sessão registra o momento
e a tela repete a operação, agora dentro da janela de validade.
"""
from datetime import datetime

from PySide6.QtWidgets import QDialog, QVBoxLayout

from ecosec.interface.estilo import COR_NIVEL
from ecosec.dominio.niveis import Nivel
from ecosec.servicos.acervo import VerificacaoNecessaria


class DialogoVerificacao(QDialog):
    def __init__(self, app, sessao, motivo: str, parent=None):
        super().__init__(parent)
        from ecosec.interface.tela_autenticacao import TelaAutenticacao
        self.setWindowTitle("Confirmar presença")
        self.setModal(True)
        self.resize(980, 700)
        self.momento: datetime | None = None
        self._sessao_app = sessao
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.tela = TelaAutenticacao(app, self)
        self.tela.concedido.connect(self._concedido)
        self.tela.voltar.connect(self.reject)
        v.addWidget(self.tela)
        self.tela.iniciar(lambda: app.autenticacao.nova_verificacao_operacao(sessao.identidade),
                          "Confirmar presença", motivo, COR_NIVEL[Nivel.N2])

    def _concedido(self, _sessao_autenticacao):
        self.momento = datetime.now()
        self._sessao_app.verificacao.registrar(self.momento)
        self.accept()

    def done(self, resultado):
        self.tela.encerrar()                     # desliga a câmera em qualquer saída
        super().done(resultado)


def executar_com_verificacao(pai, app, sessao, operacao):
    """Roda `operacao(verificado_em)`; se o serviço pedir o rosto, abre o diálogo e repete uma vez.
    Devolve o resultado da operação, ou None se a pessoa desistiu da conferência."""
    verificado_em = sessao.verificacao.momento if sessao is not None else None
    try:
        return operacao(verificado_em)
    except VerificacaoNecessaria as pedido:
        if sessao is None:
            raise
        dialogo = DialogoVerificacao(app, sessao, str(pedido), pai)
        if dialogo.exec() != QDialog.DialogCode.Accepted or dialogo.momento is None:
            return None
        return operacao(dialogo.momento)
