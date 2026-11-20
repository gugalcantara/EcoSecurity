"""S5 Habilitação: tem direito?"""
from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.seguranca.acesso.veredito import Veredito, aprovar, negar

CAMADA = CamadaSeguranca.S5_HABILITACAO


def avaliar(usuario: Usuario | None, consentimento_vigente: bool | None,
            nivel_solicitado: Nivel, entrada: bool = False, administrador: bool = False) -> Veredito:
    if usuario is None:
        # rosto reconhecido sem cadastro correspondente: modelo e banco
        # divergem. Não é culpa de quem tenta: é inconsistência interna.
        return negar(Motivo.ERRO_INTERNO, CAMADA)
    if usuario.ativo is not True:
        return negar(Motivo.USUARIO_INATIVO)
    if consentimento_vigente is not True:
        return negar(Motivo.CONSENTIMENTO_AUSENTE)
    if entrada:
        if usuario.perfil.camada is None and administrador is not True:
            return negar(Motivo.SEM_ACESSO)
    elif not usuario.perfil.ve(nivel_solicitado):
        return negar(Motivo.NIVEL_INSUFICIENTE)
    return aprovar(CAMADA)
