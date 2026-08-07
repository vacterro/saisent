# SAISENT 4.0

Un panneau de contrôle qui colle du texte préparé à l'avance dans les sessions d'agents actuellement en cours sur cette machine.

Mettez le texte dans la file de la bonne session — SAISENT active la fenêtre de l'agent, bascule sur l'onglet de cette session, colle le texte en une seule opération et appuie sur Entrée.

## Démarrage rapide

```
START_SAISENT.bat
```

Nécessite Python 3.11+ sous Windows.

## Comment l'utiliser

1. **Agents.** Rangée du haut — cases à cocher : Claude Code, Freebuff, Antigravity, CodeNomad.
   Cochez un agent et ses sessions apparaissent dans le panneau de gauche.
2. **Sessions en direct.** À gauche, ce qui tourne réellement : nom de la session, numéro d'onglet, capteur d'activité et projet. La liste ne s'actualise pas seule, sauf si « toutes les N s » est activé — par défaut, l'actualisation se fait uniquement via le bouton **Actualiser**.
3. **Onglet.** SAISENT devine le numéro d'onglet à partir de l'ordre de lancement des sessions. Faux ? Saisissez le numéro manuellement dans `SAISENT.json`, clé `tabs` (clé de session de la forme `<agent>:<id>`, ex. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = ne pas changer d'onglet du tout.
4. **Texte.** Écrivez (ou collez) en bas à droite, appuyez sur **File** (ou Ctrl+Entrée). **Tout mettre en file** place le même texte dans chaque session en direct — remplace l'ancienne macro « CTRL+2, texte, CTRL+3, texte ».
5. **File.** L'ordre des lignes = l'ordre d'envoi. Faites glisser une ligne à la souris ou déplacez-la avec **Haut**/**Bas**. Chaque session a sa propre file. Double-cliquez sur une ligne (ou bouton **Modifier**) pour ramener le prompt dans le champ texte ; **Enregistrer la modification** le réécrit sur place, **Annuler** abandonne. Modifier un prompt déjà envoyé le remet dans la file — le texte de la ligne ne correspond plus à ce que la session a reçu. **Dupliquer** place une copie juste en dessous.
6. **Envoi.** **ENVOYER CETTE FILE** — session sélectionnée uniquement. **TOUT ENVOYER** — toutes les files à la suite. **Test à blanc** n'envoie rien, montre juste le plan dans le journal. Les vrais envois demandent confirmation et nomment les sessions.

## Annuler l'envoi

Après l'envoi, un bouton **Annuler** apparaît pendant 30 secondes. Il ramène le dernier prompt envoyé dans la file comme `pending` — sauf si la session l'a déjà traité (livraison confirmée).

## Planification et limites

Dans le groupe « Envoi » :

- **Envoyer à (HH:MM)** — vide signifie « maintenant ». Avec une heure, la file attend la prochaine occurrence de cette heure (aujourd'hui, ou demain si passée) et affiche un compte à rebours dans la barre d'état.
- **Attendre le reset du taux** — avant chaque prompt, SAISENT lit le texte de l'agent lui-même. S'il dit « limit reached », la file attend et reprend automatiquement quand la limite se libère. Aucun prompt ne frappe une porte verrouillée.
- **Vérifier les limites** — rescanner maintenant.
- Le champ d'état à droite montre l'état en direct : `limits: all agents free` ou `claude-code: LIMITED until 09:22 (1h 05m remaining)`, en rouge. Le compte à rebours tictaque une fois par seconde depuis le cache ; le disque n'est touché que lorsque la lecture est périmée ou que l'heure de reset nommée arrive.

L'heure de reset provient des propres mots de l'agent. S'il n'en énonce pas, SAISENT écrit « reset time not stated » plutôt que d'inventer un espace réservé comme « +5 heures ».

### Quand les limites se reset

Si l'agent ne nomme jamais d'heure de reset, SAISENT se rabat sur une règle par agent :

| Agent | Règle | Signification |
|---|---|---|
| Freebuff | `daily 10:00` | reset chaque jour à 10:00 |
| CodeNomad | `daily 03:00` | reset chaque jour à 03:00 |
| Claude Code | `rolling 5h` | 5 heures après le dernier prompt envoyé |
| Antigravity | mots de l'agent uniquement | pas de règle — ce qu'il indique, ou rien |

Une règle ne remplace jamais une heure énoncée par l'agent ; l'agent est l'autorité sur son propre quota. Toute règle peut être remplacée dans `SAISENT.json` sous `quota_plans`, ex. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Pourquoi les suivants ne partent pas

L'envoi est strictement séquentiel et s'arrête à la première vraie erreur. La raison apparaît dans la barre d'état (`stopped: window not found: ...`), sur la ligne du prompt dans la liste et dans le journal. Le reste reste `pending` — rien n'est perdu.

Entre les prompts, il y a une pause `gap_ms` (défaut 1500 ms), et l'état affiche `Waiting N.Ns before next`. Si un prompt a été envoyé mais que la session n'a pas bougé, il est marqué **non confirmé** et reste dans la file. « Envoyé » ne s'applique qu'aux livraisons confirmées.

## Capteur d'activité

La colonne « Capteur » répond à « puis-je taper maintenant ».

- `busy` — la session a écrit dans son store il y a moins de 20 secondes (l'agent est en plein tour) ;
- `idle` — silence de plus de 20 secondes, le champ de saisie est libre.

D'où il vient :

| Agent | Source | Capteur |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transcription | dernière écriture dans la transcription |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, table `threads` | champ `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime de la base et de son `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | dernière écriture dans la transcription |

La vivacité est une vérification distincte, pas « le fichier sur le disque est frais » :

- **Claude Code** — le PID de `~/.claude/sessions/<pid>.json` est vivant. Le fichier survit à la fermeture de la session ; pas le PID.
- **Freebuff** — `Freebuff.exe` tourne. La base garde les threads `open` même après la sortie de l'application.
- **Antigravity** — `Antigravity.exe` tourne **et** la conversation est fraîche. La fraîcheur seule ne suffit pas : ce store garde toutes les conversations pour toujours, et un éditeur fermé remplissait autrefois la liste de sessions qu'aucune frappe ne pouvait atteindre.
- **CodeNomad** — la ligne de la base n'est pas archivée (`time_archived IS NULL`). Seules les sessions actuellement ouvertes sont actives.

## Adresse de livraison — colonne « Adresse »

La barre latérale montre exactement comment chaque session sera touchée :

| Valeur | Méthode | Fiabilité |
|---|---|---|
| `cdp:28194` | Collage via le débogueur de l'agent | Exact : champ lu avant et après, le focus n'est pas volé |
| `CTRL+3` | Changement d'onglet dans la fenêtre de l'agent | Bon, si le numéro d'onglet est correct |
| `blind` | Pas de port, pas de numéro d'onglet | Le prompt atterrit dans le chat ouvert |

Aucun titre de fenêtre ne contient de nom de session — `claude.exe` s'appelle « Claude », Antigravity s'appelle « Antigravity », Freebuff s'appelle « Freebuff Desktop ». L'adressage par fenêtre est donc impossible, et `blind` veut dire exactement ce qu'il dit.

### CDP — le chemin fiable

Si un agent a été lancé avec `--remote-debugging-port`, SAISENT envoie via le débogueur et ne touche ni au focus ni au clavier. Cela signifie :

- le texte est collé directement dans le champ de saisie, pas « n'importe où » ;
- le champ est lu **avant** le collage : si un message à moitié écrit s'y trouve, l'envoi refuse plutôt que d'ajouter à la phrase d'un autre ;
- le champ est lu **après** le collage : s'il n'a pas atterri, nous n'envoyons pas.

Un refus CDP ne retombe jamais sur des frappes à l'aveugle. Le transport précis vient de dire que le moment est mauvais ; marteler des frappes par-dessus est exactement la façon de ruiner le chat d'un autre.

Le port est lu depuis `DevToolsActivePort` de l'agent, mais un fichier seul ne suffit pas — il survit à un lancement précédent. SAISENT se connecte réellement au port avant chaque sondage.

Activer le débogueur pour un agent (un redémarrage tue ce qu'il fait — SAISENT ne le fait jamais lui-même) :

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Sélecteurs de page (DOM réel, 2026-08-05)

| Agent | Port | Champ de saisie | Liste de dialogues |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | aucun | — | — |

Antigravity vérifié : 16 boutons, les étiquettes correspondent exactement aux noms de projets que SAISENT affiche (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — la sélection du dialogue par nom fonctionne précisément.

CodeNomad est Electron sur OpenCode ; le dossier de données s'appelle toujours `Plasticity`. La liste de sessions dans le DOM ne contient que les sessions du **projet actuellement ouvert** ; une session d'un autre projet n'est pas rendue, et SAISENT ne la trouvera pas — l'envoi refuse plutôt que de frapper à l'aveugle le chat ouvert.

Remplacer n'importe quelle clé de profil dans `SAISENT.json` :

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Les sessions sont lues depuis `~/.local/share/opencode/opencode.db`, table `session` : nom = `title`, projet = `directory`, les archivées filtrées par `time_archived`, le capteur par `time_updated`. Le seul agent ici dont la liste de sessions est de simples colonnes, sans protobuf ni parsing.

Vivacité — `CodeNomad.exe` tourne. Pas de numéro d'onglet : adressé par nom via le débogueur.

## Pourquoi pas par titre de fenêtre

Chaque fenêtre `claude.exe` s'appelle « Claude ». Le nom de session n'apparaît jamais dans le titre, donc l'adressage par fenêtre est impossible — le nom, le projet et le PID viennent du disque ; la fenêtre n'est nécessaire que pour le focus.

## Confirmation de livraison

Chromium ne répond pas à `WM_GETTEXT`, donc lire « est-ce que c'est arrivé » via Win32 est impossible — l'ancien read-back pour ces agents retournait toujours « non confirmé ». À la place, SAISENT attend que le même fichier que surveille le capteur d'activité bouge. Bougé ? Livré. Pas bougé dans le temps imparti ? Le prompt est marqué comme envoyé mais non confirmé, et c'est visible dans le journal. Ce n'est pas considéré comme une erreur : l'agent n'a peut-être pas encore commencé son tour.

L'envoi s'arrête à la première vraie erreur (fenêtre introuvable, focus perdu, presse-papiers occupé). Les prompts suivants restent dans la file — ils ne sont pas perdus et ne partent pas à l'aveugle.

## Export & Import

Les boutons **Exporter** et **Importer** sauvegardent/chargent les files au format JSONL. Chaque ligne est autonome avec sa clé de session. L'import fusionne sans perte de données — les doublons (même clé + texte) sont ignorés.

## Fichiers à côté du programme

| Fichier | Contenu |
|---|---|
| `SAISENT.json` | paramètres : agents, numéros d'onglets, délais, géométrie de la fenêtre |
| `SAISENT_QUEUES.json` | files par session, survivent au redémarrage |
| `SAISENT.log` | journal des envois |

La file n'est jamais nettoyée automatiquement. Si une session disparaît de la liste mais a des éléments non envoyés, la file reste : les agents sont redémarrés, et une file silencieusement jetée est pire qu'une ligne en trop dans un fichier.

## Paramètres cachés

Modifiez `SAISENT.json` pendant que le programme est fermé :

- `gap_ms` — pause entre les prompts dans un lot (défaut 1500) ;
- `settle_ms` — pause après le changement d'onglet et après le collage (400) ;
- `confirm_seconds` — combien de temps attendre la confirmation de livraison (10) ;
- `busy_seconds` — seuil du capteur « busy/idle » (20) ;
- `freebuff_roots` — racines où chercher `.freebuff/desktop-v2.db`, ex. `["V:\\___VAC\\__K\\__CODE"]` ; profondeur limitée à 3 ;
- `submit` — touche pour envoyer, défaut `ENTER`.

## Limitations

- Les onglets sont adressés via `Ctrl+1..Ctrl+9`. Une dixième session est inaccessible — `Ctrl+10` n'existe pas, et SAISENT refuse plutôt que de deviner.
- Le numéro d'onglet est une estimation basée sur l'ordre de lancement. Faites votre premier passage avec **Test à blanc**, puis sur une session sans importance.
- Antigravity ne stocke pas les noms de conversation en texte : la liste montre le nom du dossier de travail extrait des métadonnées.

## Tests

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
