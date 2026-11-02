# RC6 : précontrôle instrumenté, sans changement fonctionnel du PiKVM

Correctif local de RC6 `de431b7`, sur `codex/portable-os`. Aucun accès SSH ni
déploiement effectué. Aucun changement GPIO, Drive, SHARE ou service d'alimentation.

## Diagnostic et correction

Les mesures réelles (8,54 s pour un essai complet réussi, ~3 s d'imports, ~5 s
pour `kvmd-otgmsd -i 1`) ne permettent pas d'identifier la commande bloquée lors
des échecs. Elles ne prouvent ni un défaut de subprocess, ni une panne permanente
de Drive 1. La pression mémoire peut contribuer aux variations mais n'est pas une
cause établie. Le défaut certain dans RC6 est l'absence de supervision individuelle :

- Le shell lance pacman, imports, Drive 1, nginx et systemctl sans délai propre.
- La sortie de Drive 1 est supprimée, et les vérifications ne sont pas horodatées.
- Le délai Python de 60 s porte sur tout le shell ; il n'identifie pas la commande
  en cours et ne garantit pas l'arrêt des descendants.
- Les vérifications supplémentaires power-hold/Pillow ne sont pas bornées.

`scripts/pikvm_preflight.py` est désormais l'unique implémentation des contrôles
de compatibilité. Le shell l'exécute directement, et l'installateur l'utilise dans
le même processus : il n'existe plus de délai global opaque autour d'un shell.
Le module ne charge que la bibliothèque standard, sans importer `logging` ; son
intégrité est toujours validée **avant** les imports applicatifs et la lecture USB.

| Commande / étape | Délai individuel |
| --- | ---: |
| Chaque `pacman -Q` | 10 s |
| Pipeline gzip/awk du mtree | 10 s |
| SHA256 de logging | 10 s |
| Imports Python/KVMD | 15 s |
| `kvmd-otgmsd -i 1` uniquement | 20 s |
| `nginx -t` | 15 s |
| Chaque `systemctl is-active` (KVMD, nginx, power-hold) | 10 s |
| Imports Pillow | 15 s |

Aucune relance automatique, aucun résultat non nul ignoré, aucun seuil de sécurité
modifié. Une vérification expirée interrompt toute la suite. La commande Drive est
strictement informative : aucun attachement, montage, détachement ou formatage.

Chaque sous-commande possède une nouvelle session/groupe POSIX. À expiration,
le superviseur journalise TIMEOUT, envoie TERM au groupe, attend 1 s, puis KILL au
groupe **même si son chef est déjà sorti**, et récupère son processus direct.
Il ne signale jamais les démons systemd/KVMD ni les services d'alimentation : seuls
ses propres clients et leurs descendants sont ciblés. Un échec de nettoyage reste
fatal. Les sorties vont directement dans des fichiers, sans pipe bloquant ni
accumulation illimitée en RAM ; les résultats utilisés par les contrôles sont
limités à 64 Kio à la lecture. Un processus bloqué dans le noyau peut rester
non récupérable malgré KILL ; cela est signalé et l'installation ne continue pas.

## Lire le journal après un échec

Chaque invocation affiche immédiatement un chemin unique, par exemple :

```text
/tmp/pikvm-portable-preflight-XXXXXXXX/steps.log
```

Ce dossier privé reste présent après réussite, erreur ou timeout. Les entrées UTC
BEGIN/OK/FAIL/TIMEOUT/CLEANUP donnent la commande exacte, le délai, la durée monotone,
le PID et les fichiers `.stdout`/`.stderr`. Les étapes navigation, empreintes OLED
et politique/authentification SHARE sont également horodatées. Aucune opération
de réparation ni d'authentification SSH n'est exécutée par ce module.

Pour le chemin **effectivement affiché** :

```bash
cat /tmp/pikvm-portable-preflight-XXXXXXXX/steps.log
cat /tmp/pikvm-portable-preflight-XXXXXXXX/06-drive1-read.stdout
cat /tmp/pikvm-portable-preflight-XXXXXXXX/06-drive1-read.stderr
```

Le numéro peut varier : utiliser les noms présents dans BEGIN. Les fichiers sont
dans le stockage temporaire du Pi ; les récupérer avant redémarrage. Le précontrôle
n'exige pas `rw` et ne modifie aucun fichier système, hormis ces diagnostics temporaires.

## Tests locaux

Les nouveaux tests couvrent de vrais processus simulés bloqués, avec sorties
partielles conservées, pour les imports, Drive 1 et systemctl ; la réussite suivante
ne masque pas le premier échec. Ils couvrent aussi un petit-enfant ignorant TERM,
l'arrêt du pipeline dès la première erreur, le maintien de tous les contrôles,
les budgets individuels, la liaison shell/installateur et l'installation du module
partagé nécessaire à une réinstallation autonome.

