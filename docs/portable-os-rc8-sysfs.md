# RC8 : validation sysfs/Device Tree sans fichier resource obligatoire

Correctif local de RC8 `341d879`, destiné au Zero 2 W décrit avec noyau
`6.12.105-1-rpi`. Aucun accès SSH, transfert, déploiement ou mesure matérielle effectué.
Les observations GPIO17 HIGH, GPIO18 `ip --` et LOW/HIGH/LOW sont celles communiquées
par l'utilisateur ; le correctif n'écrit aucun GPIO et ne modifie pas le démarrage.

## Cause et correspondance matérielle

La première validation RC8 imposait un attribut sysfs `resource` et une fenêtre de
4096 octets. Cette présentation sysfs n'est pas disponible sur le noyau testé.
Cela ne prouve pas l'absence de ressources internes du device plateforme.

Le correctif valide désormais une seule chaîne de preuves, avec ou sans cet attribut :

1. Carte Zero 2 W et SoC BCM2837 reconnus par `compatible`, avant tout mapping.
2. `/dev/gpiomem` caractère, major/minor lus dynamiquement (238:0 sur la cible),
   classe sysfs unique et lien `/sys/dev/char/238:0` vers le même device canonique.
   Si `uevent` est disponible, MAJOR, MINOR et DEVNAME doivent également correspondre.
3. Lien du pilote reconnu `rpi-gpiomem` (ou ancien `gpiomem-bcm2835`) vers
   `/sys/devices/platform/soc/3f200000.gpiomem`, backlink `driver` concordant et
   `of_node` vers le binding legacy `brcm,bcm2835-gpiomem` du Device Tree courant.
4. Contrôleur `soc/gpio@7e200000` compatible `brcm,bcm2835-gpio`, actif, avec
   `reg = <0x7e200000 0xb4>`. Le `reg` du **nœud lié à gpiomem** est aussi vérifié :
   même base, taille 0xb4 ou 0x1000. La taille du contrôleur et celle du mapping du
   pilote sont distinctes. Le seul reg GPIO ne suffit pas à autoriser gpiomem.
5. Décodage big-endian des propriétés réelles `#address-cells`, `#size-cells` et
   `soc/ranges`. Une ou deux cellules d'adresse parent sont prises en charge.
   Aucun comptage ni adresse de remplacement n'est deviné si une propriété manque.

Pour la plage BCM2837 attendue, mais **après lecture et validation** :

```text
soc/ranges : bus 0x7e000000 -> CPU 0x3f000000, longueur 0x01000000
GPIO bus   : 0x7e200000, longueur 0xb4
CPU        : 0x3f000000 + (0x7e200000 - 0x7e000000) = 0x3f200000
```

La plage doit couvrir entièrement chaque fenêtre et donner une traduction unique.
Les chevauchements partiels, plages ambiguës, troncatures, débordements et autres
adresses physiques sont refusés. Une carte non reconnue n'arrive pas au mapping.

Si `resource` manque, le diagnostic indique `resource_present: false` et
`basis: device-tree+sysfs-links`. Si le fichier est présent, ses bornes et son flag
mémoire doivent correspondre au Device Tree ; une contradiction, erreur de lecture
ou valeur malformée reste fatale à la sélection du lecteur rapide.

Le driver legacy crée la classe caractère sans parent plateforme direct. La
correspondance utilise donc l'identité caractère/classe, l'unicité du binding
legacy, les liens du pilote et les propriétés OF ; aucun faux lien `device` n'est
supposé entre la classe virtuelle et le device plateforme.

