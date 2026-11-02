# PiKVM Portable OS 0.2.0-rc.7 — performances

Candidate locale sur `codex/portable-os`, dérivée de RC6 et de son superviseur de
précontrôle (`5167351`). Aucun accès SSH ni déploiement pendant ce travail.

## Audit et choix

L'audit porte sur les scripts du dépôt, les unités systemd et les modules web.
Il ne mesure pas les services actuellement exécutés sur le Pi. Les seuils ci-dessous
proviennent du code, non d'un relevé CPU ou I2C matériel.

| Composant | Coûts identifiés / état existant | Décision RC7 |
| --- | --- | --- |
| OLED statut | Boucle 100 ms ; Pillow redessine même si compteur et télémétrie sont identiques | Dessiner sur changement de page, seconde réelle ou révision du cache ; observer les résultats asynchrones toutes les 100 ms |
| Framebuffer partagé | Fichier JSON atomique jusqu'à 4 fois/s, même image ; base64 recalculé | Heartbeat de producteur à 1 s si tout est identique ; changements toujours soumis au plafond existant de 250 ms ; base64/pixel ID mémorisés |
| Sortie SSD1306 | Copie Pillow et génération I2C à chaque display, même pixels | Comparer les 1024 octets ; une copie/transmission seulement par changement ; worker et reconnexion autonomes conservés |
| Bouton / menus | Lecteur `pinctrl get 18` séparé, pause 40 ms après chaque lecture ; contrôleur Unix, heartbeat indépendant ; TTL gestes 800 ms | Aucun changement de fréquence ni de logique ; menus et barres de maintien restent sur leur chemin existant |
| Télémétrie OLED | AsyncCache : 2 workers, 32 entrées maximum, intervalle 1 s ; lecteurs système/I2C hors rendu | Réutilisé ; compteur de révision sur valeurs réellement changées ; aucun lecteur de page inactive ajouté |
| API Portable | `systemctl show` groupé, cache observationnel 5 s ; USB/configfs lus directement | Cache et lectures sensibles conservés ; réponse OLED conditionnelle sur pixel ID |
| API SHARE / images | Vérifications image, LUN, lease, montages et concurrence ; stat/listing, pas de lecture intégrale des ISO pour statut | Inchangés ; aucun cache susceptible d'autoriser une opération avec un état ancien |
| Wi-Fi / MAX17048 | iw/ip/wpa et i2cget ; l'API batterie utilise 4 i2cget par appel, OLED statut jusqu'à 4 sur une mise à jour batterie+charge | Pas de nouveau bus ou service central ; baisse des requêtes des onglets cachés ; mutualisation interprocessus différée aux mesures Pi |
| Frontend global | 6 ressources/batch, toutes les 8 s visibles et 45 s cachées ; OLED 200 ms uniquement ouvert | Suspension des nouveaux batches cachés, reprise immédiate ; pas de duplication de timer après stop/start |
| Adaptateur KVM | Projection du panneau actif toutes les 150 ms ; un seul moteur natif | Suspension cachée, libération HID, reprise synchronisée ; aucune modification de `/kvm/` |
| Alimentation / hotspot / transfert USB / installateurs | Services et commandes à la demande, timer d'inactivité historique 5 s ; superviseur de précontrôle borné | Inchangés ; aucun réglage systemd, fréquence CPU, swap ou arrêt automatique |

Le rendu réutilise les mêmes fonctions Pillow ; aucun deuxième moteur ni nouvelle
dépendance. Le statut réduit ses allocations en évitant les dessins identiques.
Les compteurs restent issus de l'horloge et des menus réels, jamais extrapolés par
le navigateur. Les actions sensibles relisent leurs états actuels.

Le navigateur demande `?pixels_id=<sha256>` après une image complète. Le serveur
authentifie **chaque requête**, valide toujours la fraîcheur du framebuffer, puis
omet uniquement `pixels` si l'identifiant concorde. Contrôle, menu, âge et état
physique restent transmis. Un producteur ancien sans pixel ID reste compatible
(réponse complète). Un accusé incohérent est rejeté sans modifier le canvas ni le
geste. Le polling 200 ms et son nombre de requêtes ne sont pas réduits par ce
protocole : seuls le volume et les décodages inutiles diminuent. WebSocket et
long-polling n'apportent ici aucun gain démontré justifiant leur complexité.
Une image qui change à chaque requête conserve sa réponse complète avec quelques
octets supplémentaires d'identification ; le gain de trafic dépend donc du contenu.

