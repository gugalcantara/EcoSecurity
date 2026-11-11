"""Repositórios: onde os dados moram.

contratos.py define o que se pode guardar e consultar. As implementações dizem
COMO:
    memoria/  dicionários em RAM: permite construir regras e telas sem banco
    mysql/    (depois) a mesma interface sobre o MySQL

As regras de negócio dependem só dos contratos. Trocar memória por MySQL é
trocar uma linha na montagem da aplicação, sem tocar em nenhuma regra.
"""
