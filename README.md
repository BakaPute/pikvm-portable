# PiKVM Portable OS

**Un PiKVM autonome sur batterie, construit autour d'un Raspberry Pi Zero 2 W, avec une interface Web unifiée.**

Le projet associe un montage matériel portable (batterie, relais d'alimentation, OLED, bouton et Wi-Fi de secours) à **Portable OS**, qui regroupe dans une même interface la console KVM, les images ISO, les lecteurs USB, le partage de fichiers, les réglages et les diagnostics.

> **État au 6 novembre 2026 :** **Portable OS 0.2.0-rc.13.2 est installée** sur le PiKVM de développement. La gestion des comptes Portable est présente, mais leur **portail de connexion restreint reste inactif** : DNS, TLS, nginx et les tests de la passerelle sont à finaliser. Ce dépôt n'est pas une image prête à flasher.

[Code de développement](https://github.com/BakaPute/pikvm-portable/tree/codex/portable-os) · [Guide RC13.2](https://github.com/BakaPute/pikvm-portable/blob/codex/portable-os/docs/portable-os-rc13.2.md) · [Documentation de l'interface](https://github.com/BakaPute/pikvm-portable/blob/codex/portable-os/docs/portable-os.md)

## Fonctionnalités

| Domaine | Fonctionnalités | État |
|---|---|---|
| **KVM** | Capture HDMI, clavier et souris USB, commandes intégrées, accès natif de secours `/legacy/` | Opérationnel ; validation vidéo HDMI complète de RC13.2 encore requise |
| **Images / Drive 0** | Bibliothèque ISO/IMG/RAW, dossiers, importation, déplacement, renommage, montage et éjection | Installé ; opérations sensibles protégées |
| **PIKVM-SHARE / Drive 1** | Clé USB indépendante, import/téléchargement de fichiers, bascule USB/Web et éjection propre | Installé |
| **OLED et bouton** | Afficheur 128 × 64, miroir Web, modes lisible/compact, compteur Batterie, pages et gestes configurables | Installé |
| **Alimentation** | Batterie 18650, jauge MAX17048, relais de maintien et télémétrie | Installé, précautions GPIO17 indispensables |
| **Réseau** | Assistant Wi-Fi et point d'accès de dépannage | Installé |
| **Portable OS** | Tableau de bord, thèmes clair/sombre, paramètres, journaux, diagnostics, préférences persistantes | Installé |
| **Utilisateurs** | Comptes, rôles, permissions par catégories, recherche et droits effectifs | Gestion installée ; **connexion restreinte non activée** |
| **Sécurité** | Portail Web dédié et passerelle appliquant les autorisations côté serveur | Code préparé, mais activation et validation sur le Pi en attente |

## Accès Web et authentification

- **Administration native :** `https://<ip-du-pikvm>/`. Sur le Pi de développement : `https://192.168.168.99/`.
- **Portable OS :** `/extras/portable-os/` depuis l'accès administrateur.
- **Portail des comptes Portable prévu :** `https://share.pikvm.home.arpa:8443/login/`. **Non accessible actuellement** : configuration TLS/nginx et activation de la passerelle encore en attente.

Les comptes **Portable**, **KVMD natifs** et **Linux/SSH** sont volontairement séparés. Un compte créé dans les paramètres Portable OS ne peut pas être utilisé sur la page de connexion KVMD native.

La migration du certificat HTTPS natif (actuellement autosigné et dépourvu de SAN adapté à l'IP) vers une autorité locale de confiance est **en préparation**, pas déployée. Ne pas désactiver les vérifications TLS pour contourner l'avertissement du navigateur.

## Matériel

- Raspberry Pi **Zero 2 W** et adaptateur de capture HDMI → CSI compatible PiKVM.
- Écran OLED SSD1306 **128 × 64** en I²C (`0x3C`).
- Jauge de batterie **MAX17048** en I²C (`0x36`).
- Batterie **18650**, chargeur/protection USB-C, Step-Up réglé à **5,1 V**.
- Relais **SRD-05VDC-SL-C**, MOSFET low-side et bouton poussoir.
- Breakout USB-C USB 2.0 avec résistances 5,1 kΩ sur CC1/CC2, diodes Schottky SS34 et résistances 47 kΩ / 100 kΩ.

| Fonction | GPIO BCM | Broche physique |
|---|---:|---:|
| **Maintien d'alimentation** | **GPIO17** | **11** |
| Bouton | GPIO18 | 12 |
| I²C SDA | GPIO2 | 3 |
| I²C SCL | GPIO3 | 5 |

Les GPIO 22, 23, 24 et 27 restent réservés aux fonctions ATX PiKVM.

### Précautions matérielles impératives

**GPIO17 doit rester en sortie HIGH pendant le fonctionnement** : il maintient le relais d'alimentation. Le désactiver, redémarrer `pikvm-power-hold.service` ou effectuer un redémarrage non préparé peut interrompre brutalement l'alimentation.

Le relais coupe le **positif** de la batterie en amont du Step-Up ; les masses restent communes pour éviter les retours de courant par HDMI/USB. Respecter la configuration de GPIO18 et l'accès I²C. Vérifier les transferts et montages USB/SHARE avant toute migration. Les partitions système sont normalement en **lecture seule** et doivent revenir en RO après toute intervention.

L'arrêt automatique sur inactivité est **facultatif et désactivé tant qu'il n'est pas explicitement activé** ; les installateurs ne l'activent pas.

## Historique récent

| Version | Principaux changements |
|---|---|
| **RC13.2 — installée** | Éditeur de permissions plus large, groupes repliables, recherche, portail Portable dédié préparé, optimisation expérimentale de chargement de configuration et mesures USS/PSS. |
| **RC13.1** | Politique de mots de passe Portable assouplie, accents OLED, compteur Batterie et indicateurs RAM. |
| **RC13** | Comptes et rôles Portable, contrôle des permissions côté serveur et préparation des accès HTTPS/SSH restreints. |
| **RC12 / RC12.1** | Personnalisation et amélioration de la lisibilité de l'OLED. |
| **RC11** | Centre de paramètres, préférences persistantes, diagnostic et configuration OLED. |
| **RC10.x** | Fiabilisation des transferts, gestion des images et intégration SHARE. |

Les versions précédentes, correctifs et limites sont documentés dans le [guide RC13.2](https://github.com/BakaPute/pikvm-portable/blob/codex/portable-os/docs/portable-os-rc13.2.md) et le dossier `docs/` de la branche de développement.

### Mémoire : mesures et limites

Le Pi Zero 2 W expose environ **389 Mio** de RAM à Linux. Lors d'un essai **isolé** sur le Pi, l'optimisation de lecture de la configuration KVMD a réduit la **PSS du processus API de 19,49 Mio**, avec un premier appel passant de **5,87 à 7,29 secondes**. Ce résultat **ne constitue pas un gain global démontré en production** : certaines écritures PST peuvent recharger les modules natifs. Des mesures prolongées et des comparaisons avec vidéo HDMI active restent nécessaires.

## Installation et mises à jour

**Ne pas confondre installation initiale du matériel et mise à jour de Portable OS.**

Pour consulter les sources et les procédures de développement :

```bash
git clone --branch codex/portable-os https://github.com/BakaPute/pikvm-portable.git
cd pikvm-portable
# Lire docs/portable-os-rc13.2.md avant toute opération sur le Pi.
```

- **Installation initiale** : `install.sh --initial-hardware-setup` configure notamment le démarrage et l'alimentation. Usage réservé à une nouvelle installation matérielle après vérification du câblage, jamais pour une mise à jour RC.
- **Mise à jour Portable OS** : installateur additif `install-portable-os.sh`, avec archive et manifeste SHA256 vérifiés, précontrôles, sauvegarde de la **version réellement installée**, autorisation explicite et procédure de rollback.
- Un commit publié ou des tests CI réussis **ne constituent pas une autorisation de déploiement**. Ne jamais activer automatiquement la passerelle, modifier nginx/TLS ou créer des comptes Linux.

## Documentation

- [Architecture Portable OS](https://github.com/BakaPute/pikvm-portable/blob/codex/portable-os/docs/portable-os.md)
- [RC13.2 : permissions, portail, mémoire, tests et restauration](https://github.com/BakaPute/pikvm-portable/blob/codex/portable-os/docs/portable-os-rc13.2.md)
- [RC13.1 : OLED, mots de passe, RAM et HTTPS](https://github.com/BakaPute/pikvm-portable/blob/codex/portable-os/docs/portable-os-rc13.1.md)
- [RC13 : utilisateurs et passerelle](https://github.com/BakaPute/pikvm-portable/blob/codex/portable-os/docs/portable-os-rc13.md)
- [PIKVM-SHARE](https://github.com/BakaPute/pikvm-portable/blob/codex/portable-os/docs/pikvm-share.md)
- [Miroir OLED](https://github.com/BakaPute/pikvm-portable/blob/codex/portable-os/docs/portable-os-oled.md)

## Statut

Projet personnel **expérimental**, développé sur la branche [`codex/portable-os`](https://github.com/BakaPute/pikvm-portable/tree/codex/portable-os). **RC13.2 est installée**, mais les comptes Portable restreints ne peuvent pas encore se connecter : le portail du port 8443 et la passerelle restent inactifs jusqu'à validation réelle de TLS, nginx et des règles d'accès.
