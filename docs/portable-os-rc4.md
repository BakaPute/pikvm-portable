# Portable OS 0.2.0-rc.4 — SSD1306 facultatif et reconnexion sans blocage

La candidate suivante [RC5](portable-os-rc5.md) remplace la fenêtre par un panneau
latéral, ajoute les maintiens logiques et retire les autres I/O synchrones du rendu.

## Correction

Le matériel ciblé est exactement un **SSD1306 I2C, adresse 0x3C, 128×64 monochrome**.
RC3 interceptait les exceptions du pilote dans le module partagé, mais exécutait
encore la création du périphérique et `display()` dans la boucle de rendu. Un appel
I2C lent pouvait donc figer les images suivantes et la navigation. Si le service
installé échoue dès l'import ou la création du SSD1306, il faut aussi vérifier que
ses scripts ont réellement migré vers le module partagé.

RC4 garde les mêmes fonctions de dessin dans `pikvm-oled-custom` et
`pikvm-button-menu`. `MirrorDevice` publie le framebuffer 1 bit natif avant de
proposer une copie au worker physique. Le navigateur conserve le décodage MSB des
1024 octets, le canevas 128×64 et l'agrandissement `image-rendering: pixelated`.
Aucun moteur de rendu ou menu supplémentaire n'est ajouté.

Un seul worker I2C par producteur traite **la dernière image**, sans file croissante.
La création du SSD1306 et ses écritures s'effectuent hors de la boucle de rendu et
hors du verrou du framebuffer à transmettre. Les exceptions, dont
`DeviceNotFoundError`, restent dans ce worker. Sans écran, le processus continue
à publier les images et le bouton logique reste disponible.

Après une erreur de détection ou d'écriture, le worker attend 30 secondes avant
une nouvelle tentative. Il conserve la dernière image, même si aucun nouveau dessin
n'arrive. Après reconnexion, il envoie l'image la plus récente disponible. Un appel
du pilote bloqué n'empêche ni la publication web ni la navigation : aucun second
worker n'est lancé pour le remplacer. Si l'appel reste bloqué indéfiniment, la
reconnexion physique attend son retour ; le miroir virtuel continue. La candidate
ne réinitialise pas le bus et ne redémarre pas le système pour débloquer un pilote.

La fenêtre indique discrètement **« Mode virtuel »** jusqu'à un envoi physique
réussi, puis **« OLED physique connecté »**. L'indication est un état observé lors
du dernier échange, pas une mesure électrique continue. Elle est publiée au rendu
suivant et lue par le navigateur à sa cadence existante d'une seconde.

Les clics restent des appuis **courts uniquement**, avec les gardes de durée et
d'origine de RC3. Authentification KVMD, cookies et CSRF sont inchangés. Aucun GPIO,
Drive, UDC, image exFAT ou service d'arrêt automatique n'est modifié par cette
correction. Le programme de power-hold reste intégralement inchangé.

## Migration et systemd

Avant toute copie, l'installateur vérifie les deux scripts OLED installés et,
s'il existe, **le module partagé installé**. Il accepte les versions historiques
connues, le module RC3 identifié par son SHA256 et la version candidate courante.
Un correctif local inconnu est refusé avant l'arrêt des services et conservé.
Une installation ancienne sans module partagé peut migrer si ses scripts sont
identifiés. Une réinstallation de RC4 est également acceptée.

Les sauvegardes incluent les fichiers remplacés ainsi que les états actif/activé
des services. L'installateur attend un nouveau framebuffer et la réponse du
gestionnaire logique avant de basculer nginx. Un ancien fichier ne suffit pas.
Les contrôles Python 3.14.7-1 / KVMD 4.213 et nginx restent obligatoires. Le
power-hold doit être déjà actif : l'installateur ne le démarre jamais.

Les unités systemd ne sont pas changées : `Restart=always` reste une protection
contre une panne du processus. Une absence du SSD1306 ne fait plus sortir la boucle
OLED. Localement, un test lance la **vraie fonction main du service** dans un
processus distinct avec `DeviceNotFoundError` injectée ; il vérifie plusieurs
framebuffers successifs, le même PID vivant et l'absence de traceback. Le service
systemd et le bus I2C réels ne peuvent être vérifiés sous Windows et restent à
contrôler sur le Pi après autorisation.

## Tests locaux

Bilan : **95 tests Python réussis, deux ignorés sous Windows**, **18 tests JavaScript
réussis** et scénario navigateur Edge desktop/tactile réussi. Syntaxe Python et
`git diff --check` validés. La migration a aussi été exécutée en simulation à partir
des trois fichiers réels de l'archive RC3, sans remplacement de fichiers système.

