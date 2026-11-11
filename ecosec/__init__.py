"""EcoSecurity: controle de acesso multinível por reconhecimento facial.

Regra de dependência (as setas só apontam para dentro):

    interface  ->  servicos  ->  seguranca / visao  ->  dominio
                       |
                       +-> repositorios (contratos)

Quanto mais interna a camada, menos ela conhece. O dominio não conhece nada;
a interface conhece tudo, mas não decide nada.
"""
