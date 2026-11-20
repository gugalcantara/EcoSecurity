"""S7 Custódia: outra pessoa confirma?"""
from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.seguranca.acesso.veredito import Veredito, aprovar, negar

CAMADA = CamadaSeguranca.S7_CUSTODIA


def avaliar(primeiro: Usuario | None, segundo: Usuario | None, segundo_autenticado: bool | None,
            segundos_entre: float | None, janela_segundos: float) -> Veredito:
    # o tempo decorrido é um fato objetivo, conhecido mesmo sem a segunda pessoa:
    # janela vencida é o motivo, ainda que ninguém tenha chegado.
    # A forma `not (...)` nega também negativo (relógio voltou) e NaN.
    if segundos_entre is not None and not (0 <= segundos_entre <= janela_segundos):
        return negar(Motivo.JANELA_EXPIRADA)
    if segundo is None:
        return negar(Motivo.SEGUNDA_PESSOA_AUSENTE)
    # identidade antes da autenticação: "a mesma pessoa duas vezes" é inválido
    # já na matrícula, sem precisar passar pela câmera de novo
    if (primeiro is None or segundo.id is None or segundo.id == primeiro.id
            or segundo.nivel is not Nivel.N3 or segundo.ativo is not True):
        return negar(Motivo.SEGUNDA_PESSOA_INVALIDA)
    if segundo_autenticado is not True:
        return negar(Motivo.SEGUNDA_PESSOA_AUSENTE)
    if segundos_entre is None:
        return negar(Motivo.JANELA_EXPIRADA)
    return aprovar(CAMADA)
