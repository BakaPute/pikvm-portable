# RC8 corrigée : profil réel GPIO18 `ip --`

Pour le noyau 6.12 sans fichier sysfs `resource`, utiliser aussi
[le correctif de validation Device Tree/sysfs](portable-os-rc8-sysfs.md).

Le test matériel communiqué montre deux impulsions HIGH d'environ **554 ms** et
**332 ms**, avec retour LOW. Il confirme la polarité historique HIGH=appuyé et le
fonctionnement du lecteur pinctrl sur cette installation. Il ne constitue pas à
lui seul une comparaison avec `/dev/gpiomem`.

Le correctif remplace l'exigence exclusive `ip pd` de la première RC8. `--` est
traité comme un **profil de sortie pinctrl observé**, sans en déduire une absence
de résistance ou une valeur électrique de pull. Aucune commande de configuration,
écriture de registre ou opération sur GPIO17 n'est ajoutée.

## Conditions d'acceptation

- Le parser reconnaît uniquement `18: ip pd | lo/hi` et `18: ip -- | lo/hi`, avec
  commentaire pinctrl optionnel. Les sorties partielles, mode sortie, `pu` et autres
  configurations sont refusés.
- Le fallback pinctrl accepte `ip --` seulement après identification exacte du
  **Zero 2 W / BCM2837** dans le Device Tree, conformément au test utilisateur.
  Il reste utilisable si l'ouverture MMIO est indisponible. Ailleurs, ce nouveau
  profil est refusé. La polarité reste HIGH=appuyé.
- Le lecteur rapide exige en plus les vérifications matérielles RC8 existantes
  et une preuve explicite de concordance **LOW et HIGH** issue du diagnostic ci-dessous.
  Sans preuve valide, il reste en fallback ; un simple LOW commun ne suffit pas.
- La preuve est privée, root-owned, sous `/run/pikvm-oled/gpio18-validation.json`.
  Elle est liée au boot ID, à l'identité de plateforme/devices, au profil exact et
  à une validation datant de moins de 24 h lors de l'activation. Elle ne survit pas
  à un redémarrage. Aucun fichier utilisateur ou image disque ne sert de preuve.

## Comparaison passive des deux lecteurs

Les lectures sont séquentielles : MMIO avant, pinctrl, MMIO après. Si les deux
lectures MMIO diffèrent, une transition a traversé la mesure : la paire est écartée
et ne compte pas comme preuve. Si MMIO est stable mais pinctrl indique l'inverse,
la validation échoue. Un changement de profil, même à niveau identique, échoue.
Un rebond qui traverse entièrement la fenêtre peut donc provoquer un refus
conservateur ; il ne doit jamais autoriser le lecteur rapide par approximation.

Le diagnostic demande au moins deux paires stables par niveau et **deux cycles
complets LOW/HIGH/LOW**. Il ne simule aucun appui. Une revalidation avec sauvegarde
retire d'abord l'ancienne preuve : un échec ne laisse pas une ancienne réussite
autoriser une nouvelle activation. La seule écriture est ce fichier de validation
temporaire, jamais le GPIO.

Après transfert manuel de l'archive vérifiée, dans le stage corrigé sur le Pi :

```bash
python3 -B scripts/pikvm_gpio.py --diagnose
python3 -B scripts/pikvm_gpio.py --compare --seconds 30
```

Pendant les 30 secondes, faire **deux appuis courts contrôlés**, relâchés entre eux,
semblables aux 332/554 ms déjà mesurés ; laisser le bouton relâché à la fin.
Ne pas maintenir 2/3/5 s pour ce diagnostic. Le gestionnaire en service réagira
normalement aux appuis physiques : choisir un contexte de menu non sensible.
Le diagnostic ne stoppe ni ne reconfigure ce service.

Si le rapport est satisfaisant, refaire les deux appuis pour enregistrer la preuve :

```bash
python3 -B scripts/pikvm_gpio.py --compare --seconds 30 --save-validation
python3 -B scripts/pikvm_gpio.py --diagnose
```

Attendre `valid: true`, `config: "ip --"`, au moins deux cycles, et ensuite
`backend: "gpiomem-readonly"`. Un échec rend un code non nul et le motif explicite.
Ne pas contourner le contrôle si la plateforme, les permissions ou les niveaux
ne concordent pas. Ces commandes ne sont pas exécutées automatiquement.

