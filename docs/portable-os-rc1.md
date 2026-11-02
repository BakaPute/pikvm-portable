# Portable OS 0.2.0-rc.1 — stabilisation et migration progressive

Branche : `codex/portable-os`. Cette candidate est locale, non déployée.
Aucune commande SSH, GPIO, Drive 0 ou écriture dans l'image SHARE exécutée par Codex.

## Priorité 1 : réparation ciblée de Python

Le relevé communiqué indique `python 3.14.7-1`, un checksum SHA-256 incorrect pour
`/usr/lib/python3.14/logging/__init__.py`, et aucun autre fichier modifié parmi
3 198 contrôles. L'absence d'erreur microSD explicite ne détermine pas l'origine
du changement. Conserver le fichier défectueux pour comparaison.

Ne pas exécuter `pikvm-update`, `pacman -Syu`, `pacman -Sy`, une réinstallation
globale de Python, ni copier un fichier issu d'un autre Python/architecture.
Les correctifs locaux KVMD/Python 3.14 restent en place.

### Acquisition du paquet : condition préalable

Obtenir **le paquet Arch Linux ARM `python-3.14.7-1` de l'architecture réellement
installée**, et sa signature détachée `.sig`. Le relevé historique du projet
est armv7h/armv7l, mais le script vérifie `%ARCH%` dans la base pacman du Pi ;
il ne déduit pas l'architecture du modèle du Raspberry Pi.

Les dépôts sont roulants : la page Python et certains miroirs présentent déjà
des versions plus récentes. Les tentatives depuis cet environnement n'ont pas
permis de récupérer le paquet exact. **Aucun paquet de remplacement n'est livré
ou déclaré vérifié ici.** Chercher dans un cache sauvegardé fiable, auprès de
la distribution/du mainteneur ou sur un miroir conservant encore le paquet signé.
Un fichier trouvé via un index ancien n'est pas une preuve d'authenticité.

Le nom attendu pour armv7h est par exemple :

```text
python-3.14.7-1-armv7h.pkg.tar.xz
python-3.14.7-1-armv7h.pkg.tar.xz.sig
```

Le script ne dépend pas de Python pour son inspection : il utilise `pacman-key`,
`bsdtar`, `gzip`, `awk` et `sha256sum`. Il vérifie la signature avec le trousseau
de confiance **déjà présent**, puis `.PKGINFO` (nom/version/architecture), le
SHA-256 du membre dans `.MTREE`, sa correspondance exacte avec le `.mtree`
enregistré à l'installation, et le contenu effectivement extrait.
Ne pas désactiver les signatures, importer aveuglément une clé ou changer sa
confiance. Un échec de confiance nécessite une vérification séparée du trousseau.
La documentation Arch Linux ARM identifie la clé de construction
`68B3537F39A313B3E574D06777193F152BDBE6A6` ; vérifier l'identité du signataire.

### Inspection sans remplacement système

Depuis ton terminal personnel, connexion SSH root par mot de passe masqué :

```powershell
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password -o PasswordAuthentication=yes -o StrictHostKeyChecking=ask root@192.168.168.99
```

Après avoir obtenu/transféré le paquet et sa signature, adapter uniquement le
chemin local du paquet. Depuis le dépôt complet sur le Pi :

```bash
bash scripts/pikvm-python-logging-repair.sh inspect /root/python-3.14.7-1-armv7h.pkg.tar.xz
```

L'inspection extrait un seul membre dans un répertoire temporaire, sans remplacer
le fichier système, monter SHARE ou arrêter un service. Elle refuse un paquet
d'une autre architecture, une mauvaise signature ou un checksum de référence
différent. Elle vérifie également les bytecodes logging appartenant au paquet.

### Application, seulement après autorisation explicite

```bash
rw
bash scripts/pikvm-python-logging-repair.sh apply /root/python-3.14.7-1-armv7h.pkg.tar.xz --authorized
ro
```

La sauvegarde datée se trouve dans `/root/pikvm-python-repair-backups/DATE-PID`.
Elle contient l'ancien source avec ses attributs, son hash, la description du
paquet installé et l'empreinte de l'archive utilisée. Seul le source logging est
remplacé atomiquement, avec propriétaire/mode conservés et date du fichier du
paquet. Les `.pyc` suivis par pacman sont contrôlés et conservés ; seuls d'éventuels
bytecodes logging non suivis sont mis de côté, jamais supprimés.

