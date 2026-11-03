# PiKVM Portable OS 0.2.0-rc.10 — audit, intégrité et reprise

Branche `codex/portable-os`, base RC9 `7745f4e`, correctif RC9.1 conservé.
Travail local du 3 novembre 2026. Aucun SSH, déploiement, redémarrage, accès GPIO,
montage Linux ni lecture/modification des ISO réelles pendant cette mission.

**Candidate pour validation progressive, pas certification de fiabilité matérielle.**
Le redémarrage inattendu et l'anomalie transitoire de lecture de `copyreg.py` restent
inexpliqués. Les tests locaux ne permettent pas de déclarer la microSD défectueuse,
ni d'écarter alimentation, RAM, contrôleur, cache, noyau ou logiciel.

## 1. Faits, causes et hypothèses

Les mesures matérielles ci-dessous proviennent du rapport utilisateur, sans nouvelle
mesure sur le Pi : cinq ISO récupérées et comparées intégralement, conteneur de secours
conservé, GPIO17 HIGH, ancien journal de boot indisponible. Le fichier Python signalé
binaire a ensuite retrouvé son contenu officiel, cinq hashes stables et un paquet
Python sans fichier altéré. Une corruption persistante de ce fichier n'est donc pas
démontrée aujourd'hui. Ne pas lancer une réparation ou mise à jour globale par réflexe.

| Défaut confirmé dans le code antérieur | Gravité | Conséquence | Correction RC10 / preuve |
|---|---|---|---|
| `command_import()` appelle `create_image()`, qui supprime la source | Critique | Perte du seul conteneur de secours après import, même partiel | Aucun reset après import ; `reset` refuse ; création exclusivement `xb` si image absente ; tests source conservée, répétition et erreurs |
| Copie publiée par `replace()` sans relecture intégrale | Critique | Écrasement concurrent, destination non vérifiée | SHA256 source/destination, taille, fsync, publication `link()` sans remplacement ; collision injectée |
| JSON `connected` non corrigé lorsque LUN vide | Élevée | Interface incohérente, opérations bloquées | Observation configfs ; contrôleur lié distinct de support attaché ; état inconnu explicite |
| Statut API relance Python et attend jusqu'à 10 s | Élevée | Import Python lent/corrompu bloque des lectures répétées | Module partagé en processus, aucun sous-processus ni attente de verrou pour le statut |
| `.part` seul bloque tous les dossiers | Élevée | Bibliothèque inutilisable après crash | Verrou réel distingue activité ; `.part` inventorié mais ne bloque plus globalement ; `.incomplete` natif reste bloquant |
| Polling `done` appelle automatiquement une API native modifiant Drive 0 | Élevée | Mutation sur simple consultation | Suppression de cette action ; régression navigateur exige zéro POST natif |
| Import/arrêt forcent éjection et déconnexion globale | Élevée | Accès exFAT prématuré, interruption de Drive 1/HID | Import/stop exigent LUN vide ; aucun reset USB ; activation globale uniquement après confirmation, autres LUN vides et aucune réservation SHARE |
| Verrous dossiers et transfert indépendants | Élevée | Remontage RO concurrent avec une copie | Verrou commun non bloquant, en plus du verrou transfert ; helpers héritent des descripteurs de verrou ; maintenance utilise les mêmes verrous |
| Wi-Fi/API historique dépend seulement du proxy pour l'authentification | Élevée | Accès local sans session, CSRF non vérifié par le backend | Auth KVMD et règles CSRF SHARE réutilisées pour chaque requête ; proxy écrase l'origine de confiance ; clients historiques adaptés |
| HTTP historique mono-thread ; autres serveurs sans plafond de threads | Élevée | Statut bloqué par scan/requête lente, ressources non bornées | Wi-Fi multithread plafonné à 8 ; SHARE et Portable également 8 ; mutations Wi-Fi sérialisées ; test HTTP concurrent réel localhost |
| Configuration Wi-Fi écrite directement, priorité interpolée, backup au nom non unique | Élevée | Configuration tronquée, injection de lignes, sauvegarde écrasée | Validation priorité/SSID/WPA, remplacement atomique synchronisé, backups privés uniques, mot de passe WPA sur stdin |
| Démarrage Wi-Fi pouvait échouer avec `true` final | Moyenne | Succès artificiel | Échec explicite si les deux unités de secours échouent |
| Appels I2C batterie sans timeout | Moyenne | Threads bloqués indéfiniment | Budget 2 s par lecture ; absence/erreur renvoyée, aucune écriture du registre |
| Sauvegardes applicatives copiées sans fsync des données/répertoires | Élevée | Manifest durable mais sauvegarde non durable après coupure | fsync des copies et répertoires, comparaison source/copie, budget disque avant arrêt de services |
| Arrêt/redémarrage historique sans garde de stockage côté backend | Élevée | Arrêt pendant copie ou volume attaché malgré un ancien état UI | Garde passive commune : transfert actif/inconnu, deux lecteurs, réservation SHARE, upload natif ; avant action physique autorisée ou requête Web authentifiée |
| Bootstrap matériel utilisable par erreur comme mise à jour ; `pacman -Sy` implicite | Élevée | Reconfiguration électrique/boot, mise à jour partielle | `install.sh` refuse sans option explicite d'installation initiale ; aucune installation automatique de paquet manquant |
| Hotspot imprime sa clé à l'activation | Moyenne | Secret susceptible d'aboutir dans les journaux | Suppression de cet affichage ; erreurs de commandes désormais propagées |

