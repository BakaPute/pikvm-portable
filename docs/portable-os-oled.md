# OLED miroir — candidate 0.2.0-rc.3

## Fonctionnement

La carte « Pi Zero 2 W » de la barre latérale ouvre une fenêtre OLED. Elle présente
les **pixels 128×64 réellement calculés** par `pikvm-oled-custom` ou
`pikvm-button-menu`. Le navigateur ne possède ni menu parallèle, ni police OLED,
ni calcul de batterie ou de réseau. Les textes, icônes, défilements, QR, menus et
messages sont ceux des fonctions de dessin existantes.

Les deux producteurs utilisent `scripts/pikvm_oled.py` : une image Pillow 1 bit
est publiée avant l'envoi au SSD1306, puis la même image est envoyée au périphérique.
Le format est 1024 octets, lignes successives, bit de poids fort en premier, codés
en base64. Le canevas web agrandit ces pixels sans lissage. Les fonctions de dessin
et leurs polices sont conservées. Le chemin est équivalent au
[canevas luma](https://github.com/rm-hull/luma.core/blob/master/luma/core/render.py).

`/run/pikvm-oled/frame.json` est remplacé atomiquement, avec une publication courante
plafonnée à quatre fois par seconde et une mise à jour immédiate de l'état physique.
Il contient les pixels, l'identifiant de frame, le producteur, le contexte
de sélection, la date et l'état physique. Le répertoire est privé (0700), le fichier
0600 ; aucun framebuffer ni contenu de requête n'est journalisé. Cette image peut
contenir les mêmes informations Wi-Fi que l'écran physique : elle reste protégée
par la session KVMD. Elle n'est pas incluse dans une sauvegarde de déploiement.

Le navigateur lit ce framebuffer une fois par seconde **uniquement lorsque la
fenêtre est ouverte et l'onglet visible**, sans requêtes parallèles persistantes.
Fermer la fenêtre annule la lecture et arrête son minuteur. Le rendu physique
conserve son rythme existant. Le miroir peut donc présenter un léger retard
(publication plafonnée à 4 Hz, lecture à 1 Hz).

L'absence de l'écran à 0x3C, une erreur I2C ou l'absence de luma ne bloquent pas le
rendu virtuel. La création du périphérique physique est facultative et réessayée
au plus une fois toutes les 30 secondes. Pillow reste nécessaire, comme auparavant
pour le menu physique ; l'installateur vérifie sa présence sans installer de paquet.
Une image de plus de 15 secondes est refusée comme périmée. Les erreurs affichent
« Hors ligne », conservent la dernière image et désactivent les clics.

## Un seul chemin de navigation

L'autorité de navigation demeure la boucle existante de `pikvm-button-menu`.
Les menus ISO, le mode dépannage, les QR et les temporisations ne sont pas réécrits.
La distinction entre court et long reste celle du programme physique.

Un clic, un toucher ou Entrée sur l'écran virtuel envoie **uniquement** un événement
`short`. Le gestionnaire reçoit cet événement sur un socket Unix privé, valide
l'identifiant de l'écran vu par l'utilisateur et le consomme dans sa boucle
`button_down()` commune. Un jeton de geste en conserve l'origine : sa durée logique
reste exactement 0,10 seconde, même si un dessin ou l'ordonnanceur prend plusieurs
secondes. Un appui physique concomitant ne peut pas prolonger ce geste virtuel.

L'effet est celui d'un appui court : ouverture du menu depuis l'affichage normal,
sélection suivante, retour depuis un QR, annulation d'une confirmation ISO, ou
navigation du mode dépannage selon l'état courant. Le clic n'ouvre donc pas les
fonctions qui exigent un maintien de deux, trois ou cinq secondes. Le navigateur
n'offre pas d'appui long, même si le doigt ou la souris reste maintenu sur l'écran.

Des gardes supplémentaires refusent un appel virtuel à `poweroff`, au redémarrage,
au basculement hotspot ou à la suppression d'une image. Les entrées trop proches,
en attente, périmées, issues d'un ancien écran ou pendant un appui physique sont
refusées. Une erreur réseau ne provoque **jamais de répétition automatique** d'appui.
L'utilisateur doit attendre le nouvel affichage avant de réessayer.

Le gestionnaire lit seulement GPIO18. Ses anciennes reconfigurations répétées
`pinctrl set` ont été supprimées : la configuration initiale reste celle de
`pikvm-power-hold-startup`, qui n'est pas modifié. Aucun événement web ne configure
un GPIO et aucun nouveau code ne commande GPIO17, un UDC, un Drive ou une image.
Les actions physiques longues existantes sont conservées, avec leurs seuils.

Les deux producteurs se transmettent la propriété de l'écran comme auparavant :
le menu arrête l'affichage normal avant ses dessins, puis le relance à sa sortie.
Le socket reste dans le processus du bouton, distinct du producteur normal arrêté.
Il n'existe pas de troisième producteur web.

## API

Toutes les routes utilisent l'authentification et les cookies KVMD déjà partagés
par l'API Portable OS ; aucun nouveau mot de passe n'est créé.

| Route | Résultat |
| --- | --- |
| `GET /extras/portable-os/api/oled` | Framebuffer et état physique ; 503 si absent ou périmé |
| `POST /extras/portable-os/api/oled/short` | Appui court consommé par le gestionnaire |

La requête POST doit être exactement `{"action":"short","frame_id":"…"}` et
porter les protections CSRF/origine existantes. Aucun paramètre de durée, GPIO ou
commande n'est accepté. Le socket `/run/pikvm-oled/button.sock` est 0600 ; sous Linux,
le serveur vérifie également l'UID root du client local (API). Une réponse positive
signifie que l'entrée a été consommée ; le rendu suivant peut encore être en cours.
Si le gestionnaire est arrêté ou occupé, la requête échoue sans entrée différée.

## Fichiers

- Ajouts : `scripts/pikvm_oled.py`, `scripts/pikvm-oled-baselines.json`,
  `web/extras/portable-os/modules/oled.js`, `tests/test_oled.py`, ce document.
- Producteurs modifiés : `scripts/pikvm-oled-custom`, `scripts/pikvm-button-menu`.
- Intégration : `scripts/pikvm-portable-api`, `scripts/pikvm-portable-install`,
  `scripts/pikvm-portable-package.py`, `web/extras/portable-os/{app.js,index.html,style.css,package.json}`.
- Tests : `tests/{test_portable_os.py,test_portable_install.py,portable-ui.test.mjs,portable-browser.cjs,portable_preview.py}`
  et `tests/fixtures/oled-frames.json` (vrais dessins enregistrés avec télémétrie simulée).
  Workflow `.github/workflows/pikvm-share.yml` : Pillow pour les tests.
- Installation initiale : `install.sh` copie aussi le module partagé ; `.gitattributes`
  impose LF aux scripts OLED pour les réinstallations depuis GitHub.
- Documentation : `README.md`.

Les fichiers de service systemd sont analysés mais ne sont pas remplacés : leurs
ExecStart utilisent déjà les deux scripts concernés. L'installateur sauvegarde et
restaure leurs états actif/activé. Il les active pour les démarrages futurs et les
lance pour le miroir, même sans écran. Leur lancement pendant la migration utilise
`--job-mode=ignore-dependencies` pour ne jamais démarrer indirectement le service
power-hold. Le précontrôle exige que ce dernier soit **déjà actif** ; il ne le démarre pas.

## Tests et limites

Bilan local : **91 tests Python réussis, deux ignorés sous Windows**, **18 tests
JavaScript réussis**, scénario Edge desktop/tactile réussi, validations nginx et
syntaxe Bash/Python réussies. Les deux exclusions sont le transport AF_UNIX et un
test existant nécessitant les privilèges de création de liens symboliques Windows.

Les tests locaux comparent les octets publiés à ceux remis au pilote physique
simulé, exécutent les vrais dessins de statut et de menus, vérifient le mode sans
I2C et parcourent la vraie boucle de navigation avec des entrées courtes.
Ils vérifient aussi les gestes très ralentis, les collisions physiques, le refus
des actions dangereuses, les frames périmées, l'authentification, CSRF et les
correctifs locaux non reconnus. Le navigateur teste ouverture, pixels, clic/tactile,
états hors ligne, fermeture et arrêt de l'actualisation.

Le runtime Python Windows ne fournit pas AF_UNIX : le test du transport Unix réel
est ignoré localement et prévu dans la matrice CI Linux Python 3.11/3.14. La logique
du bouton et le protocole encadré sont testés séparément sous Windows. La CI n'a
pas été lancée à distance pendant ce développement. Aucune validation I2C, GPIO ou
vidéo n'est revendiquée sur le Raspberry Pi.

Les messages de démarrage électrique du script power-hold, exécutés avant que le
Web soit disponible, ne sont pas ajoutés au miroir : ce script reste intégralement
inchangé. Le miroir concerne les deux producteurs OLED demandés une fois les
services applicatifs démarrés.

## Déploiement — après autorisation explicite seulement

La candidate reprend les contrôles KVMD 4.213 / Python 3.14.7-1 et nginx de RC2.
Le précontrôle refuse un script OLED installé différent de la version de base
connue **et** de la nouvelle version, afin de ne pas écraser un correctif local.
Dans ce cas, examiner le diff des deux scripts avant toute migration ; ne pas
contourner ce contrôle ni recopier aveuglément les fichiers du dépôt.

Sur Windows, construire l'archive (ou utiliser celle livrée) et transférer :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.3.tar.gz private/pikvm-portable-os-0.2.0-rc.3.tar.gz.sha256 root@192.168.168.99:/tmp/
ssh @sshOptions root@192.168.168.99
```

Saisir le mot de passe aux invites, sans l'inscrire dans un fichier ou une commande.
Sur le Pi, après autorisation du déploiement :

```bash
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.3.tar.gz.sha256
work=$(mktemp -d /tmp/portable-os-rc3.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.3.tar.gz -C "$work"
cd "$work/pikvm-portable-os-0.2.0-rc.3"
sha256sum -c MANIFEST.sha256
python3 -B scripts/pikvm-portable-install check
```

Si les contrôles passent et la modification est autorisée :

```bash
rw
bash install-portable-os.sh
ro
```

Conserver le chemin de sauvegarde imprimé. Les deux scripts, le module partagé,
l'API, le frontal et la configuration nginx sont inclus dans la transaction.
Les services OLED/bouton sont arrêtés avant les copies puis relancés ; leurs états
antérieurs sont mémorisés. Une erreur provoque le rollback.
Le basculement attend un framebuffer publié après la mise à jour et un contrôle
de santé du socket, sans injecter d'appui. Un ancien fichier ou socket ne suffit pas.
Une absence de disponibilité provoque aussi le rollback. Aucun redémarrage
matériel, service KVMD ou power-hold n'est demandé. Les services d'arrêt automatique,
les correctifs Python système, Drive 0/1 et les données SHARE ne sont pas modifiés.

Ouvrir Portable OS, cliquer la carte Pi Zero 2 W, vérifier les pages normales,
puis toucher l'écran pour ouvrir POWER et parcourir WIFI / DEPANNAGE / ISO.
Vérifier qu'un toucher maintenu ne produit qu'un appui court, puis laisser expirer
le menu. Une reconnexion physique de l'OLED devra montrer les mêmes pixels ; le
pilote est réessayé sous 30 secondes lors d'un prochain dessin.

## Retour arrière

Depuis SSH, utiliser le chemin exact imprimé, en remplaçant `DATE-ID` :

```bash
rw
python3 -B /usr/local/bin/pikvm-portable-install restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

Le script de l'archive vérifiée peut également exécuter `restore` si celui installé
est indisponible. La restauration vérifie les empreintes avant d'arrêter les
services, remet les anciens fichiers et la navigation, valide/recharge nginx puis
restaure les états actif/activé des deux services OLED. Elle peut être répétée.
Si l'OLED était arrêté ou désactivé avant la migration, il le redevient. Le
framebuffer temporaire devient périmé et n'est plus exposé par l'ancienne API.
Les anciennes versions peuvent à nouveau échouer sans écran physique : il s'agit
du comportement sauvegardé, pas d'une réparation ou d'un changement matériel.