Le script vérifie ensuite le hash sur disque, l'import isolé de logging/asyncio/ssl
et `pacman -Qkk python`. Il ne redémarre aucun service. Si l'une de ces étapes
échoue, conserver la sauvegarde et le résultat ; ne pas poursuivre la migration.
Le remplacement a pu avoir réussi même si un contrôle ultérieur échoue : relever
son hash avant toute nouvelle action. Ne pas restaurer automatiquement un source
connu corrompu. Pour une annulation explicitement décidée, la copie
`__init__.py.before` et le dossier `cache/` préservent l'état antérieur.

## Priorité 2 : No Media sous Windows

Avec `mass_storage.usb1/lun.0/file` vide, le lecteur USB existe mais **aucun média
ne lui est attaché** : cela correspond au relevé « PiKVM Flash Drive / capacité 0 /
No Media ». `configured` confirme le gadget USB, pas la présence d'une image
dans ce LUN. Rien dans ces données ne justifie un formatage exFAT.

Après réparation et contrôle Python, relevés en lecture seule :

```bash
kvmd-otgmsd -i 1
bash scripts/pikvm-portable-diagnose.sh
python3 scripts/pikvm-share-api --check
```

Vérifier l'image 4 Gio existante, l'absence de montage/loop concurrent, les liens
de `mass_storage.usb1` dans `configs/`, `cdrom=0`, `ro=0`, `removable=1` et l'UDC.
Ne pas activer un `--set-*` à ce stade.

Comparer également, en lecture seule, `pinctrl get 17` (HIGH attendu),
`pinctrl get 18` et les attributs `file`, `cdrom`, `ro` du Drive 0 avant/après
la migration. Aucune commande `pinctrl set` ni éjection du Drive 0 n'est requise.

Après autorisation d'essai, cliquer **Connecter en USB** dans SHARE : le code
démonte normalement le volume Web, libère ses loops et appelle exclusivement
`kvmd-otgmsd -i 1 --set-cdrom=0 --set-rw=1 --set-image=...`. La candidate vérifie
maintenant aussi les attributs réellement relus après l'attachement. Si ces
attributs sont inattendus, elle garde la réservation et bloque, sans éjection
forcée ni tentative de modification d'un média attaché.

Relire ensuite `kvmd-otgmsd -i 1` et les attributs. Côté **PC Windows commandé** :

```powershell
.\scripts\pikvm-share-windows-diagnose.ps1
```

Le script ne fait que `Get-Disk`, `Get-Partition` et `Get-Volume`. Si le LUN contient
l'image mais Windows affiche encore 0/No Media, relever les nouveaux résultats,
l'état USB et les événements du périphérique. Si la capacité devient 4 Gio mais
qu'aucune lettre n'existe, il s'agit d'un autre stade du diagnostic : aucune
initialisation, réparation ou attribution automatique de lettre n'est proposée.
Avant retour Web : éjection propre dans Windows, LUN vide, confirmation puis
contrôle hors ligne normal. Aucun accès exFAT concurrent.

## Correctifs de la candidate

- Précontrôle Bash avant migration : version exacte KVMD/Python, hash de logging,
  imports, commande Drive 1 en lecture seule, nginx et état de **chaque** service
  natif. Il ne répare et n'actualise aucun paquet.
- Disponibilité de l'API prouvée avant bascule nginx : réponse 401, identité du
  nouveau service, JSON d'erreur et unité active. Un HTTP 200 sans session est refusé.
- Helper de restauration et précontrôle embarqués avec la candidate ; le rollback
  ne dépend plus d'une ancienne version éventuellement installée du helper SHARE.
- Vérification des empreintes de sauvegarde avant arrêt de services ; verrou
  empêchant deux installations/restaurations simultanées.
- Événement de relâchement HID natif lors du masquage du KVM, sortie du verrouillage
  pointeur et commande explicite de focus clavier/souris ; aucune réécriture HID.
- Navigation des liens natifs connus vers le shell. Les anciennes entrées
  Image Manager/SHARE/Wi-Fi ouvrent leurs nouvelles sous-vues ; leurs APIs et
  ressources ne sont pas redirigées. `?legacy=1` ouvre toujours les anciennes pages.
