# SAISENT 4.0

Un panel de control que pega texto preparado de antemano en las sesiones de agentes que están ejecutándose ahora mismo en esta máquina.

Coloca el texto en la cola de la sesión correcta — SAISENT activa la ventana del agente, cambia a la pestaña de esa sesión, pega el texto en una sola operación y pulsa Enter.

## Inicio rápido

```
START_SAISENT.bat
```

Requiere Python 3.11+ en Windows.

## Cómo usarlo

1. **Agentes.** Fila superior — casillas: Claude Code, Freebuff, Antigravity, CodeNomad.
   Marca un agente y sus sesiones aparecen en el panel izquierdo.
2. **Sesiones en vivo.** A la izquierda lo que realmente se ejecuta: nombre de sesión, número de pestaña, sensor de actividad y proyecto. La lista no se actualiza sola a menos que actives «cada N s» — por defecto la actualización es solo con el botón **Actualizar**.
3. **Pestaña.** SAISENT adivina el número de pestaña por el orden de lanzamiento de las sesiones. ¿Mal? Escribe el número manualmente en `SAISENT.json`, clave `tabs` (clave de sesión con forma `<agente>:<id>`, p. ej. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = no cambiar de pestaña.
4. **Texto.** Escribe (o pega) abajo a la derecha, pulsa **En cola** (o Ctrl+Enter). **Todo en cola** mete el mismo texto en cada sesión en vivo — reemplaza el antiguo macro «CTRL+2, texto, CTRL+3, texto».
5. **Cola.** El orden de filas = el orden de envío. Arrastra una fila con el ratón o muévela con **Arriba**/**Abajo**. Cada sesión tiene su propia cola. Doble clic en una fila (o botón **Editar**) devuelve el prompt al campo de texto; **Guardar edición** lo reescribe en el sitio, **Cancelar** lo descarta. Editar un prompt ya enviado lo devuelve a la cola — el texto de la fila ya no coincide con lo que recibió la sesión. **Duplicar** coloca una copia justo debajo.
6. **Envío.** **ENVIAR ESTA COLA** — solo la sesión seleccionada. **ENVIAR TODAS** — todas las colas en orden. **Prueba en seco** no envía nada, solo muestra el plan en el registro. Los envíos reales piden confirmación y nombran las sesiones.

## Deshacer envío

Tras el envío, aparece un botón **Deshacer** durante 30 segundos. Devuelve el último prompt enviado a la cola como `pending` — salvo que la sesión ya lo haya procesado (entrega confirmada).

## Programación y límites

En el grupo «Envío»:

- **Enviar a las (HH:MM)** — vacío significa «ahora». Con una hora, la cola espera la próxima ocurrencia de esa hora (hoy, o mañana si ya pasó) y muestra una cuenta atrás en la barra de estado.
- **Esperar al reinicio del límite** — antes de cada prompt, SAISENT lee el texto del propio agente. Si dice «limit reached», la cola espera y se reanuda automáticamente cuando se libera el límite. Ni un solo prompt golpea una puerta cerrada.
- **Comprobar límites** — reescanear ahora.
- El campo de estado a la derecha muestra el estado en vivo: `limits: all agents free` o `claude-code: LIMITED until 09:22 (1h 05m remaining)`, en rojo. La cuenta atrás late una vez por segundo desde la caché; el disco solo se toca cuando la lectura está obsoleta o llega la hora de reinicio nombrada.

La hora de reinicio se toma de las propias palabras del agente. Si el agente no la indica, SAISENT escribe «reset time not stated» en lugar de inventar un marcador como «+5 horas».

### Cuándo se reinician los límites

Si el agente nunca nombra una hora de reinicio, SAISENT recurre a una regla por agente:

| Agente | Regla | Significado |
|---|---|---|
| Freebuff | `daily 10:00` | se reinicia cada día a las 10:00 |
| CodeNomad | `daily 03:00` | se reinicia cada día a las 03:00 |
| Claude Code | `rolling 5h` | 5 horas después del último prompt enviado |
| Antigravity | solo las palabras del agente | sin regla — lo que indique, o nada |

Una regla nunca anula una hora indicada por el agente; el agente es la autoridad sobre su propia cuota. Cualquier regla se puede sobrescribir en `SAISENT.json` bajo `quota_plans`, p. ej. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Por qué no se envían los siguientes

El envío es estrictamente secuencial y se detiene en el primer error real. El motivo aparece en la barra de estado (`stopped: window not found: ...`), en la fila del prompt en la lista y en el registro. El resto permanece `pending` — no se pierde.

Entre prompts hay una pausa `gap_ms` (por defecto 1500 ms), y el estado muestra `Waiting N.Ns before next`. Si un prompt se envió pero la sesión no se movió, se marca **sin confirmar** y permanece en la cola. «Enviado» solo se aplica a entregas confirmadas.

## Sensor de actividad

La columna «Sensor» responde a «¿puedo escribir ahora?».

- `busy` — la sesión escribió en su almacén hace menos de 20 segundos (el agente está a mitad de turno);
- `idle` — silencio de más de 20 segundos, el campo de entrada está libre.

De dónde viene:

| Agente | Fuente | Sensor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transcripción | última escritura en la transcripción |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabla `threads` | campo `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime de la base y su `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | última escritura en la transcripción |

La vivacidad es una comprobación aparte, no «el archivo en disco está fresco»:

- **Claude Code** — el PID de `~/.claude/sessions/<pid>.json` está vivo. El archivo sobrevive al cierre de la sesión; el PID no.
- **Freebuff** — `Freebuff.exe` está en ejecución. La base mantiene los hilos `open` incluso después de salir de la aplicación.
- **Antigravity** — `Antigravity.exe` está en ejecución **y** la conversación es fresca. La frescura sola no basta: este almacén guarda todas las conversaciones para siempre, y un editor cerrado solía llenar la lista con sesiones a las que ninguna tecla podía llegar.
- **CodeNomad** — la fila de la base no está archivada (`time_archived IS NULL`). Activas son solo las que están abiertas ahora.

## Dirección de entrega — columna «Dirección»

La barra lateral muestra exactamente cómo se golpeará cada sesión:

| Valor | Método | Fiabilidad |
|---|---|---|
| `cdp:28194` | Pegado vía depurador del agente | Exacto: campo leído antes y después, no se roba el foco |
| `CTRL+3` | Cambio de pestaña en la ventana del agente | Bueno, si el número de pestaña es correcto |
| `blind` | Sin puerto, sin número de pestaña | El prompt cae en el chat que esté abierto |

Ningún título de ventana contiene un nombre de sesión — `claude.exe` se llama «Claude», Antigravity se llama «Antigravity», Freebuff se llama «Freebuff Desktop». Por tanto, dirigirse por ventana es imposible, y `blind` significa exactamente lo que dice.

### CDP — la vía fiable

Si un agente se lanzó con `--remote-debugging-port`, SAISENT envía a través del depurador y no toca ni el foco ni el teclado. Esto significa:

- el texto se pega directamente en el campo de entrada, no «donde sea»;
- el campo se lee **antes** de pegar: si hay un mensaje a medio escribir, el envío se niega en vez de añadirse a la frase de otro;
- el campo se lee **después** de pegar: si no aterrizó, no enviamos.

Una negativa de CDP nunca cae en pulsaciones a ciegas. El transporte preciso acaba de decir que el momento no es el adecuado; martillar teclas por encima es exactamente la forma de arruinar el chat de otro.

El puerto se lee de `DevToolsActivePort` del agente, pero un archivo solo no basta — sobrevive a un lanzamiento anterior. SAISENT realmente se conecta al puerto antes de cada sondeo.

Activar el depurador para un agente (un reinicio mata lo que esté haciendo — SAISENT nunca lo hace por sí mismo):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Selectores de página (DOM real, 2026-08-05)

| Agente | Puerto | Campo de entrada | Lista de diálogos |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | ninguno | — | — |

Antigravity verificado: 16 botones, las etiquetas coinciden exactamente con los nombres de proyecto que muestra SAISENT (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — la selección de diálogo por nombre funciona con precisión.

CodeNomad es Electron sobre OpenCode; la carpeta de datos sigue llamándose `Plasticity`. La lista de sesiones en el DOM solo contiene las sesiones del **proyecto actualmente abierto**; una sesión de otro proyecto no se renderiza y SAISENT no la encontrará — el envío se niega en vez de golpear a ciegas el chat abierto.

Sobrescribir cualquier clave de perfil en `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Las sesiones se leen de `~/.local/share/opencode/opencode.db`, tabla `session`: nombre = `title`, proyecto = `directory`, las archivadas filtradas por `time_archived`, el sensor por `time_updated`. El único agente aquí cuya lista de sesiones son columnas simples, sin protobuf ni análisis.

Vivacidad — `CodeNomad.exe` está en ejecución. Sin número de pestaña: se dirige por nombre a través del depurador.

## Por qué no por título de ventana

Cada ventana `claude.exe` se llama «Claude». El nombre de sesión nunca aparece en el título, por lo que dirigirse por ventana es imposible — el nombre, el proyecto y el PID vienen del disco; la ventana solo se necesita para el foco.

## Confirmación de entrega

Chromium no responde a `WM_GETTEXT`, por lo que leer «¿aterrizó?» a través de Win32 es imposible — la antigua relectura para estos agentes siempre devolvía «sin confirmar». En su lugar, SAISENT espera a que se mueva el mismo archivo que vigila el sensor de actividad. ¿Se movió? Entregado. ¿No se movió en el tiempo asignado? El prompt se marca como enviado pero sin confirmar, y es visible en el registro. Esto no se considera un error: el agente puede simplemente no haber empezado su turno.

El envío se detiene en el primer error real (ventana no encontrada, foco perdido, portapapeles ocupado). Los prompts siguientes permanecen en la cola — no se pierden ni se envían a ciegas.

## Exportar e Importar

Los botones **Exportar** e **Importar** guardan/cargan las colas en formato JSONL. Cada línea es autosuficiente con su clave de sesión. El import fusiona sin pérdida de datos — los duplicados (misma clave + texto) se omiten.

## Archivos junto al programa

| Archivo | Contenido |
|---|---|
| `SAISENT.json` | ajustes: agentes, números de pestaña, tiempos de espera, geometría de ventana |
| `SAISENT_QUEUES.json` | colas por sesión, sobreviven al reinicio |
| `SAISENT.log` | registro del historial de envíos |

La cola nunca se limpia automáticamente. Si una sesión desaparece de la lista pero tiene elementos sin enviar, la cola permanece: los agentes se reinician, y una cola descartada silenciosamente es peor que una línea de más en un archivo.

## Ajustes ocultos

Edita `SAISENT.json` con el programa cerrado:

- `gap_ms` — pausa entre prompts dentro de un lote (por defecto 1500);
- `settle_ms` — pausa tras el cambio de pestaña y tras pegar (400);
- `confirm_seconds` — cuánto esperar la confirmación de entrega (10);
- `busy_seconds` — umbral del sensor «busy/idle» (20);
- `freebuff_roots` — raíces donde buscar `.freebuff/desktop-v2.db`, p. ej. `["V:\\___VAC\\__K\\__CODE"]`; profundidad limitada a 3;
- `submit` — tecla para enviar, por defecto `ENTER`.

## Limitaciones

- Las pestañas se abordan vía `Ctrl+1..Ctrl+9`. Una décima sesión es inalcanzable — `Ctrl+10` no existe, y SAISENT se niega en vez de adivinar.
- El número de pestaña es una suposición basada en el orden de lanzamiento. Haz tu primera pasada con **Prueba en seco**, luego en una sesión sin importancia.
- Antigravity no guarda los nombres de conversación como texto: la lista muestra el nombre de la carpeta de trabajo extraído de los metadatos.

## Pruebas

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
