# PiKVM Portable OS 0.2.0-rc.9 — disposition Console KVM

Candidate locale sur `codex/portable-os`, basée sur RC8 `c8587be`. Aucun accès SSH,
déploiement ou test matériel sur le Pi pendant ce travail. Les modifications
fonctionnelles concernent uniquement l'interface KVM ; GPIO, OLED, API, lecteurs,
power-hold et mécanismes de sauvegarde/restauration sont inchangés.

## Diagnostic de la capture et nouveau layout

RC8 calcule `--native-height` avec la hauteur de fenêtre moins la position verticale
de l'iframe. Les contrôles et le panneau sont insérés avant cette iframe ; leur
ResizeObserver refait le calcul. Plus le panneau grandit, plus la vidéo rétrécit.
Le panneau possède aussi `max-height:45vh; overflow:auto`, d'où la scrollbar interne.

RC9 conserve le même iframe, les mêmes médias et les contrôleurs KVMD. Il ajoute
les composants de commande **après** l'iframe, sans déplacer ni recréer celui-ci :

```text
vidéo native, largeur utile et ratio réel
barre de commandes, boutons sur plusieurs lignes si nécessaire
panneau sélectionné, hauteur naturelle
suite de la page et footer
```

L'iframe KVM utilise une largeur de 100 % et un aspect-ratio provenant des dimensions
du média natif décodé (MJPEG, vidéo, canvas), ou du statut de résolution natif.
Les barres de fenêtre natives ne font pas partie du ratio. Hors ligne, le dernier
ratio connu reste conservé ; avant toute résolution connue, le placeholder est 16:9.
La résolution est observée dans la synchronisation existante : aucune nouvelle
requête, connexion vidéo/HID, API de capture ou boucle de polling n'est introduite.

La taille ne dépend plus du panneau ni de la hauteur disponible de la fenêtre.
Les changements de largeur, de résolution native et le plein écran volontaire
peuvent toujours modifier la taille. Les médias remplissent la surface avec
object-fit:contain, sans recadrage ; les calculs de coordonnées restent ceux du
moteur natif. Le module Terminal conserve son dimensionnement précédent.

## Défilement et panneaux

Le véritable propriétaire du défilement normal est **document.scrollingElement,
l'élément html**, confirmé par les tests navigateur. La workspace et main sont dans
le flux ; la sidebar est fixed et conserve son propre overflow-y:auto.

Pendant la route KVM uniquement, le document réserve la place de la scrollbar
verticale et désactive le scroll anchoring pour éviter que l'ajout d'un panneau
déplace la page ou change la largeur utile. Aucun scrollTo/scrollIntoView de
production n'est ajouté. La classe de layout est retirée à la sortie de la route.

Le panneau et ses blocs de texte n'ont plus de hauteur maximale ni d'overflow
interne imposé. Le document s'allonge jusqu'au dernier contrôle. Les widgets natifs
comme les listes ou les zones de texte conservent leur comportement normal ; les
confirmations gardent leur dialogue modal et leurs protections.

En plein écran, la console devient le conteneur de défilement de **tout l'écran** :
vidéo, commandes et panneau dans le même ordre. La vidéo garde son ratio selon
la largeur plein écran, sans compression pour le panneau. Les commandes situées
sous une grande vidéo restent accessibles par la scrollbar de cette vue.

Les formulaires ont une largeur de contenu maximale de 64rem ; les lignes simples
KVMD deviennent deux colonnes sur écran large et une colonne sous 700 px. Les
lignes complexes restent complètes et leurs boutons reviennent à la ligne.
Les styles globaux de listes/tableaux du shell (première cellule min-width 145 px,
texte/boutons réduits) sont neutralisés **dans le panneau KVM seulement**.
Les rowspan/colspan natifs sont conservés pour les avertissements et tableaux.
Sur écran étroit, le bouton du sélecteur de fichier passe sur sa propre ligne,
pour laisser son libellé lisible sans remplacer le contrôle de fichier natif.

Un seul panneau actif, aucun par défaut : clic pour ouvrir, changer, ou fermer
le panneau déjà actif. Le bouton sélectionné est indiqué par couleur/bordure et
aria-expanded ; le bouton Fermer reste disponible. La fermeture d'une fenêtre
clavier/souris met immédiatement à jour son panneau parent, sans attendre le tick
de synchronisation. Les actions, confirmations, valeurs et états désactivés restent
liés aux nœuds natifs d'origine, sans adoption de nœuds vidéo.

## Fichiers concernés

- `web/extras/portable-os/modules/kvm.js` : ordre des composants, dimensionnement
  KVM indépendant des panneaux, classe de layout limitée à la route.
- `core/stream-size.js` : observation passive des dimensions natives.
- `core/kvm-adapter.js` : sélection/fermeture du panneau et synchronisation du ratio.
- `core/native-controls.js` : marqueurs de présentation, colspan/rowspan conservés.
- `kvm.css` : surface média native remplissant son iframe, scoped `.portable-kvm`.
- `style.css` : taille au ratio, barre dessous, formulaires et défilement de page.
- Version, empaqueteur, README, tests/fixtures et CI navigateur.

