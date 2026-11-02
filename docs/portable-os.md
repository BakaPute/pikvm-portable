# PiKVM Portable OS — première version

La candidate stabilisée est décrite dans [portable-os-rc1.md](portable-os-rc1.md) :
réparation ciblée préalable de Python, contrôles renforcés et procédure de migration.

Branche locale : `codex/portable-os`, créée depuis `feature/pikvm-share`.
Cible : Pi Zero 2 W, KVMD 4.213, Python 3.14.7. Adresse communiquée :
`192.168.168.99`. Aucun déploiement ni diagnostic distant effectué par Codex.

## Architecture et périmètre livré

Application ES modules sans framework, build ou téléchargement CDN sur le Pi.
L'interface est servie dans les Extras à `/extras/portable-os/` : elle ne remplace
ni la page native, ni ses fichiers JS/CSS, ni les protocoles vidéo/HID.

| Dossier | Responsabilité |
| --- | --- |
| `web/extras/portable-os/core/` | client API, états, routeur, composants, dialogues, notifications |
| `web/extras/portable-os/modules/` | tableau de bord, KVM, images, SHARE, réseau, outils, alimentation, paramètres |
| `scripts/pikvm-portable-api` | diagnostics authentifiés, journaux filtrés, état des services et hotspot |
| `kvmd-extras/portable-os/` | manifeste et règles nginx authentifiées |
| `scripts/pikvm-portable-install` | installation additive, sauvegarde et restauration |

Le moteur KVM natif `/kvm/` est intégré dans un cadre de même origine persistant,
avec une feuille de style d'adaptation. Le terminal utilise le terminal natif
`/extras/webterm/ttyd/`. La navigation conserve les cadres et la connexion KVM.
Les autres modules sont de nouvelles vues, utilisant les composants communs :
ils ne chargent pas les anciennes pages Image Manager/SHARE/Wi-Fi dans des cadres.
Les dialogues internes au moteur natif restent sous son contrôle.

Le tableau de bord et les indicateurs sont rafraîchis toutes les 8 secondes,
45 secondes lorsque l'onglet est masqué. Une source indisponible conserve sa
dernière valeur en la marquant comme ancienne. L'aperçu vidéo utilise le snapshot
natif toutes les 20 secondes sur le tableau de bord ; aucun nouveau protocole vidéo.
Le KVM natif conserve sa propre connexion WebSocket, ses réglages de qualité,
macros, plein écran, clavier/souris et raccourcis. Les transferts interdisent
la navigation de l'application jusqu'à leur fin ou annulation.

## API et permissions

| Fonction | API utilisée |
| --- | --- |
| Session | `/api/auth/check`, `/api/auth/logout`, cookie PiKVM existant |
| ISO/IMG/RAW | `/api/msd`, `set_params`, `set_connected`, `write`, `read`, `remove` |
| Dossiers d'images | `/extras/image-manager/api/image-manager/folders[/action]` |
| Drive 1 | `/extras/pikvm-share/api/*`, sans changer ses garanties d'exclusivité |
| Batterie et Wi-Fi | `/extras/wifi-wizard/api/*` |
| Intégration | `/extras/portable-os/api/status`, `usb`, `logs`, `hotspot` |

Les routes natives ont été vérifiées dans les sources du tag KVMD `v4.213`.
Le client n'invente pas de succès : les écritures attendent la réponse de l'API.
Les fichiers techniques cachés, dont `.PIKVM-SHARE.img`, ne sont jamais proposés
à la sélection du Drive 0. Ses commandes ne sont émises que sur action explicite.

Nginx exige `/auth_check` sur l'application et son API. Le nouveau service Python
réutilise les vérifications de session et CSRF SHARE via le socket KVMD ; il refuse
une authentification désactivée. Le proxy conserve le préfixe et remplace l'en-tête
d'origine attendu. Aucun rôle supplémentaire n'est simulé : KVMD 4.213 ne fournit
pas de RBAC spécifique à cette couche. Tous les opérateurs authentifiés ont les
capacités autorisées par les API existantes.

Le service d'intégration est lié à `127.0.0.1:9878`, sans nouvelle exposition réseau.
Les journaux sont bornés et limités à une liste de services ; les lignes pouvant
contenir des mots de passe/tokens sont masquées. Le changement de hotspot appelle
uniquement le script existant, capture et jette sa sortie (qui peut contenir le
mot de passe), et exige session, CSRF et confirmation de coupure réseau.
Le client ne recopie pas les mots de passe retournés par l'ancienne API Wi-Fi dans
le store, les formulaires, le DOM ou le stockage navigateur.

