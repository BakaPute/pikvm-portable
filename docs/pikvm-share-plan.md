# PIKVM-SHARE — analyse et plan technique

Plan initial conservé pour expliquer les choix. L'implémentation locale est
désormais décrite dans [pikvm-share.md](pikvm-share.md), qui fait référence pour
l'installation et la maintenance. Aucun déploiement effectué par Codex.
Diagnostic confirmé par l'utilisateur : KVMD 4.213, Python 3.14.7, Drive 1 éjecté,
image exFAT de 4 Gio saine et partition PIMSD en RW.

## État connu et vérifications restantes

Le dépôt local pointe vers `BakaPute/pikvm-portable`, dernier commit observé
`2201ab9`. L'arbre était propre avant l'ajout de ce plan et du diagnostic.
Aucun fichier AGENTS.md trouvé dans le projet.

Selon l'utilisateur, Drive 1 (`mass_storage.usb1`) est fonctionnel et éjecté ;
`/var/lib/kvmd/msd/.PIKVM-SHARE.img` contient un exFAT de 4 Gio déjà testé.
Ces éléments restent à confirmer par lecture de l'appareil.
`reference/kvmd-info.txt` mentionne KVMD 4.66-1 : c'est une référence historique,
pas une mesure de la version actuellement installée.

Constats dans le code :

| Élément | Conséquence pour PIKVM-SHARE |
| --- | --- |
| `scripts/pikvm-usb-transfer` cible `mass_storage.usb0`, appelle `kvmd-otgmsd` sans index et écrit dans UDC | Ne pas réutiliser son mécanisme de bascule : il touche le Drive 0 et l'USB global. |
| Ce script crée/recrée `.USB-TRANSFER.img` de 64 Gio et reformate après import | Ne jamais adapter ces fonctions à `.PIKVM-SHARE.img`. Aucun formatage dans le nouveau gestionnaire. |
| `web/share/js/usb-transfer.js` agit sur `/api/msd/set_params` | Conserver l'outil historique, mais aucune requête PIKVM-SHARE vers l'API du Drive 0. |
| Image Manager et Wi-Fi Wizard utilisent un manifeste Extras et nginx avec `loc-login.conf` | Réutiliser ce modèle d'intégration après vérification de l'authentification installée. |
| `wifi-wizard-api` écoute en root sur 127.0.0.1:9876 | Isoler la nouvelle API pour éviter de bloquer batterie/Wi-Fi pendant les transferts. |
| `pikvm-image-folders`, l'ancien transfert et l'API d'images remontent le stockage MSD en RW/RO | Le verrou du nouveau service ne suffira pas : vérifier aussi les remontages déclenchés par KVMD. |
| `pikvm-auto-shutdown` ne surveille que HDMI et HID | Prévoir une inhibition coordonnée pendant les accès SHARE, sans écrire les GPIO. |
| `install.sh` configure GPIO17/18 et redémarre KVMD | Ne pas l'exécuter sur l'appareil pour ajouter SHARE. Prévoir une installation ciblée. |
| Les sauvegardes actuelles de l'installateur couvrent seulement certains fichiers web | Étendre la sauvegarde aux scripts, services, manifestes et configurations modifiés. |

## Architecture prévue

Application `/extras/pikvm-share/` indépendante, ajoutée à l'accueil PiKVM par
un manifeste Extras. Interface en français : état USB/Web, navigation, fil
d'Ariane, liste des fichiers/dossiers, création de fichier vide et de dossier,
renommage, suppression confirmée, import avec progression/annulation,
téléchargement et espace réellement utilisé/disponible dans l'exFAT.
Suppression initialement limitée aux fichiers et dossiers vides ; aucune
suppression récursive implicite. Ne jamais afficher la taille sparse de l'image
comme l'espace libre du volume. En mode USB, indiquer que les chiffres du
dernier montage Web sont anciens, ou les rendre indisponibles.

Service dédié `pikvm-share-api.service`, proxy nginx authentifié et socket Unix
avec permissions restreintes, sous `/run/pikvm-share/`. Le processus chargé
des montages nécessitera des privilèges ; limiter ses commandes et chemins
à une liste fixe, sans shell construit depuis les entrées utilisateur.
Choix du serveur Python après inventaire des dépendances installées.
Pas de nouveau port accessible au réseau.

Protéger **toutes** les routes : état, listes, espace, téléchargements et
mutations. Vérifier le comportement effectif de `loc-login.conf`, des sessions
PiKVM et de la configuration nginx générée. Ajouter protection CSRF pour les
mutations, contrôle d'origine et absence de CORS permissif. Ne pas se fier à
un en-tête utilisateur fourni par le navigateur. Ne jamais réutiliser ni
stocker le mot de passe SSH pour l'authentification Web.

