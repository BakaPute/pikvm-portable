# Portable OS 0.2.0-rc.2 — navigation principale et KVM intégré

Cette candidate met à jour RC1 sans remplacer les fichiers internes de KVMD.
Elle n'a pas été déployée sur le Raspberry Pi pendant son développement.
L'intégrité Python exigée par RC1 reste un prérequis ; aucune mise à jour de paquet,
réparation Python, commande GPIO ou modification USB n'est exécutée par cette migration.

## Routes après installation

| Route | Comportement |
| --- | --- |
| `/` | Redirection temporaire 302 vers `/extras/portable-os/` |
| `/extras/portable-os/` | Application principale, session KVMD obligatoire |
| `/legacy/` | Menu de secours autonome, session KVMD obligatoire |
| `/kvm/` | KVM natif inchangé, sans adaptation lorsque ouvert directement |

Le menu de secours affiche, dans l'ordre, **KVM, Terminal, Logout, Portable OS,
Extras**. Extras lit `/api/info?legacy=0&fields=auth,node,extras`, trie les extensions
suivant `place` et conserve les applications activées ou démarrées, comme KVMD.
Les trois outils historiques utilisent `?legacy=1` pour éviter leur redirection vers
Portable OS. Les futures extensions apparaissent sans modifier ce menu.
Le menu reste utilisable avec le service `pikvm-portable-api` arrêté ; ses liens
essentiels fonctionnent aussi sans JavaScript. Une erreur
d'énumération ne supprime pas les accès KVM et Terminal. Une session KVMD et nginx
restent nécessaires. Les fichiers originaux `/index.html`, `/kvm/`, les ressources
`/share/` et les API ne sont pas remplacés.

## Adaptation KVM

`core/kvm-adapter.js` vérifie le contrat DOM de KVMD 4.213 avant d'activer sa feuille
de style. Le cadre reste de même origine et conserve la session, les éléments vidéo,
la connexion native et les gestionnaires HID. Les six menus vivants Drive, ATX,
Shortcuts, Macro, Text et System sont déplacés dans une barre flottante ; leurs
contrôles, attributs, IDs, confirmations et événements natifs sont conservés.
System devient « Vidéo & HID » et conserve aussi les commandes clavier et souris.
Une commande matériellement indisponible reste désactivée par KVMD.

Le mode natif « full tab » remplit le cadre. Seuls la barre de navigation d'origine,
son bouton de rappel, son pied de page et l'en-tête du flux sont masqués, après
validation de leur remplacement. Le KVM direct `/kvm/` ne charge pas l'adaptateur.
Une incompatibilité affiche une erreur et un lien vers le moteur natif ; elle ne
tente pas de reconstruire des commandes ni de deviner un nouveau protocole.

La capture est désactivée initialement. Le bouton clavier/souris active la capture,
donne le focus au flux et utilise le mute natif. Un second appui désactive la capture.
Le changement de vue, la désactivation et l'expiration de session relâchent les
touches via le hook `window.blur` de KVMD et libèrent le pointer lock. La lecture ou
l'enregistrement de macro est arrêté via son bouton natif à la désactivation,
car le lecteur de macros émet directement ses événements HID, hors du mute.
Le simple masquage de la barre ne modifie ni la capture ni la session.

La barre disparaît après quatre secondes sans interaction ; un menu ouvert, le
survol ou le focus sur ses contrôles la maintiennent visible. Le survol du haut de
l'image, le focus clavier et le bouton permanent « Commandes KVM » la rappellent.
Le bouton permanent reste utilisable au toucher. Ctrl+Maj+Échap libère la capture
si le navigateur laisse parvenir ce raccourci à la page. Le plein écran concerne
le panneau intégré, avec ses contrôles et sans l'ancienne navigation.

Les routes partagées sont définies dans `web/legacy/routes.js`. Le menu de secours
n'importe aucun module Portable OS. Aucun framework ou paquet d'exécution n'est ajouté.

## Tests et limites

Bilan local de cette candidate : **75 tests Python réussis, un test ignoré**
(privilège de création de liens symboliques Windows), **17 tests JavaScript réussis**,
scénario navigateur Edge desktop/tactile réussi. Les contrôles nginx utilisent un
vrai exécutable nginx ; les commandes de déploiement ne sont jamais exécutées sur
le Pi pendant ces tests.

Les tests Python couvrent les transactions répétées installation/restauration,
le refus des sauvegardes altérées, le contrat KVM et l'absence de remplacement des
fichiers natifs. Un vrai nginx local valide `-t`, `-T`, les inclusions, les redirections,
les sessions présentes/absentes, les API et les ressources. L'installateur rejette
aussi une boucle vers `/` ou un secours sans authentification avant de remplacer
la configuration active.

Les tests Edge/Playwright utilisent une simulation native instrumentée : événements
clavier/souris, raccourcis, macros, qualité, persistance du cadre, relâchement des
touches, masquage/rappel, plein écran, tactile et session expirée. Ils ne constituent
pas une validation du flux vidéo réel, de WebRTC/MJPEG, du pointer lock relatif,
des touches interceptées par Windows, d'ATX ou d'un lecteur USB matériel.