## Alimentation et sécurité des données

Aucun GPIO n'est lu/configuré par la nouvelle interface ou son installateur.
Aucune écriture UDC, configfs ou image n'est ajoutée au service d'intégration.
Les mécanismes physiques du bouton et du maintien d'alimentation restent natifs.
L'arrêt manuel utilise le mécanisme existant, après confirmation et nouvelle
vérification que les deux lecteurs sont détachés et SHARE démonté.

L'arrêt automatique est désormais **strictement manuel**. SHARE ne redémarre
jamais `pikvm-auto-shutdown.service`, même si une ancienne réservation dit
`auto_active=true`. Les outils de sauvegarde ne le relancent pas non plus.
L'ancien installateur complet n'active ni ne redémarre plus ce service : son état
est préservé. Le nouveau déploiement ne lance pas l'installateur matériel complet.

L'accès Web au volume exFAT reste impossible lorsque le LUN SHARE contient une
image. Confirmation d'éjection côté PC, vérification hors ligne, verrou couvrant
les opérations et démontage normal avant attachement sont conservés. Aucun
formatage, aucune création d'image, aucun détachement forcé ni reset USB global.

## Diagnostic du Drive 1 sous Windows

L'audit du chemin de connexion confirme `kvmd-otgmsd -i 1 --set-cdrom=0
--set-rw=1 --set-image=...` après démontage/libération des loops. Il ne force
pas de réénumération du gadget. Sans relevé réel côté Pi et PC, la cause du
problème Windows n'est **pas établie** et aucune correction matérielle n'est simulée.

La vue Outils distingue : présence de la fonction, liens dans les configurations,
image/attributs du LUN, UDC lié et état `configured`. Un gadget configuré ne prouve
pas que Windows a détecté ce disque particulier, monté exFAT ou attribué une lettre.

Relevé Pi en lecture seule, dans ton terminal personnel avec mot de passe masqué :

```powershell
Get-Content -Raw .\scripts\pikvm-portable-diagnose.sh | ssh -T -o PubkeyAuthentication=no -o PreferredAuthentications=password -o PasswordAuthentication=yes -o StrictHostKeyChecking=ask root@192.168.168.99 'bash -s'
```

Saisir le mot de passe uniquement dans l'invite SSH, jamais dans le chat ou un
script. Si le pipeline gêne l'invite, ouvrir une session avec les mêmes options
et coller ensuite les commandes du diagnostic.

Sur **le PC Windows commandé**, exécuter le script en lecture seule
`scripts/pikvm-share-windows-diagnose.ps1`, éventuellement avec `-DiskNumber N`
après avoir identifié le disque. Il utilise `Get-Disk`, `Get-Partition` et
`Get-Volume`, sans initialisation, formatage, réparation ou attribution de lettre.

Interprétation :

- Fonction non liée : le LUN existe mais n'est pas nécessairement exposé au PC.
- UDC non configuré : liaison USB non confirmée ; ne pas corriger en détachant
  tout le gadget, car le KVM/HID et le Drive 0 seraient affectés.
- Disque absent dans Windows : investiguer l'énumération et le pilote avant exFAT.
- Disque visible mais volume/lettre absents : examiner partitions, état hors ligne,
  système de fichiers et politique de montage Windows, sans formater.

## Installation et restauration préparées

À exécuter sur le Pi **après autorisation explicite** et une fois cette branche
publiée/récupérée. Ne pas démarrer par l'installateur Portable matériel complet.

```bash
cd /root/pikvm-portable
python3 scripts/pikvm-portable-install check
rw
bash install-portable-os.sh
ro
```

L'installation sauvegarde les fichiers visés et la configuration nginx générée
dans `/root/pikvm-portable-os-backups/DATE-ID`, puis ajoute uniquement l'application,
son service et ses Extras. Elle valide les includes effectifs avec `nginx -T`,
teste encore nginx avant son rechargement et n'effectue aucun redémarrage KVMD.
Les anciens fichiers web, helper MSD et correctifs Python système ne sont pas copiés.

Si l'API SHARE installée contient encore le redémarrage d'inactivité connu,
l'installateur exige SHARE éjecté et sans montage/réservation, sauvegarde son
source et remplace seulement cette expression AST par un `pass`. Tous les autres
correctifs locaux, imports et commentaires sont conservés. Une forme de commande
inconnue est refusée. Seul SHARE est alors arrêté/redémarré s'il était actif ;
le service d'arrêt automatique n'est jamais démarré.

En cas d'échec, les fichiers sont restaurés et nginx retesté/rechargé. La
réinstallation préserve l'existant et les snapshots sont vérifiés par empreinte.
Pour revenir à la sauvegarde choisie :

```bash
rw
python3 scripts/pikvm-portable-install restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