Le TypeError `HTMLSelectElement.type` est corrigé en RC9.1 et conservé. Ce défaut
frontend n'est pas la cause du redémarrage, des octets binaires de `copyreg.py` ou
du conteneur destructivement recréé : ces incidents ont des chemins distincts.

## 2. Architecture et inventaire examinés

```
Navigateur : Portable OS / KVM natif / interfaces historiques
  nginx, auth_request KVMD, origine de confiance écrasée
    9878 Portable API -> services, journaux, OLED logique
    9877 SHARE API -> contrôleur exclusif Drive 1 / bail / loop exFAT
    9876 Wi-Fi API -> réseau, dossiers ISO, commandes transfert
      pikvm-image-folders -> verrou commun MSD -> métadonnées ISO
      pikvm-usb-transfer -> verrou commun MSD + verrou transfert
        source exFAT RO -> copies temporaires -> SHA256 -> publication
        journal durable PIMSD ; progression volatile /run
  OLED et bouton -> même framebuffer natif / logique / garde stockage
  power-hold historique -> GPIO17 HIGH, non remplacé par cette migration
```

Revue des scripts `pikvm-usb-transfer`, `pikvm-image-folders`, `wifi-wizard-api`,
`pikvm-hotspot`, `pikvm-share-api`, `pikvm-share-remount`, `pikvm-share-install`,
`pikvm-portable-api`, `pikvm-portable-install`, `pikvm-portable-package.py`,
`pikvm_preflight.py`, scripts de précontrôle/diagnostic/réparation/performance,
`pikvm_gpio.py`, `pikvm_oled.py`, OLED/bouton, power-hold et auto-shutdown.
Les installateurs racine, configurations nginx des quatre extensions, unités et
dépendances systemd, pont KVM, module registry, poller, stockage, réseau,
alimentation et dialogues Web ont été examinés avec leurs tests.

Les dépendances ajoutées sont exclusivement celles de la bibliothèque standard.
Pillow/luma restent utilisés par le rendu existant ; aucune bibliothèque GPIO
exclusive, base de données ou framework Web supplémentaire n'est ajouté.
Le gros doublon de copie/transfert et le renommage historique indépendant ont été
remplacés par les primitives partagées. Le réseau conserve son service existant.

Le moteur natif KVMD, ses transports vidéo/HID, le terminal natif, les paramètres
USB système, les services d'alimentation et les données ne sont pas remplacés.
Le code GPIO18 optimisé et le moteur de framebuffer sont identiques à la base RC9.
La modification OLED concerne uniquement la consommation du statut USB commun ;
celle du bouton ajoute une garde de stockage, sans changer les seuils/gestes.

## 3. Contrat de stockage et reprise

### États et séparation des commandes

`ready`, `connected`, `starting`, `stopping`, `importing`, `done`, `interrupted`,
`error`, `unknown`. `drive.known`, `drive.image`, `drive.transfer_active`, `busy`,
`observed_at` et `errors` exposent les faits séparément de la progression.
`configured` ou UDC non vide ne prouve jamais un support présent ni un montage Windows.
Une lecture configfs impossible bloque la gestion. Le statut ne crée pas de verrou,
n'écrit pas de cache et n'exécute aucune commande externe.

