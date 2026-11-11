"""Ponto de entrada:  .venv\\Scripts\\python.exe -m ecosec

Erro não previsto em qualquer ponto é registrado em logs/erros.log com data,
hora e rastreamento, e nada é concedido por causa dele: a política e os
serviços transformam exceção em negação (falha segura).

Se o sistema não puder abrir com segurança (banco fora do ar, contas não
criadas, modelo que não decifra), mostra o que fazer e não abre.
"""
import logging
import sys

from ecosec.configuracao import ErroConfiguracao, carregar


def _configurar_log(cfg):
    pasta = cfg.caminho("logs")
    pasta.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING, filename=pasta / "erros.log", encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def registrar(tipo, valor, rastro):
        if not issubclass(tipo, KeyboardInterrupt):     # Ctrl+C no terminal é encerramento, não erro
            logging.getLogger("ecosec").critical("Erro não tratado", exc_info=(tipo, valor, rastro))
        sys.__excepthook__(tipo, valor, rastro)
    sys.excepthook = registrar


def _argumentos(argv):
    import argparse
    parser = argparse.ArgumentParser(prog="python -m ecosec", description="EcoSecurity: controle de acesso")
    parser.add_argument("--memoria", action="store_true",
                        help="roda sem banco: cadastros em memória, perdidos ao fechar")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _argumentos(argv)
    # pelo atalho (pythonw.exe) não há console: um print sumiria e o programa
    # "não abriria" sem explicação. Todo erro de abertura vira a caixa de mensagem.
    from ecosec.interface import janela                 # Qt só é carregado aqui
    try:
        cfg = carregar()
    except ErroConfiguracao as erro:
        print(f"[FALHA] {erro}")
        return janela.mostrar_erro_abertura(str(erro))
    _configurar_log(cfg)
    from ecosec.aplicacao import ErroAbertura, montar
    from ecosec.segredos import ErroSegredo
    try:
        app = montar(cfg, modo="memoria" if args.memoria else None)
        return janela.executar(app)          # as telas leem parâmetros ao serem montadas
    except (ErroAbertura, ErroConfiguracao, ErroSegredo) as erro:
        logging.getLogger("ecosec").error("Abertura recusada: %s", erro)
        return janela.mostrar_erro_abertura(str(erro))


if __name__ == "__main__":
    sys.exit(main())
