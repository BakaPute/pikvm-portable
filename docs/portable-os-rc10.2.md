# PiKVM Portable OS 0.2.0-rc.10.2 — candidate

**Validation matérielle en attente. Aucun déploiement effectué.** Le test local
charge le DOM et les contrôleurs réels de KVMD 4.213 dans un navigateur, mais ses
API, événements serveur, médias et hôte USB sont simulés. Il ne valide pas le Pi,
le streaming réel, les sept ISO existantes ni leur montage côté PC.

## Correction

Le navigateur de dossiers existant `web/share/js/drive-folders.js` conserve le
sélecteur natif dans le DOM. Son bouton ouvre `#pkdf-panel` dans `#pkdf-overlay`,
ajouté directement au body. Le style de la console intégrée cache les éléments
extérieurs au flux vidéo : l'overlay était donc invisible. L'adaptateur projetait
le menu MSD et les confirmations natives, mais pas ce navigateur externe.

L'adaptateur projette maintenant ce seul navigateur connu dans un dialogue
Portable OS. Les nœuds source, événements, navigation de dossiers, sélection,
vérifications d'image complète, état occupé/connecté et exclusion du transfert
restent dans l'implémentation existante. Les connexions/éjections et modes CD/DVD,
Flash et lecture seule restent gérés par le contrôleur natif KVMD. Les radios
projetées conservent désormais leur groupe exclusif sans mélanger les panneaux.
Échap, fermeture, navigation et suspension ferment aussi le sélecteur source.

La commande affiche **Lecteur ISO** ; `msd-dropdown`, les API MSD et Drive 0
restent inchangés. **Clé USB**, placé immédiatement après, ouvre un résumé
authentifié en lecture seule du Drive 1 : état SHARE, transfert occupé, preuve USB,
erreurs et lien vers `#share`. Ouvrir/actualiser ce panneau ne fait que des GET.
Les changements de mode et les fichiers restent dans la page SHARE existante,
avec sa confirmation d'éjection propre et son exclusivité exFAT. Les réponses
tardives après fermeture sont ignorées ; la session expirée suspend l'adaptateur.
Le poller partagé assure les actualisations suivantes, sans nouvelle boucle.

Le correctif ne modifie ni backend de stockage/transfert, ni règles de montage,
ni lecteur GPIO, ni services d'alimentation, ni moteurs vidéo, ni transaction de
sauvegarde/restauration. Aucun fichier de données n'est inclus dans l'archive.

## Tests reproductibles, sans matériel

```bash
python -B -m unittest discover -s tests -v
node --test tests/portable-ui.test.mjs
# Avec Playwright 1.62.1 installé uniquement sur le poste de développement :
python -B tests/portable_preview.py --port 8765
# Dans un autre terminal, avec NODE_PATH pointant vers Playwright :
node tests/portable-native-4213.cjs
node tests/portable-browser.cjs
node tests/portable-kvm-layout.cjs
node tests/portable-dialogs.cjs
node tests/portable-transfer.cjs
```

Le corpus upstream sous `tests/fixtures/kvmd-4.213` est accompagné de sa licence,
de sa provenance et d'empreintes vérifiées par le test. Il n'est pas installé sur
le Pi. Les sept ISO synthétiques reproduisent les quatre dossiers signalés ; les
mutations HTTP sont interceptées, sans accès aux véritables images.

Résultats locaux Windows : 233 tests Python exécutés, 227 réussis et 6 ignorés
(sockets Unix, permissions de liens symboliques et primitives mémoire/verrous
Linux). 23 tests Node réussis. Cinq suites navigateur réelles Edge/Playwright
réussies, dont les mises en page 1920×1080, 1366×768, 820×1180 et 390×844.
Validation nginx locale incluse dans la suite Python. Python utilisé localement :
3.12.14 ; la CI prévoit Python 3.14 et Chromium/Linux, sans revendiquer son
exécution distante ni un test sur Python 3.14.7/KVMD installés sur le Pi.

Le test couvre ouverture du sélecteur, sous-dossiers, parent/racine, recherche,
espaces, image cachée de transfert, sélection, connexion, état réel simulé,
éjection/changement, Flash/CD/DVD, refus en cours de transfert/lecteur occupé,
erreurs GET/POST, confirmations KVMD, fermeture/Échap/navigation, mobile, panneau
SHARE occupé/423/401, aucune mutation à l'ouverture et reprise clavier/souris via
les contrôleurs natifs. Les suites précédentes couvrent RC9 à RC10.1.

## Mise à jour depuis RC10.1 — uniquement après autorisation

