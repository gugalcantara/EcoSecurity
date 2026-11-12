"""Motivos de uma decisão de acesso: o que a trilha grava e o que a tela diz.

Cada motivo pertence a uma camada. Há dois textos possíveis por motivo, e a
diferença entre eles é uma regra de segurança, não de interface:

- o código (ex.: CREDENCIAL_ALHEIA) vai para a trilha de auditoria, completo;
- a mensagem vai para a tela, e às vezes esconde a distinção de propósito.

Exemplo: rosto desconhecido e rosto que não casa com a matrícula respondem
igual na tela. Dizer "o rosto não confere com a matrícula" confirmaria a quem
tenta entrar que a SENHA estava certa: ele saberia que só falta o rosto.
Pelo mesmo motivo, matrícula inexistente e senha errada dizem o mesmo.
"""
from enum import Enum

from ecosec.dominio.camadas import CamadaSeguranca as C

_CREDENCIAIS = "Matrícula ou senha incorretas. Confira os dois campos."
_IDENTIDADE = ("Não foi possível confirmar a sua identidade. "
               "Posicione o rosto no centro, com boa luz, e tente de novo.")


class Motivo(str, Enum):
    CONCEDIDO = "CONCEDIDO"
    NIVEL_INVALIDO = "NIVEL_INVALIDO"
    # S1 Contenção
    BLOQUEADO = "BLOQUEADO"
    RISCO_CONTEXTUAL = "RISCO_CONTEXTUAL"              # sessão de risco alto: só consulta (MFA adaptativo)
    # S2 Conhecimento
    USUARIO_INEXISTENTE = "USUARIO_INEXISTENTE"
    SENHA_INCORRETA = "SENHA_INCORRETA"
    SENHA_FRACA = "SENHA_FRACA"
    # S3 Qualidade
    FACE_AUSENTE = "FACE_AUSENTE"
    MULTIPLAS_FACES = "MULTIPLAS_FACES"
    QUALIDADE_INSUFICIENTE = "QUALIDADE_INSUFICIENTE"
    # S4 Inerência
    FACE_NAO_RECONHECIDA = "FACE_NAO_RECONHECIDA"
    CREDENCIAL_ALHEIA = "CREDENCIAL_ALHEIA"            # senha certa, rosto de outra pessoa
    # S5 Habilitação
    USUARIO_INATIVO = "USUARIO_INATIVO"
    CONSENTIMENTO_AUSENTE = "CONSENTIMENTO_AUSENTE"
    NIVEL_INSUFICIENTE = "NIVEL_INSUFICIENTE"          # a camada pedida não é a do perfil (escopo exclusivo)
    SEM_ACESSO = "SEM_ACESSO"                          # Externo sem o papel de administrador: não entra
    # S6 Vivacidade
    VIVACIDADE_NAO_CONFIRMADA = "VIVACIDADE_NAO_CONFIRMADA"
    # S7 Custódia
    SEGUNDA_PESSOA_AUSENTE = "SEGUNDA_PESSOA_AUSENTE"
    SEGUNDA_PESSOA_INVALIDA = "SEGUNDA_PESSOA_INVALIDA"
    JANELA_EXPIRADA = "JANELA_EXPIRADA"
    # Papel de administrador: o código do celular (TOTP), fora dos anéis S1 a S10
    CODIGO_INCORRETO = "CODIGO_INCORRETO"
    # qualquer falha não prevista: nega (falha segura)
    ERRO_INTERNO = "ERRO_INTERNO"

    @property
    def camada(self) -> C | None:
        return _DETALHES[self][0]

    @property
    def mensagem(self) -> str:
        return _DETALHES[self][1]

    @property
    def concede(self) -> bool:
        return self is Motivo.CONCEDIDO


_DETALHES = {
    Motivo.CONCEDIDO: (None, "Acesso concedido."),
    Motivo.NIVEL_INVALIDO: (None, "Nível de acesso inválido."),
    Motivo.BLOQUEADO: (C.S1_CONTENCAO,
                       "Matrícula bloqueada por tentativas seguidas. Aguarde alguns minutos "
                       "ou procure o administrador."),
    Motivo.USUARIO_INEXISTENTE: (C.S2_CONHECIMENTO, _CREDENCIAIS),
    Motivo.SENHA_INCORRETA: (C.S2_CONHECIMENTO, _CREDENCIAIS),
    Motivo.SENHA_FRACA: (C.S2_CONHECIMENTO,
                         "O nível 3 exige senha forte. Peça ao administrador a troca da sua senha."),
    Motivo.FACE_AUSENTE: (C.S3_QUALIDADE,
                          "Nenhum rosto foi detectado. Olhe para a câmera, a cerca de meio metro."),
    Motivo.MULTIPLAS_FACES: (C.S3_QUALIDADE,
                             "Há mais de um rosto na imagem. A autenticação é feita uma pessoa por vez."),
    Motivo.QUALIDADE_INSUFICIENTE: (C.S3_QUALIDADE,
                                    "Não foi possível obter uma imagem nítida. "
                                    "Melhore a iluminação e fique parado por um instante."),
    Motivo.FACE_NAO_RECONHECIDA: (C.S4_INERENCIA, _IDENTIDADE),
    Motivo.CREDENCIAL_ALHEIA: (C.S4_INERENCIA, _IDENTIDADE),
    Motivo.USUARIO_INATIVO: (C.S5_HABILITACAO,
                             "Este cadastro está inativo. Procure o administrador."),
    Motivo.CONSENTIMENTO_AUSENTE: (C.S5_HABILITACAO,
                                   "Não há consentimento vigente para o uso da sua imagem facial. "
                                   "Refaça o cadastro com o termo de consentimento."),
    Motivo.NIVEL_INSUFICIENTE: (C.S5_HABILITACAO, "Este conteúdo não faz parte do seu perfil."),
    Motivo.SEM_ACESSO: (C.S5_HABILITACAO, "Este cadastro não tem acesso ao sistema. Procure o administrador."),
    Motivo.RISCO_CONTEXTUAL: (C.S1_CONTENCAO,
                              "Sessão só para consulta, por segurança. Para acesso completo, entre pela sua "
                              "estação habitual."),
    Motivo.VIVACIDADE_NAO_CONFIRMADA: (C.S6_VIVACIDADE,
                                       "Desafio não confirmado. Refaça o gesto pedido olhando "
                                       "para a câmera, sem sair do enquadramento."),
    Motivo.SEGUNDA_PESSOA_AUSENTE: (C.S7_CUSTODIA,
                                    "O nível 3 exige uma segunda pessoa autorizada, que deve se "
                                    "autenticar logo em seguida."),
    Motivo.SEGUNDA_PESSOA_INVALIDA: (C.S7_CUSTODIA,
                                     "A segunda pessoa precisa ser outra identidade, também de nível 3."),
    Motivo.JANELA_EXPIRADA: (C.S7_CUSTODIA,
                             "O tempo para a segunda pessoa se autenticar terminou. Recomece."),
    Motivo.CODIGO_INCORRETO: (None,
                              "Código não aceito. Digite o código atual do aplicativo ou um código de "
                              "recuperação."),
    Motivo.ERRO_INTERNO: (None,
                          "Não foi possível concluir a verificação. Procure o administrador."),
}
