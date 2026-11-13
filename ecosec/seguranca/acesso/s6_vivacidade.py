"""S6 Vivacidade: "É uma pessoa viva, não uma foto?"

O LBPH compara texturas; uma foto impressa ou na tela do celular tem a mesma
textura do rosto. A S6 pede um gesto que uma imagem parada não faz.

O desafio é sorteado com secrets (gerador criptográfico), não com random.
O random é previsível: quem conhece alguns valores pode antecipar os
próximos e gravar o vídeo certo. Sorteando uma sequência de gestos, um vídeo
pré-gravado precisa acertar todas: com 3 gestos, 2 por sequência e a piscada
garantida, o melhor chute acerta 2 em 9 (sem a piscada garantida seria 1 em 9;
só com os 2 deslizes, 1 em 4).

Limitação: um vídeo da pessoa fazendo o gesto pedido, ao vivo, passaria.
Detecção de profundidade e de textura está fora do escopo.

A detecção do gesto (piscada, giro) é trabalho da camada de visão; aqui
ficam o sorteio e a decisão.
"""
import secrets
from enum import Enum

from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.motivos import Motivo
from ecosec.seguranca.acesso.veredito import Veredito, aprovar, negar

CAMADA = CamadaSeguranca.S6_VIVACIDADE


class Desafio(str, Enum):
    PISCAR = "PISCAR"
    MOVER_ESQUERDA = "MOVER_ESQUERDA"
    MOVER_DIREITA = "MOVER_DIREITA"

    @property
    def instrucao(self) -> str:
        return {
            Desafio.PISCAR: "Pisque os olhos uma vez, olhando para a câmera",
            Desafio.MOVER_ESQUERDA: "Vire ou deslize o rosto para a sua esquerda e volte",
            Desafio.MOVER_DIREITA: "Vire ou deslize o rosto para a sua direita e volte",
        }[self]


def sortear(disponiveis, quantidade: int, gerador=None, exigir: str | None = None) -> list[Desafio]:
    """Sequência imprevisível de desafios (pode repetir gestos).

    exigir: um gesto que precisa aparecer ao menos uma vez, em posição
    sorteada. Usado para a PISCADA: deslizar uma foto impressa para o lado
    cumpre "mover o rosto", mas uma foto não pisca. Sem a piscada garantida, o
    sorteio poderia sair só com movimentos: e uma foto passaria.
    """
    gerador = gerador or secrets.SystemRandom()
    opcoes = [Desafio(d) for d in disponiveis]
    if not opcoes or quantidade < 1:
        raise ValueError("Configure ao menos um desafio e quantidade >= 1.")
    sequencia = [gerador.choice(opcoes) for _ in range(quantidade)]
    if exigir is not None and Desafio(exigir) not in sequencia:
        sequencia[gerador.randrange(quantidade)] = Desafio(exigir)
    return sequencia


def validar(disponiveis, exigir: str | None) -> None:
    """Confere os nomes dos gestos da configuração. Feita NA ABERTURA: um nome errado
    ("piscada" no lugar de PISCAR) só estouraria no sorteio, no meio do step-up, e o
    nível 3 passaria a negar sempre."""
    validos = [d.value for d in Desafio]
    use = f"use {', '.join(validos[:-1])} ou {validos[-1]}"
    for valor in disponiveis:
        if valor not in validos:
            raise ValueError(f"[s6_vivacidade] desafios: valor inválido {valor!r}, {use}.")
    if exigir and exigir not in validos:
        raise ValueError(f"[s6_vivacidade] gesto_obrigatorio: valor inválido {exigir!r}, {use} "
                         "(ou \"\" para desligar).")


def avaliar(vivacidade_confirmada: bool | None) -> Veredito:
    if vivacidade_confirmada is not True:
        return negar(Motivo.VIVACIDADE_NAO_CONFIRMADA)
    return aprovar(CAMADA)
