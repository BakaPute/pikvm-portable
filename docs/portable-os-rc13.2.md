# RC13.2 — permissions, portail et mémoire

Candidate `0.2.0-rc.13.2`, branche `codex/portable-os`. **Aucun déploiement**.
Le Pi réel reste en RC13.1. `baka` reste un compte Portable, jamais ajouté
automatiquement à htpasswd natif, Linux, SSH, VNC ou IPMI.

## Permissions

Fenêtre centrée jusqu'à 1100 px, hauteur 88 % de l'écran (90 % mobile),
en-tête/actions fixes et défilement interne. Huit catégories repliables,
descriptions complètes, recherche accent-insensible, Hériter/Autoriser/Refuser,
résultat effectif et compteurs recalculés dans le brouillon. Les droits et leurs
identifiants serveur restent ceux de RC13.1, sans nouveau droit root implicite.

Actions globales confirmées sur toutes les catégories, y compris filtrées.
Les autorisations restent limitées aux droits détenus. Dernier administrateur,
comptes supérieurs, réauthentification, CSRF et révision restent contrôlés côté
serveur. Quitter/Échap/navigation avec brouillon déclenche un avertissement.
Un refus API ou une annulation de réauthentification conserve les choix.

Captures [avant PC](images/rc132/permissions-before-desktop.png),
[après PC](images/rc132/permissions-after-desktop.png),
[avant mobile](images/rc132/permissions-before-mobile.png),
[après mobile](images/rc132/permissions-after-mobile.png).

## Où se connecter

URL prévue, **à activer séparément** :
`https://share.pikvm.home.arpa:8443/login/`.
Nom DNS à configurer explicitement et certificat de confiance avec ce SAN.
Les modèles TLS RC13.1 proposent déjà ce nom. Le navigateur ne doit pas
utiliser d'exception de certificat. L'entrée native administrateur reste sur
son origine actuelle, notamment `https://192.168.168.99/`.

La catégorie Utilisateurs explique cette séparation et affiche l'URL prévue
ou l'origine relue depuis une configuration d'activation root privée approuvée.
Une configuration présente ne prouve pas que le service est actif/validé.
Le portail en français prend en charge les secrets courts/vides explicitement
autorisés, puis affiche le compte connecté dans Portable OS. L'expiration et
la déconnexion renvoient à `/login/` sur la même origine, donc au bon portail.
Une sonde publique `/api/portable-entry` identifie la passerelle avant envoi
du formulaire : ouvrir ce HTML sur l'origine native ne doit pas envoyer par
erreur un mot de passe Portable à la connexion KVMD.

[Portail PC](images/rc132/portal-desktop.png),
[portail mobile](images/rc132/portal-mobile.png).

Le cookie Portable reste HttpOnly/Secure/SameSite=Strict et limité à son hôte.
Les ports seuls n'isolent pas les cookies : utiliser le nom dédié et un profil
navigateur distinct pour les essais. Ne pas fournir à un compte restreint un
cookie ou mot de passe administrateur natif : posséder déjà cet autre accès
reste une autorité distincte, que les ACL Portable ne peuvent retirer.

## Gateway : ce qui est corrigé et ce qui reste bloqué

Le validateur d'intégrité refusait sa propre unité gateway, présente dans le
manifeste mais absente de son périmètre : le correctif accepte ses deux noms
d'unités exacts, sans ouvrir `/etc/systemd/system` en entier. Un test couvre
le nom légitime et le rejet d'un suffixe inattendu.

Le modèle nginx HTTP dédié ajoute `server_name share.pikvm.home.arpa` et refuse
les autres hôtes (421). Les identifiants/en-têtes clients ne sont pas propagés
aux sockets privilégiés. Requêtes HTTP, WebSocket texte/binaire, cookies,
permissions ISO/SHARE/OLED/ATX gardent les contrôles RC13.1. Les voies inconnues,
terminal, legacy, Redfish, media/Janus/VNC restent refusées sur cette origine.
Vidéo seule : MJPEG sans WS HID ; clavier/macros/souris ensemble pour la console
native. Aucun attachement USB automatique ni second moteur de stockage/OLED.

Les tests utilisent la vraie passerelle avec cinq rôles, un compte vide
confirmé et un backend matériel synthétique. La connexion native refuse les
identités Portable dans le job utilisant les sources officielles KVMD 4.213.
**Ces tests ne valident pas une activation complète sur le Pi réel.**
Le service reste inactif ; les modèles reviewed/proofs restent false.

### Procédure d'activation à préparer, jamais exécutée automatiquement