Références primaires :
[spécification Device Tree, reg/ranges/cellules](https://devicetree-specification.readthedocs.io/en/stable/devicetree-basics.html),
[ranges BCM2837 officiels](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/arch/arm/boot/dts/broadcom/bcm2837.dtsi),
[driver gpiomem Raspberry Pi 6.12](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/drivers/char/raspberrypi-gpiomem.c).

## Diagnostic passif et activation

Le mapping conserve O_RDONLY, ACCESS_READ et une vue mémoire read-only ; aucune
réservation de ligne GPIO, écriture de registre, configuration de pull, ioctl GPIO,
modification de Device Tree ou chargement de module. GPIO17 n'est pas modifié.

Le diagnostic ajoute les propriétés DT brutes en hexadécimal, les liens plateforme,
driver et of_node, les reg du nœud gpiomem et les fenêtres décodées. Ces informations
restent disponibles même quand la sélection échoue, avec le motif complet dans
`hardware.platform_validation.error`. Le fallback pinctrl est conservé.

Après transfert manuel du stage corrigé, **seulement après autorisation** :

```bash
python3 -B scripts/pikvm_gpio.py --diagnose
```

Vérifier `hardware.platform_validation` : identité 238:0 sur cette cible, lien vers
`rpi-gpiomem`, `resource_present: false` accepté, bus 2116026368 (`0x7e200000`),
physical 1059061760 (`0x3f200000`), taille GPIO 180 (`0xb4`). Les nombres JSON sont
décimaux. Si `of_node/reg`, `ranges`, cellules ou liens sont absents/incompatibles,
ne pas forcer les adresses : conserver la sortie complète pour examen.

Les preuves LOW/HIGH précédentes ne correspondent plus à l'identité enrichie.
Le lecteur rapide reste refusé tant qu'une nouvelle comparaison n'a pas réussi :

```bash
python3 -B scripts/pikvm_gpio.py --compare --seconds 30 --save-validation
python3 -B scripts/pikvm_gpio.py --diagnose
```

Faire deux appuis **courts** contrôlés avec relâchement complet, sans maintien
sensible. Le service bouton actif réagit normalement à ces appuis ; choisir un
contexte non sensible. La commande ne simule pas d'appui et ne stoppe aucun service.
Elle enregistre uniquement une preuve temporaire privée sous `/run` après succès.
Attendre deux cycles et les paires stables LOW et HIGH avant toute activation.
Le détail de cette validation est dans [le correctif du profil ip --](portable-os-rc8-gpio-profile.md).

Les règles de supervision, de fallback, de panne GPIO, de gestes physiques et
virtuels, les permissions sensibles et le bail de 800 ms sont inchangés. Une
concordance DT ne remplace jamais la comparaison réelle des niveaux.

## Installation et retour arrière

Archive distincte de la première RC8 et du correctif de profil :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python -B scripts/pikvm-portable-package.py --output private/pikvm-portable-os-0.2.0-rc.8-sysfs-fix.tar.gz
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
$PiKvmHost = Read-Host 'Adresse IP actuelle du PiKVM'
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.8-sysfs-fix.tar.gz private/pikvm-portable-os-0.2.0-rc.8-sysfs-fix.tar.gz.sha256 "root@${PiKvmHost}:/tmp/"
ssh @sshOptions "root@${PiKvmHost}"
```

Mot de passe aux invites uniquement. Ces commandes sont proposées, non exécutées.
Après autorisation de transfert, préparer sans remplacer l'ancien stage :

```bash
set -e
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.8-sysfs-fix.tar.gz.sha256
stage=$(mktemp -d /tmp/pikvm-portable-os-rc8-sysfs.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.8-sysfs-fix.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
python3 -B scripts/pikvm-portable-install check
```

Effectuer alors le diagnostic et les deux appuis contrôlés ci-dessus. Si les
vérifications réussissent et après autorisation explicite de déploiement, utiliser
la transaction d'installation RC8 existante :

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

Conserver le chemin de sauvegarde imprimé. Les empreintes des RC8 précédentes
sont reconnues ; les correctifs locaux inconnus ne sont pas écrasés. Vérifier le
backend réellement sélectionné et `/run/pikvm-oled/button.json` après démarrage
applicatif. Aucun redémarrage matériel ni changement power-hold demandé.

Pour restaurer exactement l'état pré-installation (DATE-ID imprimé lors de cette
installation, `stage` à redéfinir si le shell a été fermé) :

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

Le script installé peut aussi restaurer si le stage temporaire a disparu. Une
preuve d'activation sous `/run` n'est jamais restaurée comme une donnée utilisateur.

## Tests et limites

**159 tests Python réussis, 2 ignorés sous Windows** (161 au total),
**22 tests JavaScript réussis**. Nouveaux scénarios : absence de resource, cellules
parent 32/64 bits, reg GPIO b4, fenêtres gpiomem b4/1000, mauvais ranges même avec
resource présent, traductions partielles/ambiguës, compatibles et statuts incorrects,
major/minor incohérents, liens driver/of_node/char erronés, resource contradictoire
et plusieurs bindings. Les tests existants couvrent toujours LOW/HIGH, rebonds,
pertes GPIO, maintiens 2/3/5 s, collision physique/virtuel, alimentation et bail.

Fixtures DT/sysfs et résolution de liens simulées : aucun périphérique matériel
ou symlink privilégié Windows nécessaire. Python local 3.12.14 ; aucune exécution
sur le Pi ou validation Linux/Python 3.14 distante revendiquée. Les propriétés
restant à confirmer sur la cible sont exposées par le diagnostic, jamais déduites
du seul numéro de noyau. La baisse CPU reste à mesurer après validation autorisée.

Fichiers modifiés : `scripts/pikvm_gpio.py`, baselines de migration, empaqueteur,
`tests/test_gpio_platform.py`, test historique de refus d'une ressource seule,
README et documentation. Aucun changement des menus, du KVM natif, de SHARE,
des GPIO, des services ou de la configuration du démarrage.