## Surveillance en service

Le sampler reste à 40 ms et son chemin ne lance pas de commande. Le thread de
heartbeat **déjà existant** effectue au maximum une vérification pinctrl par
seconde, hors du chemin d'échantillonnage et de gestion des gestes. Cette
supervision remplace la promesse « zéro commande continue » de la première RC8 :
le budget devient environ **1 commande/s**, contre jusqu'à 25/s en RC7/fallback.

La configuration est liée à celle sélectionnée au démarrage. Une divergence,
sortie non reconnue, timeout ou changement de profil verrouille le lecteur rapide
en erreur. La prochaine lecture devient inconnue et les protections existantes
annulent le maintien physique ; aucun dernier HIGH n'est prolongé. Un contrôle
de plus de deux secondes d'ancienneté rend également le lecteur indisponible.
Le diagnostic heartbeat expose `input.validation.config` et `failure`.

Le changement de direction est toujours vérifié à chaque lecture MMIO. Une
modification de profil/biais rapporté par pinctrl est détectée par la supervision,
avec son délai borné nominal, pas instantanément. Deux changements entre deux
contrôles ne sont pas observables ; `--` ne donne pas un readback électrique de
tous les pulls. Aucun outil purement passif ne peut garantir leur absence.

Le verrou d'erreur n'est pas levé silencieusement : vérifier de nouveau les niveaux
avant une relance applicative autorisée. Le fallback initial et les gestes virtuels
restent disponibles ; un GPIO incertain ne prolonge ni ne renouvelle leur bail
de 800 ms. Les permissions, CSRF et règles d'actions sensibles sont inchangées.

## Mise à jour et restauration

Archive distincte, sans écraser la première RC8 :

```powershell
python -B scripts/pikvm-portable-package.py --output private/pikvm-portable-os-0.2.0-rc.8-gpio-profile-fix.tar.gz
```

Utiliser le transfert SSH **root par mot de passe** décrit dans
[la procédure RC8](portable-os-rc8.md#livraison-et-installation-rc8), en remplaçant
les noms de l'archive et de son `.sha256` par ceux du correctif. Conserver l'ancien
stage. Sur le Pi, seulement après autorisation de transfert :

```bash
set -e
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.8-gpio-profile-fix.tar.gz.sha256
stage=$(mktemp -d /tmp/pikvm-portable-os-rc8-profile.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.8-gpio-profile-fix.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
python3 -B scripts/pikvm-portable-install check
```

Faire ensuite la comparaison contrôlée et son enregistrement ci-dessus. Après
succès, utiliser les commandes `install`/`restore` de la procédure RC8, seulement
avec autorisation de déploiement. Ne pas copier le module seul. Les empreintes de
la première RC8 sont reconnues ; les correctifs locaux inconnus restent refusés.
La sauvegarde transactionnelle remet exactement la version précédemment installée,
RC7 ou première RC8 selon le cas. Le fichier de preuve sous `/run` n'est pas une
configuration persistante ni une donnée à restaurer.

## Validation locale et limites

Tests : acceptation du profil exact sur carte connue, refus sur carte inconnue,
preuve obligatoire pour le chemin rapide, changement de profil à niveau identique,
divergence LOW/HIGH, preuve périmée/autre boot/autre matériel/incomplète,
deux cycles contrôlés, invalidation de l'ancienne autorisation après échec,
watchdog du contrôle périodique. Les tests historiques de rebonds, pertes GPIO,
appuis 2/3/5 s, collisions physiques/virtuelles et expiration de bail restent exécutés.

Les résultats matériels fournis sont conservés comme contexte utilisateur. Aucune
concordance MMIO/pinctrl ni baisse de CPU réelle n'est revendiquée avant la
comparaison sur le Pi. Aucun déploiement automatique.

Bilan local : **153 tests Python réussis, 2 ignorés sous Windows** (155 au total),
**22 tests JavaScript réussis**. Python local 3.12.14 ; aucune validation matérielle
MMIO, Python 3.14/Linux ni mesure CPU sur le Pi revendiquée. Les empreintes de
migration de la première RC8 et le manifeste de l'archive corrigée sont vérifiés.
