"""Verificação de ambiente: confirma que esta máquina consegue rodar o EcoSecurity.

Cada integrante roda na própria máquina e cola o resultado no grupo:
    .venv\\Scripts\\python.exe -m ferramentas.verificar_ambiente

Sai com código 1 se houver qualquer FALHA (útil em script de instalação).
"""
import platform
import sys
import time

OK, FALHA, AVISO = "[ OK ]", "[FALHA]", "[AVISO]"
problemas = []


def secao(titulo):
    print(f"\n{titulo}\n" + "-" * len(titulo))


def falha(mensagem, *orientacoes):
    print(f"{FALHA} {mensagem}")
    for linha in orientacoes:
        print(f"       {linha}")
    problemas.append(mensagem)


def verificar_python():
    secao("1. Python")
    v = sys.version_info
    marca = OK if v[:2] == (3, 11) else AVISO
    print(f"{marca} Python {v.major}.{v.minor}.{v.micro} ({platform.system()} {platform.machine()})")
    if v[:2] != (3, 11):
        print("       O projeto fixa 3.11; outra versão pode não ter wheel do opencv-contrib 4.10.")
    if sys.prefix == sys.base_prefix:
        print(f"{AVISO} Fora do ambiente virtual. Use .venv\\Scripts\\python.exe")


def verificar_opencv():
    secao("2. OpenCV (contrib), LBPH e KCF")
    try:
        import cv2
    except ImportError:
        falha("OpenCV não instalado.", "pip install -r requirements.txt")
        return None
    print(f"{OK} OpenCV {cv2.__version__}")

    # armadilha nº 1 do projeto: o pacote comum não traz o módulo face
    if hasattr(cv2, "face"):
        cv2.face.LBPHFaceRecognizer_create()
        print(f"{OK} cv2.face disponível, LBPH criado")
    else:
        falha("cv2.face NÃO existe: está instalado o opencv-python comum.",
              "pip uninstall -y opencv-python opencv-contrib-python",
              "pip install -r requirements.txt")

    if hasattr(cv2, "TrackerKCF_create"):
        print(f"{OK} Rastreador KCF disponível")
    else:
        falha("TrackerKCF_create ausente (rastreamento entre detecções).")

    from importlib.metadata import distributions
    instalados = {(d.metadata["Name"] or "").lower() for d in distributions()}
    opencvs = sorted(n for n in instalados if n.startswith("opencv"))
    if len(opencvs) > 1:
        falha(f"Mais de um OpenCV instalado: {', '.join(opencvs)}",
              "Deixe apenas opencv-contrib-python: os outros conflitam em silêncio.")
    else:
        print(f"{OK} Apenas {opencvs[0]} instalado")

    haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if haar.empty():
        falha("Classificador Haar de face não carregou.")
    else:
        print(f"{OK} haarcascade_frontalface_default.xml carregado")
    verificar_landmarks()
    return cv2, haar


def verificar_landmarks():
    """Modelo LBF da piscada (S6): presente e com o SHA-256 do config."""
    from ecosec.configuracao import carregar
    from ecosec.visao.gestos import ErroModeloLandmarks, ParametrosGestos, carregar_landmarks
    pg = ParametrosGestos.de_configuracao(carregar())
    try:
        carregar_landmarks(pg.modelo_landmarks, pg.modelo_landmarks_sha256)
        print(f"{OK} Modelo de landmarks (piscada) presente e conferido")
    except ErroModeloLandmarks as erro:
        falha(str(erro), r".venv\Scripts\python.exe -m ferramentas.baixar_modelo_landmarks")


def verificar_interface():
    secao("3. Interface (PySide6 / Qt)")
    try:
        import PySide6
        from PySide6 import QtCore, QtWidgets  # noqa: F401, carregar a DLL é o teste
    except ImportError as erro:
        falha(f"PySide6 não carregou: {erro}",
              "Se o Windows bloqueou a DLL (Smart App Control), use o Python oficial do python.org.")
        return
    print(f"{OK} PySide6 {PySide6.__version__} (Qt {QtCore.qVersion()})")