- Erreurs 403 (permission/CSRF) distinguées d'un token expiré par consultation
  de `/api/auth/check` (KVMD peut aussi répondre 403 pour ce dernier) ; timeout court du
  statut SHARE pour ne pas bloquer les indicateurs des autres services.
- Erreurs d'import préservées même si le nettoyage ou l'actualisation échoue,
  timeout explicite de l'upload natif, reprise du polling au retour du cache navigateur.
- Préférences robustes si localStorage est interdit ; registre de modules séparé
  de la structure du shell, dans `modules/index.js`.
- Arrêt automatique toujours manuel, sans démarrage/activation implicite.

## Audit des modules et limites de preuve

| Module | Vérifié localement / dans les sources 4.213 | À vérifier réellement après réparation et autorisation |
| --- | --- | --- |
| KVM | moteur complet conservé, hooks clavier/souris, blur releaseAll, commandes natives, focus, plein écran et navigation testés sur fixture instrumentée | vidéo, transport HID réel, touches maintenues, relative/absolute mouse, raccourcis, macros, qualité et plein écran sur le PC cible |
| Terminal | cadre persistant, permissions et focus conservés, navigation intégrée | ouverture ttyd, saisie, redimensionnement et session réelle |
| Drive 0 / images | routes natives vérifiées, upload/fichiers/dossiers, masquage images techniques ; aucune commande automatique de connexion | sélection/boot ISO, import/annulation/dossiers et maintien HID pendant l'usage |
| SHARE | exclusivité et récupération testées, index 1 explicite, flags relus, diagnostic No Media | attachement après réparation, capacité Windows et aller-retour avec éjection propre |
| Réseau | session/CSRF, confirmation hotspot, script existant et redaction des secrets testés | lecture Wi-Fi, reconnexion, bascule hotspot et retour sans perte d'accès durable |
| Batterie | adaptation de l'API existante, valeurs absentes signalées | MAX17048 réel, charge/décharge ; OLED déconnecté non sollicité par cette couche |
| Alimentation | aucun accès GPIO dans l'intégration, politique manuelle et contrôles avant arrêt | lecture GPIO17 HIGH et GPIO18 inchangé dans le relevé utilisateur ; aucun essai de coupure nécessaire pour cette migration |
| Auth | 401/403, session native, CSRF, proxy et routes authentifiées | expiration/reconnexion avec les cookies et en-têtes exacts du Pi |
| Paramètres | thème, stockage refusé, absence de migration matérielle | persistance navigateur réel ; pas de réglage système arbitraire ajouté |
| Services / logs | allowlist, bornes, secrets masqués, diagnostics sans shell utilisateur | sorties et états effectivement observés sur l'appareil |

Cette matrice est un audit logiciel et des tests locaux ; elle ne certifie pas
du matériel distant qui n'a pas été interrogé. Les anciens correctifs Python
du Pi ne peuvent pas être comparés octet par octet sans relevé de leurs fichiers.
L'installateur ne les remplace pas aveuglément : son patch SHARE reste étroit
et les fichiers remplacés sont sauvegardés intégralement.

## Déploiement progressif exact — après autorisation

Un bundle candidat est généré localement dans
`private/pikvm-portable-os-0.2.0-rc.1.tar.gz`, avec empreinte externe `.sha256` et
`MANIFEST.sha256` interne. Il n'inclut ni données du Pi, ni image, ni mot de passe,
ni dossier privé ; le paquet système Python n'en fait pas partie. Construction
reproductible : `python scripts/pikvm-portable-package.py`.

Après autorisation de transfert, depuis le terminal PowerShell du PC :

```powershell
scp -o PubkeyAuthentication=no -o PreferredAuthentications=password -o PasswordAuthentication=yes -o StrictHostKeyChecking=ask .\private\pikvm-portable-os-0.2.0-rc.1.tar.gz .\private\pikvm-portable-os-0.2.0-rc.1.tar.gz.sha256 root@192.168.168.99:/tmp/
```

Puis, dans la session SSH personnelle, après réparation de Python :

