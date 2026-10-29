# PIKVM-SHARE

Gestionnaire Web indépendant de l'image existante
`/var/lib/kvmd/msd/.PIKVM-SHARE.img`, pour le **Drive 1 uniquement**.
Développement local terminé ; aucun déploiement ni essai matériel effectué par
Codex. Plateforme cible confirmée : KVMD 4.213, Python 3.14.7, Pi Zero 2 W.

## Fonctionnement

L'application apparaît parmi les Extras PiKVM et à `/extras/pikvm-share/`.
Elle utilise la session Web PiKVM existante, distincte du mot de passe SSH.
Toutes les routes API, y compris état et téléchargement, vérifient cette session.
L'API refuse de fonctionner si l'authentification PiKVM est désactivée.

- Navigation, fichiers cachés ordinaires, création de dossiers et fichiers vides.
- Renommage, suppression de fichiers et dossiers vides, confirmation avant suppression.
- Téléchargements en pièce jointe, sans exécuter les fichiers HTML importés.
- Imports multiples séquentiels, progression, annulation, blocs de 1 Mio et
  fichiers temporaires non publiés tant que l'import n'est pas terminé.
- Espace exFAT réellement disponible/utilisé en mode Web.
- Validation des noms exFAT/Windows, des chemins, des collisions et de la session.

USB → Web : éjecter proprement PIKVM-SHARE dans l'OS du PC, puis cocher la
confirmation et choisir « Passer en gestion Web ». Tant que le backing file
du Drive 1 reste renseigné, le montage est refusé. Débrancher le câble ne suffit
pas. Le service ne vide jamais le LUN et n'utilise jamais `forced_eject`.
Le volume est contrôlé avec `fsck.exfat -n` hors ligne avant chaque montage.
Une erreur bloque le montage, sans réparation ni formatage automatique.

**Limite de preuve :** un LUN vide ne certifie pas historiquement que l'OS a
vidé ses caches. La confirmation utilisateur est donc obligatoire, notamment
si SHARE n'a pas observé la connexion précédente. Le contrôle hors ligne ne
prouve pas la sauvegarde des données encore dans le cache du PC. Aucune
commande root extérieure ne doit manipuler le Drive 1 ou monter cette image
pendant que le service la gère.

Web → USB : finir ou annuler les imports, puis connecter au PC. Un verrou
protège l'intégralité des téléchargements, écritures et transitions. Le volume
doit être synchronisé, démonté normalement et ses loops libérés avant tout
attachement `kvmd-otgmsd -i 1`. Un démontage occupé bloque la connexion.

« Démonter / récupérer » quitte le mode Web, annule les imports en attente et
libère la réservation après vérification de l'état physique. Après un crash,
la réservation conservée impose cette récupération ; aucun retour automatique
à l'USB. Les fichiers temporaires réservés sont nettoyés au démontage.
Les imports abandonnés expirent après 15 minutes d'inactivité, lors de la
prochaine requête en mode Web.

## Coexistence avec PiKVM Portable

Aucun changement des scripts batterie, Wi-Fi, OLED, bouton ou alimentation.
Aucune écriture des GPIO, du Drive 0 ou de l'UDC ; aucun redémarrage KVMD.
Les correctifs Python 3.14 et HTML existants ne sont pas remplacés.

Une intégration ciblée est nécessaire pour la partition MSD partagée :
`kvmd-helper-otgmsd-remount` est sauvegardé, puis remplacé par une garde.
La copie native est conservée sous
`/usr/local/lib/pikvm-share/native/kvmd-helper-otgmsd-remount`, **avec le même
nom de fichier**, requis par le code natif. La garde transmet les demandes RW
et toutes les demandes hors réservation. Pendant une réservation SHARE, elle
diffère seulement les demandes RO, afin de protéger les écritures exFAT et de
laisser fonctionner les uploads natifs. Elle ne manipule aucun LUN.
Le stockage peut rester RW après libération jusqu'à la prochaine demande RO
native ; SHARE ne le remonte pas arbitrairement en RO au milieu d'un upload ISO.

