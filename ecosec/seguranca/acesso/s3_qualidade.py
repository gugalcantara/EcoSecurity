"""S3 Qualidade: "A imagem permite decidir?"

Com um rosto escuro ou borrado, o histograma LBP fica pobre e a distância vira ruído:
o sistema poderia negar o dono ou aceitar alguém parecido. Por isso a S3 é avaliada
antes da S4.

As medidas (nitidez, brilho, contraste e número de faces) vêm da camada de visão;
esta camada decide se bastam. Com duas faces na cena, o quadro é recusado: escolher
a maior deixaria uma terceira pessoa entrar ao fundo.
"""
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