- **Terminer transfert / `stop`** : exige éjection préalable côté PC et LUN vide ;
  ne copie, ne formate, ne réinitialise et ne reconfigure aucun lecteur. Répétable.
- **Importer / reprendre / `import`** : lecteur vide, aucune association loop
  préexistante, aucun upload natif, source ordinaire. Loop explicitement RO,
  `fsck.exfat -n` sans réparation, montage exFAT `ro,nosuid,nodev,noexec`.
- **Activer / `start --allow-usb-reset`** : seul chemin de reconfiguration globale.
  Refus si un autre support est attaché ou si SHARE possède un bail ; protection
  de réservation SHARE pendant la reconfiguration. L'interruption HID est annoncée.
  Aucune reconnexion d'un contrôleur déjà délié n'est devinée.
- **Préparer / `prepare`** : une image existante est conservée. Seule une image
  réellement absente peut être créée. Échec de formatage initial : fichier conservé
  pour inspection, aucune réinitialisation implicite au prochain essai.
- **Réinitialiser / `reset`** : refus systématique dans cette candidate ; aucune
  voie Web ou CLI n'efface le conteneur de secours existant.

L'éjection PC doit réellement vider le LUN. Une simple confirmation Web, un câble
débranché ou un gadget `configured` ne suffit pas. Si Windows ne l'éjecte pas, ne pas
contourner la garde avec `--eject` : recueillir d'abord le diagnostic.

### Publication et journal

Journal courant privé : `/var/lib/kvmd/msd/.pikvm-transfer-journal.json`, version 1,
identifiant d'opération, identité source (nom/taille/mtime), nom temporaire aléatoire,
destination, étapes `planned`, `verified`, `published`, `done`, taille et SHA256.
Étapes synchronisées sur PIMSD ; progression limitée à une écriture/seconde en tmpfs.
Limite 512 entrées / 1 Mio en lecture. Aucun journal par bloc sur microSD.

La source est relue pour chaque validation ; la destination est relue indépendamment.
Une ISO existante identique est réutilisée sans changer son inode. Une ISO différente
provoque un conflit, sans suffixe automatique ni écrasement. Publication par hardlink
atomique sans remplacement puis fsync du répertoire. Le temporaire est retiré
uniquement s'il est exactement un deuxième nom du même inode publié.

| Interruption | État conservé | Reprise |
|---|---|---|
| Avant copie | Journal planifié, source intacte | Relancer import |
| Pendant copie | `.part` partiel et source | Détection de copie partielle ; mise de côté explicite puis nouvelle copie |
| Copie complète avant vérification | `.part` complet | Relecture/hash puis publication, sans recopier |
| Après publication, avant retrait du temporaire | Deux liens sur le même inode | Revalidation puis retrait du seul lien redondant |
| Après succès, réponse HTTP perdue | ISO déjà publiée | Relancer : même hash, même inode, aucun doublon |
| Collision native/concurrente | Destination concurrente et `.part` préservés | Conflit explicite, examen utilisateur |
| Échec démontage | Montage et loop conservés | État erreur ; aucun détachement forcé ni nouvel attachement USB |
| Redémarrage | Journal/ISO/temporaires durables, /run perdu | Statut interrompu depuis journal ; diagnostic puis reprise |

Commandes **à exécuter uniquement après autorisation** des opérations de données :

```bash
pikvm-usb-transfer diagnose
# Reprise normale, source conservée :
pikvm-usb-transfer import
# Si le journal identifie partial_or_conflict : conservation sous nom
# .usbimport-retained-UUID, puis nouvelle copie ; exige de la place supplémentaire.
pikvm-usb-transfer import --recover-partial 'NOM_SOURCE.iso'
# Ancien incident : uniquement un doublon de nom prouvé par samefile(), répétable.
pikvm-usb-transfer recover-link --temporary-name '.__usbimport-NOM.part' --target-name 'NOM.iso'
```

