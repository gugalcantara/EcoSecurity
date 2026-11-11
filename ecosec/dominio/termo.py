"""Termo de consentimento para o tratamento da imagem facial (LGPD).

Imagem de rosto é dado pessoal sensível (Lei 13.709/2018, art. 5º, II), e
tratá-la exige consentimento específico e destacado (art. 11, I). O termo é
apresentado ANTES de a câmera abrir.

Quatro escolhas de projeto:

1. Notificação em camadas. Primeiro um QUADRO-RESUMO (o que se coleta, para
   quê, por quanto tempo, como desistir); depois as cláusulas completas.
   Quem lê só o quadro já sabe o essencial.

2. Uma autorização por finalidade (art. 8º, §4º: autorização genérica é nula).
     (a) autenticação no EcoSecurity ........................ obrigatória
     (b) estatísticas e experimentos do trabalho ........ OPCIONAL
   Recusar (b) não impede o cadastro.

3. O que se grava no aceite é o HASH SHA-256 do texto exato apresentado, com
   o nome da pessoa e as escolhas feitas. Provar o consentimento é ônus do
   controlador (art. 8º, §2º); o hash prova o que foi lido e o que foi escolhido.

4. Redação de instrumento formal (preâmbulo, cláusulas, quadro de
   autorizações, bloco de assinatura), porque é isso que o termo é: um
   documento que o titular assina e do qual recebe uma via.

Regra de manutenção: o termo descreve só o que o sistema de fato faz. Mudou o
tratamento ou a redação, sobe a versão, e a versão anterior é arquivada sem
nenhuma alteração (ver `termo_v2.py`, `termo_v3_0.py`, `termo_v3_1.py`,
`termo_v3_2.py` e `termo_v3_3.py`): sem ela, os hashes já gravados não poderiam mais ser conferidos.
"""
import hashlib
from datetime import datetime
from html import escape

from ecosec.dominio import termo_v2, termo_v3_0, termo_v3_1, termo_v3_2, termo_v3_3

VERSAO = "3.4"
# 1.0 -> 1.1: contato do controlador (art. 9º), idade (art. 14), eliminação na revogação.
# 1.1 -> 2.0: resumo em camadas e consentimento separado por finalidade (art. 8º, §4º).
# 2.0 -> 3.0: redação formal (preâmbulo, cláusulas, assinatura eletrônica descrita, revisão
#             humana com base no art. 20); conteúdo do tratamento inalterado.
#             Ajuste na 3.0 (07/10/2026, sem subir versão porque NENHUM aceite 3.0 tinha sido
#             registrado): a Cláusula 7ª deixa de afirmar que a segunda pessoa é sempre exigida.
#             Ajuste na 3.0 (07/10/2026, mesmo motivo): o sistema passa a se chamar EcoSecurity.
# 3.0 -> 3.1: contato do controlador preenchido (endereço SIMULADO, sem caixa postal real) e rodapé de
#             documento simulado (premissa formal do projeto acadêmico). A 3.0 foi
#             arquivada em termo_v3_0.py, com o contato provisório com que sempre foi apresentada.
# 3.1 -> 3.2: só descritiva: a Cláusula 2ª (IV) fala do PERFIL de acesso (um por cadastro;
#             o administrador não tem camada) e a 7ª, dos fatores de cada perfil (o código do celular do
#             administrador). Finalidades, forma, prazo, controlador e compartilhamento iguais: os aceites 3.1
#             continuam valendo. A 3.1 foi arquivada em termo_v3_1.py.
# 3.2 -> 3.3: revisão só descritiva: os perfis passam a ser externo, servidor, diretor e ministro, e
#             administrador é um papel de um cadastro externo (o Ministério Público saiu). Os aceites 3.2
#             continuam valendo. A 3.2 foi arquivada em termo_v3_2.py.
# 3.3 -> 3.4: sai o rodapé de documento simulado e a
#             nota do endereço simulado. Os pedidos do TITULAR continuam indo ao administrador (Cláusula 6ª e
#             quadro-resumo). O resto do texto é igual. A 3.3 foi arquivada em termo_v3_3.py.
TITULO = ("Termo de consentimento livre e esclarecido para tratamento de dado pessoal sensível "
          "(biometria facial)")
CABECALHO = ("Universidade Paulista (UNIP) · Ciência da Computação · Processamento de Imagens e Visão "
             "Computacional · Sistema EcoSecurity · 2026/2")