Suite locale : **125 tests Python réussis, 2 ignorés sous Windows** (127 au total),
**21 tests JavaScript réussis**. Le nettoyage d'un vrai arbre est testé sous Windows ;
la séquence POSIX TERM/KILL est testée par simulation ici et le même scénario réel
est prévu dans la CI Linux. Python local : 3.12.14 ; aucun résultat Python 3.14/Linux
ou matériel n'est revendiqué. Le contrôle nginx réel de la suite utilise nginx 1.26.3.
Les pages et contrôleurs web RC6 sont inchangés par ce correctif.

## Mise à jour : une nouvelle zone de préparation, original conservé

L'archive complète RC6 corrigée évite de mélanger un nouvel installateur et un
ancien module. **Ne pas copier uniquement `pikvm-portable-install`** : il dépend
désormais de `scripts/pikvm_preflight.py`. L'empaqueteur inclut ce module et
l'installateur le sauvegarde/installe comme les autres fichiers.

Les commandes ci-dessous sont une procédure proposée, **à exécuter sur le Pi
uniquement après autorisation**. Elles conservent `/root/pikvm-portable-os-stage`
et ses éventuels changements pour revenir immédiatement au préparatif d'origine.

Sur Windows, construire puis transférer en imposant le mot de passe SSH :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python -B scripts/pikvm-portable-package.py --output private/pikvm-portable-os-0.2.0-rc.6-preflight-fix.tar.gz
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
$PiKvmHost = Read-Host 'Adresse IP actuelle du PiKVM'
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.6-preflight-fix.tar.gz private/pikvm-portable-os-0.2.0-rc.6-preflight-fix.tar.gz.sha256 "root@${PiKvmHost}:/tmp/"
ssh @sshOptions "root@${PiKvmHost}"
```

Saisir le mot de passe aux invites ; ne jamais le mettre dans une commande ou un journal.
Sur le Pi, vérifier et préparer sans remplacer l'ancien stage :

```bash
set -e
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.6-preflight-fix.tar.gz.sha256
stage=$(mktemp -d /tmp/pikvm-portable-os-stage-preflight.XXXXXX)
tar -xzf /tmp/pikvm-portable-os-0.2.0-rc.6-preflight-fix.tar.gz -C "$stage" --strip-components=1
cd "$stage"
sha256sum -c MANIFEST.sha256
printf 'Stage corrigé : %s\n' "$stage"
python3 -B scripts/pikvm-portable-install check
```

Le nouveau stage est temporaire : aucun besoin de rendre la racine inscriptible
avant les vérifications. Le conserver jusqu'à la fin de la mise à jour et de sa
validation ; ne pas redémarrer le Pi pendant cette procédure.

Si l'ancien stage contenait des modifications locales, les comparer avant
installation (ne pas les écraser) :

```bash
diff -ru --exclude=.git --exclude=__pycache__ --exclude=MANIFEST.sha256 /root/pikvm-portable-os-stage "$stage" || [ "$?" -eq 1 ]
```

`diff` retourne 1 lorsqu'il trouve des différences ; le bloc l'accepte explicitement,
mais échoue en cas d'erreur de lecture. Les différences fonctionnelles attendues sont le nouvel installateur,
le wrapper de précontrôle et le module `pikvm_preflight.py` ; l'empaqueteur et la
documentation évoluent aussi. Tout autre correctif local reste à examiner.

Si `check` échoue : **ne pas lancer l'installation**, conserver le dossier de
journal annoncé et analyser sa première étape FAIL/TIMEOUT. Ne pas supprimer le
contrôle, augmenter aveuglément le délai, ni lancer de mise à jour globale.

Après réussite, accord explicite de déploiement et examen des éventuels écarts :

```bash
cd "$stage"
rw
if python3 -B scripts/pikvm-portable-install install; then
    ro
else
    status=$?
    ro
    printf 'Installation échouée (code %s) : examiner le journal et le rollback.\n' "$status" >&2
    exit "$status"
fi
```

Conserver le chemin **Sauvegarde : /root/pikvm-portable-os-backups/…** imprimé.
Le correctif n'ajoute aucun arrêt/reconfiguration de matériel. L'installation RC6
conserve sa transaction existante, ses redémarrages applicatifs nécessaires,
ses validations nginx et son rollback automatique ; aucun redémarrage matériel.

## Retour arrière

**Après `check` seulement** : aucun fichier installé n'a changé. Revenir dans
`/root/pikvm-portable-os-stage` suffit ; conserver les journaux pour diagnostic.

**Après installation** : restaurer la sauvegarde créée par cette invocation,
qui remet exactement l'état antérieur (RC5 ou autre version effectivement installée),
et non le contenu de l'ancien dossier stage. Dans le même shell, remplacer DATE-ID :

```bash
rw
if python3 -B "$stage/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID; then
    ro
else
    status=$?
    ro
    printf 'Restauration échouée (code %s) : conserver les sauvegardes.\n' "$status" >&2
    exit "$status"
fi
```

Si le shell a été fermé, redéfinir `stage` avec le chemin imprimé, ou utiliser
`/usr/local/bin/pikvm-portable-install restore …`. `restore` ne lance pas le
précontrôle de compatibilité. Le manifeste et les empreintes de sauvegarde restent
vérifiés avant toute restauration. Recharger le navigateur après retour arrière.
