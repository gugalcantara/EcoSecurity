# EcoSecurity

Controle de acesso multinível por reconhecimento facial, que protege um cadastro de passivos ambientais perigosos.
APS de Processamento de Imagens e Visão Computacional, UNIP, 2026/2.

Windows · Python 3.11 · PySide6 (Fluent Widgets) · OpenCV contrib · MySQL 8.4

## O que o sistema faz

O acesso é feito com matrícula, senha e rosto. Cada cadastro tem um perfil, e cada perfil vê apenas a sua camada de
informação:

| Perfil | Nível | O que vê |
|---|---|---|
| Servidor | 1 | Estatísticas agregadas, sem localização |
| Diretor | 2 | Os casos da própria UF, com os responsáveis |
| Ministro | 3 | Visão nacional: custódia, criticidade, custos e fila do orçamento público |
| Externo | nenhum | Pode receber o papel de administrador, que cadastra pessoas e cuida do acesso, sem ver o acervo |

Nenhuma imagem de rosto é guardada e nada é enviado para a internet.

## Requisitos

- Windows 10 ou 11, com webcam;
- Python **3.11** (as versões 3.12 ou mais novas não servem);
- MySQL 8.4 (ou 8.0) para o uso completo. Sem ele, o sistema roda em memória;
- internet só durante a instalação.

Instale o projeto numa pasta de caminho curto e fora do OneDrive, por exemplo `C:\EcoSecurity`. Caminhos longos fazem
a instalação do PySide6 falhar, e a pasta guarda segredos que não devem ir para a nuvem.

## Instalação

No PowerShell:

```powershell
winget install Python.Python.3.11
git clone https://github.com/gugalcantara/EcoSecurity.git C:\EcoSecurity
cd C:\EcoSecurity
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m ferramentas.baixar_modelo_landmarks
.venv\Scripts\python.exe -m ferramentas.verificar_ambiente
```

O último comando deve terminar com **Ambiente válido**. Depois de instalar o Python, feche e abra o PowerShell de
novo. Sem o Git, baixe o ZIP pelo GitHub (**Code > Download ZIP**) e extraia em `C:\EcoSecurity`.

Use sempre o `.venv\Scripts\python.exe`, e não instale o pacote `opencv-python` comum, que conflita com o
`opencv-contrib-python`.

### Rodar sem banco de dados

```powershell
.venv\Scripts\python.exe -m ecosec --memoria
```

Os cadastros ficam só na memória e são descartados ao fechar o programa.

### Rodar com o MySQL

1. Instale o MySQL Community Server 8.4 LTS ([dev.mysql.com/downloads/mysql](https://dev.mysql.com/downloads/mysql/)),
   na porta 3306, e defina uma senha para o `root`.
2. Prepare os bancos (a senha do `root` é pedida uma vez e não é guardada):

   ```powershell
   .venv\Scripts\python.exe -m ferramentas.preparar_banco
   ```

3. Abra o sistema:

   ```powershell
   .venv\Scripts\python.exe -m ecosec
   ```

Para criar um atalho no Menu Iniciar: `.venv\Scripts\python.exe -m ferramentas.criar_atalho` (acrescente
`--area-de-trabalho` para criar também na Área de Trabalho).

## Primeiro uso

1. Defina a **senha de instalação**, usada só nesta etapa.
2. Faça o seu cadastro com o perfil **Externo**: termo de consentimento, nome e senha, captura do rosto. Anote a
   matrícula e salve a via do termo em PDF. Você passa a ser o primeiro administrador.
3. Entre pelo login e abra a **Administração**. No primeiro acesso, leia o QR code com um aplicativo autenticador
   (Google ou Microsoft Authenticator) e guarde os códigos de recuperação.
4. Cadastre as demais pessoas, cada uma com o seu perfil, e designe um segundo administrador.
5. Faça o backup dos segredos:

   ```powershell
   .venv\Scripts\python.exe -m ferramentas.proteger_segredos --backup E:\ecosec_segredos.bak
   ```

   Guarde o backup fora do computador. Para restaurar em outro computador, use `--restaurar ARQUIVO`.

## Uso

- **Login:** matrícula, senha e rosto, com luz de frente e uma pessoa por vez diante da câmera.
- **Início:** mostra o cartão do seu nível. O nível 3 pede uma nova verificação facial ao abrir.
- **Exportar:** disponível conforme o nível.
- **Inatividade:** a tela é bloqueada depois de um tempo sem uso e volta com a sua senha.
- **Esqueci minha matrícula:** ela consta na via do termo; o administrador também pode consultá-la.

As configurações ficam em [`config/ecosec.toml`](config/ecosec.toml). Se a câmera aberta for a errada, troque
`[captura] indice_camera` para `1` ou `2`.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `py -3.11` não é reconhecido | Instale o Python 3.11 e reabra o PowerShell |
| `OSError ... Long Path support` ao instalar | Mova o projeto para `C:\EcoSecurity`, apague a `.venv` e reinstale |
| "O banco ainda não foi preparado" | Rode o `preparar_banco` ou abra com `--memoria` |
| Banco indisponível | Inicie o serviço **MySQL84** (ou **MySQL80**) em *Serviços* do Windows |
| "Câmera indisponível" | Feche outros programas que usam a webcam e rode o `verificar_ambiente` |
| Rosto não reconhecido | Luz de frente, rosto dentro do oval, uma pessoa por vez |
| A piscada não é detectada | Rode `.venv\Scripts\python.exe -m ferramentas.calibrar_vivacidade` e ajuste o valor sugerido no config |
| Código do celular não é aceito | Ative a hora automática no celular e no computador |
| "O segredo ... não abre nesta conta do Windows" | Restaure o backup com `proteger_segredos --restaurar ARQUIVO` |

## Ferramentas

Todas com `.venv\Scripts\python.exe -m` antes:

| Comando | O que faz |
|---|---|
| `ferramentas.verificar_ambiente` | Confere Python, bibliotecas, modelo e webcam |
| `ferramentas.preparar_banco` | Cria ou atualiza os bancos e as contas. `--recriar-acervo` reimporta o acervo |
| `ferramentas.proteger_segredos` | Protege o `.env`; `--backup` e `--restaurar` |
| `ferramentas.calibrar_vivacidade` | Calibra a detecção da piscada para a sua câmera |
| `ferramentas.verificar_trilha` | Verifica a integridade da trilha de auditoria |
| `ferramentas.extrair_marca ARQ.png` | Identifica a origem de um arquivo exportado |
| `ferramentas.experimento_det` | Experimento da curva DET (`coletar`, `base` e `analisar`); pede o login de um administrador |

## Testes

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Os testes de banco usam bancos descartáveis criados pelo `preparar_banco`; sem o MySQL, eles são ignorados.

## Privacidade

As imagens do rosto ficam só na memória durante o cadastro; o que se guarda é um modelo cifrado. Senhas são
guardadas apenas como hash. O `.env`, o modelo facial, as capturas e os resultados não vão para o repositório. A
revogação do consentimento e a exclusão de cadastros são feitas pela Administração.