Les anciens temporaires sans journal ne sont jamais présumés valides ni effacés.
`diagnose` les inventorie (taille/liens/type). Une copie partielle ancienne sans
journal exige encore un examen et une comparaison contrôlée avec sa source.
Les journaux conflictuels, sources modifiées et limites atteintes exigent un
archivage explicite après examen ; aucune rotation effaçant des preuves n'est faite.
La reprise partielle conserve le fragment et recommence la copie : elle ne reprend
pas encore au dernier octet, et ne peut pas résoudre automatiquement un conflit ISO.

## 4. Matrice de validation et risques résiduels

« Local réussi » signifie simulation/fixture ou nginx local, jamais validation Pi.

| Fonctionnalité | Audit | Correctif | Test automatique | Test matériel | Risque résiduel |
|---|---|---|---|---|---|
| Source XFER / cinq ISO | Statique réalisé | Aucune suppression/recréation, sorties sans écrasement | Source synthétique préservée après succès/erreurs/crash | À réaliser | Coupure/lectures instables sur vraie microSD non résolues |
| Reprise import / orphelins | Réalisé | Journal, validation, récupération explicite | Checkpoints, partiel, conflit, inode double, import répété | À réaliser | Anciennes copies non journalisées ; conflit/métadonnées source modifiées à examiner |
| Dossiers / déplacer / renommer | Réalisé | Verrou commun, publication fichier sans remplacement, fsync ciblés | Racine/sous-dossier/Unicode/espaces/collisions/annulation | À réaliser | Client natif/administrateur ne partage pas forcément le verrou |
| Suppression native ISO / upload natif | Interaction examinée | `.incomplete` reste bloquant | CRUD UI simulé, protections chemin | À réaliser | Crash natif et récupération `.incomplete` restent sous contrat KVMD |
| Drive 0 / transfert | Réalisé | Statut réel, éjection exigée, reset explicite limité | LUN vide/inconnu, Drive 1 occupé, pas de mutation au polling | À réaliser | Reconfiguration globale interrompt HID ; succès réel dépend gadget/noyau |
| Drive 1 / SHARE | Réalisé | Auth/exclusivité conservées, admission HTTP bornée | Web/USB mutuellement exclusifs, leases, erreurs montage, auth/CSRF | À réaliser | Administrateur root peut contourner les garde-fous ; partiels SHARE expirés suivent encore la politique existante |
| GPIO17 / alimentation | Lecture du code et unités | Aucun changement électrique ou de service ; garde stockage avant arrêt explicite | Aucun mapping de migration vers power-hold ; permissions/gestes testés | À réaliser sans commutation | Cause du reboot/relais/tension/watchdog non déterminée |
| GPIO18 optimisé | Revu, inchangé | Backend readonly RC8 conservé | DT/sysfs, preuve LOW/HIGH, divergence, fallback, rebonds et pertes | Validation antérieure rapportée ; à revérifier passivement | Preuve par boot et configuration réelle toujours nécessaires |
| OLED physique/virtuel | Revu | Statut USB partagé | Pixels natifs, absence/retour I2C, disponibilité, bail 800 ms | À réaliser | Blocage noyau I2C ne peut pas être certifié par mocks |
| KVM vidéo/HID/macros/plein écran | Pont natif et lifecycle revus | RC9 conservée | Vrai DOM, quatre formats, ratio, menus, capture/libération simulées | À réaliser | Flux MJPEG/H.264, USB HID et reconnections réelles non validés ici |
| Terminal natif | Routage/auth/iframe revus | Aucun moteur remplacé | Navigation et document natif simulés | À réaliser | Session ttyd/WebSocket et reconnexion Pi non mesurées |
| Wi-Fi | Revu | Auth, sérialisation, validation, backup et remplacement atomique, erreurs explicites | Injection, stdin secret, EIO, HTTP concurrent | À réaliser | Échec de redémarrage après écriture conserve le backup, sans transaction réseau complète automatique |
| Hotspot | Revu | Fail-fast, pas de clé imprimée à l'activation | Syntaxe, routage, secret masqué | À réaliser | Bascule radio réelle et restauration après échec intermédiaire restent à valider ; marqueur seul reste une observation imparfaite |
| Batterie MAX17048 | Revu | Lectures I2C bornées | API/erreurs simulées | À réaliser | Pourcentage historique estimé depuis tension, calibration et lectures matérielles non certifiées |
| Authentification/session/CSRF | Revu | Backend historique protégé ; origine proxy vérifiée | Auth absente/expirée, CSRF, corps limité, erreurs et contraintes de session | À réaliser | Pas de rôles distincts KVMD pour ces interfaces ; utilisateurs authentifiés ont les fonctions de gestion |
| Paramètres/modules/navigation | Revu | Registre existant conservé | Routes uniques, état périmé, thèmes, extension future simulée | À réaliser | Dépend des contrats natifs 4.213, versions ultérieures refusées |
| Install/rollback | Revu | Baselines héritées, garde serveur SHARE, budget disque, sauvegarde durable, readiness Wi-Fi, nginx -T effectif | Réinstallation/restore répétés, nginx invalide, sauvegarde altérée, espace nul | À réaliser | Coupure à mi-installation n'est pas un rollback automatique au boot ; utiliser sauvegarde durable |
| Python système | Incident séparé | Bootstrap Bash sans Python, logging + copyreg contrôlés avant imports | Copie binaire corrompue, mismatch, deadlines/imports bloqués | À réaliser | Lectures incohérentes transitoires et stabilité RAM/SD non élucidées |
| Journaux / diagnostic | Revu | Export borné et journal d'import durable | Budgets/fichiers et tests de reprises | À réaliser | Absence de journal persistant du boot précédent ; configuration de stockage à établir avant modification journald |

