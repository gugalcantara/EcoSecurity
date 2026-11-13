"""Repositórios: onde os dados moram.

contratos.py define o que se pode guardar e consultar. As implementações dizem
como:
    memoria/  dicionários em RAM: o modo --memoria e os testes, sem banco
    mysql/    a mesma interface sobre o MySQL

As regras de negócio dependem só dos contratos. Trocar memória por MySQL é
trocar uma linha na montagem da aplicação, sem tocar em nenhuma regra.
"""