RESUMO = (
    "Dado tratado: um modelo matemático do rosto, e não a fotografia, gerado a partir de imagens da webcam.",
    "Finalidade obrigatória (a): confirmar a identidade do titular no acesso ao EcoSecurity.",
    "Finalidade opcional (b): uso dos registros de acesso, sem identificação nominal, nas estatísticas do "
    "trabalho acadêmico. A recusa não impede o cadastro.",
    "Armazenamento: o modelo fica cifrado neste computador. Nada é enviado à internet ou a terceiros, e as "
    "fotografias do cadastro são descartadas logo após o treinamento.",
    "Prazo: até o fim da avaliação do trabalho acadêmico, ou até a revogação, o que ocorrer primeiro.",
    "Revogação: a qualquer tempo, junto ao administrador. O cadastro é desativado e o modelo facial, eliminado.",
)

PREAMBULO = (
    "Pelo presente instrumento, eu, {nome}, maior de 18 (dezoito) anos, doravante denominado(a) TITULAR, "
    "declaro ter lido e compreendido integralmente este Termo e manifesto, de forma livre, informada e "
    "inequívoca, o meu consentimento específico e destacado para o tratamento da minha imagem facial, dado "
    "pessoal sensível, nos termos do art. 5º, inciso II, e do art. 11, inciso I, da Lei nº 13.709, de 14 de "
    "agosto de 2018 (Lei Geral de Proteção de Dados Pessoais, LGPD), conforme as cláusulas a seguir.")

FINALIDADE_A = ("(a) Autenticação: confirmar a identidade do TITULAR no acesso ao sistema EcoSecurity. Finalidade "
                "obrigatória, sem a qual o cadastro não se realiza.")
FINALIDADE_B = ("(b) Estatística e experimentação: utilizar os registros das tentativas de acesso do TITULAR "
                "(resultado e distância facial) e os índices de qualidade das suas amostras, de forma agregada "
                "e sem identificação nominal, no cálculo das taxas de acerto e de erro do trabalho acadêmico. "
                "Finalidade opcional.")

# (título, parágrafos). Os parágrafos de uma cláusula ficam separados por "\n".
CLAUSULAS = (
    ("Cláusula 1ª. Do controlador",
     "O tratamento é realizado no âmbito do sistema EcoSecurity, trabalho acadêmico da disciplina de Processamento "
     "de Imagens e Visão Computacional do curso de Ciência da Computação da Universidade Paulista (UNIP), "
     "semestre 2026/2, pelos integrantes do grupo identificados na capa do trabalho, sob orientação docente, "
     "doravante denominados CONTROLADOR. Canal de atendimento ao TITULAR: {contato}."),
    ("Cláusula 2ª. Dos dados tratados",
     "São tratados: (I) imagens do rosto do TITULAR, capturadas por webcam no cadastro e em cada "
     "autenticação; (II) nome completo; (III) matrícula gerada pelo sistema; (IV) perfil de acesso atribuído "
     "(externo, servidor, diretor ou ministro), o papel de administrador, quando atribuído, e, no perfil de "
     "diretor, a unidade da federação sob responsabilidade do TITULAR."),
    ("Cláusula 3ª. Das finalidades",
     "O tratamento destina-se exclusivamente às finalidades abaixo, autorizadas de forma separada, nos "
     "termos do art. 8º, § 4º, da LGPD:\n" + FINALIDADE_A + "\n" + FINALIDADE_B + "\n"
     "Parágrafo único. Os dados não serão utilizados para nenhuma outra finalidade, nem compartilhados, "
     "comercializados ou publicados."),
    ("Cláusula 4ª. Da forma de tratamento",
     "As imagens são convertidas para tons de cinza, recortadas na região do rosto e transformadas em um "
     "modelo matemático (histogramas de padrões binários locais, LBPH). As imagens originais não são "
     "gravadas em disco: permanecem em memória apenas durante o cadastro e são descartadas após o "
     "treinamento. O modelo é armazenado cifrado, no próprio computador, sem transferência para serviço de "
     "nuvem ou serviço externo de reconhecimento."),
    ("Cláusula 5ª. Do prazo de conservação e da eliminação",
     "Os dados serão conservados até o término da avaliação do trabalho acadêmico, quando o modelo e o "
     "cadastro serão eliminados, com registro em ata, ou até a revogação deste consentimento, hipótese em "
     "que o modelo facial do TITULAR será eliminado imediatamente. Serão conservados apenas os registros "
     "deste aceite e da eventual revogação, como prova de que o tratamento foi autorizado e encerrado "
     "(art. 8º, § 2º, da LGPD)."),
    ("Cláusula 6ª. Dos direitos do titular",
     "É assegurado ao TITULAR, a qualquer tempo e mediante requisição ao administrador do sistema, o "
     "exercício dos direitos previstos no art. 18 da LGPD, em especial: confirmação da existência de "
     "tratamento, acesso aos dados, correção de dados incompletos ou inexatos, eliminação e informação "
     "sobre o tratamento.\n"
     "Parágrafo único. O TITULAR poderá revogar este consentimento a qualquer momento (art. 8º, § 5º), o "
     "que acarretará a desativação do cadastro e a eliminação do modelo facial, sem prejuízo da licitude "
     "do tratamento realizado anteriormente."),
    ("Cláusula 7ª. Dos riscos e das salvaguardas",
     "O TITULAR declara ciência de que, diferentemente de uma senha, a característica biométrica não pode "
     "ser substituída em caso de vazamento. Como salvaguarda, o modelo é armazenado cifrado, as imagens não "
     "são conservadas e o reconhecimento facial nunca é o único fator de acesso: exige-se também senha em todos "
     "os perfis; para o ministro, prova de vivacidade e, quando a configuração do sistema a exigir, a "
     "confirmação por uma segunda pessoa autorizada; para o administrador, o código do celular."),
    ("Cláusula 8ª. Da recusa",
     "A recusa da finalidade (a) não acarreta prejuízo algum ao TITULAR: apenas o cadastro não será "
     "realizado e nenhuma imagem será capturada. A recusa da finalidade (b) não impede o cadastro."),
    ("Cláusula 9ª. Da natureza do sistema",
     "O EcoSecurity é um protótipo acadêmico, com taxa de erro conhecida e mensurada. Toda negação de acesso "
     "pode ser revista por um responsável humano (art. 20 da LGPD)."),
    ("Cláusula 10ª. Da idade",
     "O TITULAR declara ter 18 (dezoito) anos ou mais. Dados de crianças e de adolescentes exigem "
     "consentimento específico de ao menos um dos pais ou do responsável legal (art. 14 da LGPD) e não são "
     "tratados por este sistema."),
    ("Cláusula 11ª. Da assinatura eletrônica",
     "A assinatura eletrônica consiste na digitação do nome completo do TITULAR. No ato do aceite, o sistema "
     "calcula e registra o resumo criptográfico SHA-256 do texto integral apresentado, incluindo o nome e as "
     "autorizações registradas ao final, como prova do conteúdo consentido. Uma via deste Termo, com a "
     "assinatura, é disponibilizada ao TITULAR."),
)

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")


