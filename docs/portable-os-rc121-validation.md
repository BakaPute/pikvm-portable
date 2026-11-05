# RC12.1 — Validation sur Pi Zero 2 W, 5 novembre 2026

Code : `c434f2910cd9d14449d838c9f4bc39734ccaf0b8`, branche `codex/portable-os`.
[Validation GitHub réussie](https://github.com/BakaPute/pikvm-portable/actions/runs/42002007219).
Installation réelle terminée : `RC121_DEPLOYMENT=OK`, `RC121_EXIT=0`, SSH 0.

Archive `pikvm-portable-os-0.2.0-rc.12.1.tar.gz`, SHA256 :

```text
cf32ea86bd335c323c805b610bdb5d647db0566fb9c4a2688c56258c838fe317
```

Les 196 fichiers du manifeste ont été contrôlés avant installation. Les
précontrôles Python système, KVMD 4.213, nginx, authentification, stockage,
navigation et migration OLED ont réussi sur Python 3.14.7.

## Tests et état constaté

- 319 tests Python locaux réussis, six tests Linux ignorés sous Windows.
- Matrice GitHub Python 3.11/3.14 réussie, avec nginx réel.
- 23 tests JavaScript et huit suites navigateur réussis, moteur natif KVMD
  4.213 et API synthétiques ; aucune ISO réelle manipulée.
- Polices DejaVu, accents, textes longs, marges, non-chevauchement et bits du
  framebuffer vérifiés ; 79 captures natives avant/après dans les deux profils.
- Sauvegarde RC12 et préférences brutes vérifiées avant arrêt des services.
  Préférences réelles inchangées pendant l’installation ; lecture migrée
  vers le schéma 3. Intégrité applicative correcte après installation.
- Double clic virtuel : menu observé 63,95 ms après le second relâchement ;
  RPC maximal 4,24 ms. Retour long réussi, aucun permis sensible ni action ISO.
- GPIO17 OUTPUT HIGH ; GPIO18 INPUT `--`, relâché LOW. Module GPIO inchangé,
  aucun redémarrage de power-hold, aucun reboot.
- KVMD, nginx, API Portable OS, OLED, bouton et PST actifs, zéro redémarrage
  automatique indiqué. Écran physique absent ; fonctionnement virtuel normal.
- Sept ISO et deux conteneurs : taille, mtime_ns et inode inchangés. Aucun
  nouveau hachage des 28 Gio d’ISO pendant ce déploiement ; les sept SHA256
  précédemment comparés ne constituent pas un nouveau contrôle du contenu.

Validation utilisateur après rechargement : « Tout fonctionne » pour les deux
profils, les pages secondaires, la sauvegarde/relecture des préférences, les
gestes du miroir (simple, double, retour), la vidéo, le clavier, la souris KVM
et l’ouverture du sélecteur ISO sans connexion de lecteur. Cette vérification
du miroir ne remplace pas un essai sur SSD1306 physique.

## Mesures sur le Pi

Deux fenêtres de 30 secondes, CPU d’un cœur incluant les enfants via cgroups.
Observations sans charge KVM identique imposée entre les fenêtres :

| Service | CPU RC12 | CPU RC12.1 | PSS avant → après | Descripteurs |
|---|---:|---:|---:|---:|
| OLED | 8,50 % | 8,47 % | 16 667 → 16 530 Kio | 3 → 3 |
| Bouton | 16,79 % | 16,70 % | 9 635 → 9 569 Kio | 4 → 4 |
| API | 0,91 % | 0,91 % | 10 244 → 9 936 Kio | 4 → 4 |

Pas de hausse mesurée de CPU ou de mémoire. Rendu synthétique des douze scènes
communes : 1,615 ms en moyenne RC12, 1,298 ms en Lisible, 1,530 ms en Compact ;
30 itérations avec caches chauds, hors I2C et navigation.
[Données et limites](performance/rc121-pi.json).

Le bouton conserve le fallback `pinctrl` : le profil temporaire
`/run/pikvm-oled/gpio18-validation.json` est absent après démarrage. Aucune
activation forcée du lecteur rapide ni modification électrique. Une nouvelle
validation passive par deux appuis contrôlés reste nécessaire pour réactiver
ce lecteur, selon la procédure RC8 existante.

## Retour exact à RC12

Sauvegarde vérifiée : `/root/pikvm-portable-os-backups/20261105-092739-196f2e69`.
Stage conservé : `/tmp/portable-rc121.RrwEPt`.
Après libération des lecteurs, transferts et accès Web SHARE :

```bash
cd /tmp/portable-rc121.RrwEPt
bash install-portable-os.sh check
rw
if python3 -B scripts/pikvm-portable-install restore /root/pikvm-portable-os-backups/20261105-092739-196f2e69; then
    ro
else
    result=$?
    ro
    exit "$result"
fi
```

Si le stage temporaire a disparu, extraire l’archive RC12.1 vérifiée et utiliser
son installateur avec la même sauvegarde. Aucun rollback n’a été exécuté sur
ce Pi après la mise à jour réussie ; restauration exacte des préférences testée
sur données isolées. `/legacy/` et `/kvm/` restent accessibles.

Lisibilité du SSD1306 physique et délais des appuis physiques à vérifier lorsque
le matériel est disponible. L’origine de l’extinction ancienne reste inconnue ;
les contrôles d’alimentation actuels réussis ne permettent pas de l’expliquer.
