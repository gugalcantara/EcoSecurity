"""S5 Habilitação: "Tem direito?"

Provar quem se é (S2, S4) não basta: a identidade confirmada ainda precisa
estar AUTORIZADA. Três condições, todas obrigatórias:

1. Cadastro ativo: desativar é a forma de suspender alguém sem apagar a
   história (amostras e trilha continuam íntegras).
2. Consentimento vigente: sem termo aceito e não revogado não há base legal
   para tratar a face (LGPD art. 11, I). É verificado a cada acesso, não só no
   cadastro: o rosto continua no modelo depois da revogação, e só esta
   checagem impede que ele siga abrindo a porta.
3. Acesso habilitado: no LOGIN, ter um perfil com camada (servidor, diretor,
   ministro) ou o papel de administrador (um Externo sem esse papel não entra); ao
   abrir uma camada, ser a camada do perfil. Escopo exclusivo: o ministro não
   abre a camada 1 nem a 2, e o administrador (Externo) não abre camada nenhuma.
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