Le bootstrap historique `pikvm-power-hold-startup` configure GPIO18 `ip pd` et
GPIO17 HIGH. C'est distinct du profil réel `ip --` rapporté. **Il n'est ni installé,
ni lancé, ni modifié par cette mise à jour.** Ne pas utiliser le bootstrap complet
sur le Pi actuel. La reconfiguration initiale d'une nouvelle carte exige une revue
matérielle explicite ; l'option obligatoire n'est pas une validation de compatibilité.

Après une demande explicite d’arrêt, un marqueur bloque les nouvelles opérations
XFER/dossiers/SHARE pendant la file d’attente d’arrêt. Une panne du lancement peut
laisser ce marqueur en place : examiner les jobs systemd et confirmer que l’arrêt
est réellement annulé avant toute levée manuelle du blocage. Aucun nettoyage
automatique du marqueur n’est effectué et aucun GPIO n’est changé par ces gardes.

Les verrous sont consultatifs : KVMD natif et des commandes root externes peuvent
les ignorer. Fermer les autres clients et interdire les opérations parallèles de
maintenance reste nécessaire. Aucun logiciel local ne peut garantir l'exclusivité
face à une écriture configfs directe d'un administrateur. Ne jamais lancer d'upload
natif, de commande USB ou de bascule SHARE pendant l'installation/import autorisé.

Les partiels du transfert XFER sont conservés. La politique existante d'expiration/
annulation des uploads navigateur SHARE n'a pas été refondue : elle peut retirer
ses propres temporaires non publiés. Ce point ne concerne pas la source XFER ni
les cinq ISO récupérées et reste une limite du contrat de récupération SHARE.

## 5. Tests, performance et endurance

Environnement local Windows, Python 3.12.14, Node, Edge headless, nginx 1.26.3 pour
analyse de configuration uniquement. La CI est configurée pour Python 3.11 et 3.14
sur Linux ; elle n'a pas été déclenchée ni observée à distance par cette mission.
Les cinq cas ignorés Windows couvrent les sockets Unix, les symlinks et
les verrous flock réels, y compris leur héritage après disparition du parent.
Ne pas considérer ces contrats Linux comme exécutés localement.

Bilan : **205 tests Python réussis sur 210, 5 ignorés**, puis test ciblé de migration
de la garde SHARE réussi ; **23 tests JavaScript réussis**. Les quatre suites
navigateur sont réussies : fonctionnelle générale, layout KVM sur quatre formats,
dialogues de déplacement ISO, transfert USB (y compris Image Manager historique).
Les tests nginx analysent la configuration réelle avec les quatre extensions,
leurs includes, proxies, authentification et origine ; aucun serveur Pi n'est lancé.

Commandes utilisées (avec les chemins des runtimes locaux si absents du PATH) :