API indicative : `GET status`, `GET files`, `GET download`, `POST upload`,
`POST mkdir`, `POST create-file`, `POST rename`, `POST delete`,
`POST mode/web`, `POST mode/usb`. Erreurs structurées et traduites : conflit
de mode, éjection attendue, montage occupé, espace insuffisant, volume sale,
nom existant, session expirée. Les téléchargements restent des pièces jointes,
sans exécution de HTML importé dans l'origine PiKVM.

## Bascule et garanties de sécurité

États : `usb`, `waiting_eject`, `detached`, `mounting`, `web`, `unmounting`,
`error`. Un état JSON est informatif ; la vérité vient de configfs, des
montages et des associations loop. En cas d'incertitude : refuser l'accès.

1. USB vers Web : demander l'éjection dans l'OS du PC, observer ensuite que
   `mass_storage.usb1/lun.0/file` est vide. Ne jamais vider ce fichier ni utiliser
   `forced_eject` pour simuler une éjection propre. Un délai ou un bouton de
   confirmation ne remplace pas cette vérification.
2. LUN vide ne prouve pas à lui seul une éjection propre passée. Sur un premier
   démarrage ou après perte de suivi, afficher « détaché, historique inconnu ».
   Exiger confirmation explicite de l'éjection déjà réalisée, vérifier la
   cohérence du volume hors ligne sans réparation, et bloquer si elle est
   douteuse. Tester le comportement réel SCSI sous Ubuntu puis Windows avant
   de promettre une détection automatique.
3. Sous verrou exclusif, vérifier l'identité du fichier, sa taille, l'absence
   d'attachement dans **tous** les LUN, et l'absence de montage/loop concurrent.
   Détecter la disposition exFAT réelle : volume direct ou partition. Ne pas
   présumer un offset ; ne pas lancer de réparation automatique.
4. Monter seulement ensuite dans `/run/pikvm-share/mnt`, avec
   `nosuid,nodev,noexec`, options et permissions adaptées à exFAT.
5. Web vers USB : refuser de nouveaux accès, attendre/annuler proprement les
   transferts, synchroniser, démonter normalement, libérer les loops détenus
   par SHARE, vérifier l'absence de montage, puis attacher exclusivement au
   Drive 1. Toute commande `kvmd-otgmsd` devra cibler explicitement l'index 1,
   après examen de l'aide et du code installés. Aucun démontage forcé/paresseux.
6. Échec de démontage : état d'erreur et aucun attachement USB. Après crash ou
   redémarrage : réconcilier l'état physique, ne jamais reconnecter d'office
   une image dont le montage n'est pas exclu.

Un verrou partagé entre transitions et opérations protège toute leur durée,
y compris les flux upload/download. Vérifications de chemins contre traversée,
liens et courses ; noms compatibles exFAT et collisions de casse ; aucun
écrasement implicite. Imports par morceaux bornés en mémoire, fichier temporaire
sur le volume puis publication atomique, traitement des annulations et de ENOSPC.

L'image ne doit être publiée dans aucun sélecteur d'images pouvant l'attacher
au Drive 0. Son nom caché doit rester protégé. Auditer tous les chemins natifs
qui pourraient néanmoins l'attacher ou la modifier. Un verrou applicatif ne
protège pas d'une commande root extérieure ; aucun gestionnaire parallèle du
Drive 1 ne doit rester actif pendant SHARE.