Pendant la réservation, le service d'arrêt automatique est arrêté s'il était
actif ; il est redémarré à la libération. Son code et sa configuration restent
inchangés. Une interruption laisse cette information dans la réservation pour
la récupération. Après une éjection PC, choisir Web ou « Démonter / récupérer »
pour libérer la réservation. Un arrêt manuel ou physique reste sous le contrôle
de l'utilisateur ; éjecter et démonter avant un arrêt du Pi.

Après mise à jour PiKVM, le paquet peut remplacer la garde. Quitter SHARE avant
la mise à jour puis relancer l'installation ciblée avant de réutiliser SHARE.
L'installateur sauvegarde la nouvelle version native sans modifier ses correctifs.

## Déploiement préparé — à exécuter seulement après autorisation

Connexion depuis ton propre terminal, mot de passe saisi dans l'invite masquée :

```powershell
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password -o PasswordAuthentication=yes -o StrictHostKeyChecking=ask root@10.101.4.99
```

Sur le Pi, dans le clone GitHub contenant cette version :

```bash
cd /root/pikvm-portable
python3 scripts/pikvm-share-install check
```

Ce précontrôle est en lecture seule. Il exige l'image existante, le Drive 1
éjecté, aucun montage/loop/réservation, les commandes système nécessaires et
l'authentification PiKVM active. Ne pas remplacer ce contrôle par un formatage.

Pour l'installation autorisée, quitter tout transfert SHARE et natif, puis :

```bash
rw
bash install.sh --share-only
ro
```

`--share-only` bifurque **avant** les commandes matérielles de l'ancien
installateur. `bash install-share.sh` est équivalent. Ne pas lancer l'installateur
Portable complet pour ajouter SHARE à ce Pi déjà configuré.

L'installation crée une sauvegarde applicative datée dans
`/root/pikvm-share-backups/`, installe l'API, le service, les fichiers web et
Extras, puis génère et valide la configuration nginx avant son rechargement.
Elle active seulement `pikvm-share-api.service`. Elle ne redémarre pas KVMD,
ne copie pas les fichiers web historiques et ne recrée pas l'image.
Un échec entraîne un retour arrière si le stockage est au repos ; si le nettoyage
échoue, les outils de récupération et la garde restent en place.

```bash
systemctl is-active pikvm-share-api.service
journalctl -u pikvm-share-api.service -n 30 --no-pager
```

Ouvrir ensuite `/extras/pikvm-share/` depuis la session PiKVM. Vérifier une
création/import/téléchargement, éjection et bascule dans chaque sens. Comparer
par lecture les attributs du Drive 0 avant et après et vérifier que l'ISO,
clavier/souris et fonctions Portable restent disponibles. Ces essais matériels
ne sont pas remplacés par les tests locaux.

L'API écoute seulement sur `127.0.0.1:9877`. Nginx protège l'application et
retransmet la session à l'API, qui vérifie aussi `/auth/check` via le socket KVMD.
Les mutations exigent un en-tête non simple et un contrôle de l'origine ; aucun
CORS n'est ouvert. Aucun mot de passe SSH n'est stocké ou transmis à cette API.

## Sauvegarde des données

Éjecter côté PC, choisir « Démonter / récupérer », arrêter uniquement SHARE.
Prévoir plus de 4 Gio libres sur la destination, hors de la partition MSD :

```bash
rw
systemctl stop pikvm-share-api.service
python3 scripts/pikvm-share-install backup-image /root/PIKVM-SHARE.backup.img
systemctl start pikvm-share-api.service
ro
```

La destination doit être nouvelle. La copie est complète, contrôlée par SHA-256,
accompagnée d'un fichier `.sha256`. L'arrêt automatique est suspendu pendant la
copie. Conserver ensuite la copie et son empreinte hors du Pi, par transfert SSH
classique avec mot de passe interactif. Ne pas ajouter ces fichiers à Git.
Une copie interrompue est conservée pour inspection et n'est pas une sauvegarde
valide tant que sa vérification n'a pas réussi.

## Restauration

Application : SHARE doit être détaché et démonté. Après autorisation :

