"""Leitura do arquivo de configuração (config/ecosec.toml)."""
import tomllib
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
CAMINHO_PADRAO = RAIZ_PROJETO / "config" / "ecosec.toml"


class ErroConfiguracao(Exception):
    """Arquivo ausente, TOML inválido ou parâmetro que não existe."""


class _Secao(dict):
    """Cópia de uma seção: um parâmetro ausente vira ErroConfiguracao com o nome completo, não KeyError."""

    def __init__(self, nome: str, origem: Path, valores: dict):
        super().__init__(valores)
        self._nome, self._origem = nome, origem

    def __missing__(self, chave):
        raise ErroConfiguracao(f"Parâmetro '{self._nome}.{chave}' não encontrado em {self._origem.name}. "
                               f"Acrescente-o ao arquivo: não há valor padrão no código.")


class Configuracao:
    """Acesso somente leitura aos parâmetros, por chave pontuada ("secao.chave")."""

    def __init__(self, dados: dict, origem: Path):
        self._dados = dados
        self.origem = origem

    def __getitem__(self, chave: str):
        valor = self._dados
        for parte in chave.split("."):
            if not isinstance(valor, dict) or parte not in valor:
                raise ErroConfiguracao(
                    f"Parâmetro '{chave}' não encontrado em {self.origem.name}. "
                    f"Acrescente-o ao arquivo: não há valor padrão no código.")
            valor = valor[parte]
        return valor

    def secao(self, nome: str) -> dict:
        valor = self[nome]
        if not isinstance(valor, dict):
            raise ErroConfiguracao(f"'{nome}' é um parâmetro, não uma seção.")
        return _Secao(nome, self.origem, valor)  # cópia: quem recebe não altera a configuração global

    def caminho(self, nome: str) -> Path:
        """Caminho de [caminhos], resolvido a partir da raiz do projeto."""
        return RAIZ_PROJETO / self[f"caminhos.{nome}"]


def carregar(caminho: Path | str | None = None) -> Configuracao:
    origem = Path(caminho) if caminho else CAMINHO_PADRAO
    try:
        with open(origem, "rb") as arquivo:  # tomllib exige modo binário
            dados = tomllib.load(arquivo)
    except FileNotFoundError:
        raise ErroConfiguracao(f"Arquivo de configuração não encontrado: {origem}") from None
    except tomllib.TOMLDecodeError as erro:
        raise ErroConfiguracao(f"{origem.name} tem erro de sintaxe: {erro}") from None
    return Configuracao(dados, origem)