Les écritures OLED étaient déjà sous `/run` : leur réduction concerne tmpfs et
les traitements associés, **pas un gain mesuré d'usure microSD**. Aucun log continu
n'est ajouté. Les fichiers, sockets et connexions continuent à être fermés par les
context managers. Les caches restent bornés : dernier framebuffer, dernière copie
physique, 32 entrées de télémétrie et dernier état des services. Les quelques Kio
de cache pixels supplémentaires ne constituent pas une réduction RSS démontrée.

## Mesures locales avant/après

Benchmark `tests/portable-perf.py`, Python Windows 3.12.14, Pillow, médiane de 5
exécutions. Scénario A : 600 dessins sur 30 secondes **virtuelles**, 150 réponses
JSON, pilote I2C factice. Le temps CPU est celui du processus Windows, sans
authentification réseau réelle ; les octets excluent les en-têtes HTTP et TLS.
Les horloges simulées ne servent qu'au benchmark, jamais au produit.

| Mesure | RC6 | RC7 | Écart |
| --- | ---: | ---: | ---: |
| Image fixe : appels au faux pilote | 600 | 1 | −99,8 % |
| Compteur 1 Hz : appels au faux pilote | 600 | 30 | −95 % |
| Remplacements du fichier frame (chaque scénario) | 121 | 31 | −74,4 % |
| JSON image fixe, octets / 150 réponses | 280 551 | 90 394 | −67,8 % |
| JSON compteur 1 Hz, octets / 150 réponses | 280 513 | 129 379 | −53,9 % |
| CPU Windows, image fixe | 406,250 ms | 296,875 ms | −26,9 % |
| CPU Windows, compteur 1 Hz | 390,625 ms | 312,500 ms | −20 % |

Scénario B : exécution de la véritable boucle de statut pendant 60 secondes
virtuelles, télémétrie stable factice. Seule la source du producteur varie
(RC6 originale exportée de Git contre RC7) ; le miroir RC7 est commun aux deux
pour isoler le coût du rendu :

| Mesure | Source statut RC6 | Source statut RC7 |
| --- | ---: | ---: |
| Dessins Pillow | 600 | 60 |
| CPU Windows médian | 468,750 ms | 156,250 ms |

Résultats bruts : [RC6](performance/rc6-local.json), [RC7](performance/rc7-local.json).
Ces nombres sont des résultats locaux, **pas des gains CPU/RAM/I2C mesurés sur le
Pi Zero 2 W**. Les temps CPU Windows ont une granularité notable et restent
indicatifs ; les comptes d'opérations expliquent le gain. RSS/PSS, latences
matérielles, sous-processus exacts, writes SD et stabilité sur plusieurs heures
restent non mesurés. Aucun gain RAM global ni test d'endurance matériel revendiqué.

## Diagnostic réel passif avant/après

`scripts/pikvm-portable-perf` lit uniquement `/proc`, sans sous-processus, réseau,
GPIO/I2C, signal ou modification de service. Il produit du JSONL sur stdout :

