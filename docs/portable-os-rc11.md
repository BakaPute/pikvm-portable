# RC11 — Centre de configuration avancé

Configuration partagée versionnée, sans activation d’une règle d’alimentation ni
changement électrique. Aucun succès matériel n’est déduit des fixtures. Le résultat
du déploiement est consigné séparément dans le compte rendu de livraison.

## Capacités réellement exposées

Douze catégories, recherche instantanée, brouillon, Appliquer/Annuler/défauts,
valeurs enregistrées et défauts, validation serveur, confirmations sensibles,
navigation tactile et thème sombre. Tous les réglages exposés s’appliquent à chaud.

| Catégorie | Capacités |
|---|---|
| Général | Thème partagé, migration proposée de l’ancien thème local |
| Inactivité et veille | Suivi désactivé par défaut, délais en secondes, avertissement, actions OLED noir/écran d’inactivité/économie, sources indépendantes, diagnostic et simulation |
| Alimentation et batterie | Seuils bas/critique, alertes Web, accès aux mesures MAX17048 existantes |
| OLED et écrans | Pages existantes activables, ordre par glisser-déposer ou boutons, durées individuelles, page permanente, priorités batterie/transfert, rotation 0/180°, contraste SSD1306 |
| Bouton physique | Appui court hors menu : menu/page suivante/batterie/accueil ; maintien 2 s ouvre toujours le menu ; expiration du menu |
| Console KVM | Ordre et visibilité des commandes, panneau initial, cadrage vidéo, cible du plein écran ; capture manuelle et libération toujours accessibles |
| USB et stockage | Tri nom/taille/date, dossier favori dans Images & Drive 0, accès aux diagnostics/gestion existants |
| Réseau | IP sur OLED/tableau de bord, alertes de télémétrie ; liens vers les changements réseau déjà confirmés |
| Performances et ressources | Profils de polling, animations, RAM/disponible, PSI, CPU échantillonné, charge, stockage ; états et compteurs de redémarrage dans Outils |
| Sécurité et maintenance | Version/date d’installation, intégrité applicative, rapport JSON sans secrets |
| Sauvegarde et restauration | Export/import strict des préférences, défauts, historique borné des champs modifiés |
| Options avancées | Affichage technique facultatif ; limites de sécurité explicites |

Le brouillon OLED réutilise les **fonctions de dessin du script natif** avec des
données d’exemple et le même traitement de rotation que le périphérique réel.
Il n’instancie pas de pilote I2C et n’applique pas le brouillon. Le miroir en direct
affiche séparément les pixels réellement publiés. Une erreur de configuration
stockée entraîne les valeurs sûres ; elle ne désactive ni GPIO, ni KVM, ni stockage.

## Inactivité : portée exacte et protections

Les événements reconnus sont les interactions Web, clavier/souris du KVM intégré,
terminal intégré, bouton/menu, et les opérations transfert/import ou verrous
stockage effectivement observés. La simple présence d’un média n’est jamais
traitée comme une écriture. Le KVM visible possède un bail de présence de 25 s,
distinct de l’activité. Les signalements navigateur sont bornés à un par source
et par 10 s ; le producteur physique écrit seulement de petites métadonnées tmpfs.

Les deux lecteurs attachés/inconnus, les transferts, SHARE, les écritures stockage
et la maintenance restent des inhibiteurs obligatoires. RC11 ne sait pas prouver
l’absence de **tous** les écrivains natifs, d’une installation externe ou de toute
session SSH. Ces observations restent donc inconnues. Une observation inconnue
n’est jamais remplacée par « libre ».

**L’arrêt réel n’est pas activable dans RC11.** Il n’existe aucun exécuteur d’arrêt
dans le nouveau moteur. Le diagnostic explique ce refus ; la simulation utilise
des observations synthétiques clairement identifiées. Les gestes matériels
d’alimentation et l’arrêt manuel existants conservent leurs protections. Aucun
test ne coupe l’alimentation. Les actions logicielles de repos n’effacent pas les
alertes batterie/transfert et ne masquent pas les menus interactifs.

## Limites et options volontairement indisponibles

- Pas de veille matérielle, changement de fréquence/tension ou swap microSD.
- Le pourcentage de batterie est une estimation du code existant ; la charge
  positive ne prouve pas une alimentation externe. Pas de délais secteur/batterie
  séparés ni d’arrêt critique fondé sur une déduction incertaine.
- Pas de détection des frappes SSH, du montage Windows, de présence humaine,
  des clients KVM externes ou d’une activité déduite du signal HDMI/réseau.
- Pas de déplacement libre des pixels/tailles de police : les quatre pages
  natives restent la base stable 128×64. Pas de second moteur ni de nouveaux
  sondages I2C pour des pages coûteuses. Les alertes conditionnelles configurées
  concernent les mesures déjà disponibles (batterie/transfert).
- Pas de double-clic ni de remappage des gestes sensibles. Les durées 2/3/5 s,
  l’origine des gestes, l’annulation GPIO incertaine et le bail virtuel 800 ms
  restent dans le gestionnaire existant. Un clic ne peut pas devenir un arrêt.
- Macros/raccourcis restent dans KVMD natif. Aucune connexion USB initiale,
  suppression de conteneur, modification réseau automatique ou désactivation
  de contrôle d’intégrité n’est proposée.

## Stockage des préférences et compatibilité

