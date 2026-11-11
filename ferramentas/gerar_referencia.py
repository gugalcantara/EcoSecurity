"""Regrava sql/acervo/02_referencia.sql a partir de ecosec/acervo/sinteticos.py.

O catálogo da camada causal (AG/MP) e os eventos regulatórios moram no código;
o SQL de referência é derivado dele, para o banco e o código nunca divergirem
Rode depois de mudar ATIVIDADES, MOTIVOS ou EVENTOS:

    python -m ferramentas.gerar_referencia
"""
from ecosec.configuracao import RAIZ_PROJETO
from ecosec.repositorios.mysql.importacao import sql_referencia

DESTINO = RAIZ_PROJETO / "sql" / "acervo" / "02_referencia.sql"


def main():
    DESTINO.write_text(sql_referencia(), encoding="utf-8")
    print(f"[OK] {DESTINO.relative_to(RAIZ_PROJETO)} regravado a partir do código.")


if __name__ == "__main__":
    main()
