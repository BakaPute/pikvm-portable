# RC13 — Utilisateurs et permissions, candidate à validation

Version : **0.2.0-rc.13**, branche `codex/portable-os`. **Aucun déploiement sur le
Pi de production. RC12.1 et l’authentification actuelle sont conservées.**

## Architecture retenue

KVMD 4.213 authentifie des utilisateurs, sans ACL par fonction. Ses cookies
restent valides après certaines modifications htpasswd ; un changement de
mot de passe natif n’est donc pas une révocation de session. Le socket Unix
autorise certaines opérations à l’UID root ; `/auth/check` interdit ce bypass.
Ces comportements ont été examinés dans les sources officielles :
[AuthManager](https://github.com/pikvm/kvmd/blob/v4.213/kvmd/apps/kvmd/auth.py),
[API auth](https://github.com/pikvm/kvmd/blob/v4.213/kvmd/apps/kvmd/api/auth.py),
[htpasswd](https://github.com/pikvm/kvmd/blob/v4.213/kvmd/apps/htpasswd/__init__.py),
[nginx](https://github.com/pikvm/kvmd/blob/v4.213/configs/nginx/kvmd.ctx-server.conf).

RC13 sépare trois identités :

1. **KVMD natif** : comptes existants, dont `admin`, inchangés et protégés.
   Ils restent administrateurs sur l’origine actuelle, avec `/kvm/`,
   `/legacy/`, terminal et accès SSH root de récupération conservés.
2. **Portable Web** : base distincte, aucun ajout à htpasswd, PAM, vncpasswd
   ou ipmipasswd. Cookie `portable_session`, jamais `auth_token` KVMD.
3. **Linux SSH** : création root séparée, UID/groupe/home distincts, uniquement
   après approbation d’un plan SHA256. Aucun couplage implicite avec le rôle Web.

Les comptes restreints utilisent **la même application Portable OS**, sur une
entrée TLS dédiée devant une passerelle loopback `127.0.0.1:9879`. Ce n’est pas
un filtrage de boutons : requêtes HTTP, WebSocket texte/binaire et actions sont
autorisées côté serveur, avec refus par défaut. Les cookies et en-têtes
d’authentification fournis par le navigateur ne sont jamais transmis aux
services privilégiés. Les accès Unix KVMD sont limités par une liste explicite ;
les autres backends vérifient une délégation HMAC éphémère liée à la méthode,
la cible, l’utilisateur, sa révision et un nonce non réutilisable.

Utiliser un nom d’hôte et un profil navigateur séparés de l’administration
native. Les cookies HTTP ne sont pas isolés par port. Détenir déjà un compte
ou cookie administrateur natif constitue toujours un accès administrateur ;
RC13 ne prétend pas restreindre ce second accès.

## Gestion dans Paramètres

La catégorie **Utilisateurs et permissions** gère création, nom affiché,
activation, mot de passe, suppression Web, rôles et exceptions individuelles.
Elle affiche les droits effectifs, les identités natives protégées, les liens
Linux disponibles, les clés publiques, plans SSH, révisions et traces d’activité.

Les rôles prédéfinis sont immuables ; leur duplication crée un rôle `custom_*`
modifiable. Un refus individuel prime sur une autorisation. Aucun utilisateur
ne peut déléguer des droits qu’il ne détient pas, ni modifier/réinitialiser un
compte supérieur. Le dernier administrateur Portable activé et non restreint
ne peut être supprimé, désactivé ou rétrogradé. Les comptes natifs ne sont pas
modifiables par ce gestionnaire : changer leur mot de passe, les migrer ou
révoquer leurs sessions demande une procédure KVMD distincte.

| Rôle | Droits par défaut sur l’entrée restreinte |
|---|---|
| Administrateur | Administration Portable, utilisateurs, permissions et opérations prises en charge ; confirmations conservées |
| Opérateur | Vidéo, clavier/souris, raccourcis, texte/HID, ISO lecture/montage/éjection, diagnostics, états ATX/SHARE, OLED consultable |
| Utilisateur | Vidéo, diagnostics, état SHARE, OLED consultable ; autres droits sur attribution explicite |
| Lecture seule | Vidéo, diagnostics, OLED consultable ; aucune écriture ni contrôle HID |
| Maintenance | Diagnostics, journaux autorisés, états SHARE/OLED ; SSH facultatif et séparé |

Le catalogue serveur comprend vidéo, clavier, souris, macros, texte, HID ;
lecture/ajout/dossiers/renommage/déplacement/suppression/montage/éjection/info ISO ;
état/Web/transfert/import/exposition SHARE ; état/actions ATX ; pages/durées/
gestes/notifications OLED ; diagnostics/journaux/paramètres/réseau/export/
restauration/arrêt ; comptes/rôles/permissions/clés/audit/révocation.

### Limites réellement appliquées

- **Clavier et macros** partagent les événements KVMD. Sans les deux droits,
  les événements clavier sont refusés ; on ne présente pas le masquage d’un
  bouton macro comme une protection contre un script envoyant des touches.
- KVMD libère globalement les touches et boutons sur ajout/retrait d’un WS.
  La passerelle refuse donc le WS aux comptes sans clavier+macros+souris.
  Leur page KVM lit directement le MJPEG natif, sans iframe/WS/HID, et indique
  si le producteur vidéo est indisponible. Les droits HID partiels restent
  utilisables via les API HTTP, pas via la console native. Cette limitation
  empêche un compte vidéo seul de libérer les touches d’un opérateur.
- Le miroir OLED est consultable séparément. Ses gestes ouvrent un menu qui
  peut agir sur ISO, réseau et alimentation : la télécommande de ce menu
  nécessite tous ces droits, avec les confirmations RC12.1 et le bail 800 ms.
  Un écran QR pouvant contenir un secret Wi-Fi est refusé sans droit réseau,
  avant transmission des pixels ; aucun second rendu OLED n’est créé.
- `/legacy/`, terminal Web, Redfish, Janus, KVMD-Media, API inconnues, import
  d’URL distante et reset USB sont refusés sur l’entrée restreinte. Le KVM
  natif y utilise MJPEG et un WebSocket filtré. L’origine administrateur
  conserve ses fonctions actuelles, dont H.264/terminal si disponibles.
- Les ISO exposées par la passerelle sont des `.iso` visibles. Les conteneurs
  cachés ne sont pas des cibles autorisées. Montage en lecture seule, CD/DVD ou
  Flash ; le moteur KVMD et les verrouillages existants traitent les opérations.
- Les changements SHARE passent par le contrôleur existant. L’ouverture du
  panneau ne connecte rien ; éjection PC et exclusivité Web/USB sont conservées.
- Les actions ATX demandent une confirmation de requête indépendante. Une
  commande native qui ne la fournit pas est refusée. Avant chaque action, la
  configuration KVMD est relue sans instancier le pilote GPIO : seul un Zero
  2 W identifié, le backend GPIO sur `/dev/gpiochip0` et des broches connues
  excluant 17/18 sont acceptés. Une configuration inconnue bloque l’action ;
  cette vérification ne demande aucune ligne et ne change aucun niveau.
  Les permissions stockées
  n’activent pas une voie inconnue : `system.update` n’offre aucun exécuteur
  root et les arrêts directs/réinitialisations restent bloqués.
- Les mots de passe Wi-Fi sont masqués dans les réponses de la passerelle ;
  les métadonnées natives arbitraires ne sont pas projetées vers les comptes
  restreints. Les exports ordinaires de préférences ne contiennent ni base
  d’identités, ni hachages, sessions, secrets ou clés privées.

## Stockage, sessions et audit

`/var/lib/kvmd/pst/portable-security/identities.json` : root, mode 0600,
écriture atomique sous bail PST natif et verrou interprocessus. Aucune écriture
dans les ISO/conteneurs. Révisions optimistes, validation stricte, permissions
inconnues refusées, corruption bloquante sans retour à un rôle permissif.
La lecture cache seulement une version validée et recontrôle inode/mtime/mode.

Mots de passe : PBKDF2-HMAC-SHA256, sel aléatoire 128 bits, 600 000 itérations,
14 caractères minimum ou phrase robuste. Une seule vérification coûteuse
simultanée, limite d’essais par compte/adresse. Sessions aléatoires de 30 minutes,
128 maximum, conservées seulement en mémoire ; révocation lors des changements
sensibles, expiration et redémarrage de la passerelle. WebSocket et transferts
en cours recontrôlés ; fermeture des connexions révoquées. Le WS impose une
origine exacte et une limite de cadence HID ; pas de proxy arbitraire.

Les modifications sensibles requièrent confirmation, CSRF et, pour les comptes
Portable, réauthentification par leur mot de passe. Le TOTP natif KVMD n’est
ni modifié ni contourné ; il ne devient pas un second facteur Portable par
magie. Une MFA propre au nouveau domaine reste une évolution distincte.

Historique borné de 200 changements sans secrets dans la base ; journal court
dans `/run/pikvm-portable-security/audit.jsonl`, rotation bornée. Les dernières
connexions affichées sont les traces disponibles, pas la preuve d’absence de
connexions anciennes. Les traces SSH/natives restent dans leurs journaux
autorisés, avec masquage. Aucun corps HTTP, mot de passe, cookie, jeton ou clé
privée n’est journalisé.

## Compte Codex et clé sur le PC

Le bouton **Préparer le compte Codex** prépare une identité Web Maintenance.
SSH reste interdit jusqu’à l’import d’une clé publique, au choix du mode
diagnostic et à l’application root du plan. Aucune clé privée n’est générée
sur le Pi ni transportée par le navigateur.

Sur le PC, procédure interactive, hors dépôt :

```powershell
$codexKey = Join-Path $env:USERPROFILE '.ssh\pikvm_codex_ed25519'
ssh-keygen.exe -t ed25519 -a 64 -f $codexKey -C pikvm-codex-maintenance
# Saisir une phrase de passe dans l’invite native, puis charger la clé
# dans l’agent OpenSSH du PC selon sa politique locale :
ssh-add.exe $codexKey
Get-Content ($codexKey + '.pub')
```

Importer seulement la ligne `ssh-ed25519` publique. Ne jamais écraser une clé
existante. Restreindre l’ACL de la clé privée au compte Windows et aux accès
système nécessaires ; aucune clé privée, même chiffrée, ne va dans GitHub.
L’agent permet les connexions suivantes sans redemander le mot de passe root.

Après approbation distincte, depuis un stage root immuable/installé :

```bash
python3 -B /usr/local/lib/pikvm-portable/pikvm-security-ssh plan codex
# Lire le plan, son SHA256, la révision et les privilèges ; puis seulement
# après approbation précise de ce plan :
python3 -B /usr/local/lib/pikvm-portable/pikvm-security-ssh apply codex --approve-plan-sha256 SHA256_DU_PLAN
```

Le plan vérifie `sshd -t`, les options effectives du compte et l’égalité des
options root avant/après. Il refuse identité/home existants, configuration
globale incompatible ou helper modifiable. UID/groupe distincts, home dédié
sans fichier de démarrage modifiable, mot de passe Linux inutilisable, aucun
groupe sensible/sudo. `ForceCommand` accepte uniquement `status`, `services`,
`version` : aucun shell, chemin arbitraire, SCP/SFTP, transfert, tunnel, PTY ou
agent forwarding. Seules les clés Ed25519 brutes sont acceptées : un certificat
issu d’une éventuelle CA SSH globale ne contourne pas la liste gérée. Les
helpers et leurs répertoires doivent être immuables pour le compte. Le compte
ne peut pas écrire les GPIO ni effacer les
sauvegardes via cette interface. Il n’est pas un compte root d’automatisation.

Le résolveur de clés root, de chemin fixe et non modifiable par le compte,
lit l’activation et les clés actuelles à chaque connexion. Son mapping lie
UID et identifiant aléatoire Web : supprimer/recréer un nom ne récupère pas
un ancien accès Linux. Révocation immédiate des nouvelles connexions ; une
commande déjà admise peut finir, au plus 8 secondes pour les diagnostics.
Les mises à jour restent une opération root explicitement autorisée, pas une
commande privilégiée exposée au compte Codex.

```powershell
ssh.exe -o IdentitiesOnly=yes -i $codexKey codex@192.168.168.99 status
ssh.exe -o IdentitiesOnly=yes -i $codexKey codex@192.168.168.99 version
# Révoquer la clé dans la fiche, puis vérifier que la même connexion échoue.
```

## Installation progressive, sans activation automatique

**Ne pas exécuter maintenant sur le Pi de production.** Vérifier archive,
SHA256 et manifeste, puis tous les précontrôles RC12.1 : Python/KVMD, nginx,
GPIO17 HIGH, GPIO18 inchangé/relâché, lecteurs libres, aucune opération SHARE.
Conserver une session administrateur native et un accès local de récupération.

L’installateur refuse `install` sans approbation du SHA256 exact du manifeste :

```bash
sha256sum -c pikvm-portable-os-0.2.0-rc.13.tar.gz.sha256
stage=$(mktemp -d /tmp/portable-rc13.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.13.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
bash install-portable-os.sh check
sha256sum MANIFEST.sha256
# Après autorisation explicite de cette candidate uniquement :
rw
bash install-portable-os.sh install --approve-security-candidate SHA256_DU_MANIFEST
ro
```

Une **nouvelle sauvegarde RC12.1** est copiée et vérifiée avant tout arrêt des
services applicatifs : application, préférences brutes, état sécurité éventuel,
htpasswd/VNC/IPMI/config SSH et mapping éventuel, dans un répertoire root privé.
Ne pas confondre la sauvegarde RC12 créée lors de la mise à jour RC12.1 avec
cette future sauvegarde RC12.1. Les secrets sauvegardés restent root 0600,
hors exports ordinaires. Les correctifs locaux inconnus bloquent la migration.

Cette installation **ne démarre ni la passerelle ni de nouveau compte Linux**.
Elle conserve les routes et identités administrateur natives. Le modèle nginx
TLS est sous `config/`, jamais copié automatiquement dans les extensions.
Une panne doit restaurer la racine RO (`ro`) ; utiliser la même gestion
`if ...; then ro; else code=$?; ro; exit "$code"; fi` que pour RC12.1.

Pour une activation ultérieure : tester une origine TLS dédiée, certificats,
nginx `-t`/`-T`, comptes réels séparés, HTTP/WebSocket/API natives, KVM complet,
refus terminal/legacy/VNC, accès SSH limité et révocation, puis récupération
root. La passerelle exige un rapport root privé
`/etc/kvmd/portable-security-native-tests.json` attestant ces essais et son
empreinte dans `/etc/kvmd/portable-security-activation.json`, liée au manifeste
d’intégrité installé et à une origine HTTPS précise. Ces fichiers ne sont
créés ni par l’API ni par l’installateur. Elle refuse une autre version KVMD,
une auth native désactivée ou un accès Unix non vérifié.

**Sans cette validation native, les comptes restreints ne sont pas activés en
production.** Aucun clic dans une grille de droits ne remplace ce contrôle.

## Retour RC12.1

Utiliser l’installateur du stage RC13 avec sa **nouvelle sauvegarde RC12.1**.
Après lecteurs/transferts/SHARE libérés et autorisation de restauration :

```bash
rw
if python3 -B "$stage/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID; then
    ro
else
    result=$?
    ro
    exit "$result"
fi
```

Le rollback vérifie toutes les sauvegardes avant arrêt, ferme/désactive la
passerelle si présente, restaure les fichiers et préférences, puis l’état PST
de sécurité précédent. L’état abandonné est sauvegardé avant retrait. Les
identités/mots de passe natifs n’ayant pas changé, ils ne sont pas remplacés
automatiquement par une ancienne copie. Leurs copies privées sont disponibles
pour une récupération distincte et examinée.

Un éventuel vhost TLS ajouté manuellement doit être retiré après validation
nginx, sans modifier les routes administrateur. Les comptes Linux ne sont
jamais effacés ni leurs homes supprimés par le rollback applicatif. Si leurs
helpers sont retirés, l’authentification par clé échoue fermée (`AuthorizedKeysFile
none`, méthode publickey uniquement). Les désactiver par leur shell nologin
avant un retrait manuel du confinement SSH ; vérifier leur UID/mapping et
conserver l’accès root. Ne jamais retirer un garde SSH en laissant un compte
avec un shell libre.

## Validation et limites de la candidate

Validation du 5 novembre 2026 : 361 tests Python locaux, aucun échec,
6 cas réservés à Linux ; puis 22 tests ciblés incluant le nouveau cas sudo.
23 tests JavaScript et 9 suites navigateur réussis. Les tableaux de sécurité
conservent une largeur lisible sur mobile, avec défilement interne tactile et
clavier ; l’accès aux actions et l’absence de débordement de page sont testés.
La fermeture des navigateurs attend les interceptions réseau en cours,
sans masquer les assertions. Ces résultats concernent des données isolées,
jamais les ISO ou comptes du Pi de production.

Les tests isolés couvrent comptes, mots de passe, rôles, dernière administration,
élévation par réinitialisation de mot de passe, corruption, concurrence, CSRF,
WebSocket/HID, sessions, délégations non rejouables, sauvegardes et restauration.
Le navigateur teste le gestionnaire, les clés publiques, les rôles personnalisés,
la persistance et les régressions KVM/OLED/USB/SHARE, sur données synthétiques.
Un job distinct utilise **OpenSSH réel dans un conteneur jetable**, sans réseau
extérieur à l’exécution, pour UID, clés, absence de sudo/shell/tunnels,
révocation et récupération root. Les clés privées de test restent dans ce
conteneur et disparaissent avec lui.

Le test OpenSSH a reproduit un cas réel de `sudo -l -U` : un code de sortie
0 accompagné d’un refus explicite pour l’utilisateur interrogé. Le contrôle
accepte uniquement ce refus complet et identifié, sans liste de commandes ;
une réponse ambiguë, un droit présent ou une erreur de politique bloque le
provisionnement. Un avertissement DNS isolé reconnu ne remplace jamais ce refus.

Le backend matériel des tests passerelle est synthétique ; ils ne remplacent
pas une validation de la passerelle contre tous les services KVMD réels du Pi.
Les fixtures navigateur du moteur natif 4.213 restent inchangées. Aucun compte
restreint ni Codex Linux n’a été créé sur le Pi, aucune clé privée de production
n’a été générée et aucune nouvelle authentification n’a été déployée.
Les performances de RC13 sur le Pi ne sont pas revendiquées avant ce test
autorisé. Cadences, connexions, sessions, tailles et vérifications PBKDF2 sont
bornées pour limiter la charge ; aucun swap ni dépendance matérielle ajouté.
[Mesures locales du validateur](performance/rc13-local.json), sur PC uniquement.

Audit passif du Pi : KVMD 4.213, Python 3.14.7, aiohttp 3.13.5, htpasswd interne,
seul utilisateur Web natif `admin`, service VNC inactif. Les sockets KVMD et
uStreamer sont 0660 UID/GID 961 ; les périphériques GPIO sont 0660 groupe 963.
Le compte Codex ne reçoit aucun de ces groupes. GPIO17 est resté OUTPUT HIGH,
GPIO18 INPUT `--` relâché LOW ; aucun service n’a été modifié. Le dump SSH réel
emploie CamelCase (`Port`, `AddressFamily`) : le parseur accepte ce format et
le format minuscule sans changer les valeurs ; les options effectives complètes
devront réussir le précontrôle du plan avant tout provisionnement.