```powershell
$env:NGINX_BINARY = "$PWD/private/nginx-validation/nginx-1.26.3/nginx.exe"
python -B -m unittest discover -s tests -v
node --test tests/portable-ui.test.mjs
python -B tests/transfer-endurance.py --cycles 64 --output docs/performance/rc10-local.json
# Sur la fixture localhost tests/portable_preview.py --port 8765 uniquement :
node tests/portable-browser.cjs
node tests/portable-kvm-layout.cjs
node tests/portable-dialogs.cjs
node tests/portable-transfer.cjs
```

Le serveur de prévisualisation créé pour les tests est arrêté après leur exécution.
Les mutations navigateur sont interceptées en mémoire. Les tests backend n'utilisent
que des fichiers synthétiques temporaires ; tous les outils mount/USB/GPIO sont mockés.
Le bootstrap Bash est réellement exécuté contre une copie de test et des métadonnées
gzip artificielles, avec binaire `copyreg.py` injecté, sans Python système du Pi.

L'endurance locale couvre 64 copies de 1 Mio et 64 finalisations répétées, hashes et
nombre de sorties vérifiés : 64 Mio copiés, 2,344 s murales, 2,047 s CPU, pic du tas
Python tracé 4 374 969 octets, journal 18 596 octets. Ces mesures ne sont **ni un RSS
global ni un débit Pi**, et ne constituent pas un essai prolongé de fichiers de 7 Gio.
Compteurs de descripteurs `/proc` indisponibles sous Windows, valeurs nulles publiées.

Sur Pi : buffers de copie/hash de 1 Mio, décompression XZ plafonnée à 32 Mio et
buffers bornés ; archives concaténées/tronquées refusées. Vérifier la marge RAM avant
usage XZ. Les imports restent intensifs en I/O/CPU par conception : source + relecture
destination pour validation. Le journal n'est pas écrit par bloc. Le polling USB
est désormais sans sous-processus, avec une seule requête frontend en vol. Aucun
résultat CPU/latence/RSS du Pi n'est revendiqué sans mesure réelle.

## 6. Mise à jour progressive et sauvegarde

**Instructions préparées, non exécutées. Obtenir l'autorisation avant chaque phase
qui modifie le Pi. Ne pas utiliser `install.sh` pour cette mise à jour.**