Après autorisation et installation, vérifier ces fonctions avec le PC cible, les
modes souris disponibles et un téléphone réel. Tester un raccourci sans risque,
une petite macro et du texte de test dans un éditeur distant ; quitter la vue avec
une touche maintenue et vérifier son relâchement. Tester les fenêtres clavier/souris,
la sélection vidéo et le retour du plein écran. Ne pas changer Drive 0 pour valider
la seule présentation du menu. Les capacités ATX suivent la configuration native.
Une évolution de KVMD peut demander une adaptation du contrat DOM ; la candidate
refuse les versions hors KVMD 4.213 / Python 3.14.7-1.

Sources auditées : [page KVM 4.213](https://github.com/pikvm/kvmd/blob/v4.213/web/kvm/index.html),
[gestionnaire de fenêtres](https://github.com/pikvm/kvmd/blob/v4.213/web/share/js/wm.js),
[HID et relâchement](https://github.com/pikvm/kvmd/blob/v4.213/web/share/js/kvm/hid.js),
[menu des extensions](https://github.com/pikvm/kvmd/blob/v4.213/web/share/js/index/main.js),
[routage nginx natif](https://github.com/pikvm/kvmd/blob/v4.213/configs/nginx/kvmd.ctx-server.conf).

## Fichiers livrés

- Ajouts : `web/legacy/{index.html,main.js,routes.js,style.css,package.json}`,
  `web/extras/portable-os/core/kvm-adapter.js`, `web/extras/portable-os/kvm.css`,
  `tests/test_portable_routes.py` et ce document.
- Interface modifiée : `app.js`, `index.html`, `style.css`, `package.json`,
  `core/native-bridge.js`, `modules/{index,kvm,system}.js` dans
  `web/extras/portable-os/`.
- Installation : `scripts/pikvm-portable-install`, `scripts/pikvm-portable-package.py`
  et `kvmd-extras/portable-os/nginx.ctx-server.conf`.
- Tests modifiés : `tests/{test_portable_install.py,portable-ui.test.mjs,portable-browser.cjs,portable_preview.py}`
  et `tests/fixtures/native-kvm.html`.
- Documentation modifiée : `README.md` et `docs/portable-os.md`.

## Mise à jour — uniquement après autorisation explicite

Construire l'archive sur Windows :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.2.tar.gz private/pikvm-portable-os-0.2.0-rc.2.tar.gz.sha256 root@192.168.168.99:/tmp/
ssh @sshOptions root@192.168.168.99
```

Saisir le mot de passe aux invites SSH/SCP, jamais dans une commande ou un fichier.
Sur le PiKVM, dans cette session interactive :

```bash
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.2.tar.gz.sha256
work=$(mktemp -d /tmp/portable-os-rc2.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.2.tar.gz -C "$work"
cd "$work/pikvm-portable-os-0.2.0-rc.2"
sha256sum -c MANIFEST.sha256
python3 -B scripts/pikvm-portable-install check
```

Ne continuer que si tous les contrôles passent. Puis, après l'autorisation de
modification du système :

```bash
rw
bash install-portable-os.sh
ro
```

Noter le chemin **Sauvegarde : /root/pikvm-portable-os-backups/…** imprimé.
Tous les fichiers remplacés sont sauvegardés avec leurs sommes de contrôle et
métadonnées, y compris le nginx généré, les nouvelles routes, le secours et l'ancienne
version Portable OS. Le service API est vérifié avant basculement nginx ; `nginx -T`
vérifie les fichiers réellement chargés, puis `nginx -t` précède le rechargement.
Un échec déclenche le rollback. Il n'y a ni redémarrage matériel ni redémarrage KVMD.
Les réinstallations créent une nouvelle sauvegarde sans dupliquer les locations nginx.
Les éventuels correctifs locaux de SHARE sont conservés ; le patch de politique
d'arrêt existant reste étroitement contrôlé et impose SHARE au repos s'il est requis.

Ouvrir `https://192.168.168.99/`, puis tester `/legacy/` et `/kvm/` dans des onglets
distincts. Vérifier aussi la déconnexion et la reconnexion à partir de `/legacy/`.

## Retour arrière indépendant du navigateur et du service Portable OS

Depuis la session SSH, utiliser le **chemin exact** imprimé lors de cette mise à jour :

```bash
rw
python3 -B /usr/local/bin/pikvm-portable-install restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

Si le script installé est indisponible, utiliser celui de l'archive vérifiée encore
présente dans le répertoire `$work` :

```bash
rw
python3 -B "$work/pikvm-portable-os-0.2.0-rc.2/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

Remplacer `DATE-ID`, ce n'est pas une valeur à copier littéralement. Si la session
SSH a été fermée, retrouver le répertoire `/tmp/portable-os-rc2.…` avant cette commande.
La restauration vérifie les sauvegardes avant tout arrêt de service, restaure les
fichiers et l'état antérieur du service, valide nginx et le recharge. Elle remet les
routes de RC1 (ou la configuration sauvegardée), donc l'entrée `/` précédente.
Elle peut être répétée. Si cette installation a aussi modifié la politique SHARE,
il faut d'abord éjecter proprement et libérer SHARE pour restaurer ce fichier.
Aucune restauration d'image exFAT, de GPIO ou du Drive 0 n'est effectuée.