Garder le stage RC10.1 et toutes les sauvegardes existantes. Construire si besoin :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python -B scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
$PiKvmHost = Read-Host 'Adresse actuelle du PiKVM'
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.10.2.tar.gz private/pikvm-portable-os-0.2.0-rc.10.2.tar.gz.sha256 "root@${PiKvmHost}:/tmp/"
ssh @sshOptions "root@${PiKvmHost}"
```

Saisir le mot de passe exclusivement aux invites SSH/SCP. Après autorisation de
transfert, extraction et vérification, sur le Pi :

```bash
set -euo pipefail
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.10.2.tar.gz.sha256
stage=$(mktemp -d /tmp/portable-rc10.2.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.10.2.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
bash install-portable-os.sh check 2>&1 | tee /tmp/portable-rc10.2-check.log
```

Ne pas poursuivre après un échec. Conserver les journaux détaillés du précontrôle
RC10.1, notamment sous pression mémoire. Ne lancer ni bootstrap `install.sh`, ni
mise à jour globale, ni réparation Python non nécessaire, ni reset USB. Le contrôle
ne connecte/monte/éjecte aucun lecteur. Prévoir la fenêtre de maintenance habituelle,
terminer les transferts et libérer les volumes selon les préconditions existantes.

Après réussite du contrôle **et autorisation explicite d'installation** :

```bash
rw
if bash "$stage/install-portable-os.sh" install; then
    ro
else
    status=$?
    ro
    printf 'Installation échouée (%s), conserver les journaux.\n' "$status" >&2
    exit "$status"
fi
```

Noter le chemin **Sauvegarde : /root/pikvm-portable-os-backups/DATE-ID** imprimé
par cette transaction. Il contient les fichiers remplacés et leurs empreintes.
L'installateur conserve la vérification nginx, les contrôles de compatibilité et
le refus des correctifs locaux non reconnus ; rollback automatique en cas d'échec.
Aucun redémarrage matériel n'est requis. Les interfaces précédentes restent
accessibles via `/legacy/` et le KVM de secours `/kvm/`. Recharger Portable OS avec
Ctrl+Maj+R pour charger les nouveaux modules frontend.

## Recette réelle requise avant validation

1. Confirmer RC10.2 affichée, KVMD 4.213, session authentifiée, vidéo et HID.
2. Ouvrir Lecteur ISO, puis Choisir une image. Vérifier les sept noms et les
   dossiers Windows/Win10, Windows/Win11, Linux/Debian, Linux/Ubuntu, navigation,
   recherche et fermeture. Aucune suppression, déplacement ou réécriture d'ISO.
3. Après accord de présentation USB à l'hôte et état libre confirmé, sélectionner
   une ISO existante **en CD/DVD lecture seule**, connecter, vérifier son état
   KVMD et sa présence sur le PC. Éjecter proprement côté PC puis déconnecter.
   Choisir une autre ISO, vérifier le changement et revenir à l'état initial.
   Tester les modes sur un support synthétique autorisé si nécessaire ; ne jamais
   activer l'écriture sur les ISO réelles. Ne pas toucher à `.USB-TRANSFER.img`.
4. Ouvrir Clé USB dans les états connus : aucun changement de mode/connexion ne
   doit apparaître au simple affichage. Vérifier le lien SHARE, les erreurs, le
   transfert occupé, et la conservation de l'éjection propre/exclusion Web/USB.
5. Après chaque panneau/dialogue, confirmer clavier/souris (puis libérer la
   capture), vidéo continue et absence de rechargement du moteur. Vérifier aussi
   mobile/tactile, session expirée, KVM de secours et interfaces précédentes.
6. Lire les journaux et confirmer les états d'alimentation/lecteurs inchangés.
   Une anomalie interdit de conclure à la validation matérielle.

Cette recette n'a pas été exécutée dans le cadre du développement local.

## Retour immédiat à RC10.1

Sans installation, réutiliser le stage précédent suffit. Après installation,
utiliser la sauvegarde de **cette** mise à jour (pas une sauvegarde plus ancienne),
après libération des transferts/volumes et autorisation de restauration :

```bash
rw
if python3 -B "$stage/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID; then
    ro
else
    status=$?
    ro
    printf 'Restauration échouée (%s), conserver les sauvegardes.\n' "$status" >&2
    exit "$status"
fi
```

Recharger avec Ctrl+Maj+R. La restauration vérifie le manifeste avant arrêt des
services, restaure les fichiers/états sauvegardés et vérifie nginx. Elle ne restaure
ni ne supprime d'ISO ou de conteneur SHARE. En cas d'échec, conserver les traces
et utiliser `/kvm/` ou `/legacy/` ; aucun reboot ou reset ne fait partie du correctif.