- Configuration SSD1306 exacte : port I2C 1, adresse 0x3C, 128×64.
- Pixels publiés identiques à ceux envoyés au pilote simulé.
- Écran connecté, débranché, reconnexion échouée puis réussie ; temporisation de
  30 secondes et transmission de la dernière image, sans dessin supplémentaire.
- Création du pilote et écriture bloquées : le rendu continue, une seule copie
  en attente et un seul worker.
- Processus OLED réel avec pilote absent simulé, sans sortie ni redémarrage.
- Migration des fichiers connus, refus et conservation de correctifs locaux.
- Régressions d'appuis courts, actions dangereuses, auth/CSRF, nginx, sauvegarde,
  réinstallation et rollback ; fenêtre OLED desktop/tactile et session expirée.

Le test AF_UNIX réel et un test de privilèges de liens symboliques sont exclus sous
le Python Windows disponible. La matrice CI Linux 3.11/3.14 conserve leur exécution ;
elle n'a pas été lancée à distance pendant cette tâche. Les tests matériels restent
distincts des simulations locales.

## Mise à jour exacte — après autorisation explicite

Ne pas utiliser l'installateur global `install.sh` pour cette mise à jour.
Utiliser l'archive RC4 construite depuis `codex/portable-os` ou la reconstruire :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.4.tar.gz private/pikvm-portable-os-0.2.0-rc.4.tar.gz.sha256 root@192.168.168.99:/tmp/
ssh @sshOptions root@192.168.168.99
```

Saisir le mot de passe aux invites SSH/SCP, sans l'inscrire dans les commandes.
Dans la session du Pi :

```bash
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.4.tar.gz.sha256
work=$(mktemp -d /tmp/portable-os-rc4.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.4.tar.gz -C "$work"
cd "$work/pikvm-portable-os-0.2.0-rc.4"
sha256sum -c MANIFEST.sha256
python3 -B scripts/pikvm-portable-install check
```

Si un script ou module local n'est pas reconnu, **arrêter la procédure** et examiner
son diff avant de remplacer quoi que ce soit. Pour un diagnostic en lecture seule :

```bash
systemctl cat pikvm-oled-custom.service pikvm-button-menu.service
systemctl show -p ActiveState -p NRestarts pikvm-oled-custom.service pikvm-button-menu.service
journalctl -u pikvm-oled-custom.service -n 30 --no-pager
sha256sum /usr/local/bin/pikvm-oled-custom /usr/local/bin/pikvm-button-menu
```

Après réussite des contrôles et autorisation de modification :

```bash
rw
bash install-portable-os.sh
ro
```

Noter le chemin **Sauvegarde : /root/pikvm-portable-os-backups/…** imprimé.
L'installation est progressive, sans redémarrage matériel ni redémarrage KVMD.
Elle arrête brièvement les producteurs OLED puis les relance sans démarrer leurs
dépendances power-hold. Elle valide nginx avant son rechargement.

Ouvrir Portable OS : carte Pi Zero 2 W → fenêtre OLED. Sans écran, vérifier « Mode
virtuel », les changements de pages et les appuis courts. Puis lire, sans rien écrire :

```bash
systemctl show -p ActiveState -p NRestarts pikvm-oled-custom.service pikvm-button-menu.service
journalctl -u pikvm-oled-custom.service --since '-2 min' --no-pager
```

Comparer le compteur de redémarrages après plus de 30 secondes **sans menu ouvert**
(le menu arrête intentionnellement le producteur normal). Il ne doit pas augmenter
du seul fait de l'absence à 0x3C. Une reconnexion physique devra être effectuée en
respectant les précautions matérielles habituelles ; après le prochain essai, le
pilote doit afficher les mêmes pixels et l'indicateur doit changer. Aucun scan I2C,
reset du bus ou manipulation GPIO n'est nécessaire à cette procédure logicielle.

## Retour arrière exact

Depuis SSH, avec le chemin exact imprimé lors de la mise à jour :

```bash
rw
python3 -B /usr/local/bin/pikvm-portable-install restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

Remplacer `DATE-ID`. Si le script installé est indisponible, utiliser celui de
l'archive vérifiée :

```bash
rw
python3 -B "$work/pikvm-portable-os-0.2.0-rc.4/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

Si la session SSH a changé, retrouver d'abord le répertoire `/tmp/portable-os-rc4.…`.
La restauration vérifie les empreintes avant tout arrêt, remet scripts/module,
API, interface et configuration nginx, puis rétablit les états des services.
Elle est répétable et n'écrit aucune donnée SHARE ni aucun GPIO. La version
précédente retrouve son comportement antérieur, y compris ses éventuelles erreurs
en l'absence d'écran. Aucun déploiement sur le Pi n'a été effectué pendant la
préparation de cette candidate.