- CPU processus et threads (pourcentage d'un cœur), RSS et PSS si autorisé ;
- regroupement par unité cgroup PiKVM/KVMD/Wi-Fi, processus/threads/FD ;
- compteurs d'I/O des processus, deltas, context switches et attentes wchan ;
- mémoire, pression CPU/I/O/mémoire, compteurs réseau et disques de l'hôte ;
- temps CPU et durée d'échantillonnage de l'observateur pour évaluer son coût.

Les instantanés successifs sont bornés en mémoire et les résultats sont streamés.
Un PID réutilisé n'est jamais comparé à son ancien occupant. Un champ inaccessible
reste null ; PSS agrégé est null si incomplet. La lecture de smaps_rollup a un coût :
commencer à 5 s, augmenter à 10 s si `sample_ms` devient important. Les commandes
très courtes peuvent échapper à l'échantillonnage ; `syscr/syscw` ne comptent pas
tous les syscalls. Réseau/disques sont globaux : ne pas les présenter comme des
compteurs HTTP ou des écritures exclusives Portable OS. L'outil ne compte pas les
transactions I2C/GPIO ni les execs de manière exhaustive. Pas de cmdline, cookie,
mot de passe ou contenu de fichiers utilisateur collecté.

Après autorisation de transfert de l'outil, sur le Pi RC6, dans son stage :

```bash
python3 -B scripts/pikvm-portable-perf --label RC6-idle --duration 120 --interval 5 > /tmp/rc6-idle.jsonl
```

Effectuer séparément les mêmes profils avant et après installation : idle, OLED
ouvert sans geste, mêmes maintiens 2/3/5 s sur menu non sensible, KVM avec même
résolution/FPS, navigation normale. Noter écrans physiques, clients, réseau et
transferts ; ne pas comparer un idle RC6 à une session vidéo RC7.

```bash
python3 -B scripts/pikvm-portable-perf --label RC7-idle --duration 120 --interval 5 > /tmp/rc7-idle.jsonl
python3 -B scripts/pikvm-portable-perf --label RC7-soak --duration 10800 --interval 10 > /tmp/rc7-soak.jsonl
```

Surveiller l'espace de `/tmp` pendant l'endurance, ou streamer stdout vers le PC
par SSH avec mot de passe. Comparer PSS/FD/threads et pentes au fil des heures,
sans confondre caches Linux et fuite. Mesurer les latences réelles via « Diagnostic
OLED » et les requêtes du navigateur. Ne pas lancer de benchmark de copie ISO,
strace/perf ou capture réseau par défaut : leur coût perturberait les résultats.

## Tests et fichiers

Les tests couvrent déduplication, changements de contexte sans pixels, heartbeat
de fraîcheur, refus d'une frame périmée, réponse conditionnelle authentifiée,
repli legacy, révision de télémétrie et compteurs réels, PID réutilisés, parsing
Linux, pause/reprise du polling sans double timer. La suite existante conserve
les maintiens 2/3/5 s, la perte de bail réelle, CSRF, I2C absent/reconnecté,
installation/restauration répétées, nginx, SHARE et commandes KVM desktop/tactiles.
Validation locale : **131 tests Python réussis, 2 ignorés sous Windows** (133 au
total), **22 tests JavaScript réussis**, scénario navigateur Edge desktop/tactile
réussi. Le parsing `/proc` est testé avec des fichiers simulés ; la matrice CI
Linux/Python 3.14 et l'endurance matérielle restent à exécuter. Syntaxe Python,
manifeste de paquet, empreintes et fins de ligne Linux sont vérifiés séparément.

Fichiers fonctionnels modifiés : `scripts/pikvm_oled.py`, `pikvm-oled-custom`,
`pikvm-portable-api`, nouvel outil `pikvm-portable-perf`, installateur/empaqueteur
et baselines OLED ; `app.js`, `core/api.js`, `core/kvm-adapter.js`, `modules/oled.js`
et version sous `web/extras/portable-os/`. Tests, fixture HTTP, rapport et données
de comparaison accompagnent ces changements. `pikvm-button-menu`, SHARE, Wi-Fi,
unités systemd, GPIO et KVM natif ne sont pas modifiés.

## Installation RC7 et retour RC6 — uniquement après autorisation

Construire puis transférer en imposant le mot de passe (aucune clé SSH) :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python -B scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
$PiKvmHost = Read-Host 'Adresse IP actuelle du PiKVM'
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.7.tar.gz private/pikvm-portable-os-0.2.0-rc.7.tar.gz.sha256 "root@${PiKvmHost}:/tmp/"
ssh @sshOptions "root@${PiKvmHost}"
```

Saisir le mot de passe aux invites. Sur le Pi :

```bash
set -e
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.7.tar.gz.sha256
stage=$(mktemp -d /tmp/pikvm-portable-os-rc7.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.7.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
printf 'Stage RC7 : %s\n' "$stage"
python3 -B scripts/pikvm-portable-install check
```

Le superviseur de précontrôle RC6 est conservé. Les empreintes des scripts RC6
officiels sont reconnues ; un correctif local inconnu reste refusé avant remplacement.
Ne pas contourner ce refus. Conserver le stage et son chemin jusqu'à validation.
Enregistrer les profils RC6 avant toute modification puis, seulement après
autorisation et réussite des contrôles :

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

Conserver le chemin de sauvegarde imprimé. Pas de redémarrage matériel. Vérifier
`/legacy/`, `/kvm/`, reconnexion/session, compteurs et maintiens non sensibles,
KVM/HID et sous-menus ; effectuer les profils RC7 dans les mêmes conditions.
Une baisse des compteurs simulés ne dispense pas de cette validation matérielle.

Pour restaurer l'état RC6 réellement installé avant RC7, remplacer DATE-ID par la
sauvegarde de **cette** installation, et redéfinir `stage` si le shell a été fermé :

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

Le script installé `/usr/local/bin/pikvm-portable-install` peut aussi restaurer si
le stage temporaire a disparu. Le manifeste de sauvegarde est vérifié avant
restauration ; recharger le navigateur pour quitter les modules RC7 en mémoire.