```bash
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.1.tar.gz.sha256
tar -xzf pikvm-portable-os-0.2.0-rc.1.tar.gz
cd /tmp/pikvm-portable-os-0.2.0-rc.1
sha256sum -c MANIFEST.sha256
python3 -B scripts/pikvm-portable-install check
rw
bash install-portable-os.sh
ro
```

L'extraction préparatoire reste dans `/tmp` et ne remplace aucun fichier système.
Le bundle ne contient pas l'ancien installateur matériel `install.sh`. Son chemin
temporaire peut être remplacé par un clone complet de la même candidate si préféré.

1. Obtenir/vérifier le paquet Python exact, appliquer la réparation autorisée et
   conserver tous les résultats. Sans cela, la migration reste bloquée.
2. Maintenir la session SSH personnelle ouverte et l'accès `/kvm/` disponible.
   Arrêter les transferts administratifs ; éjecter et libérer SHARE si le patch
   de politique de l'ancienne API est nécessaire. Ne pas modifier Drive 0.
3. Depuis le dépôt complet de cette branche sur le Pi :

```bash
cd /root/pikvm-portable
python3 -B scripts/pikvm-portable-install check
rw
bash install-portable-os.sh
ro
```

Le précontrôle est sans écriture système. L'installation sauvegarde les fichiers
remplacés et l'état du service dans `/root/pikvm-portable-os-backups/DATE-ID`, écrit
les fichiers atomiquement, démarre seulement les services applicatifs concernés,
vérifie l'API puis les includes effectifs via `nginx -T` avant rechargement nginx.
Elle ne redémarre ni KVMD ni le gadget, ne reboote pas et ne touche aucun GPIO,
partition ou image. Le patch éventuel SHARE conserve le reste du source local.

4. Ouvrir `/extras/portable-os/`. Tester d'abord les vues en lecture seule puis
   KVM/terminal. Comparer les attributs Drive 0 avant/après, sans les changer.
5. Après accord d'essai, vérifier SHARE puis les autres actions réseau/fichiers
   une par une. Ne pas déclencher d'arrêt électrique pour valider l'interface.

Accès immédiats de secours, sans restauration :

```text
/kvm/
/extras/pikvm-share/?legacy=1
/extras/image-manager/?legacy=1
/extras/wifi-wizard/?legacy=1
```

Retour arrière applicatif, uniquement avec le chemin de sauvegarde effectivement
affiché lors de l'installation :

```bash
rw
python3 -B /usr/local/bin/pikvm-portable-install restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

Les empreintes sont vérifiées avant tout arrêt ; les fichiers, permissions et
l'état antérieur de l'application sont restaurés, puis nginx est retesté/rechargé.
Si une ancienne API SHARE doit être restaurée, le volume doit être éjecté et
libéré ; sinon le rollback refuse de l'interrompre. L'image et les GPIO ne font
jamais partie de la restauration. Aucun reboot matériel requis.

## Contrôles locaux

Suite Python/nginx, tests Node et navigateur local, compilation Python et
syntaxes Bash/PowerShell. Les tests du navigateur utilisent une fixture KVM
instrumentée, pas des HID réels. Le script de réparation est préparé et contrôlé
statiquement : ni signature de paquet sur le Pi ni remplacement système n'ont
été exécutés ici. Les tests ARM/Python 3.14 du Pi restent une étape distincte.

Bilan local de la candidate : 73 tests Python (72 réussis, un test de lien
symbolique ignoré sous Windows), 16 tests Node réussis et parcours navigateur
desktop/mobile réussi. Le parcours étendu teste aussi clavier/souris simulés,
raccourcis, macros, qualité, plein écran, relâchement lors de navigation et
terminal. Quatre contrôles utilisent nginx 1.26.3 réel en mode validation ;
la compilation Python et les syntaxes des scripts passent. Le Python local
est 3.12.14 ; la CI 3.11/3.14 est préparée et non exécutée dans cette session.

Sources : [paquets ARM](https://archlinuxarm.org/packages/armv7h/python),
[miroirs](https://archlinuxarm.org/about/mirrors),
[signature des paquets](https://archlinuxarm.org/about/package-signing),
[HID KVMD 4.213](https://github.com/pikvm/kvmd/blob/v4.213/web/share/js/kvm/hid.js),
[clavier natif](https://github.com/pikvm/kvmd/blob/v4.213/web/share/js/kvm/keyboard.js).