def verificar_webcam(cv2, haar):
    from ecosec.configuracao import carregar
    cfg = carregar()
    indice, larg, alt = cfg["captura.indice_camera"], cfg["captura.largura"], cfg["captura.altura"]

    secao(f"4. Webcam (índice {indice}, meta: {larg}x{alt} a 15 FPS ou mais)")
    from ecosec.visao.aquisicao import BACKENDS
    backend = cfg.secao("captura")["backend"]
    abertura = time.perf_counter()
    camera = cv2.VideoCapture(indice, BACKENDS[backend])
    if not camera.isOpened() and backend != "auto":
        camera.release()
        print(f"{AVISO} Backend {backend} não abriu a webcam; tentando o padrão do OpenCV")
        camera = cv2.VideoCapture(indice)
    if not camera.isOpened():
        falha(f"Webcam não abriu no índice {indice}.",
              "Feche outros programas que usem a câmera (Teams, navegador...).")
        return
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, larg)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, alt)
    camera.read()
    segundos = time.perf_counter() - abertura
    obtida = (int(camera.get(cv2.CAP_PROP_FRAME_WIDTH)), int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    print(f"{OK if obtida == (larg, alt) else AVISO} Webcam aberta em {obtida[0]}x{obtida[1]} "
          f"({camera.getBackendName()})")
    print(f"{OK if segundos <= 5 else AVISO} 1º quadro em {segundos:.1f} s"
          + ("" if segundos <= 5 else " (lento: experimente [captura] backend = \"dshow\")"))

    for _ in range(cfg["captura.frames_aquecimento"]):
        camera.read()

    total, lidos, com_face = 60, 0, 0
    inicio = time.perf_counter()
    for _ in range(total):
        ok, frame = camera.read()
        if not ok:
            continue
        lidos += 1
        cinza = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        if len(haar.detectMultiScale(cinza, 1.1, 5, minSize=(80, 80))):
            com_face += 1
    camera.release()
    fps = lidos / (time.perf_counter() - inicio)

    marca = OK if fps >= 15 else (AVISO if fps >= 10 else FALHA)
    print(f"{marca} {fps:.1f} FPS com captura + cinza + equalização + Haar EM TODO frame")
    if fps < 10:
        falha(f"Desempenho baixo ({fps:.1f} FPS).",
              "A thread de captura e o Haar a cada N frames devem compensar.")
    elif fps < 15:
        print("       Abaixo da meta, mas o sistema roda o Haar só a cada N frames.")
    if com_face:
        print(f"{OK} Face detectada em {com_face} de {lidos} frames")
    else:
        print(f"{AVISO} Nenhuma face detectada (normal se ninguém estava diante da câmera).")


def verificar_demais():
    from importlib.metadata import version
    secao("5. Demais dependências")
    # o Fluent entra pelo módulo do sistema, que cala o anúncio que a biblioteca imprime
    for nome, modulo in [("numpy", "numpy"), ("PySide6-Fluent-Widgets", "ecosec.interface.fluent"), ("Pillow", "PIL"),
                         ("mysql-connector-python", "mysql.connector"), ("bcrypt", "bcrypt"),
                         ("cryptography", "cryptography"), ("python-dotenv", "dotenv")]:
        try:
            __import__(modulo)
            print(f"{OK} {nome} {version(nome)}")  # do metadado: nem todo pacote tem __version__
        except ImportError:
            falha(f"{nome} ausente.", "pip install -r requirements.txt")


def main():
    verificar_python()
    resultado = verificar_opencv()
    verificar_interface()
    if resultado:
        verificar_webcam(*resultado)
    verificar_demais()

    secao("Resultado")
    if problemas:
        print(f"{FALHA} Pendências a resolver:")
        for p in problemas:
            print(f"       - {p}")
        sys.exit(1)
    print(f"{OK} Ambiente válido para o EcoSecurity.")


if __name__ == "__main__":
    main()