def _normalizar(nome: str) -> str:
    return " ".join(nome.split())


def _manifestacao_b(autoriza_pesquisa: bool | None) -> str:
    if autoriza_pesquisa is None:
        return "a manifestar"
    return "AUTORIZO" if autoriza_pesquisa else "NÃO AUTORIZO"


def _escolhas(autoriza_pesquisa: bool | None) -> str:
    return f"Finalidade (a): AUTORIZO. Finalidade (b): {_manifestacao_b(autoriza_pesquisa)}."


def renderizar(nome: str, contato: str, autoriza_pesquisa: bool | None = None) -> str:
    """Texto exato apresentado, com o nome e as escolhas. É sobre ele que o hash é calculado."""
    nome = _normalizar(nome)
    partes = [TITULO.upper(), f"Versão {VERSAO}", "", "Quadro-resumo"]
    partes += [f"{i}. {item}" for i, item in enumerate(RESUMO, 1)]
    partes += ["", PREAMBULO.format(nome=nome or "_" * 30)]
    for titulo, corpo in CLAUSULAS:
        partes += ["", titulo.upper(), corpo.format(contato=contato)]
    partes += ["", "DAS AUTORIZAÇÕES", _escolhas(autoriza_pesquisa)]
    return "\n".join(partes)


# ------------------------------------------------------------------ apresentação (tela e PDF)
_PARAGRAFO = "<p align='justify' style='margin-top:4px; margin-bottom:4px'>{}</p>"


def _marca(marcado: bool | None) -> str:
    return "(X)" if marcado else "(&nbsp;&nbsp;)"


def _corpo_html(nome: str, contato: str, autoriza_pesquisa: bool | None) -> list[str]:
    nome = _normalizar(nome)
    nome_html = f"<b>{escape(nome)}</b>" if nome else "______________________________"
    resumo = "".join(f"<p style='margin:3px 0'>{i}.&nbsp; {escape(item)}</p>" for i, item in enumerate(RESUMO, 1))
    html = [
        f"<p align='center' style='font-size:8.5pt; color:#555'>{escape(CABECALHO)}</p>",
        f"<p align='center' style='font-size:13pt; margin-top:10px'><b>{escape(TITULO.upper())}</b></p>",
        f"<p align='center' style='font-size:9pt; color:#555'>Versão {VERSAO}</p>",
        "<table width='100%' border='1' cellspacing='0' cellpadding='8' style='border-color:#999; "
        "margin-top:10px; margin-bottom:12px'><tr><td style='background-color:#f2f2ee'>"
        f"<p style='margin:0 0 4px 0'><b>QUADRO-RESUMO</b></p>{resumo}</td></tr></table>",
        _PARAGRAFO.format(escape(PREAMBULO).replace(escape("{nome}"), nome_html)),
    ]
    for titulo, corpo in CLAUSULAS:
        html.append(f"<p style='margin-top:12px; margin-bottom:2px'><b>{escape(titulo.upper())}</b></p>")
        html += [_PARAGRAFO.format(escape(p)) for p in corpo.format(contato=contato).split("\n")]
    b = autoriza_pesquisa
    assinado = b is not None             # antes da assinatura, nenhum quadro aparece marcado
    html.append(
        "<p style='margin-top:14px; margin-bottom:4px'><b>DAS AUTORIZAÇÕES</b></p>"
        "<table width='100%' border='1' cellspacing='0' cellpadding='6' style='border-color:#999'>"
        "<tr><td width='62%'><b>Finalidade</b></td><td><b>Manifestação do TITULAR</b></td></tr>"
        "<tr><td>(a) Autenticação (Cláusula 3ª). Obrigatória.</td>"
        f"<td>{_marca(assinado)} Autorizo</td></tr>"
        "<tr><td>(b) Estatística e experimentação (Cláusula 3ª). Opcional.</td>"
        f"<td>{_marca(b is True)} Autorizo<br>{_marca(b is False)} Não autorizo</td></tr></table>")
    return html