`scripts/pikvm_config.py` est partagé par Python et l’API. Schéma 1, types stricts
(booléens distincts des entiers), bornes, chemins relatifs, ensembles fermés,
révisions optimistes et verrou interprocessus. Les champs inconnus sont refusés.
Les imports ont un format/version uniques, ne contiennent pas de shell, secret,
historique ou jeton, et nécessitent une confirmation.

Le chemin provient du contrat `X-kvmd.pst-root/user/group` de `/etc/fstab` : sur
le Pi diagnostiqué, `/var/lib/kvmd/pst/portable-os/settings.json`. Le writer utilise
`kvmd.apps.init().make_pst_client(...).writable()` de KVMD 4.213, avec sa configuration
native et son socket effectif. Aucun remount racine ou MSD. Références primaires :
[client PST](https://github.com/pikvm/kvmd/blob/v4.213/kvmd/clients/pst.py),
[résolution fstab](https://github.com/pikvm/kvmd/blob/v4.213/kvmd/fstab.py).

Écriture temporaire exclusive, fsync, remplacement atomique et fsync du répertoire.
Pas d’écriture si les valeurs ne changent pas ; seuls les boutons explicites
enregistrent. Historique limité à 20 entrées et à 16 Kio avec le document complet.
Métadonnées d’activité et d’inactivité uniquement en tmpfs. Les lecteurs OLED/bouton
n’importent pas asyncio/KVMD pour lire les préférences ; cache de 2 s et valeurs
de secours sûres. Aucun paquet supplémentaire sur le Pi.

Les réglages RC10.2 étaient locaux au navigateur : le thème clair est proposé dans
le brouillon pour validation. L’absence de fichier n’écrit rien et conserve
l’inactivité désactivée. Une ancienne enveloppe minimale de thème version 0 est
convertie en mémoire ; les versions inconnues sont refusées. Un JSON corrompu
affiche un avertissement et requiert une restauration explicite des défauts.

## Validation locale et recette réelle

Les tests couvrent types/bornes, schémas inconnus, concurrence, interruption avant
replace, corruption, migration, no-op, révisions, historique maximal, rotation OLED,
pages/durées/conditions, contraste, authenticité des API/CSRF, import/export,
inhibiteurs, simulation, redémarrage du suivi et maintien des protections de gestes.
Les fixtures n’accèdent ni aux ISO réelles ni aux sorties GPIO/I2C.

Résultat Windows avant déploiement : 261 tests Python, dont 255 réussis et 6
ignorés (primitives Linux/permissions Windows), 23 tests Node et six suites
navigateur Edge/Playwright réussis. Les tests navigateur natifs chargent le DOM et
les contrôleurs KVMD 4.213 avec API et transport simulés. La CI Python 3.14/Linux
est configurée ; elle n’est pas assimilée à une validation matérielle distante.

```bash
python -B -m unittest discover -s tests -v
node --test tests/portable-ui.test.mjs
python -B tests/portable_preview.py --port 8765
# Autre terminal, Playwright 1.62.1 installé sur le poste de développement :
node tests/portable-settings.cjs
node tests/portable-native-4213.cjs
node tests/portable-browser.cjs
node tests/portable-kvm-layout.cjs
node tests/portable-dialogs.cjs
node tests/portable-transfer.cjs
```

Sur le Pi, vérifier à minima : sauvegarde vérifiée, contrôles RC10.1/RC10.2,
PST disponible et retour RO après sauvegarde, deux changements de contraste ou
thème puis retour aux défauts, persistance et export/import, miroir sans SSD1306,
service OLED/bouton actif, gestes non sensibles et KVM natif fonctionnels, API sans
authentification refusée, nginx valide, GPIO17 HIGH, aucune modification de lecteurs
ou de noms/tailles d’ISO. Ne pas tester de coupure réelle.

## Mise à jour et retour à RC10.2

Conserver le stage RC10.2, l’archive RC11 et les sauvegardes. Depuis Windows :

```powershell
python -B scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.11.tar.gz private/pikvm-portable-os-0.2.0-rc.11.tar.gz.sha256 root@192.168.168.99:/tmp/
ssh @sshOptions root@192.168.168.99
```

Mot de passe aux invites uniquement. Sur le Pi :

```bash
set -euo pipefail
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.11.tar.gz.sha256
stage=$(mktemp -d /tmp/portable-rc11.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.11.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
bash install-portable-os.sh check
systemctl is-active --quiet kvmd-pst.service
pinctrl get 17
```

Toute erreur interdit de poursuivre. Après réussite, GPIO17 HIGH, volumes libres
et absence de transfert confirmés :

```bash
rw
if bash "$stage/install-portable-os.sh" install; then
    ro
else
    status=$?
    ro
    exit "$status"
fi
```

La transaction crée sa sauvegarde, la vérifie avant arrêt de tout service, vérifie
nginx et revient automatiquement aux fichiers précédents si l’installation échoue.
Elle ne redémarre/désactive jamais le maintien d’alimentation. Ne pas lancer
`install.sh`, un reset USB, une mise à jour globale ou un reboot matériel.

Noter le chemin `Sauvegarde : /root/pikvm-portable-os-backups/DATE-ID` de **cette**
mise à jour. Recharger le navigateur avec Ctrl+Maj+R. Pour restaurer RC10.2,
après libération des volumes/transferts :

```bash
rw
if python3 -B "$stage/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID; then
    ro
else
    status=$?
    ro
    exit "$status"
fi
```

La restauration vérifie la sauvegarde avant arrêt des services. Les préférences
PST restent présentes, mais sont ignorées par RC10.2 ; aucun effacement de données
n’est nécessaire. `/legacy/` et `/kvm/` restent disponibles comme secours.
