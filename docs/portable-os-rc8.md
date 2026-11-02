# PiKVM Portable OS 0.2.0-rc.8 — lecteur physique GPIO18

Candidate locale de `codex/portable-os`, basée sur RC7 `db1e079`. Aucun accès SSH,
diagnostic matériel ou déploiement effectué pendant ce développement.

## Audit et décision

Mesures réelles communiquées par l'utilisateur : bouton **14,83–19,23 % d'un cœur**
sur 30 s, statut OLED environ 4,1 %, ustreamer 4 % idle / 35,33 % en KVM. Ces valeurs
ne constituent pas une mesure RC8. La baisse CPU réelle reste à relever sur le Pi.

Lectures présentes dans le dépôt :

- `pikvm-power-hold-startup` configure le bouton puis surveille son relâchement à
  50 ms durant le démarrage, avec debounce de relâchement 300 ms. Ce service et ses
  opérations GPIO17/18 sont **intégralement inchangés**. Il ne s'agit pas de la boucle
  permanente RC7 une fois le démarrage terminé normalement.
- `pikvm-button-menu.configure_async_readers()` crée un seul `ButtonReader` qui
  exécute `physical_button_down()` puis attend 40 ms. Les boucles menu (40/50/60/120 ms,
  boucle principale 50 ms et délais 200 ms) lisent son échantillon en mémoire : elles
  ne multiplient pas le nombre de commandes pinctrl. Le maximum permanent est
  `1 / (40 ms + durée pinctrl)`, donc environ 25 processus/s, même idle.
- Aucun autre lecteur permanent GPIO18 trouvé dans les scripts/services du dépôt.
  Cela n'exclut pas un service local absent du dépôt : prévoir l'inventaire passif.

