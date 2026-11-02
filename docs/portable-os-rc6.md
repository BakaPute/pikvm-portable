# PiKVM Portable OS 0.2.0-rc.6

Candidate locale sur `codex/portable-os`. Aucun déploiement ni diagnostic SSH du Pi
n'a été effectué pendant ce travail. Les trois captures réelles ont été rapprochées
des scripts et de l'adaptateur RC5 ; les causes suivantes sont établies dans le code.

## Diagnostic OLED

RC5 publie son heartbeat uniquement depuis `button_down()`, dans la boucle qui
dessine le menu. Son seuil de fraîcheur est 500 ms. Or cette boucle s'arrête aussi
pendant les messages temporisés, les opérations natives et les transferts de
propriété : `run_menu()` arrête le producteur normal par systemd, puis le relance à
sa sortie. Le contrôleur Unix peut parfaitement continuer à répondre pendant que
ce heartbeat est périmé. « Gestionnaire indisponible » confondait donc deux états.

Ensuite, chaque frame RC5 affecte `screen.disabled` à ce résultat. Une frame absente,
périmée, ou un contrôle considéré indisponible appelle aussi `finish(true)`.
Désactiver un bouton capturé peut perdre le pointer capture. Le problème ne vient
pas d'une recréation du canvas (déjà stable dans RC5), mais de la liaison entre état
du rendu, état de l'élément interactif et annulation du geste. Les captures de la
même page ISO à 14 s puis 7 s montrent cet état alternant ; elles ne suffisent pas
à mesurer seules les temps I2C, HTTP ou systemd réels.

Enfin, le timer de renouvellement attendait **200 ms après la réponse**. Le temps
HTTP s'ajoutait donc à chaque intervalle : un aller-retour lent pouvait approcher le
bail serveur de 800 ms même sans saturation CPU. RC6 ne change pas ce bail.

### Correction

- La santé du contrôleur est publiée par un thread dédié à son service Unix.
  L'âge du dernier poll de rendu reste un diagnostic distinct. Le writer réessaie
  après une erreur de publication temporaire, sans tuer son thread.
- Un début reçu pendant une transition attend sa consommation ; si le menu logique
  a réellement changé avant consommation, le geste est annulé plutôt qu'appliqué
  au mauvais menu. Un geste déjà consommé n'a plus besoin de lire des frames pour
  renouveler son bail.
- `core/oled-input.js` possède seul le cycle start/keep/stop/cancel. La réception
  d'images n'appelle plus son annulation. Des frames absentes plusieurs secondes
  conservent les derniers pixels et produisent un indicateur discret, sans désactiver
  un bouton maintenu ni remplacer le canvas.
- Les pixels sont mis à jour uniquement si leur contenu change. Les textes ne sont
  réaffectés que s'ils changent. Le canvas et le bouton restent les mêmes nœuds.
- Les renewals ont une cadence de 200 ms corrigée de la durée de la requête, sans
  chevauchement. Leur timeout client est 650 ms. Si le canal d'entrée échoue, le
  geste est annulé ; le serveur expire toujours un bail réellement perdu à 800 ms.
- Perte de focus, onglet caché, Échap, session expirée et fermeture du panneau
  conservent leurs annulations. Les permissions sensibles par geste et les gardes
  médias de RC5 restent actives.

Le diagnostic repliable « Diagnostic OLED » mesure RTT frame et commandes,
maximum de renewal, authentification/API, lecture du framebuffer, rendu,
publication précédente, âge de la frame et âge du poll de rendu du contrôleur.
Ces nombres ne sont pas des durées inventées du compteur ; aucun pixel n'est
extrapolé. Les métriques sont bornées, sans journalisation des cookies ou gestes.

## KVM : architecture de commande

RC5 déplaçait les menus natifs dans une barre créée **à l'intérieur** de l'iframe.
Les widgets locaux ajoutés par `power-control.js` (`pkpm-root`, `pk-battery`) ne
figuraient pas dans les sélecteurs masqués. Cela explique leur présence sur la
troisième capture. Une simple recoloration de l'ancien menu ne suffisait pas.

RC6 garde un seul iframe, un seul moteur vidéo/HID et les contrôleurs natifs.
`core/native-controls.js` construit de **nouveaux composants dans la page Portable
OS**, avec ses styles, champs, tableaux, boutons, panneaux et dialogues. Il lie
leurs valeurs, états et actions aux contrôles natifs vivants. Les nœuds sources
ne sont ni adoptés ni déplacés. Les changements de valeurs/permissions KVMD sont
répercutés dans le panneau actif, et les états sont revérifiés avant les actions.

La barre clavier/souris, plein écran, Drive 0, ATX, raccourcis, macros, texte et
vidéo/HID est dans le document principal, au-dessus de la vidéo. Les panneaux
Drive/ATX/etc. utilisent les variables et conventions UI Portable OS. Les actions
sont exécutées par les gestionnaires d'origine : aucun protocole vidéo/HID ou API
Drive parallèle n'est introduit. Les fichiers sélectionnés, sliders et événements
de formulaires sont transmis aux contrôles natifs correspondants.

Les confirmations natives sont détectées et projetées dans un dialogue Portable OS
qui actionne les vrais boutons natifs OK/Cancel. Une confirmation n'est jamais
acceptée automatiquement. Les fenêtres clavier/souris utilisent également une
surface Portable OS, en conservant les actions natives. Le terminal existant garde
sa route dédiée plutôt que de créer un second terminal dans le panneau.

