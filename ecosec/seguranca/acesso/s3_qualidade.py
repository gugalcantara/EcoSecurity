"""S3 Qualidade: a imagem permite decidir?"""
from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.motivos import Motivo
from ecosec.seguranca.acesso.veredito import Veredito, aprovar, negar

CAMADA = CamadaSeguranca.S3_QUALIDADE


def avaliar(faces_detectadas: int | None, qualidade_aprovada: bool | None) -> Veredito:
    if not faces_detectadas:             # None ou 0
        return negar(Motivo.FACE_AUSENTE)
    if faces_detectadas > 1:
        return negar(Motivo.MULTIPLAS_FACES)
    if qualidade_aprovada is not True:
        return negar(Motivo.QUALIDADE_INSUFICIENTE)
    return aprovar(CAMADA)