Si cette sauvegarde contient un patch SHARE, détacher/libérer SHARE avant de
restaurer. L'opération refuse sinon de toucher au service actif. La restauration
applicative n'inclut jamais l'image exFAT ou une configuration GPIO/gadget.
Le retour arrière peut restaurer l'ancien code SHARE ; cela ne démarre pas le
service d'inactivité, mais il faut conserver sa politique désactivée ensuite.

## Développement, aperçu et nouveaux modules

Ajouter un module `{id, title, subtitle, icon, group, mount(outlet, context)}` dans
`modules/`, puis l'enregistrer dans `modules/index.js`. `mount` retourne une fonction de
nettoyage pour ses abonnements/temporisateurs. Utiliser `context.api`, `store`,
`action` et les composants de `core/ui.js` ; ne pas ajouter de client de session,
dialogue ou boucle de polling indépendants. Les préférences sont uniquement
locales au navigateur. Les données système viennent toujours d'une API.

Aperçu local **simulé**, sans connexion au Pi :

```bash
python3 tests/portable_preview.py --port 8765
```

Ouvrir `http://127.0.0.1:8765/extras/portable-os/`. La bannière indique explicitement
les données simulées ; le KVM de la fixture n'envoie ni vidéo réelle ni HID.
Le serveur de test ne fait pas partie des fichiers déployés.

Contrôles :

```bash
python3 -m unittest discover -s tests -v
node --test tests/portable-ui.test.mjs
python3 -m py_compile scripts/pikvm-portable-api scripts/pikvm-portable-install
bash -n install-portable-os.sh
bash -n scripts/pikvm-portable-diagnose.sh
```

Pour les tests navigateur, fournir Playwright via `NODE_PATH`, démarrer la fixture,
puis lancer `node tests/portable-browser.cjs`. Les mutations du test sont refusées
pour toute URL qui n'est pas localhost. `NGINX_BINARY` active les tests nginx réels.
Les scripts de tests ne contactent ni le PiKVM ni le PC cible.

## Validation et limites

Validation locale : suite Python, suite Node, contrôles nginx réels sur fixtures,
et scénario navigateur desktop/mobile. Celui-ci couvre navigation sans rechargement,
CRUD/import SHARE, éjection refusée si USB attaché, persistance du cadre KVM,
bibliothèque ISO, réseau, journaux, thèmes et accessibilité du menu mobile.

Résultats locaux du développement : **65 tests Python, 64 réussis et un ignoré**
(création de lien symbolique non autorisée sous Windows), **10 tests Node réussis**,
et scénario navigateur réussi avec Edge headless/Playwright 1.62.1. Quatre tests
utilisent nginx Windows 1.26.3 réel en mode validation seulement. Syntaxes Python,
JavaScript, Bash et PowerShell vérifiées ; `git diff --check` réussi.
Le Python local est 3.12.14 : la CI prépare 3.11/3.14 et Chromium Linux, mais
elle n'a pas été exécutée pendant ce travail local. Les captures sont produites
dans `private/portable-os-desktop.png` et `private/portable-os-mobile.png`.

Restent à valider après autorisation : installation ARM/Python 3.14.7 réelle,
vidéo/HID/macros/focus/plein écran du moteur natif dans son cadre, autorisation
d'encadrement par les en-têtes de l'appareil, terminal ttyd, actions réseau,
coexistence des écritures Drive 0/SHARE et symptômes exacts du PC Windows.
La configuration locale testée ne prouve pas ces comportements matériels.

Les réglages matériels, la réparation de volume, la création d'image et les mises
à jour KVMD ne sont pas automatisés. Les fonctions historiques restent accessibles
via l'interface de secours jusqu'à validation de la nouvelle application.

Sources KVMD vérifiées : [API MSD 4.213](https://github.com/pikvm/kvmd/blob/v4.213/kvmd/apps/kvmd/api/msd.py),
[session KVM](https://github.com/pikvm/kvmd/blob/v4.213/web/share/js/kvm/session.js),
[API streamer](https://github.com/pikvm/kvmd/blob/v4.213/kvmd/apps/kvmd/api/streamer.py)
et [modèle nginx](https://github.com/pikvm/kvmd/blob/v4.213/configs/nginx/nginx.conf.mako).