`/kvm/` indépendant n'est pas modifié : les styles d'adaptation ne sont appliqués
qu'au document chargé dans Portable OS. Aucun changement des scripts GPIO/OLED,
services systemd, API, images disque, SHARE ou règles d'authentification.

## Validation locale

`tests/portable-kvm-layout.cjs` vérifie dans Edge :

- 1920×1080, 1366×768, 820×1180 (tablette) et 390×844 tactile ;
- vidéo puis barre puis panneau, ratio 1600/900, dimensions identiques à moins
  d'un demi-pixel avant/après tous les panneaux et plusieurs cycles ;
- un panneau actif, clic actif pour fermer, aucun scroll automatique à l'ouverture ;
- panneau volumineux avec 32 champs : hauteur libre, absence d'overflow imposé,
  dernier contrôle atteint par le document et action transmise au contrôleur ;
- même iframe, même élément média, un seul chargement du document natif ;
- plein écran sans variation de taille liée au panneau ; adaptation 4:3 lors d'un
  changement de résolution, et redimensionnement normal lors d'un changement de largeur ;
- aucun débordement horizontal ni erreur JavaScript.

La suite navigateur existante vérifie capture clavier/souris, clavier natif,
souris, raccourcis, macros, saisie, qualité/HID, upload simulé, états désactivés,
confirmation ATX annulée puis confirmée, persistance entre routes, authentification
expirée et secours /legacy/ et /kvm/. Son helper de navigation attend maintenant
la route réellement active avant de vérifier la libération HID.

Captures produites sous `private/` : `portable-os-rc9-desktop.png`, `-laptop.png`,
`-tablet.png`, `-mobile.png`. **Données simulées et bureau SVG de fixture**, pas un
flux provenant du Pi. Vérification visuelle desktop et mobile effectuée localement.
La CI publie ces captures et exécute le scénario de layout en plus de la suite existante.

Le contrôle matériel reste à faire après autorisation : média réel MJPEG/H.264,
résolutions et navigateurs utilisés, coordonnées souris et plein écran sur le Pi.
Les nouveaux contrôles lisent les mêmes états natifs ; ils ne prouvent pas à eux
seuls le fonctionnement du matériel ou de toutes les extensions KVMD tierces.

Bilan local : **159 tests Python réussis, 2 ignorés sous Windows** (161 au total),
**23 tests JavaScript réussis**, suite navigateur fonctionnelle et scénario layout
sur les quatre formats réussis. Python local 3.12.14 ; nginx réel dans les tests
de configuration. Aucune CI distante ni validation Pi/Python 3.14 matérielle revendiquée.

## Installation depuis RC8 — uniquement après autorisation

L'installateur et son rollback sont réutilisés sans modification. L'archive
conserve les scripts matériels RC8 à l'identique. La transaction complète existante
effectue ses sauvegardes et redémarrages applicatifs habituels ; aucun changement
de configuration électrique, redémarrage matériel ou nouvelle opération sur les
images n'est ajouté par RC9. Ne pas utiliser l'installateur global `install.sh`.

Sur Windows :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python -B scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
$PiKvmHost = Read-Host 'Adresse IP actuelle du PiKVM'
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.9.tar.gz private/pikvm-portable-os-0.2.0-rc.9.tar.gz.sha256 "root@${PiKvmHost}:/tmp/"
ssh @sshOptions "root@${PiKvmHost}"
```

Saisir le mot de passe uniquement aux invites. Sur le Pi, après autorisation de
transfert, conserver le stage RC8 et préparer un nouveau dossier :

```bash
set -e
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.9.tar.gz.sha256
stage=$(mktemp -d /tmp/pikvm-portable-os-rc9.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.9.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
printf 'Stage RC9 : %s\n' "$stage"
python3 -B scripts/pikvm-portable-install check
```

Tout correctif local inconnu reste refusé par les précontrôles RC8 existants ;
ne pas le contourner pour installer une modification d'interface. Après réussite
et autorisation explicite de déploiement :

```bash
rw
if python3 -B "$stage/scripts/pikvm-portable-install" install; then
    ro
else
    status=$?
    ro
    printf 'Installation échouée (%s) : examiner rollback et journaux.\n' "$status" >&2
    exit "$status"
fi
```

Conserver le chemin Sauvegarde imprimé. Recharger complètement Portable OS pour
charger le nouveau JS/CSS, puis valider l'ordre, les dimensions avant/après menus,
scroll jusqu'au dernier contrôle, capture/libération, plein écran et secours.

## Restaurer RC8

Utiliser la sauvegarde créée par **cette installation RC9**, qui contient les
fichiers RC8 antérieurs et leurs états. Remplacer DATE-ID et redéfinir `stage` si
le shell a été fermé :

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

Le script installé peut aussi restaurer si le stage temporaire a disparu.
Recharger complètement le navigateur après restauration. Le mécanisme vérifie
les sauvegardes avant restauration comme dans RC8 ; il n'a pas été modifié.
