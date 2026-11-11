"""Identidade visual: tema, cor de destaque e a cor de cada nível.

As cores dos níveis seguem a lógica de semáforo: verde (aberto), âmbar
(restrito), vermelho (custódia), e se repetem em toda tela: cartões de
acesso, cabeçalho da autenticação e tabela de usuários.
"""
from PySide6.QtGui import QColor

from ecosec.dominio.niveis import Nivel
from ecosec.interface.fluent import Theme, isDarkTheme, setTheme, setThemeColor

COR_DESTAQUE = "#1F9D6B"       # verde "eco"
COR_NIVEL = {Nivel.N1: "#2EA36B", Nivel.N2: "#D99A1E", Nivel.N3: "#D2384F"}
ICONE_NIVEL = {Nivel.N1: "PEOPLE", Nivel.N2: "CERTIFICATE", Nivel.N3: "VPN"}

VERDE, AMBAR, VERMELHO = "#2EA36B", "#D99A1E", "#D2384F"


def aplicar_tema(nome: str) -> None:
    setTheme(Theme.DARK if nome == "escuro" else Theme.LIGHT)
    setThemeColor(COR_DESTAQUE)


def alternar_tema() -> None:
    setTheme(Theme.LIGHT if isDarkTheme() else Theme.DARK)


def cor_texto_secundario() -> str:
    return "#A0A0A0" if isDarkTheme() else "#606060"


def cor_superficie() -> str:
    return "#2B2B2B" if isDarkTheme() else "#F3F3F3"


def cor_borda() -> str:
    return "#3A3A3A" if isDarkTheme() else "#DADADA"


def qcor(hex_: str, alfa: int = 255) -> QColor:
    cor = QColor(hex_)
    cor.setAlpha(alfa)
    return cor
