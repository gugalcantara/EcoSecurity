"""Termo de consentimento, versão 3.3 (arquivada em 08/11/2026). Não editar.

Os cadastros feitos sob esta versão guardam o hash SHA-256 do texto exato que foi
apresentado (LGPD art. 8º, §2º: o ônus da prova é do controlador). Qualquer mudança
aqui, até de pontuação, faz o hash deixar de conferir. Um teste trava os hashes de
referência (testes/test_perfis.py).

A 3.3 terminava com o rodapé de documento simulado; a 3.4 o tirou
(o resto do texto é igual). Os aceites 3.3 continuam valendo.

Só o necessário para reproduzir o texto (e o hash). A versão em vigor está em `termo.py`.
"""
VERSAO = "3.3"
# 1.0 -> 1.1: contato do controlador (art. 9º), idade (art. 14), eliminação na revogação.
# 1.1 -> 2.0: resumo em camadas e consentimento separado por finalidade (art. 8º, §4º).
# 2.0 -> 3.0: redação formal (preâmbulo, cláusulas, assinatura eletrônica descrita, revisão
#             humana com base no art. 20); conteúdo do tratamento inalterado.
#             Ajuste na 3.0 (07/10/2026, sem subir versão porque nenhum aceite 3.0 tinha sido
#             registrado): a Cláusula 7ª deixa de afirmar que a segunda pessoa é sempre exigida.
#             Ajuste na 3.0 (07/10/2026, mesmo motivo): o sistema passa a se chamar EcoSecurity.
# 3.0 -> 3.1: contato do controlador preenchido (endereço SIMULADO, sem caixa postal real) e rodapé de
#             documento simulado (premissa formal do projeto acadêmico). A 3.0 foi
#             arquivada em termo_v3_0.py, com o contato não preenchido com que sempre foi apresentada.
# 3.1 -> 3.2: só descritiva: a Cláusula 2ª (IV) fala do PERFIL de acesso (um por cadastro;
#             o administrador não tem camada) e a 7ª, dos fatores de cada perfil (o código do celular do
#             administrador). Finalidades, forma, prazo, controlador e compartilhamento iguais: os aceites 3.1
#             continuam valendo. A 3.1 foi arquivada em termo_v3_1.py.
# 3.2 -> 3.3: revisão só descritiva: os perfis passam a ser externo, servidor, diretor e ministro, e
#             administrador é um papel de um cadastro externo (o Ministério Público saiu). Os aceites 3.2
#             continuam valendo. A 3.2 foi arquivada em termo_v3_2.py.
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

# Premissa formal do projeto: emulação acadêmica. O canal efetivo do TITULAR continua sendo o
# administrador do sistema (revogação e relatório do titular), que existe e funciona.
# A marcação usa TRAVESSÃO (decisão de 19/10/2026), que sobrepõe, só para ela, a decisão
# do projeto (07/10/2026) contra travessão em texto visível (testes/test_arquitetura.py, EXCECOES_TEXTO).
MARCACAO_SIMULADO = "DOCUMENTO SIMULADO — PROJETO ACADÊMICO"
RODAPE_SIMULADO = (MARCACAO_SIMULADO + ". O endereço do controlador é simulado, sem caixa postal "
                   "real; pedidos do TITULAR, inclusive a revogação, são feitos diretamente ao administrador do "
                   "sistema.")

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
    partes += ["", "DAS AUTORIZAÇÕES", _escolhas(autoriza_pesquisa), "", RODAPE_SIMULADO]
    return "\n".join(partes)
