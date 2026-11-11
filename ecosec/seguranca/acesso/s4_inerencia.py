"""S4 Inerência: "É quem diz ser?"

O fator que a pessoa É, e não o que sabe (senha) ou tem (crachá): não se
empresta nem se esquece.

O LBPH devolve distância, não similaridade: menor = mais parecido. A regra é
`distancia <= limiar`. Inverter o sinal inverteria a segurança inteira: o
sistema passaria a aceitar justamente os rostos mais diferentes.

Dois modos, conforme o nível:
- 1:N (N1), compara com todos e pega o mais próximo. A chance de falsa
  aceitação cresce com o número de cadastrados.
- 1:1 (N2, N3), a senha já disse quem a pessoa alega ser; compara-se só com
  ela. Uma hipótese em vez de N: a falsa aceitação cai. É por isso que a
  senha vem ANTES da face, e não só "como um fator a mais".

Falha segura com NaN: a comparação é escrita como `not (distancia <= limiar)`.
Qualquer comparação com NaN é falsa, então uma distância corrompida nega. A
forma ingênua `distancia > limiar` também seria falsa com NaN: e aprovaria.
"""
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
    # no 1:1 a distância PRECISA ter sido medida contra o alegado; medida contra
    # outra identidade, ela não prova nada sobre quem digitou a senha
    if verificacao and identidade_medida != identidade_alegada:
        return negar(falha)
    return aprovar(CAMADA)
