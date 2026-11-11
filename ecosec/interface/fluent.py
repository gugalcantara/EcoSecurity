"""Ponto único de importação do PySide6-Fluent-Widgets.

A biblioteca imprime um anúncio no terminal ao ser importada, sem opção de
desligar. Importando-a uma vez aqui, com a saída padrão redirecionada, o
terminal fica limpo para o que importa (erros e avisos do EcoSecurity).
Todas as telas importam os componentes deste módulo.
"""
import contextlib
import io

with contextlib.redirect_stdout(io.StringIO()):
    import qfluentwidgets  # noqa: F401

from qfluentwidgets import *  # noqa: E402,F401,F403
from qfluentwidgets import FluentIcon as FIF  # noqa: E402,F401
