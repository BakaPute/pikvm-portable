# PiKVM Portable OS RC9.1 — dialogue de déplacement ISO

Version `0.2.0-rc.9.1`, correctif frontend de RC9 `7745f4e`, branche
`codex/portable-os`. Aucun déploiement, accès SSH ni déplacement de véritable ISO.

## Cause et correction

`dialog()` transmettait `type: 'select'` au constructeur `el()`. Ce constructeur
affecte les propriétés DOM présentes : `HTMLSelectElement.type` possède uniquement
un getter, ce qui déclenche un TypeError et empêche la création du dialogue.

La correction reste dans `web/extras/portable-os/core/ui.js` :

- `type` est ajouté uniquement pour un élément input ;
- les options du select sont créées avant l'application de sa valeur initiale ;
- une valeur initiale explicite, y compris la chaîne vide, est conservée ;
- sans valeur initiale, la première option reste sélectionnée normalement ;
- checkbox utilise toujours checked et renvoie un booléen ; texte/password,
  autocomplete, required, confirmation et annulation restent disponibles.

Le helper générique `el()` n'est pas modifié. `storage.js`, `core/api.js` et les
API/backend de stockage sont inchangés. Le bouton Déplacer continue d'appeler
`api.folders('move_file', {source, folder})`, transporté en POST JSON vers
`/extras/image-manager/api/image-manager/folders/action`, avec `action: 'move_file'`.
La racine s'affiche `/` mais sa valeur API reste **la chaîne vide**, conformément
au contrat existant. Espaces et sous-dossiers restent transmis tels quels en JSON.

## Audit des autres dialogues

Seul le déplacement ISO emploie actuellement un select dans `dialog()`. Les autres
appels sont : création/renommage (texte), édition Wi-Fi (texte, password, checkbox
optionnelle), éjection SHARE (checkbox obligatoire), et confirmations sans champ
pour suppression, connexion/récupération, réseau et alimentation. Aucun autre
appel ne construit un select avec une autre méthode. Aucun appelant ni règle
d'autorisation n'a été modifié pour contourner le défaut de construction DOM.

## Test de non-régression navigateur

`tests/portable-dialogs.cjs` emploie un vrai DOM Edge/Chromium sur la fixture localhost :

1. L'affectation native `select.type = 'select'` en mode strict reproduit exactement
   le TypeError de propriété getter-only.
2. Le vrai `dialog()` corrigé ouvre ensuite le select sans attribut type et applique
   une valeur initiale qui n'est pas la première option.
3. Valeur racine explicite, première option par défaut, texte requis, password,
   autocomplete et checkbox vraie/fausse sont vérifiés sur le formulaire soumis.
4. `storage.js` est monté normalement avec des API interceptées en mémoire. L'ISO
   fictif `Ubuntu Desktop avec espaces.iso` est déplacé de la racine vers
   `Outils et secours/Linux images`, puis remis à la racine.
5. Les deux payloads exacts, le transport POST et l'en-tête de gestion sont vérifiés.
   L'affichage est rechargé dans les dossiers concernés.
6. Un refus API 409 et une liste de dossiers indisponible 503 produisent leurs
   notifications. Le fichier fictif reste en place, aucun succès n'est inventé.
7. Annuler n'envoie aucune mutation. Aucune erreur JavaScript non gérée.

Les mutations ne touchent qu'une variable du mock Playwright. Aucun fichier ISO
n'est créé, ouvert, déplacé, renommé ou supprimé sur disque ; aucun serveur Pi n'est
appelé. Le script refuse toute URL de test autre que localhost/127.0.0.1.
La CI exécute désormais cette régression en plus des suites RC9 existantes.

Bilan local : **159 tests Python réussis, 2 ignorés sous Windows** (161 au total),
**23 tests JavaScript réussis**, régression navigateur du dialogue, suite
fonctionnelle et layout KVM sur quatre formats réussis. Python local 3.12.14 et
Edge headless ; aucune CI distante ni opération matérielle sur le Pi revendiquée.

Fichiers modifiés : `core/ui.js`, nouveau test navigateur, CI, version HTML/package,
empaqueteur, README et cette documentation. Les améliorations KVM RC9, le GPIO
optimisé RC8, l'OLED, les API, services, images, règles de montage/exclusivité et
les mécanismes de sauvegarde/restauration sont conservés à l'identique.

## Mise à jour depuis RC9 — seulement après autorisation

Construire et transférer avec authentification SSH par mot de passe :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python -B scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
$PiKvmHost = Read-Host 'Adresse IP actuelle du PiKVM'
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.9.1.tar.gz private/pikvm-portable-os-0.2.0-rc.9.1.tar.gz.sha256 "root@${PiKvmHost}:/tmp/"
ssh @sshOptions "root@${PiKvmHost}"
```

Mot de passe aux invites uniquement. Ces commandes ne sont pas exécutées
automatiquement. Sur le Pi, après autorisation de transfert :

```bash
set -e
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.9.1.tar.gz.sha256
stage=$(mktemp -d /tmp/pikvm-portable-os-rc9.1.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.9.1.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
printf 'Stage RC9.1 : %s\n' "$stage"
python3 -B scripts/pikvm-portable-install check
```

Les précontrôles RC9 restent inchangés et refusent toujours les correctifs locaux
inconnus. Après réussite et autorisation explicite de déploiement, utiliser la
transaction existante, avec ses sauvegardes et redémarrages applicatifs habituels :

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

Conserver le chemin de sauvegarde imprimé. Recharger complètement chaque onglet
Portable OS (**Ctrl+F5**) : changer seulement de route ne recharge pas les modules
JavaScript déjà importés. Vérifier le badge RC9.1 et l'ouverture du sélecteur de
destination. Aucun déplacement d'ISO réel n'est nécessaire pour cette vérification.

Pour revenir à RC9, utiliser la sauvegarde créée par cette installation :

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

Remplacer DATE-ID par le chemin imprimé, redéfinir stage si besoin ; le script
installé peut également restaurer si le stage a disparu. Recharger complètement
le navigateur après restauration. Le retour RC9 réintroduit son bug de dialogue.
