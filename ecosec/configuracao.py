"""Leitura dos parâmetros do sistema (config/ecosec.toml).

TOML em vez de .ini, porque o TOML tem tipos: `largura = 640` já chega como int e
`grade = [8, 8]` já chega como lista: no .ini tudo é texto e cada módulo
precisaria converter por conta própria. O leitor (tomllib) é da biblioteca
padrão do Python 3.11, sem dependência nova.

Falha segura: parâmetro ausente é erro na abertura, nunca um valor padrão
escondido no código. Um padrão silencioso faria o sistema rodar com um limiar
que ninguém escolheu: e em controle de acesso isso é uma decisão de segurança
tomada por acidente.

Uso:
    from ecosec.configuracao import carregar
    cfg = carregar()
    cfg["captura.largura"]        # 640
    cfg.secao("captura")          # dict com a seção inteira
"""
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
