"""Segurança: as dez camadas, organizadas em três anéis.

    Anel 1 - Acesso      (acesso/)     S1 Contenção ... S7 Custódia
    Anel 2 - Conteúdo    (conteudo/)   S8 Tarja, S9 Rastreio
    Anel 3 - Evidência   (evidencia/)  S10 Trilha

Cada camada responde a uma pergunta e é testável isoladamente.

Não importa: interface, servicos, repositórios concretos (só os contratos).
"""