1. Approbation distincte de l'installation applicative, puis précontrôle et
   nouvelle sauvegarde RC13.1 vérifiée. Conserver session KVMD native et SSH root.
2. Approbations séparées DNS, TLS et nginx : nom stable, certificat signé par
   CA locale dont seule la partie publique authentifiée est approuvée sur
   Windows ; sauvegardes privées avant changement. `nginx -t` et `-T`, chaîne,
   SAN, correspondance clé/certificat et accès de récupération vérifiés.
3. Après autorisation de tests d'authentification seulement : lancer une
   instance de recette root, loopback uniquement, avec code/intégrité vérifiés,
   devant le vhost TLS dédié. Une instanciation de la classe Gateway sert aux
   tests avant attestation ; ne pas préremplir un rapport de succès pour faire
   démarrer le service de production. Aucun compte Linux nécessaire.
4. Tester sur le matériel les cinq rôles : connexion, expiration/révocation,
   HTTP/WS/HID, spectateur sans effet HID, ISO/SHARE avec données synthétiques
   explicitement autorisées, OLED, ATX sous garde et récupération native.
   Ne pas utiliser les sept ISO réelles pour les tests de mutation.
5. Après résultats réels uniquement, écrire les deux attestations root 0600
   décrites dans RC13 : empreintes de `integrity.json` installé et du rapport,
   origine exacte, preuves effectivement réussies. L'API ne crée pas ces fichiers.
6. Autorisation d'activation explicite, puis enable/start de la gateway seule.
   Aucun arrêt/redémarrage de power-hold ou reboot. Refaire les essais natifs
   et une révocation. Documenter les résultats, sinon laisser l'entrée inactive.

Le guide TLS RC13.1 reste applicable. Aucun certificat, hôte Windows, vhost
effectif, fichier d'identités ou service n'a été modifié par cette préparation.

## RAM : résultats mesurés et limites

[Relevés filtrés complets](performance/rc132-pi-readonly.json).
L'utilisateur a confirmé **n'avoir réalisé aucune transition** : page Web
ouverte dès le début, sans source HDMI. Les 15 échantillons ne sont donc pas
une comparaison repos/Web/KVM ; ce sont trois lots dans un même état utilisateur.
Une stabilité vidéo HDMI et la réactivité physique du bouton ne sont pas
revendiquées. MemAvailable observé : 53220–54408 Kio (52,0–53,1 Mio), avec
observateur présent. Des valeurs PSI historiques/récentes faibles figurent dans
le rapport ; pas d'OOM dans le journal du démarrage consulté, aucun swap ajouté.

PSS médiane des services de production RC13.1 :

| Service | Mio PSS | Après RC13.2 en production |
|---|---:|---|
| API Portable | 30,6 | non mesuré |
| OLED | 12,5 | non mesuré |
| Bouton | 8,9 | non mesuré |
| SHARE | 9,6 | non mesuré |
| Wi-Fi | 9,4 | non mesuré |
| KVMD, groupe | 55,2 | non mesuré |
| Janus, groupe | 37,3 | non mesuré |
| Media | 22,7 | non mesuré |
| PST | 22,1 | non mesuré |
| nginx | 8,3 | non mesuré |

USS et RSS par service sont enregistrés. RSS peut compter les mêmes pages
partagées plusieurs fois ; ne pas le présenter comme un total physique.
MemoryCurrent cgroup indisponible reste null, jamais zéro inventé.

### Optimisation conservée : lecture de la configuration native isolée

La liste des comptes chargeait `kvmd.apps.init` dans l'API uniquement pour
obtenir le chemin htpasswd. Un lecteur éphémère renvoie désormais seulement
enabled/type/external/chemin, sans hash, mot de passe ni token. Cache borné à
une valeur et verrou single-flight, stdin fermé, délai 15 s et nettoyage du
groupe après expiration. Configuration inconnue ou erreur => refus, sans
fallback permissif. Aucun lecteur PST ou mécanisme de stockage natif remplacé.

Trois paires de processus éphémères sur **le vrai Pi**, sans remplacer le
service : PSS parent médiane 32084 → 12127 Kio, soit **19,49 Mio retenus en
moins dans ce scénario isolé**. USS 31392 → 11456 Kio. Première lecture murale
5,87 → 7,29 s ; CPU parent+enfants 4,29 → 5,62 s. Le coût initial augmente,
puis le résultat est mis en cache. Ce n'est ni un gain global de 19,49 Mio
appliqué au Pi, ni un après de l'API installée. Les écritures PST de préférences
ou d'identités peuvent encore importer KVMD dans le parent : gain conditionnel.

