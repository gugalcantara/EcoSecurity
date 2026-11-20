"""S6 Vivacidade: é uma pessoa viva, não uma foto?"""
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
    """Sequência sorteada de desafios (pode repetir gestos). `exigir` garante um gesto em posição sorteada:
    a piscada, que uma foto não consegue fazer."""
    gerador = gerador or secrets.SystemRandom()
    opcoes = [Desafio(d) for d in disponiveis]
    if not opcoes or quantidade < 1:
        raise ValueError("Configure ao menos um desafio e quantidade >= 1.")
    sequencia = [gerador.choice(opcoes) for _ in range(quantidade)]
    if exigir is not None and Desafio(exigir) not in sequencia:
        sequencia[gerador.randrange(quantidade)] = Desafio(exigir)
    return sequencia


def validar(disponiveis, exigir: str | None) -> None:
    """Confere os nomes dos gestos da configuração. Feita na abertura: um nome errado
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
