"""S5 Habilitação: "Tem direito?"

Depois de confirmada a identidade (S2 e S4), o cadastro ainda precisa estar
autorizado. São três condições, todas obrigatórias:

1. Cadastro ativo. Desativar suspende alguém sem apagar o histórico (amostras e
   trilha continuam íntegras).
2. Consentimento vigente, conferido a cada acesso (LGPD art. 11, I). Depois de uma
   revogação, o rosto ainda pode estar no modelo, e é esta checagem que o impede de
   continuar abrindo o sistema.
3. Acesso habilitado. No login, a pessoa precisa ter um perfil com camada (servidor,
   diretor ou ministro) ou o papel de administrador; ao abrir uma camada, ela
   precisa ser a do perfil. O ministro não abre as camadas 1 e 2, e o administrador
   não abre nenhuma.
"""
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