Depuis Windows, après autorisation du transfert de fichiers ; mot de passe aux invites :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python -B scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
$PiKvmHost = Read-Host 'Adresse actuelle du PiKVM'
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.10.tar.gz private/pikvm-portable-os-0.2.0-rc.10.tar.gz.sha256 "root@${PiKvmHost}:/tmp/"
ssh @sshOptions "root@${PiKvmHost}"
```

Aucun mot de passe dans une variable, un script, Git ou un journal. Sur le Pi :

```bash
set -e
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.10.tar.gz.sha256
stage=$(mktemp -d /tmp/pikvm-portable-os-rc10.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.10.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
bash scripts/pikvm-python-integrity.sh
bash install-portable-os.sh check
```

Ce check ne déploie rien. Il crée seulement ses journaux temporaires de diagnostic.
Un hash inconnu de script/HTML/nginx installé provoque un refus : exporter la version
locale et examiner son diff ; ne pas ajouter arbitrairement son hash à la liste.
La migration préserve les correctifs reconnus et refuse une classe serveur SHARE
personnalisée inconnue. Aucun remplacement intégral aveugle de l'API locale SHARE.

Avant l'installation : éjecter proprement les deux lecteurs depuis le PC, sortir du
mode Web SHARE/libérer son bail, terminer les uploads, fermer les autres clients.
Conserver une session SSH de secours. Vérifier l'espace libre et les versions exactes.
Conserver une copie externe des ISO et de la source de secours lorsque l'alimentation
aura été jugée stable : la sauvegarde applicative ne sauvegarde pas 64 Gio de données.
Une copie/lecture intégrale de ces fichiers est une opération de charge distincte,
qui nécessite son propre accord ; ne pas la déclencher pendant ce diagnostic.

Après **autorisation de déploiement**, sans redémarrage matériel :

```bash
rw
if bash "$stage/install-portable-os.sh" install; then
    ro
else
    status=$?
    ro
    printf 'Échec (%s) : examiner rollback et journaux conservés.\n' "$status" >&2
    exit "$status"
fi
```

La transaction sauvegarde tous les fichiers remplacés et leurs métadonnées sous
`/root/pikvm-portable-os-backups/DATE-ID`, synchronise leurs données, enregistre les
états des services, redémarre les seuls services applicatifs concernés, vérifie la
readiness et les refus d'accès sans session, analyse **nginx -T** et les fichiers
réellement inclus avant de recharger nginx. Aucun reboot ni redémarrage de power-hold.
Une erreur ordinaire déclenche le rollback existant. Conserver le chemin imprimé et
copier cette sauvegarde privée hors du Pi après autorisation ; elle peut contenir
des correctifs/configurations privés. Ne pas publier la sauvegarde sur GitHub.

L'interface de secours `/legacy/` et `/kvm/` reste disponible. Ctrl+F5 sur les onglets
après mise à jour. Vérifier le badge RC10 ; le KVM conserve vidéo, commandes puis
panneau et ratio natif. Les boutons transfert/terminer/import sont distincts dans
les interfaces historiques intégrées ; pas de nouvelle interface indépendante.

## 7. Retour arrière et installation interrompue

Choisir le backup créé **juste avant RC10**, sans deviner « le dernier » :

```bash
rw
if python3 -B "$stage/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID; then
    ro
else
    status=$?
    ro
    printf 'Restauration échouée (%s) : conserver les sauvegardes.\n' "$status" >&2
    exit "$status"
fi
```

Le script installé `/usr/local/bin/pikvm-portable-install` peut restaurer sans stage.
L'intégrité de chaque copie est vérifiée avant l'arrêt des services. La restauration
est répétable, rétablit les anciens fichiers/états d'activation, et ne restaure aucune
image utilisateur. Éjecter/libérer SHARE si le rollback concerne son API.

Une coupure à mi-installation nécessite une restauration explicite depuis SSH avec
le backup durable ; pas de reprise automatique aveugle au boot. Ne pas réexécuter le
bootstrap matériel. Si Python devient illisible, **ne pas lancer la restauration
Python** avant diagnostic : vérifier avec le bootstrap Bash, `pacman -Qkk python`
et les hashes. Ne réparer depuis un paquet officiel exactement compatible signé
que si une corruption persistante est confirmée et après autorisation distincte.
Le script existant de réparation logging ne traite pas automatiquement copyreg.

Le retour à une version antérieure réintroduit ses défauts USB : ne pas utiliser
son import/reset avec le conteneur de secours. Conserver source et cinq ISO en place.

## 8. Validation sur le Pi, à autoriser séparément

### A — Observations sans mutation des supports ni GPIO

Après accord d'accès, avant puis après mise à jour :

```bash
bash "$stage/scripts/pikvm-python-integrity.sh"
pacman -Qkk python
python3 -B "$stage/scripts/pikvm-portable-report" > /tmp/portable-incident.json
cat /sys/kernel/config/usb_gadget/kvmd/functions/mass_storage.usb0/lun.0/file
cat /sys/kernel/config/usb_gadget/kvmd/functions/mass_storage.usb1/lun.0/file
pinctrl get 17
pinctrl get 18
findmnt -T /var/log/journal
journalctl --list-boots --no-pager
python3 -B "$stage/scripts/pikvm-portable-perf" --duration 60 --interval 5 --label rc10-idle > /tmp/rc10-idle.jsonl
```

L'export collecte versions, hashes Python répétés, résultat Qkk, boot_id/uptime,
services, montages/loops, température/throttling, journaux noyau bornés, tailles/liens
des ISO et journal de reprise. Il ne collecte ni fichiers Wi-Fi, cookies, environnement
de services ni mots de passe. Examiner noms de fichiers/journaux avant partage.
Chaque sous-commande est bornée et ses échecs restent visibles dans le JSON.

Vérifier GPIO17 HIGH sans aucune écriture, aucune augmentation NRestarts OLED/bouton,
statut `ready` avec LUN vide même si le contrôleur est configuré, retour 401/403 sans
session sur les API, refus CSRF sans en-tête, accès valide avec session. Contrôler les
droits des backups/journaux, la marge RAM et les processus/zombies après les appels.

### B — Fonctions actives, données de test exclusivement, accord distinct

Sur un support/environnement de test isolé, jamais en réinitialisant la source
de secours : petit fichier ISO synthétique, éjection réelle PC, import, hash, reprise
après fermeture du navigateur, finalisation répétée ; montée en charge graduelle.
Tester KVM vidéo/HID réel, libération capture, raccourcis, macros, plein écran,
résolution et reconnexion ; terminal ; boutons physiques courts, gestes longs
uniquement dans des menus non destructifs ; OLED absent puis rebranché hors tension
selon procédure matérielle ; réseau de secours disponible avant bascule Wi-Fi.

Ne pas provoquer de coupure, transition GPIO17, reset USB ou arrêt réel pour tester
la récupération. Les pannes sont injectées uniquement dans les fixtures locales.
Ne pas reformater `.USB-TRANSFER.img` ou `.PIKVM-SHARE.img` pour « tester ».

### C — Incident matériel et essais prolongés encore nécessaires

Recueillir un journal de boot précédent fiable **avant** les charges longues.
Vérifier où `/var/log/journal` est réellement stocké : un `Storage=persistent` sur
tmpfs ne conserve pas un boot. Une configuration journald persistante et bornée
nécessite une décision de stockage/écritures séparée ; elle n'est pas imposée par RC10.
Exporter les traces vers un autre ordinateur pendant un essai ultérieur autorisé.

Comparer consommation CPU/RSS/PSS, cgroups, I/O, latences API, FD et NRestarts avant/
après, au repos puis KVM, puis copie synthétique progressive. Contrôler alimentation,
connectique, relais, tension transitoire et watchdog par observation compétente ;
ne désactiver aucune protection. N'entreprendre un transfert de plusieurs Gio et une
endurance prolongée qu'après stabilité des petites charges et sauvegarde externe.
Toute nouvelle anomalie Python ou reboot arrête la montée en charge et impose
l'export immédiat des preuves. RC10 ne suffit pas à diagnostiquer ce phénomène.

## 9. Fichiers livrés et contrôles de maintenance

- Noyau transfert : nouveau `scripts/pikvm_transfer.py`, refonte
  `scripts/pikvm-usb-transfer`, intégration `scripts/pikvm-image-folders`.
- Services existants : `scripts/wifi-wizard-api`, `pikvm-hotspot`, consommation
  du statut dans `pikvm-oled-custom` / `pikvm-button-menu`, garde d'arrêt et plafond
  HTTP dans `pikvm-share-api`. Aucune unité power-hold/auto-shutdown modifiée.
- Installation : `pikvm-portable-install`, `pikvm-share-install`, nouveau fichier
  `pikvm-storage-baselines.json`, empaqueteur, lanceur additif et garde du bootstrap
  initial ; `pikvm_preflight.py`, `pikvm-portable-preflight.sh` et nouveau
  `pikvm-python-integrity.sh`. Nouveau `pikvm-portable-report` passif.
- Web : configurations nginx Wi-Fi/Image Manager, scripts `usb-transfer.js`,
  `drive-folders.js`, en-tête CSRF de `power-control.js`, Image Manager `app.js` /
  `index.html`, en-tête Wi-Fi Wizard, version Portable OS et correction `core/ui.js`
  RC9.1. Vidéo, moteur natif et géométrie KVM RC9 conservés.
- Tests : nouveaux `test_transfer_recovery.py`, `test_rc10_migration.py`,
  `transfer-endurance.py`, `portable-transfer.cjs`, régression `portable-dialogs.cjs`
  RC9.1 ; compléments installateur, préflight, archive et workflow CI.
- Maintenance : `.gitattributes` pour les nouveaux scripts Linux, README,
  procédure de réinstallation, notes RC9.1 conservées, ce rapport et mesure locale
  `docs/performance/rc10-local.json`. Manifeste SHA256 intégré à l'archive et
  empreinte externe `.tar.gz.sha256` écrite en LF pour vérification sous Linux.

Les tests vérifient également la syntaxe Python de tous les scripts du dépôt,
la syntaxe Bash des installateurs/diagnostics concernés et celle des clients JS
modifiés. `git diff --check` est propre. Les nouveaux tests et les changements
restent locaux à la branche ; aucune exécution CI distante ni publication GitHub
n'est sous-entendue.