```bash
rw
python3 scripts/pikvm-share-install restore-app /root/pikvm-share-backups/DATE-ID
ro
```

Le manifeste restaure les fichiers et permissions antérieurs, supprime uniquement
les ajouts enregistrés et rétablit l'état actif/activé antérieur du service.
La configuration nginx sauvegardée est testée avant rechargement. L'image n'est
jamais remplacée par une restauration applicative.

Données : procédure séparée, avec autorisation explicite et empreinte de
confiance. SHARE doit être arrêté, éjecté et non monté :

```bash
rw
systemctl stop pikvm-share-api.service
python3 scripts/pikvm-share-install restore-image /root/PIKVM-SHARE.backup.img --sha256 EMPREINTE_64_HEXADECIMALE --confirm-restore
systemctl start pikvm-share-api.service
ro
```

La copie est contrôlée hors ligne sans réparation. L'ancienne image, si présente,
est conservée sous `.PIKVM-SHARE.pre-restore-IDENTIFIANT.img` avant substitution.
Il faut donc 4 Gio libres supplémentaires sur MSD. Aucun formatage, aucune
suppression de l'original et aucune reconnexion USB automatique. Les éventuels
fichiers de préparation d'une restauration échouée sont conservés pour inspection.

Si le service ne démarre plus après une interruption : après éjection PC,
arrêter le service puis utiliser `pikvm-share-api --recover` en root. Cette
commande prend le verrou du processus et ne force jamais un démontage occupé.
Si elle refuse, conserver la réservation et relever montages/loops ; ne pas
vider le LUN ni supprimer les fichiers de verrouillage pour forcer la suite.

## Réinstallation depuis GitHub

Le dépôt doit d'abord contenir ces fichiers dans une branche publiée ; le
travail local n'est pas automatiquement disponible sur GitHub.
Sur une nouvelle carte, restaurer la configuration matérielle existante et
la configuration Drive 1 selon la procédure Portable, avant usage opérationnel.
SHARE ne modifie pas `override.yaml`, ne crée pas de lecteur supplémentaire,
et ne redémarre pas le gadget pour contourner l'absence de Drive 1.

Restaurer ensuite l'image sauvegardée avec `restore-image` (possible avant
l'installation SHARE si Drive 1 est déjà configuré), puis lancer l'installation
ciblée. Une image absente fait volontairement échouer `install` ; aucun image
vide ne remplace silencieusement les données. Le provisionnement d'une image
neuve reste une opération distincte explicitement autorisée.

## Tests locaux et CI

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/pikvm-share-api scripts/pikvm-share-install scripts/pikvm-share-remount
bash -n install.sh
bash -n install-share.sh
bash -n scripts/pikvm-share-diagnose.sh
node --check web/extras/pikvm-share/app.js
```

Les tests utilisent des répertoires jetables, un backend simulé et un serveur
HTTP local. Ils ne contactent pas le Pi et ne montent aucune image. La CI GitHub
prépare ces contrôles sous Python 3.11 et 3.14 ; son exécution attend la publication.
La compatibilité matérielle, les montages Linux et nginx 4.213 devront encore
être validés sur l'appareil après autorisation.

Validation locale du 29 octobre 2026 : Python 3.12.14, 40 tests exécutés,
39 réussis et un test de création de lien symbolique ignoré faute de privilège
Windows (prévu pour s'exécuter sur Linux en CI). Compilation des trois scripts
Python, syntaxe JavaScript et Bash, et `git diff --check` réussis. Aucun montage
réel, aucune connexion SSH et aucune modification du Raspberry Pi pendant ces tests.

Références vérifiées : [authentification KVMD](https://github.com/pikvm/kvmd/blob/master/kvmd/apps/kvmd/api/auth.py),
[helper de remontage](https://github.com/pikvm/kvmd/blob/master/kvmd/helpers/remount/__init__.py),
[service nginx](https://github.com/pikvm/kvmd/blob/master/configs/os/services/kvmd-nginx.service).
Le code installé 4.213 reste la référence finale, notamment pour les commandes
de génération nginx ; une incompatibilité fait échouer l'installation avec sauvegarde.
