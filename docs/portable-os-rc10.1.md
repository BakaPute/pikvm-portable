# PiKVM Portable OS 0.2.0-rc.10.1 — précontrôle sous pression mémoire

Branche `codex/portable-os`, base RC10 `2f2a484`. Correctif préparé localement :
aucun SSH, déploiement, reboot, changement de service/GPIO, montage ou accès aux
contenus des cinq ISO et du conteneur de secours pendant ce développement.

## Analyse des deux échecs réels

Les résultats fournis montrent un contrôle d'import réussi en 4,5 s puis, lors d'un
autre essai, dépassant 15 s ; le CLI MSD a aussi imprimé son état sans sortir avant
20 s. Avec 44 Mio disponibles, aucun swap et une activité PSI/journald signalée,
une forte contention est une explication plausible. Elle ne prouve pas la cause de
chaque attente, ni une défaillance Python, microSD ou matérielle. Une sortie complète
n'est pas un processus terminé : il peut encore attendre un thread, un verrou,
une ressource noyau ou la fin d'une écriture de sortie.

Vérification du code officiel au tag **KVMD v4.213** :

- [otgmsd](https://github.com/pikvm/kvmd/blob/v4.213/kvmd/apps/otgmsd/__init__.py)
  appelle `init(cli_logging=True, load_msd=True)`, vérifie le type MSD `otg`, puis
  lit `file`, `cdrom`, `ro` dans configfs pour une commande sans option de modification.
- [Initialisation commune](https://github.com/pikvm/kvmd/blob/v4.213/kvmd/apps/__init__.py)
  charge/merge les fichiers de configuration et valide le schéma.
- [Schéma dynamique](https://github.com/pikvm/kvmd/blob/v4.213/kvmd/apps/_scheme.py)
  charge la classe du plugin MSD et ses options lorsque `load_msd` est demandé.

Le CLI est donc disproportionné pour une simple observation de trois attributs.
La RC10 faisait également importer HTTP/SSL/HTML/AST dans le parent avant les
sondes enfants, et relançait Pillow lors de l'installation après l'avoir déjà testé.

## Correction

### Lecture du Drive 1

`pikvm-portable-drive-check.sh`, exécuté sous `/bin/sh`, lit uniquement
`mass_storage.usb1/lun.0/{file,cdrom,ro,removable,nofua}`. Deux observations doivent
être identiques. Le LUN doit être vide, amovible et les flags strictement binaires.
Les octets sont lus par `od` : un NUL ne peut pas disparaître dans une substitution
shell et être accepté comme un lecteur vide. Aucun nom d'ISO n'est imprimé.

Fichier absent, erreur de lecture, contenu mal formé, support attaché, changement
de configuration, réponse incomplète ou timeout font échouer le contrôle. Le parent
valide également le protocole de réponse et exige une sortie normale du processus.
Le délai est **10 s**, au lieu des 20 s de l'ancien CLI lourd ; aucune grâce n'est
appliquée à cette sonde. Aucun fallback ne force une éjection ou un reset.

Le contrôle implicite de configuration n'est pas supprimé : la sonde runtime
effectue une seule initialisation KVMD en lecture seule, avec `load_msd=True`, puis
vérifie `config.kvmd.msd.type == 'otg'`. Elle ne lance ni `otgmsd.main()`, ni service,
ni fonction de modification. Les fichiers/schémas/plugins sont toujours validés.

### Imports et pic mémoire

`pikvm_preflight_probe.py` vérifie Python **3.14.7**, les imports runtime et KVMD
**4.213**, `logging.FileHandler`, la configuration MSD, puis fournit des checkpoints.
Pillow reste testé dans un **autre processus**, immédiatement après le runtime et
avant les chargements lourds du parent : on évite de cumuler leurs graphes de modules.

Le parent diffère HTTP/SSL/HTML/AST/hashlib jusqu'aux fonctions qui les utilisent.
Le mode `check` ne charge plus le helper de rollback inutilisé. Le test Pillow n'est
plus relancé dans `oled_preflight()` au début de la mutation ; les relectures de
baselines et l'état actif de power-hold restent vérifiés avant l'installation.

Comparaison des interpréteurs lourds : RC10 en lançait trois pour `check`, quatre
pour `install` ; RC10.1 en lance deux pour chaque action (runtime/config puis Pillow).
Les contrôles d'intégrité shell/Python restent indépendants : leur répétition n'est
pas supprimée vu les anomalies de lecture précédemment observées.

### Délais et admission

Les imports gardent leur délai **nominal de 15 s**. Une seule grâce de **30 s** peut
être accordée, avec plafond total **45 s** pour chaque groupe, uniquement si :

1. des compteurs PSI CPU, mémoire ou I/O ont augmenté d'au moins 100 000 µs depuis
   le début du contrôle ;
2. le processus a produit une sortie ou comptabilise du CPU/des défauts majeurs ;
3. aucun nouvel événement OOM n'est observé ;
4. aucune grâce n'a déjà été accordée à cette étape.

Cette règle est une politique bornée du projet, pas une garantie de durée ni un
seuil recommandé par le noyau. Le seuil de 100 ms constitue un indice de contention,
sans prouver qu'elle explique toute l'attente. La présence d'un checkpoint ne prouve
pas non plus que le processus continuera : un blocage permanent échoue au plafond.
PSI absent/inexploitable, simple manque de RAM sans contention mesurée, erreur
d'import ou sortie non nulle n'activent pas de nouvelle tentative automatique.

Avant chaque groupe lourd, une marge `MemAvailable` ou cgroup finie inférieure à
**24 Mio** provoque un refus `RESOURCE_PRESSURE`, sans lancer le groupe. Ce plancher
est conservateur : il n'affirme pas que 24 Mio suffiront à tous les plugins. Les
44 Mio rapportés ne provoquent donc pas un refus automatique, mais la valeur est
réévaluée à chaque étape. Un état de ressources inconnu n'invente ni mémoire libre,
ni contention ; les délais nominaux et tous les contrôles matériels demeurent.

Le succès exige **tous les checkpoints attendus et un code retour 0**. Un module
qui termine prématurément l'interpréteur avec `exit(0)` n'est pas accepté comme un
groupe complet. Un nouveau compteur OOM pendant une étape invalide aussi le résultat,
même si son propre processus a terminé correctement.

| Résultat | Sens / action |
|---|---|
| `RESOURCE_PRESSURE` | Marge insuffisante, contention à l'expiration, `MemoryError` ou OOM observé ; réduire la charge et examiner les mesures |
| `TIMEOUT_INCONCLUSIVE` | Délai dépassé sans preuve de contention ; état non validé, pas un diagnostic de corruption |
| `INTEGRITY_FAILED` | Hash différent du paquet local attendu ; arrêter la migration et enquêter |
| `CHECK_FAILED` | Commande/import/configuration a renvoyé une erreur ; consulter stderr |
| `PROBE_INCOMPLETE` / `HARDWARE_UNKNOWN` | Réponse non probante ; aucune acceptation optimiste |
| `CLEANUP_FAILED` | L'arrêt des enfants n'est pas confirmé ; conserver PID et journaux avant toute nouvelle tentative |

Les budgets nginx (15 s), services (10 s), versions et intégrité (10 s par commande)
restent inchangés. Il n'existe toujours aucun timeout global opaque ni option pour
ignorer une vérification échouée. Les deux groupes ne sont jamais parallélisés.

## Diagnostic conservé après expiration

Sous `/tmp/pikvm-portable-preflight-*/` :

- `steps.log` : étapes horodatées, commande exacte, budget, PID, attentes, grâce,
  détail de timeout et résultat du nettoyage ;
- `NN-ETAPE.stdout` / `.stderr` : sorties partielles ;
- `resources.jsonl` : mémoire/PSI/compteurs avant et après, puis toutes les 5 s
  d'attente et à l'expiration. Lectures bornées de `/proc`, sans `ps` ou `systemctl`
  supplémentaire pour cet échantillonnage.

Le rapport inclut MemAvailable/swap, PSI CPU/mémoire/I/O, défauts majeurs/reclaim,
compteurs OOM, limites et événements cgroup avec ancêtres, état/RSS/HWM/threads/wchan
du parent et de la sonde, ainsi que jusqu'à huit enfants directs. Les checkpoints
d'import/configuration indiquent aussi RSS et pic HWM du worker sous Linux.
Les 4 Kio finaux de chaque sortie figurent dans le détail du timeout.

PSI décrit des temps de blocage dus à la contention, pas une preuve d'une panne
physique. Voir la [documentation PSI du noyau](https://docs.kernel.org/accounting/psi.html).
Un `wchan` d'attente de thread diffère d'une attente I/O ; les valeurs sont des
observations à interpréter, jamais un verdict automatique sur la microSD.

Les sondes sont placées dans un groupe de processus distinct. En échec : TERM,
grâce de nettoyage de 1 s, puis KILL du groupe entier même si son leader est déjà
sorti, et confirmation bornée de fin. Un processus noyau non interruptible peut
résister : le diagnostic et le PID sont conservés, le précontrôle reste en échec.
Ne pas accumuler des tentatives si un tel processus subsiste.

Les traces sont privées dans un répertoire temporaire ; aucun cookie ou mot de
passe SSH n'est demandé/collecté et aucune configuration complète n'est dumpée.
Les erreurs natives de validation peuvent néanmoins contenir des chemins ou
valeurs : examiner ces traces avant partage. Elles survivent à l'arrêt de la commande, **pas nécessairement à un
reboot**. Les copier hors du Pi après accord ; ne pas accumuler indéfiniment des
traces sur un `/tmp` en tmpfs lorsqu'il reste peu de RAM.

## Réduire la pression mémoire — étude, aucune modification automatique

Ordre proposé pour une validation autorisée sur le Pi :

1. Mesurer la mémoire par service, les limites cgroup et PSI dans les nouvelles
   traces ; distinguer MemAvailable, RSS privé, mémoire partagée et caches.
2. Fermer les sessions/flux vidéo et terminaux supplémentaires via leurs commandes
   normales, terminer les transferts en cours ; attendre une charge stable puis
   relancer un seul précontrôle. Ne pas arrêter power-hold, bouton, KVMD ou journald.
3. Rechercher un service qui croît au fil du temps avec le diagnostic passif
   `pikvm-portable-perf`. Les mesures RC10.1 doivent qualifier la cause avant de
   limiter une unité ou de désactiver une fonction.
4. Étudier séparément zram si nécessaire : vérifier le support du noyau installé,
   les algorithmes présents et la marge CPU, définir une taille/mémoire bornée et
   mesurer CPU, taux de compression, latences KVM et OOM. Zram stocke les pages
   comprimées en RAM ; ce n'est pas de la RAM gratuite. Une expérimentation sans
   backing device évite le writeback microSD. Rien n'est créé ni activé ici.
   [Documentation zram du noyau 6.12](https://docs.kernel.org/6.12/admin-guide/blockdev/zram.html).

Aucun ajout de swap microSD, `drop_caches`, changement de swappiness, modification
du partage mémoire GPU/boot, limite mémoire imposée aux services ou neutralisation
de protection d'alimentation. Le message journald de pression n'est pas une raison
pour désactiver les journaux nécessaires au diagnostic.

## Tests et limites des mesures

Environnement local : Windows, Python 3.12.14, nginx de validation réel. Tests de
pression : valeurs `/proc`/cgroup simulées et processus synthétiques lents ; aucune
saturation volontaire de la RAM hôte ou lecture d'ISO utilisateur.

Bilan final : **227 tests Python réussis sur 233, 6 ignorés sous Windows**,
**23 tests JavaScript réussis**. Syntaxe Python/Bash et fins de ligne Linux vérifiées.
Les cas ignorés couvrent sockets Unix, symlinks, flock/héritage et RLIMIT_AS.
La CI Linux Python 3.11/3.14 est préparée, sans exécution distante revendiquée.

Les régressions couvrent les commandes lentes qui finissent, les sorties complètes
sans fin, la grâce unique conditionnelle, l'absence de grâce sans PSI, les erreurs
non nulles, OOM observé, marge mémoire/cgroup insuffisante avant lancement, compteurs
remis à zéro, ressources absentes, nettoyage incertain, configfs absent/mal formé/
attaché/instable, NUL dans les attributs, protocole incomplet et plugin non `otg`.
Les imports différés, l'absence de helper inutile et les chemins installés sont testés.
Un test de limite mémoire réelle `RLIMIT_AS` reste réservé au runner Linux ; il
limite exclusivement un enfant synthétique, sans mettre l'hôte en OOM.

```powershell
$env:NGINX_BINARY = "$PWD/private/nginx-validation/nginx-1.26.3/nginx.exe"
python -B -m unittest discover -s tests -v
node --test tests/portable-ui.test.mjs
```

Mesure de démarrage locale, trois processus frais par version : **71 → 25 modules
supplémentaires**, ensemble résident après chargement d'environ **22,5 → 17,3 Mio**.
Le cache disque n'est pas contrôlé ; les workers et services ne sont pas inclus.
Ce résultat Windows ne chiffre ni le gain RSS ni le délai du Pi. Données brutes :
`docs/performance/rc10.1-startup-local.json`. Les nouvelles traces du Pi permettront
de vérifier la baisse réelle et l'adéquation des budgets. Aucune CI distante ou
validation de Python 3.14/KVMD sur cette machine Windows n'est revendiquée.

## Mettre à disposition RC10.1 et reprendre le contrôle — après autorisation

Ne pas remplacer le stage RC10 ni ses sauvegardes. Construire et transférer la
nouvelle archive ; mot de passe SSH saisi seulement aux invites :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python -B scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
$PiKvmHost = Read-Host 'Adresse actuelle du PiKVM'
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.10.1.tar.gz private/pikvm-portable-os-0.2.0-rc.10.1.tar.gz.sha256 "root@${PiKvmHost}:/tmp/"
ssh @sshOptions "root@${PiKvmHost}"
```

Sur le Pi, après accord de transfert/extraction et de contrôle en lecture seule :

```bash
set -euo pipefail
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.10.1.tar.gz.sha256
stage=$(mktemp -d /tmp/portable-rc10.1.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.10.1.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
bash install-portable-os.sh check 2>&1 | tee /tmp/portable-rc10.1-check.log
```

Ce contrôle ne stoppe aucun service et n'attache/éjecte/monte aucun support. Les seuls
fichiers écrits sont le stage et ses journaux temporaires. Ne pas lancer `install.sh`,
ni une réparation Python quand les checksums sont conformes, ni un reset USB.
Si une ressource ou un état matériel bloque encore, conserver le dossier de journal
complet ; ne pas considérer le timeout comme une autorisation de poursuivre.

Après réussite, examiner les valeurs MemAvailable/HWM, les éventuels événements
`PRESSURE_GRACE`, le retour normal des sondes, les deux lecteurs et GPIO17 HIGH par
lecture seule. Les performances sous charge et les marges doivent être validées
sur le Pi avant de conclure à la stabilité.

L'installation reste une **autorisation distincte**. Après cette autorisation,
avec les préconditions d'éjection/libération des volumes déjà prévues par RC10 :

```bash
rw
if bash "$stage/install-portable-os.sh" install; then
    ro
else
    status=$?
    ro
    printf 'Échec (%s) ; conserver sauvegarde et journaux.\n' "$status" >&2
    exit "$status"
fi
```

La transaction et les sauvegardes RC10 sont conservées. Les deux nouvelles sondes
sont copiées à côté du superviseur dans `/usr/local/lib/pikvm-portable` ; le mode
`check` depuis le stage et le précontrôle installé utilisent les mêmes fichiers.
Les baselines/refus de correctifs locaux inconnus ne sont pas assouplis.

Sans installation, revenir à RC10 consiste simplement à réutiliser son stage
conservé ; aucun fichier système n'a été remplacé par un `check`. Après installation,
remplacer DATE-ID par la sauvegarde imprimée lors de **cette** mise à jour :

```bash
rw
if python3 -B "$stage/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID; then
    ro
else
    status=$?
    ro
    printf 'Restauration échouée (%s) ; conserver les sauvegardes.\n' "$status" >&2
    exit "$status"
fi
```

Le retour arrière restaure les fichiers applicatifs et états de services sauvegardés,
sans toucher aux images. Il réintroduit les limites de précontrôle de RC10. Aucun
redémarrage matériel n'est demandé. La procédure complète de maintenance et les
risques matériels résiduels restent documentés dans `portable-os-rc10-audit.md`.

## Fichiers modifiés

- `scripts/pikvm_preflight.py` : supervision, admission, télémétrie, protocole et
  séquencement des vérifications ; nouvelles sondes `pikvm_preflight_probe.py` et
  `pikvm-portable-drive-check.sh`.
- `scripts/pikvm-portable-install` : imports différés, suppression du helper inutile
  en mode check et de la répétition Pillow, installation des nouvelles sondes.
- `tests/test_preflight_rc10_1.py`, tests précontrôle/archives existants et CI :
  scénarios de ressources, blocage, configuration, nettoyage et non-régression.
- Empaqueteur, `.gitattributes`, version HTML/package, README, cette notice et
  mesure de démarrage locale : préparation de `0.2.0-rc.10.1`.

Les lecteurs GPIO, OLED/bouton, alimentation, services systemd, moteurs KVM,
transfert XFER et API SHARE/Wi-Fi restent identiques à RC10. Les données utilisateur
ne font partie ni du mapping de cette correction, ni de l'archive.
