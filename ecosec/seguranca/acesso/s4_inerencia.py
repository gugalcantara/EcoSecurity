"""S4 Inerência: "É quem diz ser?"

O fator inerente ao corpo da pessoa: não se empresta nem se esquece.

O LBPH devolve uma distância (menor = mais parecido), e a regra de aceite é
`distancia <= limiar`. Com o sinal invertido, o sistema aceitaria justamente os
rostos mais diferentes.

Modos:
- 1:1, no login e na abertura dos níveis: a senha já indicou quem a pessoa alega
  ser, e a comparação é só com esse cadastro. Por isso a senha vem antes do rosto.
- 1:N, comparação com todos os cadastros, ficando com o mais próximo. A chance de
  falsa aceitação cresce com o número de cadastros. Na aplicação, só a
  Identificação do administrador (servicos/identificacao.py) compara 1:N, sem
  conceder acesso.

A comparação é escrita como `not (distancia <= limiar)`: com NaN, qualquer
comparação é falsa, e uma distância corrompida nega o acesso. A forma
`distancia > limiar` também daria falso com NaN e aprovaria.
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
    # no 1:1 a distância precisa ter sido medida contra o alegado; medida contra
    # outra identidade, ela não prova nada sobre quem digitou a senha
    if verificacao and identidade_medida != identidade_alegada:
        return negar(falha)
    return aprovar(CAMADA)