**Point à résoudre avant déploiement :** l'image réside sur le stockage MSD
partagé. Il faut coordonner les remontages RW/RO avec KVMD et les outils
historiques sans empêcher l'usage normal du Drive 0. Un simple `finally: remount
ro` peut interrompre SHARE. Auditer le helper installé et retenir une stratégie
compatible (gestion commune des utilisateurs RW, ou modification minimale
des points de remontage). Si la coexistence ne peut pas être garantie, ne pas
déployer une solution qui désactive le Drive 0 pour contourner le problème.

L'arrêt automatique doit respecter une inhibition vérifiable pendant les
opérations et lorsque l'image est exposée en écriture. Prévoir arrêt du service
avec démontage propre et durée suffisante ; aucun changement des scripts
d'alimentation, aucune écriture GPIO17/18, aucun redémarrage dans le déploiement
ciblé. Toute adaptation de l'arrêt automatique sera présentée avant application.

## Fichiers et étapes de réalisation

1. Diagnostic en lecture seule avec `scripts/pikvm-share-diagnose.sh` ; inspection
   complémentaire du code local KVMD/helper et des règles nginx, sans secrets.
2. Ajouter `scripts/pikvm-share-api`, `systemd/pikvm-share-api.service`,
   `web/extras/pikvm-share/{index.html,app.js,style.css,pikvm-share.svg}` et
   `kvmd-extras/pikvm-share/{manifest.yaml,nginx.ctx-http.conf,nginx.ctx-server.conf}`.
3. Ajouter tests du contrôleur de modes, validation de chemins, authentification
   et transferts. Utiliser des doubles configfs et une image jetable distincte
   pour les tests Linux de montage ; jamais l'image réelle.
4. Ajouter un installateur SHARE ciblé, idempotent, avec précontrôles, sauvegarde,
   restauration et validation nginx avant rechargement. Aucun redémarrage KVMD,
   aucune manipulation UDC ou GPIO. L'intégrer à `install.sh` pour les futures
   installations, sans appeler la configuration matérielle dans le chemin ciblé.
   Image absente : message bloquant, aucune création/reformatage automatique.
   Nouvelle microSD : restauration d'une sauvegarde ou provisionnement séparé
   explicitement autorisé ; ne pas supposer le Drive 1 déjà configuré.
5. Mettre à jour README, documentation de réinstallation et contrôles en lecture
   seule ; préparer une branche `codex/pikvm-share`, commits et publication GitHub.
6. Présenter le diff, les tests et les commandes exactes ; attendre l'autorisation
   explicite avant sauvegarde opérationnelle, installation ou essai modifiant le Pi.

## Sauvegarde et restauration à implémenter

Avant installation autorisée : archive datée des fichiers applicatifs/configurations
touchés, permissions, état d'activation des services et version du dépôt, plus
inventaire des fichiers initialement absents. Ne pas archiver de secrets dans Git.
La restauration remet ces fichiers et l'état des services, retire exclusivement
les ajouts SHARE, valide nginx puis recharge ; elle ne touche ni Drive 0 ni GPIO.

Sauvegarde de données distincte : uniquement après éjection et démontage validés,
avec exclusivité maintenue pendant toute la copie de `.PIKVM-SHARE.img` vers
un support disposant de l'espace nécessaire. Vérifier taille et empreinte de
la copie ; ne pas sauvegarder une image active. Conserver une copie hors du Pi.

Restauration de l'image : procédure séparée soumise à autorisation explicite,
image détachée et non montée, sauvegarde de la version actuelle avant tout
remplacement, vérification de la copie et contrôle hors ligne sans réparation.
Aucun formatage ni suppression de l'original. Restaurer l'application ne doit
jamais restaurer ou remplacer automatiquement les données.

## Validation requise

- Drive 0, ISO, clavier/souris, batterie, Wi-Fi, OLED et bouton restent fonctionnels.
- Éjection absente, débranchement USB seul, volume sale, montage occupé, état perdu
  et LUN inattendu interdisent une bascule dangereuse.
- Deux navigateurs, téléchargement actif et upload annulé ne permettent jamais
  un montage et un attachement USB simultanés.
- Fichiers vides, Unicode, noms exFAT invalides, collisions, gros fichiers,
  manque d'espace et traversées de chemins sont traités.
- Aucune route de gestion accessible sans session valide ; tests CSRF et
  téléchargement HTML en pièce jointe.
- Tester les remontages MSD natifs pendant les deux modes SHARE, le crash du
  service, l'inhibition d'arrêt et le retour arrière sur un environnement de test.
- Comparer les attributs Drive 0 avant/après chaque bascule ; ne jamais les écrire.

## Diagnostic SSH sans transmettre le mot de passe à Codex

Dans **ton propre terminal PowerShell**, depuis la racine du projet :

```powershell
Get-Content -Raw .\scripts\pikvm-share-diagnose.sh | ssh -T -o PubkeyAuthentication=no -o PreferredAuthentications=password -o PasswordAuthentication=yes -o StrictHostKeyChecking=ask root@10.101.4.99 'bash -s'
```

Vérifier l'empreinte de l'hôte par un moyen de confiance si SSH la demande.
Saisir le mot de passe uniquement dans l'invite SSH masquée du terminal.
Ne pas le transmettre dans le chat. Cette méthode ne copie aucun script sur
le Pi et n'y écrit aucun fichier. Si le pipeline empêche l'invite sur le terminal,
ouvrir une session avec les mêmes options SSH et coller le contenu du diagnostic
après authentification. Transmettre seulement le résultat du diagnostic.

## Sources techniques

- [PiKVM — Mass Storage Drive](https://docs.pikvm.org/msd/) : distinction premier
  lecteur/lecteurs supplémentaires et sélection explicite de l'index. La page
  actuelle vise KVMD >= 4.230 ; vérifier la version réelle avant transposition.
- [Linux — Mass Storage Gadget](https://docs.kernel.org/usb/mass-storage.html) :
  contraintes d'accès au backing file, éjection SCSI des supports amovibles et
  signification des attributs `file` et `forced_eject`.