La surface iframe adaptée n'affiche plus ni navbar, ni footer, ni en-tête du flux,
ni Power/batterie hérités. Les commandes restent dans le parent, y compris en plein
écran. Le seul overlay natif éventuellement autorisé dans cette surface est la
sélection OCR sur le flux, quand cette fonction est utilisée. **Aucun fichier KVM
natif installé n'est modifié** : `/kvm/` direct et `/legacy/` restent les secours.

## Tests et limites

Validation locale : **115 tests Python réussis, 2 ignorés sous Windows** (117 au
total), **21 tests JavaScript réussis**, et scénario navigateur Edge desktop et
tactile réussi. Les tests Python incluent une validation avec nginx 1.26.3 réel et
les transactions répétées d'installation/restauration en environnement simulé.
La migration a également été vérifiée contre les trois scripts de l'archive RC5,
sans exécuter systemd ni modifier de fichier système.

Captures produites (données simulées, aucun Pi connecté) :

- `private/portable-os-rc6-kvm.png` et `private/portable-os-kvm-mobile.png` : vidéo seule dans l'iframe, commandes dans le parent.
- `private/portable-os-rc6-drive.png` et `private/portable-os-rc6-drive-mobile.png` : panneau Drive Portable OS.
- `private/portable-os-oled.png` : miroir OLED.

Fichiers principaux : `scripts/pikvm_oled.py`, `scripts/pikvm-button-menu`,
`scripts/pikvm-portable-api`, `core/oled-input.js`, `modules/oled.js`,
`core/native-controls.js`, `core/kvm-adapter.js`, `modules/kvm.js`, `kvm.css` et
`style.css` sous `web/extras/portable-os/`. Le manifeste des baselines OLED,
l'empaqueteur, la version et les tests accompagnent ces changements.

Les tests reproduisent des frames OLED absentes/périmées plusieurs secondes,
un heartbeat de rendu ancien avec contrôle vivant, une transition de producteur,
des maintiens 2/3/5 s pendant les actualisations, une vraie perte du canal d'entrée
et un bail réellement expiré. Le navigateur surveille identité/remplacements du
canvas, désactivations intempestives, erreurs JS et états du maintien.

Les scénarios KVM vérifient les widgets hérités absents, les sources natives restées
dans leur document, la capture HID, les champs/qualité, l'import de fichier simulé,
les états désactivés, les raccourcis/macros, les fenêtres clavier/souris et les
confirmations ATX annulées puis confirmées. Des captures desktop/tactile sont
produites sous `private/` et la CI les publiera comme artefacts.

Les tests locaux utilisent un moteur natif instrumenté ; ils ne prétendent pas
valider le flux réel, ATX physique, toutes les particularités de navigateur ou toutes
les extensions personnalisées KVMD. Les privilèges OS (raccourcis Windows, verrouillage
clavier, presse-papiers, OCR) restent dépendants du navigateur et demandent un test
sur la cible. L'adaptateur refuse une structure native incompatible et conserve
un lien vers `/kvm/`. Le transport Unix réel reste testé par la matrice CI Linux,
pas par le runtime Python Windows disponible. Aucune CI distante n'a été déclenchée.
Les tests locaux utilisent Python **3.12.14** ; la matrice Linux Python 3.14 reste
à exécuter en CI. La compatibilité réelle KVMD 4.213/Python 3.14.7 et les latences
du Pi Zero 2 W devront être confirmées après autorisation de déploiement.

## Installation RC6 — uniquement après autorisation explicite

Les empreintes de RC5 sont ajoutées au contrôle de migration. Les correctifs locaux
non reconnus restent refusés avant remplacement. La transaction, les sauvegardes,
les précontrôles Python 3.14.7-1 / KVMD 4.213, les validations nginx, le contrôle du
nouveau framebuffer et le rollback automatique sont conservés. Aucun GPIO, image
exFAT, Drive, service power-hold ou arrêt automatique n'est reconfiguré.

Sur Windows :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.6.tar.gz private/pikvm-portable-os-0.2.0-rc.6.tar.gz.sha256 root@192.168.168.99:/tmp/
ssh @sshOptions root@192.168.168.99
```

Saisir le mot de passe aux invites, sans clé ni enregistrement. Sur le Pi :

```bash
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.6.tar.gz.sha256
work=$(mktemp -d /tmp/portable-os-rc6.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.6.tar.gz -C "$work"
cd "$work/pikvm-portable-os-0.2.0-rc.6"
sha256sum -c MANIFEST.sha256
python3 -B scripts/pikvm-portable-install check
```

Après réussite des contrôles et autorisation de modification :

```bash
rw
bash install-portable-os.sh
ro
```

Conserver le chemin **Sauvegarde : /root/pikvm-portable-os-backups/…** imprimé.
Ne pas utiliser l'installateur global `install.sh` pour cette mise à jour.
Valider sans armement sensible : maintiens OLED et diagnostic pendant plusieurs
transitions, puis commandes KVM, reconnexion de session, `/legacy/` et `/kvm/`.

## Restaurer exactement RC5

Utiliser la sauvegarde créée par **cette installation RC6**, qui contient les
fichiers RC5 précédemment installés. Remplacer `DATE-ID` par le chemin imprimé :

```bash
rw
python3 -B /usr/local/bin/pikvm-portable-install restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

Si le script installé est indisponible, celui de l'archive vérifiée peut restaurer :

```bash
rw
python3 -B "$work/pikvm-portable-os-0.2.0-rc.6/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

La restauration vérifie les empreintes avant tout arrêt, remet fichiers et nginx,
puis rétablit les états des services OLED. Elle est répétable et indépendante du
navigateur. Aucun redémarrage matériel ni restauration de données SHARE/GPIO
n'est demandé. La restauration remet les comportements RC5, y compris ses limites
précédentes ; recharger le navigateur pour quitter les modules RC6 déjà chargés.
