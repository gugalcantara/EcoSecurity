"""A regra de dependência entre camadas, verificada lendo os imports.

Documentar "o domínio não importa nada" não impede ninguém de importar. Este
teste impede: analisa cada arquivo com ast e falha se uma camada importar o
que não pode.
"""
import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent / "ecosec"

# camada -> prefixos de import PROIBIDOS
PROIBIDOS = {
    "dominio": ["ecosec.seguranca", "ecosec.visao", "ecosec.servicos", "ecosec.repositorios",
                "ecosec.interface", "ecosec.configuracao", "cv2", "PySide6", "mysql", "bcrypt"],
    "seguranca": ["ecosec.servicos", "ecosec.interface", "ecosec.repositorios.memoria",
                  "ecosec.repositorios.mysql", "PySide6", "mysql"],
    "visao": ["ecosec.seguranca", "ecosec.servicos", "ecosec.repositorios", "ecosec.interface",
              "PySide6", "mysql"],
    "repositorios": ["ecosec.seguranca", "ecosec.visao", "ecosec.servicos", "ecosec.interface",
                     "PySide6"],
    "servicos": ["ecosec.interface", "PySide6"],
    # a tela mostra e coleta; quem decide é o serviço. Sem atalho até a segurança
    # ou o armazenamento.
    "interface": ["ecosec.seguranca", "ecosec.repositorios", "mysql"],
    # o acervo desenha; quem decide o que suprimir e registra é o serviço
    "acervo": ["ecosec.servicos", "ecosec.interface", "ecosec.repositorios", "ecosec.seguranca", "PySide6",
               "mysql"],
}


def _imports(arquivo: Path):
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            yield from (a.name for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            yield no.module


@pytest.mark.parametrize("camada", PROIBIDOS)
def test_camada_nao_importa_o_que_nao_pode(camada):
    violacoes = []
    for arquivo in (RAIZ / camada).rglob("*.py"):
        for modulo in _imports(arquivo):
            if any(modulo == p or modulo.startswith(p + ".") for p in PROIBIDOS[camada]):
                violacoes.append(f"{arquivo.relative_to(RAIZ)} importa {modulo}")
    assert not violacoes, "\n".join(violacoes)


# texto visível
# Regra do projeto: nenhum travessão nos textos que a aplicação
# mostra. Vale para toda string do código (telas, termo, PDF, relatórios,
# mensagens das ferramentas); comentários e docstrings não aparecem para
# ninguém e ficam de fora. Exceção: o termo 2.0 arquivado precisa continuar
# idêntico ao original, ou o hash dos consentimentos já gravados não confere.
TRAVESSOES = ("—", "–")
EXCECOES_TRAVESSAO = {"termo_v2.py"}
# A marcação do rodapé do termo 3.1 também leva travessão. Qualquer outro travessão, inclusive no resto do
# mesmo rodapé, continua barrado.
# O termo vigente e os relatórios não têm a marcação: a exceção vale só nos
# termos arquivados que a apresentaram, que não podem mudar (o hash dos aceites).
EXCECOES_TEXTO = ("DOCUMENTO SIMULADO — PROJETO ACADÊMICO",)
ARQUIVADOS_COM_MARCACAO = {"termo_v3_1.py", "termo_v3_2.py", "termo_v3_3.py"}


def _strings_visiveis(arquivo: Path):
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    docstrings = {id(no.body[0].value) for no in ast.walk(arvore)
                  if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and no.body and isinstance(no.body[0], ast.Expr) and isinstance(no.body[0].value, ast.Constant)}
    for no in ast.walk(arvore):
        if isinstance(no, ast.Constant) and isinstance(no.value, str) and id(no) not in docstrings:
            yield no.lineno, no.value


def test_nenhum_texto_da_aplicacao_usa_travessao():
    raiz = RAIZ.parent
    arquivos = [a for pasta in ("ecosec", "ferramentas") for a in (raiz / pasta).rglob("*.py")
                if a.name not in EXCECOES_TRAVESSAO]
    achados = [f"{a.relative_to(raiz)}:{linha}" for a in arquivos for linha, texto in _strings_visiveis(a)
               if any(t in (_sem_excecoes(texto) if a.name in ARQUIVADOS_COM_MARCACAO else texto)
                      for t in TRAVESSOES)]
    assert not achados, "travessão em texto visível: " + ", ".join(achados)


def test_marcacao_de_documento_simulado_so_nos_termos_arquivados():
    """O termo vigente e os relatórios não têm a marcação."""
    raiz = RAIZ.parent
    achados = [f"{a.relative_to(raiz)}:{linha}" for pasta in ("ecosec", "ferramentas")
               for a in (raiz / pasta).rglob("*.py") if a.name not in ARQUIVADOS_COM_MARCACAO
               for linha, texto in _strings_visiveis(a) if "DOCUMENTO SIMULADO" in texto.upper()]
    assert not achados, achados


def _sem_excecoes(texto: str) -> str:
    for permitido in EXCECOES_TEXTO:
        texto = texto.replace(permitido, "")
    return texto


def test_excecao_do_travessao_vale_so_para_a_marcacao_do_rodape():
    assert _sem_excecoes("DOCUMENTO SIMULADO — PROJETO ACADÊMICO. Texto") == ". Texto"
    assert "—" in _sem_excecoes("OUTRO TEXTO — COM TRAVESSÃO")
    assert "—" in _sem_excecoes("DOCUMENTO SIMULADO — PROJETO ACADÊMICO — e mais um")
