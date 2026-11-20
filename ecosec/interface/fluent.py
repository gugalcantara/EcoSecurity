"""Importação do PySide6-Fluent-Widgets sem o anúncio que ele imprime no terminal."""
import contextlib
import io

with contextlib.redirect_stdout(io.StringIO()):
    import qfluentwidgets  # noqa: F401

from qfluentwidgets import *  # noqa: E402,F401,F403
from qfluentwidgets import FluentIcon as FIF  # noqa: E402,F401
