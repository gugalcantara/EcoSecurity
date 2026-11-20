"""S4 Inerência: é quem diz ser?"""
from collections.abc import Mapping

from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import ModoBiometrico, Nivel
from ecosec.seguranca.acesso.veredito import Veredito, aprovar, negar

CAMADA = CamadaSeguranca.S4_INERENCIA


def avaliar(nivel: Nivel, distancia: float | None, identidade_medida: int | None,
            limiares: Mapping[Nivel, float], identidade_alegada: int | None = None) -> Veredito:
    """
    identidade_medida: a quem a distância se refere (o mais próximo no 1:N;
                       o alegado no 1:1).
    identidade_alegada: quem a matrícula diz ser (só 1:1).
    """
    verificacao = nivel.modo is ModoBiometrico.VERIFICACAO
    falha = Motivo.CREDENCIAL_ALHEIA if verificacao else Motivo.FACE_NAO_RECONHECIDA

    limiar = limiares.get(nivel)
    if limiar is None or distancia is None or identidade_medida is None:
        return negar(falha)
    if not (distancia <= limiar):
        return negar(falha)
    # no 1:1 a distância precisa ter sido medida contra o alegado; medida contra
    # outra identidade, ela não prova nada sobre quem digitou a senha
    if verificacao and identidade_medida != identidade_alegada:
        return negar(falha)
    return aprovar(CAMADA)