La voie événements libgpiod est étudiée mais **non activée**. Le noyau accorde une
réservation exclusive à une line request. Les événements exigent une direction
INPUT ; le mode as-is évite de changer la direction mais n'autorise pas ces flags
d'événements. Les lectures pinctrl/MMIO d'autres services ne sont pas forcément
visibles comme consommateurs dans gpioinfo : une ligne « unused » ne prouve pas
à elle seule l'absence d'interaction. Aucun gpioget/gpiomon, gpio export, module
chargé, changement d'overlay ou installation de bibliothèque n'est effectué.
[Référence noyau GPIO v2](https://docs.kernel.org/6.12/userspace-api/gpio/gpio-v2-get-line-ioctl.html).

La voie retenue est une **lecture persistante et non exclusive** de `/dev/gpiomem`.
Le driver expose la fenêtre de registres GPIO sans réserver de ligne ; le mapping
est ouvert O_RDONLY et ACCESS_READ, offset zéro. Le code lit uniquement le mode
GPIO18 dans GPFSEL1 (0x04, bits 24–26) et son niveau dans GPLEV0 (0x34, bit 18), via
une vue native 32 bits en lecture seule. Aucun registre n'est écrit, ni à l'ouverture,
ni à la fermeture. Aucun `/dev/mem` de secours. La polarité historique HIGH=appuyé
reste identique. [Driver officiel Raspberry Pi](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/drivers/char/raspberrypi-gpiomem.c),
[registre GPLEV0, documentation BCM2835](https://datasheets.raspberrypi.com/bcm2835/bcm2835-peripherals.pdf).

## Validation avant sélection

Le chemin rapide n'est sélectionné qu'après les contrôles passifs suivants :

1. Device Tree contient exactement les identifiants Zero 2 W et BCM2837 attendus ;
   userspace little-endian. Aucun autre modèle n'est deviné.
2. `/dev/gpiomem` est un périphérique caractère non symlink ; major/minor sont
   retrouvés dans sa classe sysfs connue, puis revérifiés sur le descripteur ouvert.
3. Un seul device du driver reconnu expose la compatibilité legacy GPIO et une
   unique fenêtre **0x3f200000–0x3f200fff**, déclarée ressource mémoire. Une topologie
   différente, même potentiellement valide, est refusée plutôt que devinée.
4. `pinctrl get 18`, avant/après ouverture, confirme **input / pull-down** et un
   niveau stable concordant avec la lecture MMIO. Deux commandes seulement lors
   d'une sélection réussie. Une transition pendant ce contrôle fait refuser le
   chemin rapide ; recommencer le diagnostic bouton relâché.
5. À chaque lecture, GPIO18 doit toujours être en entrée. Une permission manquante,
   identité inattendue, erreur de lecture ou changement de mode n'est jamais
   converti en appui.

[Device Tree officiel Zero 2 W](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/arch/arm/boot/dts/broadcom/bcm2837-rpi-zero-2-w.dts).

Si la sélection initiale échoue, RC8 garde **pinctrl à 40 ms**, avec motif visible.
Le fallback vérifie maintenant aussi son code retour et input/pull-down ; une
configuration inconnue produit None, sans tentative de réparation. Il ne promet
pas de baisse CPU. Après sélection MMIO, une panne ne déclenche pas une succession
de réouvertures ou de processus : le lecteur signale None et réessaie ses lectures
du mapping au rythme normal. Il ne prolonge pas le dernier HIGH.

## Gestes et ressources

- Cadence de surveillance physique maintenue à 40 ms, plus coût du lecteur ; pas
  de polling ralenti idle ni d'inversion de polarité. Ce polling n'est pas une
  garantie de détection de pulses plus courts que sa période.
- Les délais, debounces, compteurs et actions des menus restent les mêmes.
- Une erreur même brève est mémorisée jusqu'à sa consommation par le menu. Elle
  annule un maintien physique ; le verrou logique existant impose ensuite un
  relâchement confirmé avant un nouvel appui. Un trou d'échantillonnage supérieur
  à 300 ms est également mémorisé, même si la première lecture récupérée est HIGH.
- Le lecteur GPIO ne fabrique aucun événement virtuel. Le contrôleur logique,
  la priorité/collision physique-virtuel, les permissions, CSRF et le bail **800 ms**
  sont conservés. Un GPIO absent n'empêche pas un geste virtuel sain ; il ne
  renouvelle jamais son bail.
- Le thread est arrêté avant libération de la vue/mapping/descripteur. Si un appel
  noyau restait bloqué, aucun unmap concurrent n'est tenté. Pas de thread ajouté,
  de backlog d'événements ni de log par échantillon.
- Le heartbeat existant expose `input.backend`, `interval_ms`, `samples`, `errors`,
  `sample_age_ms` et le motif de fallback. L'API OLED transmet déjà ce diagnostic ;
  aucune nouvelle API ni modification des règles d'accès.

## Tests et comparaison

Tests simulés : accès réellement read-only à un fichier de registres, masque
GPIO18 sans confusion avec GPIO17, refus de mode sortie/biais inconnu/retour
pinctrl non nul, identification plateforme/fenêtre, absence/permission/timeout,
750 lectures sans commandes continues, rebond isolé, appuis 120 ms/2/3/5 s,
erreur transitoire et persistante, relâchement, collision physique/virtuel,
maintien virtuel avec GPIO absent et vraie expiration de bail, fermeture des
ressources. Les tests historiques OLED, KVM, SHARE, install/restore restent requis.

Bilan local : **146 tests Python réussis, 2 ignorés sous Windows** (148 au total),
**22 tests JavaScript réussis**. Python local 3.12.14 : le mapping d'un vrai device,
les GPIO réels, les compteurs cgroup du Pi et Python 3.14/Linux restent à valider.
La CI Linux est préparée mais aucun résultat distant n'est revendiqué. Syntaxe
des installateurs, manifeste, scripts LF et SHA256 de l'archive sont vérifiés.

| Mesure | RC7 | RC8 |
| --- | --- | --- |
| CPU bouton sur Pi, communiqué par utilisateur | 14,83–19,23 % / cœur | **Non mesuré** |
| Lecteur permanent, sélection rapide réussie | jusqu'à ~25 processus pinctrl/s | 0 processus pinctrl en régime établi |
| Test 750 lectures, lecteur rapide simulé | chemin RC7 : une commande/lecture | 2 contrôles initiaux, 0 commande/lecture |
| Intervalle d'échantillonnage | 40 ms après lecture | 40 ms après lecture |
| Wakeups du sampler | jusqu'à ~25/s | jusqu'à ~25/s, conservés pour la précision |
| Bail virtuel | 800 ms | 800 ms |

Les forks, leurs exécutions et leurs réveils sont supprimés sur la voie rapide ;
le sampler conserve ses réveils. Aucun chiffre de CPU ou de latence Windows n'est
présenté comme une mesure du Pi. Le driver, les permissions et le mapping réel
restent à confirmer sur l'installation cible avant de revendiquer le gain.

Le diagnostic `pikvm-portable-perf` ajoute les compteurs **cgroup v2** du service
(cpu.stat usage_usec, memory.current, pids.current), en conservant le détail
processus/threads. Le CPU cgroup inclut les petits pinctrl terminés entre deux
échantillons ; préférer ce compteur pour la comparaison. Un compteur inaccessible,
reset ou un cgroup recréé reste non comparable (null). Les lectures sont passives,
sans activer CPUAccounting. En cgroup v1, ne pas présenter le seul CPU du processus
parent comme le CPU total du service ; recueillir un compteur de service compatible
avant de conclure. `memory.current` n'est pas un PSS : les PSS restent séparés.

## Vérifications cibles en lecture seule — à lancer après autorisation de transfert

Depuis le stage RC8 vérifié, sans `rw`, sans redémarrage de service :

```bash
python3 -B scripts/pikvm_gpio.py --diagnose
systemctl show pikvm-button-menu.service pikvm-power-hold.service -p Id -p MainPID -p ActiveState -p SubState -p ControlGroup
command -v gpioinfo >/dev/null && timeout -k 1s 5s gpioinfo
```

La dernière commande est optionnelle et passive ; son absence n'installe rien.
Ne pas utiliser `gpioget`, `gpiomon`, `gpioset` ou `pinctrl set`. Vérifier le résultat
`backend: gpiomem-readonly`, les propriétés retournées, puis les consommateurs
existants ; si fallback, conserver le motif et ne pas modifier les permissions,
le noyau ou le GPIO pour forcer le passage. Si une hypothèse matérielle reste
inconnue, examiner ces résultats avant installation.

Pour **RC7 encore en service**, utiliser le nouvel outil RC8 du stage, sans installer :

```bash
python3 -B scripts/pikvm-portable-perf --label RC7-button-idle --duration 30 --interval 5 > /tmp/rc7-button-idle.jsonl
```

Relever `services["pikvm-button-menu.service"].cgroup.cpu_percent_one_core` dans
les six intervalles après l'instantané initial. Garder les mêmes clients, activité
KVM, pages OLED et réseau pour RC8. Répéter plusieurs mesures idle puis les mêmes
maintiens non sensibles, et une mesure KVM distincte. Après mise à jour :

```bash
python3 -B scripts/pikvm-portable-perf --label RC8-button-idle --duration 30 --interval 5 > /tmp/rc8-button-idle.jsonl
cat /run/pikvm-oled/button.json
```

Vérifier `input.backend`, l'absence d'erreurs/ancienneté croissante et de redémarrages
(`systemctl show pikvm-button-menu.service -p NRestarts`). Les compteurs CPU doivent
être disponibles et comparables ; conserver les JSONL même si le gain est nul.
L'outil n'accède ni au GPIO ni aux lecteurs USB ; sa propre charge est indiquée.

## Livraison et installation RC8

Fichiers fonctionnels : nouveau `scripts/pikvm_gpio.py`, branchement/fermeture dans
`pikvm-button-menu`, sampler/diagnostic dans `pikvm_oled.py`, métriques cgroup dans
`pikvm-portable-perf`. Installateurs Portable et global embarquent/sauvegardent le
module. Baselines RC7, empaqueteur, version, tests et documentation accompagnent
le changement. Aucun changement de `pikvm-power-hold-startup`, unités systemd,
OLED statut, KVM natif, authentification, images ou données SHARE.

Sur Windows :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python -B scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
$PiKvmHost = Read-Host 'Adresse IP actuelle du PiKVM'
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.8.tar.gz private/pikvm-portable-os-0.2.0-rc.8.tar.gz.sha256 "root@${PiKvmHost}:/tmp/"
ssh @sshOptions "root@${PiKvmHost}"
```

Mot de passe uniquement aux invites. Sur le Pi, **après autorisation**, préparer
le stage, vérifier puis effectuer les diagnostics précédents avant modification :

```bash
set -e
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.8.tar.gz.sha256
stage=$(mktemp -d /tmp/pikvm-portable-os-rc8.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.8.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
printf 'Stage RC8 : %s\n' "$stage"
python3 -B scripts/pikvm-portable-install check
```

Les empreintes officielles RC7 sont reconnues ; les correctifs locaux inconnus
restent refusés. Ne copier ni le menu seul ni la bibliothèque OLED seule : ils
dépendent du nouveau module GPIO. Après résultats compatibles et autorisation
explicite de déploiement :

```bash
rw
if python3 -B "$stage/scripts/pikvm-portable-install" install; then
    ro
else
    status=$?
    ro
    printf 'Installation échouée : code %s ; examiner rollback et journaux.\n' "$status" >&2
    exit "$status"
fi
```

Conserver le chemin **Sauvegarde : /root/pikvm-portable-os-backups/…** imprimé.
Le processus d'installation existant ne redémarre pas le matériel ni le power-hold.
Contrôler le backend réellement choisi après redémarrage applicatif : si fallback,
la baisse CPU n'est pas attendue. Tester d'abord gestes non sensibles, libération,
OLED virtuel et KVM ; ne pas déclencher d'arrêt pour un simple benchmark.

## Retour RC7

Restaurer la sauvegarde créée par cette installation RC8 : elle contient l'état
RC7 antérieur et ses correctifs connus. Remplacer DATE-ID par le chemin imprimé :

```bash
rw
if python3 -B "$stage/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID; then
    ro
else
    status=$?
    ro
    printf 'Restauration échouée : code %s ; conserver les sauvegardes.\n' "$status" >&2
    exit "$status"
fi
```

Redéfinir `stage` si le shell a été fermé ; le script installé peut aussi restaurer
si le stage a disparu. Le manifeste est vérifié avant restauration. La fermeture
du mapping ne change aucun état électrique. Recharger Portable OS après rollback.
