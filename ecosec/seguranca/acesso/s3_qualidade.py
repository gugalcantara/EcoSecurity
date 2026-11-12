"""S3 Qualidade: "A imagem permite decidir?"

Uma decisão tomada sobre imagem ruim é um sorteio. Um rosto escuro e borrado
gera um histograma LBP pobre, e a distância vira ruído: tanto pode negar o
dono quanto aceitar um parecido. Por isso a S3 vem antes da S4: o reconhecedor
só recebe o que vale a pena reconhecer.

As medidas (nitidez, brilho, contraste, número de faces) são calculadas pela
camada de visão. Aqui só se decide se elas bastam.

Uma pessoa por vez (EXC-02): duas faces na cena são recusadas, não resolvidas.
Escolher "a maior" deixaria alguém entrar com um terceiro ao fundo.
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