L'essai de partage supplémentaire de polices n'a montré qu'un gain de l'ordre
de quelques dizaines de Kio, dans le bruit du PC : **non conservé**. Rendu,
polices, caches et gestes RC13.1 restent inchangés. Aucun gain de 10–40 Mio
global ni aucune absence de fuite à plusieurs heures ne sont inventés.
Janus/Media/PST ne sont pas désactivés, le cache Linux n'est pas vidé, aucune
fusion de processus, modification GPU, swap ou service de nettoyage.

Le collecteur passif `pikvm-portable-perf` ajoute USS depuis le même smaps déjà
lu, sans lecture supplémentaire. Après installation autorisée, comparer avec
le même observateur, même source HDMI/codec/navigateur et trois scénarios
réellement exécutés ; exemple de suivi :
`python3 -B scripts/pikvm-portable-perf --duration 3600 --interval 30 --no-threads --label rc132-web`.
Conserver la sortie sur le PC ou un emplacement temporaire choisi. Les latences
du relevé présent sont des réponses HTTP 401, pas des appels authentifiés ;
elles ne prouvent pas la performance KVM. CPU bouton mesuré sans modification
de son lecteur ; un diagnostic GPIO séparé serait nécessaire pour son coût.

## Migration et rollback

Validation locale de la candidate : 380 tests Python (8 ignorés car réservés
à Linux/outils natifs), 23 tests JavaScript et 11 suites navigateur réussis.
Les suites couvrent aussi les régressions RC9 à RC13.1, l'enregistrement des
permissions après réauthentification annulée/refusée et le refus du formulaire
sur une entrée sans sonde Portable. Deux anciens tests OLED attendent désormais
la confirmation de fin d'enregistrement avant rechargement ; aucune logique
de rendu n'a été modifiée pour corriger cette course de test.

Construire avec `python3 -B scripts/pikvm-portable-package.py`. Vérifier SHA256
et chaque entrée MANIFEST après transfert autorisé ; recréer un stage, lancer
`check`, puis `backup-only --approve-security-candidate SHA256_DU_MANIFEST`
sous autorisation de copie. Racine temporairement RW pour la sauvegarde puis
RO même sur échec. Vérifier que la sauvegarde contient bien RC13.1, ses
préférences et l'état d'identités de `baka`, ainsi que le lien SSH fournisseur.
Une sauvegarde RC12.1 ou RC13 ne constitue pas ce point de retour RC13.1.

Installation applicative après approbation seulement : `install` avec le même
SHA du manifeste, encadré RW/RO. Elle n'active ni gateway, nginx dédié, TLS ni
compte Linux. L'installation ne vaut pas autorisation de les activer.

Après transfert autorisé de l'archive et vérification de son SHA256 publié,
dans le stage extrait vérifié (commandes à exécuter manuellement uniquement) :

```bash
sha256sum -c MANIFEST.sha256
python3 -B scripts/pikvm-portable-install check
sha256sum MANIFEST.sha256
```

La sauvegarde et l'installation exigent ensuite chacune l'autorisation :

```bash
# Remplacer MANIFEST_SHA_VERIFIE par les 64 caractères vérifiés ci-dessus.
rw
if python3 -B scripts/pikvm-portable-install backup-only --approve-security-candidate MANIFEST_SHA_VERIFIE; then
    ro
else
    rc=$?; ro; exit "$rc"
fi
# Conserver et vérifier le chemin de sauvegarde affiché avant de continuer.
rw
if python3 -B scripts/pikvm-portable-install install --approve-security-candidate MANIFEST_SHA_VERIFIE; then
    ro
else
    rc=$?; ro; exit "$rc"
fi
```

Retour sous autorisation, lecteurs/SHARE libres :
`python3 -B STAGE/scripts/pikvm-portable-install restore SAUVEGARDE_RC131_VERIFIEE`,
avec RW puis RO dans un bloc if/else conservant le code d'erreur. La sauvegarde
privée restaure fichiers et état d'identités initial ; l'état abandonné est
conservé pour revue, sans fusion automatique des comptes ajoutés entre-temps.
Si une activation a été autorisée plus tard, fermer la gateway et retirer le
seul include ajouté après validation nginx, en conservant l'origine native.
Les comptes Linux et leurs homes ne sont jamais supprimés par ce rollback.

Derniers relevés : GPIO17 OUTPUT HIGH, GPIO18 INPUT LOW, power-hold actif.
Aucune installation/restauration réelle n'a été exécutée pour cette candidate.
