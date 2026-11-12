# EcoSecurity

Controle de acesso multinível por reconhecimento facial, que protege um cadastro de passivos ambientais perigosos.
APS de Processamento de Imagens e Visão Computacional, UNIP, 2026/2.

Windows · Python 3.11 · PySide6 (Fluent Widgets) · OpenCV contrib (Haar, KCF, LBPH, FacemarkLBF) · MySQL 8.4

## Sumário

1. [O que o sistema faz](#o-que-o-sistema-faz)
2. [O que você precisa ter](#o-que-você-precisa-ter)
3. [Instalação passo a passo](#instalação-passo-a-passo)
4. [Primeiro uso: configuração inicial](#primeiro-uso-configuração-inicial)
5. [Uso do dia a dia](#uso-do-dia-a-dia)
6. [Administradores e segredos](#administradores-e-segredos)
7. [Configurações](#configurações)
8. [Problemas comuns](#problemas-comuns)
9. [Comandos](#comandos)
10. [Testes automatizados](#testes-automatizados)
11. [Arquitetura e camadas de segurança](#arquitetura-e-camadas-de-segurança)
12. [Privacidade e dados pessoais (LGPD)](#privacidade-e-dados-pessoais-lgpd)

## O que o sistema faz

- **Login único** com matrícula, senha e rosto. Cada cadastro tem **um perfil**, e cada perfil vê **só a própria
  camada** de informação:

  | Perfil | Nível | O que vê |
  |---|---|---|
  | Servidor | 1 | Estatísticas agregadas, sem localização |
  | Diretor (com UF) | 2 | Os casos da própria UF, com os responsáveis |
  | Ministro | 3 | A visão nacional: custódia, criticidade, custos e a fila do orçamento público |
  | Externo | nenhum | Quem não é do quadro do governo. Pode receber o papel de **administrador**, que cadastra pessoas e cuida da segurança, mas nunca vê dado do acervo |

- **Dez camadas de segurança** (S1 a S10): bloqueio por erros, senha forte, qualidade da imagem, reconhecimento
  facial (LBPH), escopo do perfil, prova de vida (piscada e movimento do rosto), segunda pessoa, tarja, marca
  d'água e trilha de auditoria encadeada por SHA-256.
- **Acervo** com 9 relatórios e um painel analítico (mapa, gráficos, planilha), desenhados na hora a partir do banco.
- **Nada vai para a internet.** O rosto vira um modelo matemático cifrado; nenhuma imagem é guardada.

## O que você precisa ter

| Item | Detalhe |
|---|---|
| Windows 10 ou 11 | O sistema usa recursos do Windows (proteção dos segredos e atalho com ícone) |
| Webcam | A integrada do notebook serve. Luz de frente para o rosto ajuda muito |
| Python **3.11** | Exatamente a 3.11: as bibliotecas foram validadas nela. A 3.12 ou mais nova não serve |
| Internet | Só na instalação, para baixar as bibliotecas (cerca de 1 GB) e o modelo dos pontos do rosto (54 MB) |
| MySQL 8.4 (ou 8.0) | Só para o uso completo. Para conhecer o sistema, dá para rodar sem banco (passo 5A) |
| Git | Opcional: também dá para baixar o projeto em ZIP |

> Coloque o projeto numa pasta **de caminho curto e fora do OneDrive**, por exemplo `C:\EcoSecurity`:
> - **caminho curto:** a biblioteca da interface (PySide6) tem arquivos com nomes muito longos, e o Windows recusa
>   caminhos acima de 260 caracteres. Numa pasta funda, a instalação falha com `OSError ... Long Path support`;
> - **fora do OneDrive:** a pasta guarda o modelo facial cifrado e o arquivo `.env` com os segredos, que não devem
>   ir para a nuvem.

## Instalação passo a passo

Todos os comandos são digitados no **PowerShell**, dentro da pasta do projeto. Para abrir o PowerShell na pasta,
abra a pasta no Explorador de Arquivos, clique na barra de endereço, digite `powershell` e aperte Enter.

### Passo 1. Instalar o Python 3.11

```powershell
winget install Python.Python.3.11
```

Feche e abra o PowerShell de novo. Para conferir, `py -3.11 --version` deve mostrar `Python 3.11.x`.

### Passo 2. Baixar o projeto

Com o Git:

```powershell
git clone https://github.com/gugalcantara/EcoSecurity.git C:\EcoSecurity
cd C:\EcoSecurity
```

Sem o Git: no GitHub, clique em **Code > Download ZIP**, extraia em `C:\EcoSecurity` e abra o PowerShell nessa pasta.

### Passo 3. Criar o ambiente e instalar as bibliotecas

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

O primeiro comando cria o ambiente isolado `.venv`; o segundo instala as bibliotecas, com as versões exatas do
`requirements.txt` (leva alguns minutos).

> Daqui em diante, use **sempre** o `.venv\Scripts\python.exe`, nunca o `python` solto. Não instale o
> `opencv-python` comum: ele conflita em silêncio com o `opencv-contrib-python`, que é o que tem o reconhecimento
> facial.

### Passo 4. Baixar o modelo do rosto e conferir o ambiente

```powershell
.venv\Scripts\python.exe -m ferramentas.baixar_modelo_landmarks
.venv\Scripts\python.exe -m ferramentas.verificar_ambiente
```

- O primeiro baixa o modelo de 68 pontos do rosto (54 MB), usado na prova de vida, e confere a integridade dele.
- O segundo testa tudo: Python, bibliotecas, modelo e webcam. Ele deve terminar com **Ambiente válido**. Se mostrar
  `[FALHA]`, veja [Problemas comuns](#problemas-comuns).

### Passo 5. Escolher como rodar

#### 5A. Teste rápido, sem banco de dados

```powershell
.venv\Scripts\python.exe -m ecosec --memoria
```

Tudo funciona, mas os cadastros ficam só na memória e **somem ao fechar** o programa. Bom para conhecer o sistema.
Siga para o [Primeiro uso](#primeiro-uso-configuração-inicial).

#### 5B. Uso completo, com o MySQL (uma vez por computador)

1. **Instale o MySQL Community Server 8.4 LTS**, pelo instalador de
   [dev.mysql.com/downloads/mysql](https://dev.mysql.com/downloads/mysql/). No **MySQL Configurator**:
   - tipo de configuração: *Development Computer*;
   - porta **3306**, sem abrir a porta no firewall;
   - defina uma **senha para o `root`** e guarde-a só para você.
2. **Prepare os bancos e as contas:**

   ```powershell
   .venv\Scripts\python.exe -m ferramentas.preparar_banco
   ```

   A ferramenta pede a senha do `root` uma vez (ela não é guardada) e:
   - cria os bancos `ecosec_seguranca` (pessoas e trilha) e `ecosec_acervo` (o cadastro de passivos);
   - importa o acervo;
   - cria três contas com o **mínimo** de privilégio e prova, no banco real, que elas não conseguem o que não devem:

     | Conta | Banco | Pode | Não pode |
     |---|---|---|---|
     | `ecosec_seg` | `ecosec_seguranca` | ler; inserir; alterar usuário e consentimento | apagar usuário, consentimento ou amostra; ler o acervo |
     | `ecosec_cofre` | `ecosec_acervo` | só ler | gravar qualquer coisa; ler usuários |
     | `ecosec_teste` | `ecosec_teste_*` | tudo, em bancos descartáveis de teste | tocar nos bancos reais |

   - grava as senhas dessas contas, geradas ao acaso, no `.env`. O EcoSecurity **nunca** usa o `root`.

   Pode rodar de novo sem medo: ela só cria o que falta e aplica as atualizações pendentes.
3. **Abra o sistema:**

   ```powershell
   .venv\Scripts\python.exe -m ecosec
   ```

### Passo 6 (opcional). Atalho com ícone

```powershell
.venv\Scripts\python.exe -m ferramentas.criar_atalho
```

Cria o **EcoSecurity** no Menu Iniciar, que abre sem a janela preta do console. Acrescente `--area-de-trabalho` para
criar também na Área de Trabalho.

### Resumo dos comandos da instalação

```powershell
winget install Python.Python.3.11
git clone https://github.com/gugalcantara/EcoSecurity.git C:\EcoSecurity
cd C:\EcoSecurity
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m ferramentas.baixar_modelo_landmarks
.venv\Scripts\python.exe -m ferramentas.verificar_ambiente
.venv\Scripts\python.exe -m ecosec --memoria
```

Para o uso com banco, troque a última linha por `preparar_banco` e depois `python -m ecosec` (passo 5B).

## Primeiro uso: configuração inicial

Numa instalação nova, o sistema abre na **Configuração inicial**, com só o menu **Administração**:

1. **Defina a senha de instalação.** Ela segue a política de senha forte (12 caracteres ou mais, com letras
   maiúsculas, minúsculas, números e símbolos) e serve só para esta etapa. Só o hash bcrypt dela é guardado.
2. **Faça o seu cadastro**, com o perfil **Externo** (o único oferecido nesta etapa):
   1. leia o termo de consentimento e marque as autorizações;
   2. informe nome e senha. O Externo e o ministro usam a mesma senha forte do item 1; o servidor e o diretor,
      pelo menos 8 caracteres, com letra e número;
   3. olhe para a câmera nas duas sessões de captura do rosto;
   4. anote a **matrícula** gerada e salve a **via do termo em PDF**, que também traz a matrícula.

   Ao concluir, você é o **primeiro administrador**.
3. O sistema passa a abrir pelo **login**: matrícula, senha e rosto.
4. Abra a **Administração**. O rosto é conferido de novo e, no primeiro acesso, aparece um **QR code**:
   - leia o QR com um aplicativo autenticador no celular (Google Authenticator ou Microsoft Authenticator);
   - digite o código de 6 dígitos que o aplicativo mostra;
   - **guarde os 8 códigos de recuperação**, que aparecem uma única vez.
5. **Cadastre as outras pessoas**, cada uma com o seu perfil (servidor, diretor ou ministro).
6. **Designe um segundo administrador:** cadastre a pessoa como Externo e use **Tornar administrador**. Com menos
   de 2 administradores, você faz tudo sozinho. A partir do segundo, cada ação crítica pede o código do celular de
   outro administrador.
7. O administrador **não vê nenhum dado do acervo**. Para ver o nível 3, entre com o cadastro de um ministro.
8. Faça o **backup dos segredos** (veja [Administradores e segredos](#administradores-e-segredos)).

## Uso do dia a dia

- **Login:** matrícula, senha e rosto. Olhe para a câmera, com luz de frente, uma pessoa por vez.
- **Início:** mostra quem você é e o cartão do seu nível.
- **Abrir o nível:**
  - os níveis 1 e 2 abrem direto, porque o login já conferiu matrícula, senha e rosto;
  - o nível 3 pede o rosto de novo e dois gestos sorteados na câmera (sempre uma piscada, mais virar ou deslizar o
    rosto), e fecha depois de 5 minutos sem uso.
- **Painel analítico:** troca os relatórios por seções interativas, conforme o nível: panorama por UF, resumo
  agregado, mapa interativo, evolução, priorização do orçamento e planilha analítica.
- **Exportar:** o nível 1 exporta os agregados; o nível 2 exporta os dados da UF e pede o rosto de novo se a última
  conferência passou de 5 minutos; o nível 3 não exporta. Toda exportação fica na trilha.
- **Bloqueio por inatividade:** depois de 10 minutos sem uso, a tela bloqueia. A sua senha devolve você para onde
  estava; o nível 3 e a Administração pedem o rosto de novo.
- **Erros seguidos:** 3 erros na mesma matrícula bloqueiam o login por 15 minutos. A tela informa até que horas.
- **Esqueci minha matrícula:** está na via do termo (PDF); senão, o administrador consulta no painel.
- **Encerrar sessão:** botão no Início ou no menu, embaixo.

## Administradores e segredos

**Uma pessoa, um cadastro.** Cada administrador entra pelo login comum, com a **própria** matrícula, senha e rosto.
Ser administrador é um papel dado a um cadastro Externo. Não existe senha de administrador compartilhada, então a
trilha sempre mostra quem fez cada coisa.

**Abrir o painel** pede três provas: o login, o rosto conferido na hora e o **código do celular** (muda a cada 30
segundos e funciona sem internet, desde que o relógio esteja certo). Perdeu o celular? Um código de recuperação abre
o painel uma vez.

**Ações críticas pedem um segundo administrador:**
- tornar alguém administrador ou tirar o papel;
- atribuir o perfil de ministro;
- excluir um cadastro;
- refazer o celular de alguém;
- revogar um consentimento (apaga o rosto do modelo);
- registrar a revisão de acessos.

Quem pede liga para outro administrador, que lê o resumo e informa o código que o celular **dele** mostra. Ninguém
aprova o próprio pedido, e o sistema não deixa ficar com menos de 2 administradores.

**O que mais fica no painel:**
- **Perfis e exclusão:** atribuir ou trocar o perfil (o diretor pede a UF) e excluir um cadastro. A exclusão é
  lógica e irreversível: desativa, revoga o consentimento e apaga o rosto; a trilha e o termo aceito ficam como prova.
- **Identificação facial:** compara um rosto com todos os cadastros e diz quem é. Não dá acesso a nada, e cada
  identificação fica na trilha.
- **Trilha de auditoria:** lista os eventos e verifica a cadeia de hash. Os botões **Gerar âncora** e **Conferir
  âncora** cuidam da âncora (veja abaixo).
- **Relatórios do sistema:** do S-01 ao S-10. O S-10 é a revisão de acessos (perfis, administradores, celular
  cadastrado, último login e versão do termo).

**Âncora da trilha.** A trilha é uma corrente de hashes: alterar uma linha no banco quebra a corrente no ponto
exato. Para pegar também a remoção das últimas linhas, gere de tempos em tempos (por exemplo, ao fim de cada dia de
uso) uma **âncora** no painel, na aba da trilha, com o código do seu celular. Guarde a linha **fora do computador**
(no celular, num e-mail ou impressa). Depois, **Conferir âncora** ou a ferramenta `verificar_trilha` provam que a
trilha continua igual até aquele ponto.

**Acesso de emergência.** Se um administrador acertou matrícula e senha mas o **rosto ou a câmera falhou**, o login
mostra o botão **Acesso de emergência**. Ele abre com os códigos de **2 administradores** em até 5 minutos e dura 30
minutos, só para consertar o acesso: recadastrar o rosto, refazer o celular ou designar outro administrador.

**Segredos protegidos pelo Windows.** O `.env` guarda as chaves de cifragem e as senhas do banco, cifradas pelo
Windows (DPAPI) e presas à sua conta neste computador: quem copiar o arquivo leva texto ilegível. Faça um backup,
que abre em outro computador com uma frase-senha:

```powershell
.venv\Scripts\python.exe -m ferramentas.proteger_segredos --backup E:\ecosec_segredos.bak
```

Guarde o backup **fora** do computador e a frase-senha em outro lugar. Trocou de computador ou reinstalou o
Windows? Use `--restaurar ARQUIVO`. Para converter um `.env` antigo, sem proteção, rode a ferramenta sem argumentos.

## Configurações

Todos os parâmetros ficam em [`config/ecosec.toml`](config/ecosec.toml), comentados. Um parâmetro ausente ou
inválido impede o sistema de abrir, com uma mensagem dizendo qual é. Os mais úteis:

| Chave | Valor atual | Para quê |
|---|---|---|
| `[persistencia] modo` | `"mysql"` | `"memoria"` roda sem banco (o mesmo que `--memoria`) |
| `[captura] indice_camera` | `0` | Troque para `1` ou `2` se abrir a câmera errada |
| `[aplicacao] tema` | `"escuro"` | `"claro"` ou `"escuro"` (também há o botão no menu) |
| `[interface] modo_demonstracao` | `false` | `true` mostra a distância do reconhecimento ao lado do limiar. Ligar só na apresentação |
| `[s4_inerencia] limiar_nivel_1`, `_2`, `_3` | `55`, `55`, `50` | Distância máxima aceita no reconhecimento facial (menor = mais parecido). O login e os níveis 1 e 2 usam 55; o nível 3, mais rígido, usa 50. Calibrados com a curva DET |
| `[identificacao] limiar` | `50` | Distância máxima para a identificação facial dizer quem é |
| `[s6_vivacidade] sinal_piscada` / `limiar_regiao` | `"regiao"` / `0.85` | Como a piscada é medida (pela região dos olhos). O limiar depende da câmera: calibre com `calibrar_vivacidade` em cada computador e não envie esse ajuste ao repositório |
| `[s1_contencao] tentativas_maximas` / `bloqueio_minutos` | `3` / `15` | Erros seguidos até bloquear a matrícula, e por quanto tempo |
| `[sessao] inatividade_minutos` / `inatividade_n3_minutos` | `10` / `5` | Minutos sem uso até bloquear a tela / fechar o nível 3 |
| `[s7_custodia] exigir_segunda_pessoa` | `false` | `true` liga a segunda pessoa no nível 3. Desligada porque o cargo de ministro é de uma pessoa só |
| `[administracao] minimo_administradores` | `2` | A partir deste número de administradores, ação crítica exige um segundo |
| `[lgpd] leitura_minima_segundos` | `5` | Tempo com o termo aberto antes de liberar o aceite |
| `[documentos] bloquear_captura` | `false` | `true` deixa a janela do documento preta em capturas de tela |
| `[interface] animacoes` | `true` | `false` desliga zoom e painéis animados |
| `[regras_negocio]`, `[custos]`, `[geracao]`, `[indice_pressao]` | ver arquivo | Regras do acervo, custos de remediação, gerador do acervo e Índice de Pressão. Mudou o `[geracao]`? Rode `preparar_banco --recriar-acervo` |

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `py -3.11` não é reconhecido | Python 3.11 não instalado, ou o PowerShell foi aberto antes da instalação | Passo 1, depois feche e abra o PowerShell |
| `OSError ... does not have Windows Long Path support enabled` ao instalar | Pasta do projeto com caminho longo demais | Mova o projeto para uma pasta curta, como `C:\EcoSecurity`, apague a `.venv` e refaça o passo 3 |
| Outro erro ao instalar o `requirements.txt` | Ambiente criado com outra versão do Python | Apague a pasta `.venv` e refaça o passo 3 com `py -3.11` |
| "O banco ainda não foi preparado" | Faltou o `preparar_banco`, ou você queria rodar sem banco | Passo 5B, ou abra com `--memoria` |
| "Não foi possível abrir com segurança" / banco indisponível | Serviço do MySQL parado | Em *Serviços* do Windows, inicie o **MySQL84** (ou **MySQL80**) |
| "Câmera indisponível" | Outro programa usando a webcam | Feche Teams, navegador ou outro app de vídeo e rode `verificar_ambiente` |
| Abre a câmera errada | Mais de uma câmera no computador | `[captura] indice_camera = 1` no config |
| Rosto não reconhecido | Luz atrás do rosto, rosto longe ou mais de uma pessoa | Luz de frente, rosto dentro do oval, uma pessoa por vez |
| "Matrícula bloqueada" | 3 erros seguidos | Espere até a hora mostrada na tela (15 minutos) |
| Nível 3 nega na prova de vida | Gesto não detectado | **Piscada:** olhe para a câmera, parado, e pisque uma vez, normalmente. **Mover:** vire ou deslize o rosto para o lado e volte. Se a piscada falha sempre, rode `calibrar_vivacidade` e ajuste o `limiar_regiao` |
| "Modelo de landmarks não encontrado" | Faltou o passo 4 | `.venv\Scripts\python.exe -m ferramentas.baixar_modelo_landmarks` |
| "Faltam tabelas" ou erro com a coluna `perfil`, depois de atualizar | Banco de uma versão anterior | Rode `preparar_banco` de novo: ele aplica as atualizações |
| Código do celular nunca é aceito | Relógio do celular ou do computador fora da hora | Ative a hora automática nos dois |
| Administrador perdeu o celular | | Ele entra com um código de recuperação e pede a outro administrador **Refazer celular** |
| Ninguém consegue abrir o painel | Rostos ou câmera falhando | Acesso de emergência, com os códigos de 2 administradores |
| "O segredo ... não abre nesta conta do Windows" | `.env` de outro computador ou conta | `proteger_segredos --restaurar ARQUIVO`, com o backup |
| Janela preta do console junto | Aberto pelo PowerShell | Use o atalho do passo 6 |

## Comandos

Todos com `.venv\Scripts\python.exe -m` antes:

| Comando | O que faz |
|---|---|
| `ecosec` | Abre o sistema. `--memoria` abre sem banco |
| `ferramentas.verificar_ambiente` | Confere Python, bibliotecas, modelo dos pontos do rosto e webcam |
| `ferramentas.baixar_modelo_landmarks` | Baixa o modelo de 68 pontos do rosto (54 MB) e confere o SHA-256 |
| `ferramentas.preparar_banco` | Cria ou repara bancos, tabelas e contas, aplica as atualizações e importa o acervo. `--recriar-acervo` apaga e reimporta o acervo |
| `ferramentas.criar_atalho` | Atalho com ícone no Menu Iniciar (`--area-de-trabalho` também na Área de Trabalho) |
| `ferramentas.proteger_segredos` | Protege o `.env` com o Windows. `--backup ARQ` grava o backup com frase-senha; `--restaurar ARQ` devolve os segredos a este computador |
| `ferramentas.calibrar_vivacidade` | Calibra a piscada com a sua câmera e a sua luz (cerca de 30 segundos diante da câmera) e sugere o `limiar_regiao`. Não grava imagem |
| `ferramentas.verificar_trilha` | Verifica a cadeia de hash da trilha no banco e aponta o registro adulterado. `--conferir "LINHA"` ou `--conferir-arquivo ARQ` confere âncoras guardadas |
| `ferramentas.experimento_det coletar --sessao 1` | Curva DET com voluntários: cada um faz tentativas curtas diante da câmera. Repita com `--sessao 2` em outra luz. Pede o login de um administrador (matrícula, senha e código do celular). `--ignorar MATRICULA` tira cadastros da mesma pessoa |
| `ferramentas.experimento_det base --pasta PASTA` | Mede a base pública Extended Yale B (versão recortada) com o mesmo tratamento do sistema. Também pede o login de um administrador |
| `ferramentas.experimento_det analisar` | Calcula FAR, FRR e EER, sugere os limiares e grava a figura `resultados/curva_det.png`. Só grava distâncias, nunca imagens, e não muda o config |
| `ferramentas.povoar_usuarios_teste` | Usuários de teste num banco **descartável** (`ecosec_teste_usuarios`); `--apagar` remove |
| `ferramentas.verificar_documento "ecosec://..."` | Confere um documento pelo QR code |
| `ferramentas.extrair_marca ARQ.png` | Rastreia um arquivo vazado: quem exportou e quando (marca d'água) |
| `ferramentas.calibrar_series` | Confere as séries do gerador do acervo |
| `ferramentas.gerar_referencia` | Regrava `sql/acervo/02_referencia.sql` a partir do código |
| `ferramentas.baixar_geografia` | Só para refazer os dados geográficos: baixa os polígonos do IBGE e os CEPs do ViaCEP (o sistema não usa internet) |

## Testes automatizados

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Roda a suíte inteira, a partir da pasta do projeto e sem argumentos (de 25 a 35 minutos). Os testes de MySQL usam
bancos descartáveis `ecosec_teste_*`, com a conta `ecosec_teste` criada pelo `preparar_banco`. Sem o MySQL preparado,
esses testes aparecem como *skipped*, e os demais rodam normalmente. Para rodar só um arquivo:
`.venv\Scripts\python.exe -m pytest -q testes\test_visao.py`.

## Arquitetura e camadas de segurança

```
interface  →  servicos  →  seguranca / visao / acervo  →  dominio
                  └──────→  repositorios (memória ou MySQL)
```

As dependências só apontam para dentro: o `dominio` não importa nada, e a `interface` não decide nada (um teste
garante isso).

| Pasta | Conteúdo |
|---|---|
| `ecosec/dominio/` | Níveis, perfis, camadas S1 a S10, motivos de negação, entidades e o termo de consentimento (3.4, com as versões anteriores arquivadas) |
| `ecosec/visao/` | Aquisição, pré-processamento (CLAHE), segmentação (Haar e KCF), qualidade, reconhecimento LBPH, gestos e medidas de desempenho (FAR, FRR, EER) |
| `ecosec/seguranca/` | Uma camada por módulo (acesso S1 a S7, conteúdo S8 e S9, evidência S10) e a matriz de autorização |
| `ecosec/acervo/` | Gerador do acervo (semente fixa), regras de negócio e os 9 relatórios |
| `ecosec/servicos/` | Cadastro, autenticação, sessão, administração, acervo, trilha e relatórios do sistema |
| `ecosec/repositorios/` | Contratos, implementação em memória e implementação MySQL, com o mesmo comportamento |
| `ecosec/interface/` | Telas em PySide6 e Fluent Widgets |
| `ecosec/aplicacao.py` | Junta as peças: o único lugar que conhece as implementações concretas |
| `config/` | `ecosec.toml`, com todos os parâmetros |
| `sql/` | Scripts dos dois bancos |
| `ferramentas/` | Os comandos de instalação, diagnóstico e auditoria |
| `testes/` | A suíte de testes |

| Anel | Código | Camada | Pergunta |
|---|---|---|---|
| Acesso | S1 | Contenção | Esta matrícula ainda pode tentar? |
| | S2 | Conhecimento | Sabe a senha? |
| | S3 | Qualidade | A imagem permite decidir? |
| | S4 | Inerência | É quem diz ser? |
| | S5 | Habilitação | O perfil tem direito a esta camada? |
| | S6 | Vivacidade | É uma pessoa viva, e não uma foto? |
| | S7 | Custódia | Outra pessoa confirma? (implementada, desligada no config) |
| Conteúdo | S8 | Tarja | O que pode ver? |
| | S9 | Rastreio | Se vazar, de quem veio? |
| Evidência | S10 | Trilha | O que aconteceu, e alguém alterou o registro? |

## Privacidade e dados pessoais (LGPD)

- **Rosto:** as imagens do cadastro ficam **só na memória** e são apagadas depois do treinamento. O que fica é o
  modelo matemático (LBPH), **cifrado** em `modelo/lbph.enc`.
- **Senhas:** só o hash bcrypt.
- **Celular dos administradores:** o segredo do autenticador fica cifrado no banco; dos códigos de recuperação, só o
  hash.
- **Consentimento:** guardado com o hash SHA-256 do texto exato aceito. As versões antigas do termo ficam arquivadas,
  sem alteração, para o hash continuar conferindo.
- **Nada vai para a internet**, e nada disso entra no Git: o `.gitignore` deixa de fora o `.env`, o `modelo/`, as
  capturas e os resultados.
- **Revogação e exclusão:** pelo painel de Administração. Desativam o cadastro e apagam o rosto do modelo; a trilha e
  o termo aceito ficam como prova.
- **Ao fim do trabalho:** descarte dos dados biométricos, com registro em ata.