def renderizar_html(nome: str, contato: str, autoriza_pesquisa: bool | None = None) -> str:
    """O termo para LEITURA na tela, antes da assinatura (o mesmo conteúdo do texto do hash)."""
    return "".join(_corpo_html(nome, contato, autoriza_pesquisa)) + (
        "<p style='margin-top:18px'>A assinatura é feita a seguir, com a digitação do nome completo do "
        "TITULAR (Cláusula 11ª).</p>")


def data_por_extenso(momento: datetime) -> str:
    return f"{momento.day} de {MESES[momento.month - 1]} de {momento.year}, às {momento:%H:%M}"


def via_do_titular_html(nome: str, contato: str, autoriza_pesquisa: bool, momento: datetime, hash_termo: str,
                        matricula: str | None = None) -> str:
    """A via assinada: o termo com as escolhas feitas, o bloco de assinatura e o registro do aceite.

    Só existe depois do aceite: o momento e o hash vêm do consentimento
    registrado, e não de um cálculo novo na hora de salvar."""
    nome = _normalizar(nome)
    identificacao = f"TITULAR · Matrícula {escape(matricula)}" if matricula else "TITULAR"
    return "".join(_corpo_html(nome, contato, autoriza_pesquisa)) + (
        f"<p align='justify' style='margin-top:22px'>E, por estar de acordo, o TITULAR assina eletronicamente "
        f"este Termo em {escape(data_por_extenso(momento))}.</p>"
        "<p align='center' style='margin-top:30px; margin-bottom:0'>______________________________________________</p>"
        f"<p align='center' style='margin:2px 0'><b>{escape(nome)}</b></p>"
        f"<p align='center' style='margin:0; font-size:9pt'>{identificacao}</p>"
        "<p align='center' style='margin:0; font-size:9pt'>Assinatura eletrônica (Cláusula 11ª)</p>"
        "<table width='100%' border='1' cellspacing='0' cellpadding='8' style='border-color:#999; "
        "margin-top:24px'><tr><td style='background-color:#f2f2ee; font-size:8.5pt'>"
        "<b>REGISTRO DO CONSENTIMENTO</b><br>"
        f"Termo versão {VERSAO} · aceito em {momento:%d/%m/%Y %H:%M}<br>"
        f"Resumo SHA-256 do texto aceito: <span style='font-family:Consolas,monospace'>{escape(hash_termo)}"
        "</span><br>Via do TITULAR. A autenticidade é conferida pelo administrador, que recalcula o resumo "
        "do texto do termo com o nome e as autorizações acima e o compara com o registro.</td></tr></table>")


# ------------------------------------------------------------------ prova do consentimento
VERSOES = {termo_v2.VERSAO: termo_v2.renderizar, termo_v3_0.VERSAO: termo_v3_0.renderizar,
           termo_v3_1.VERSAO: termo_v3_1.renderizar, termo_v3_2.VERSAO: termo_v3_2.renderizar,
           termo_v3_3.VERSAO: termo_v3_3.renderizar, VERSAO: renderizar}
# versão arquivada que só foi apresentada com um contato: a conferência usa esse, não o configurado hoje
CONTATO_DA_VERSAO = {termo_v3_0.VERSAO: termo_v3_0.CONTATO}


def calcular_hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def confere(versao: str, nome: str, contato: str, autoriza_pesquisa: bool, hash_registrado: str) -> bool | None:
    """Recalcula o hash do texto daquela versão. None se a versão não está arquivada."""
    renderizador = VERSOES.get(versao)
    if renderizador is None:
        return None
    contato = CONTATO_DA_VERSAO.get(versao, contato)
    return calcular_hash(renderizador(nome, contato, autoriza_pesquisa)) == hash_registrado
