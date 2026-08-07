# SAISENT 4.0

Um painel de controlo que cola texto preparado com antecedência nas sessões de agentes que estão a correr neste momento nesta máquina.

Coloque o texto na fila da sessão certa — o SAISENT ativa a janela do agente, muda para o separador dessa sessão, cola o texto numa única operação e carrega em Enter.

## Arranque rápido

```
START_SAISENT.bat
```

Requer Python 3.11+ no Windows.

## Como usar

1. **Agentes.** Linha de cima — caixas de verificação: Claude Code, Freebuff, Antigravity, CodeNomad.
   Marca um agente e as suas sessões aparecem no painel esquerdo.
2. **Sessões ao vivo.** À esquerda o que está realmente a correr: nome da sessão, número do separador, sensor de atividade e projeto. A lista não se atualiza sozinha, a menos que atives «cada N s» — por defeito a atualização é apenas com o botão **Atualizar**.
3. **Separador.** O SAISENT adivinha o número do separador pela ordem de arranque das sessões. Errado? Escreve o número manualmente em `SAISENT.json`, chave `tabs` (chave de sessão na forma `<agente>:<id>`, ex. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = não mudar de separador de todo.
4. **Texto.** Escreve (ou cola) em baixo à direita, carrega em **Em fila** (ou Ctrl+Enter). **Tudo em fila** coloca o mesmo texto em cada sessão ao vivo — substitui a antiga macro «CTRL+2, texto, CTRL+3, texto».
5. **Fila.** A ordem das linhas = a ordem de envio. Arrasta uma linha com o rato ou move-a com **Cima**/**Baixo**. Cada sessão tem a sua própria fila. Duplo clique numa linha (ou botão **Editar**) traz o prompt de volta ao campo de texto; **Guardar edição** reescreve-o no lugar, **Cancelar** descarta. Editar um prompt já enviado devolve-o à fila — o texto na linha já não corresponde ao que a sessão recebeu. **Duplicar** coloca uma cópia logo abaixo.
6. **Envio.** **ENVIAR ESTA FILA** — apenas a sessão selecionada. **ENVIAR TODAS** — todas as filas em sequência. **Ensaio seco** não envia nada, apenas mostra o plano no registo. Os envios reais pedem confirmação e nomeiam as sessões.

## Anular envio

Após o envio, aparece um botão **Anular** durante 30 segundos. Devolve o último prompt enviado à fila como `pending` — a menos que a sessão já o tenha processado (entrega confirmada).

## Programação e limites

No grupo «Envio»:

- **Enviar às (HH:MM)** — vazio significa «agora». Com uma hora, a fila espera a próxima ocorrência dessa hora (hoje, ou amanhã se já passou) e mostra uma contagem decrescente na barra de estado.
- **Aguardar o reset do limite** — antes de cada prompt, o SAISENT lê o texto do próprio agente. Se disser «limit reached», a fila espera e retoma automaticamente quando o limite se liberta. Nenhum prompt contra uma porta fechada.
- **Verificar limites** — reverificar agora.
- O campo de estado à direita mostra o estado ao vivo: `limits: all agents free` ou `claude-code: LIMITED until 09:22 (1h 05m remaining)`, a vermelho. A contagem decrescente bate uma vez por segundo a partir da cache; o disco só é tocado quando a leitura está desatualizada ou quando chega a hora de reset indicada.

A hora de reset vem das próprias palavras do agente. Se não a indicar, o SAISENT escreve «reset time not stated» em vez de inventar um espaço reservado como «+5 horas».

### Quando os limites se reset

Se o agente nunca indica uma hora de reset, o SAISENT recorre a uma regra por agente:

| Agente | Regra | Significado |
|---|---|---|
| Freebuff | `daily 10:00` | reset todos os dias às 10:00 |
| CodeNomad | `daily 03:00` | reset todos os dias às 03:00 |
| Claude Code | `rolling 5h` | 5 horas após o último prompt enviado |
| Antigravity | apenas as palavras do agente | sem regra — o que indicar, ou nada |

Uma regra nunca sobrepõe uma hora indicada pelo agente; o agente é a autoridade sobre a sua própria quota. Qualquer regra pode ser substituída em `SAISENT.json` sob `quota_plans`, ex. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Porque é que os seguintes não saem

O envio é estritamente sequencial e para no primeiro erro real. O motivo aparece na barra de estado (`stopped: window not found: ...`), na linha do prompt na lista e no registo. O resto fica `pending` — não se perde.

Entre prompts há uma pausa `gap_ms` (padrão 1500 ms) e o estado mostra `Waiting N.Ns before next`. Se um prompt foi enviado mas a sessão não se mexeu, é marcado **não confirmado** e permanece na fila. «Enviado» só se aplica a entregas confirmadas.

## Sensor de atividade

A coluna «Sensor» responde a «posso escrever agora?».

- `busy` — a sessão escreveu no seu armazém há menos de 20 segundos (o agente está a meio do turno);
- `idle` — silêncio superior a 20 segundos, o campo de entrada está livre.

De onde vem:

| Agente | Fonte | Sensor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transcrição | última escrita na transcrição |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabela `threads` | campo `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime da base e do seu `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | última escrita na transcrição |

A vivacidade é uma verificação separada, não «o ficheiro no disco está fresco»:

- **Claude Code** — o PID de `~/.claude/sessions/<pid>.json` está vivo. O ficheiro sobrevive ao fecho da sessão; o PID não.
- **Freebuff** — `Freebuff.exe` está a correr. A base mantém os threads `open` mesmo após sair da aplicação.
- **Antigravity** — `Antigravity.exe` está a correr **e** a conversa é fresca. A frescura sozinha não basta: este armazém guarda todas as conversas para sempre, e um editor fechado enchia a lista com sessões que nenhuma tecla podia alcançar.
- **CodeNomad** — a linha da base não está arquivada (`time_archived IS NULL`). Ativas são apenas as atualmente abertas.

## Endereço de entrega — coluna «Endereço»

A barra lateral mostra exatamente como cada sessão será atingida:

| Valor | Método | Fiabilidade |
|---|---|---|
| `cdp:28194` | Colar através do depurador do agente | Exato: campo lido antes e depois, o foco não é roubado |
| `CTRL+3` | Mudança de separador na janela do agente | Bom, se o número do separador estiver correto |
| `blind` | Sem porta, sem número de separador | O prompt cai no chat que estiver aberto |

Nenhum título de janela contém um nome de sessão — `claude.exe` chama-se «Claude», Antigravity chama-se «Antigravity», Freebuff chama-se «Freebuff Desktop». Endereçar por janela é portanto impossível, e `blind` significa exatamente o que diz.

### CDP — o caminho fiável

Se um agente foi lançado com `--remote-debugging-port`, o SAISENT envia através do depurador e não toca nem no foco nem no teclado. Isto significa:

- o texto é colado diretamente no campo de entrada, não «onde calhar»;
- o campo é lido **antes** de colar: se houver uma mensagem a meio, o envio recusa em vez de acrescentar à frase de outro;
- o campo é lido **depois** de colar: se não aterrou, não enviamos.

Uma recusa do CDP nunca cai em teclas às cegas. O transporte preciso acabou de dizer que o momento é errado; martelar teclas por cima é exatamente a forma de estragar o chat de outro.

A porta é lida de `DevToolsActivePort` do agente, mas um ficheiro sozinho não basta — sobrevive a um arranque anterior. O SAISENT liga-se realmente à porta antes de cada sondagem.

Ativar o depurador para um agente (um reinício mata o que ele está a fazer — o SAISENT nunca o faz por si):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Seletores de página (DOM real, 2026-08-05)

| Agente | Porta | Campo de entrada | Lista de diálogos |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | nenhuma | — | — |

Antigravity verificado: 16 botões, as etiquetas coincidem exatamente com os nomes de projeto que o SAISENT mostra (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — a seleção do diálogo por nome funciona com precisão.

CodeNomad é Electron sobre OpenCode; a pasta de dados ainda se chama `Plasticity`. A lista de sessões no DOM contém apenas as sessões do **projeto atualmente aberto**; uma sessão de outro projeto não é renderizada e o SAISENT não a encontrará — o envio recusa em vez de atingir às cegas o chat aberto.

Substituir qualquer chave de perfil em `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

As sessões são lidas de `~/.local/share/opencode/opencode.db`, tabela `session`: nome = `title`, projeto = `directory`, as arquivadas filtradas por `time_archived`, o sensor por `time_updated`. O único agente aqui cuja lista de sessões são colunas simples, sem protobuf nem análise.

Vivacidade — `CodeNomad.exe` está a correr. Sem número de separador: endereçado por nome através do depurador.

## Porquê não por título de janela

Cada janela `claude.exe` chama-se «Claude». O nome de sessão nunca aparece no título, por isso endereçar por janela é impossível — o nome, o projeto e o PID vêm do disco; a janela só é necessária para o foco.

## Confirmação de entrega

O Chromium não responde a `WM_GETTEXT`, por isso ler «aterrou?» através de Win32 é impossível — a antiga releitura para estes agentes devolvia sempre «não confirmado». Em vez disso, o SAISENT espera que se mova o mesmo ficheiro que o sensor de atividade vigia. Moveu-se? Entregue. Não se moveu no tempo atribuído? O prompt é marcado como enviado mas não confirmado, e isso é visível no registo. Não é considerado um erro: o agente pode simplesmente ainda não ter começado o turno.

O envio para no primeiro erro real (janela não encontrada, foco perdido, área de transferência ocupada). Os prompts seguintes ficam na fila — não se perdem e não são enviados às cegas.

## Exportar e Importar

Os botões **Exportar** e **Importar** guardam/carregam filas em formato JSONL. Cada linha é autossuficiente com a sua chave de sessão. A importação funde sem perda de dados — os duplicados (mesma chave + texto) são ignorados.

## Ficheiros junto ao programa

| Ficheiro | Conteúdo |
|---|---|
| `SAISENT.json` | definições: agentes, números de separador, tempos de espera, geometria da janela |
| `SAISENT_QUEUES.json` | filas por sessão, sobrevivem ao reinício |
| `SAISENT.log` | registo do histórico de envios |

A fila nunca é limpa automaticamente. Se uma sessão desaparecer da lista mas tiver itens não enviados, a fila fica: os agentes são reiniciados, e uma fila descartada silenciosamente é pior do que uma linha a mais num ficheiro.

## Definições ocultas

Edita `SAISENT.json` com o programa fechado:

- `gap_ms` — pausa entre prompts num lote (padrão 1500);
- `settle_ms` — pausa após a mudança de separador e após colar (400);
- `confirm_seconds` — quanto tempo esperar pela confirmação de entrega (10);
- `busy_seconds` — limiar do sensor «busy/idle» (20);
- `freebuff_roots` — raízes onde procurar `.freebuff/desktop-v2.db`, ex. `["V:\\___VAC\\__K\\__CODE"]`; profundidade limitada a 3;
- `submit` — tecla para enviar, padrão `ENTER`.

## Limitações

- Os separadores são endereçados via `Ctrl+1..Ctrl+9`. Uma décima sessão é inalcançável — `Ctrl+10` não existe, e o SAISENT recusa em vez de adivinhar.
- O número do separador é uma estimativa baseada na ordem de arranque. Faz a primeira passagem com **Ensaio seco**, depois numa sessão sem importância.
- O Antigravity não guarda nomes de conversa como texto: a lista mostra o nome da pasta de trabalho extraído dos metadados.

## Testes

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
