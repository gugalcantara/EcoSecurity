"""Correções de 12/10: câmera lenta não consome o prazo do rosto; backend DirectShow."""
import cv2
import pytest

from ecosec.dominio.motivos import Motivo
from ecosec.servicos.autenticacao import Etapa
from ecosec.visao import aquisicao
from ecosec.visao.aquisicao import Camera
from test_servico_autenticacao import SENHA_N2, alimentar, ambiente, quadro  # noqa: F401


def test_camera_lenta_nao_consome_o_prazo_do_rosto(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    ambiente.rec.distancias = {bia.id: 40.0}
    sessao = ambiente.servico.nova_sessao(2)
    sessao.informar_credenciais(bia.matricula, SENHA_N2)
    ambiente.relogio.avancar(ambiente.p.timeout_rosto + 10)     # webcam levando 25 s para abrir
    assert sessao.processar(quadro()).etapa is Etapa.ROSTO       # antes: negava aqui (FACE_AUSENTE)
    assert alimentar(sessao, 4).decisao.concedido


def test_prazo_do_rosto_continua_valendo_depois_do_primeiro_quadro(ambiente):
    bia = ambiente.criar("bia", 2, SENHA_N2)
    sessao = ambiente.servico.nova_sessao(2)
    sessao.informar_credenciais(bia.matricula, SENHA_N2)
    sessao.processar(quadro(faces=0))
    ambiente.relogio.avancar(ambiente.p.timeout_rosto + 1)
    assert sessao.processar(quadro(faces=0)).decisao.motivo is Motivo.FACE_AUSENTE


def test_backend_desconhecido_e_recusado():
    with pytest.raises(ValueError):
        Camera(0, 640, 480, 1.0, backend="v4l9")


def test_backend_indisponivel_cai_no_padrao(monkeypatch):
    pedidos = []

    class Captura:
        def __init__(self, indice, api=cv2.CAP_ANY):
            pedidos.append(api)
            self.aberta = api == cv2.CAP_ANY

        def isOpened(self):
            return self.aberta

        def release(self):
            pass

    monkeypatch.setattr(aquisicao.cv2, "VideoCapture", Captura)
    captura = Camera(0, 640, 480, 1.0, backend="dshow")._abrir_webcam(0)
    assert captura.isOpened() and pedidos == [cv2.CAP_DSHOW, cv2.CAP_ANY]
