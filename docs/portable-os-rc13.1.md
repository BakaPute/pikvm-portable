# RC13.1 — candidate, sans déploiement

Version 0.2.0-rc.13.1, branche codex/portable-os. RC13 reste installée.
Les changements d'authentification et de certificat exigent des validations
distinctes. Aucun compte Linux, gateway, certificat ou autorité Windows activé.

## Mots de passe Web

La politique Portable est libre par défaut : `123`, `admin`, `test` et les
phrases longues sont acceptés. Une limite de 1024 octets UTF-8 protège le
serveur. Valeur absente ou non textuelle refusée. Le vide exige une confirmation
séparée dans le navigateur et `allow_empty_password: true` côté serveur.
La connexion et la réauthentification distinguent `""` d'un champ absent.
PBKDF2-SHA256 600000, anti-bruteforce, CSRF, rôles et révocation sont conservés.
L'administrateur peut activer une politique stricte pour les futurs changements ;
cela ne bloque pas les comptes existants. Cette personnalisation ne modifie
jamais KVMD natif, SSH ni le mode de connexion Codex par clé.
Ne pas exposer des comptes sans secret à Internet. L'avertissement faible
reste informatif. Installer RC13.1 modifierait la politique des futures écritures
des comptes Portable ; obtenir une approbation spécifique avant installation.

## OLED

DejaVuSans et sa licence sont fournis dans `assets/fonts`, installés dans
la bibliothèque Portable uniquement. Aucun paquet système n'est ajouté.
Le rendu physique et le miroir utilisent le même framebuffer monochrome
128×64. Les textes sont normalisés NFC et les masques restent bornés/cachés.
Le titre Batterie affiche le décompte fourni par la rotation réelle ; Charge/
Repos apparaît dans le contenu, sans chevaucher le compteur. Aucun nouveau
polling n'est ajouté. Ressources affiche RAM utilisée, disponible et totale.
La durée système reste visible en pied de cette page secondaire.
[Captures natives agrandies sans interpolation](images/rc131/comparison.png).
Reproduction : `python3 -B tests/generate-oled-rc131.py`.
[Mesure locale de rendu](performance/rc131-render-local.json), sur PC uniquement,
sans extrapolation de charge CPU sur le Pi.

## Diagnostic RAM réel — 6 novembre 2026

398472 Kio totaux (389,1 Mio), 86440 Kio disponibles (84,4 Mio),
10108 Kio libres, Cached 89872, Buffers 4744, SReclaimable 8764,
Shmem 14800, Slab 33400. Utilisation pertinente :
`100 × (MemTotal − MemAvailable) / MemTotal = 78,3 %` environ.
Le pourcentage élevé ne signifie pas que le cache est perdu : MemAvailable
estime la mémoire utilisable sans swap, y compris une partie récupérable.
MemFree seul surestime la pénurie. Ne pas additionner Cached, Shmem et Slab
comme des catégories indépendantes, certaines se recouvrent.
[Documentation noyau](https://www.kernel.org/doc/html/latest/filesystems/proc.html).

PSS par service : KVMD ~59,2 Mio ; Janus 31,4 ; Media 23,5 ; PST 22,7 ;
Portable API 27,8 ; OLED 16,5 ; bouton 9,4 ; nginx 9,6 ; SHARE 10,2 ;
Wi-Fi 10,8. Les RSS cumulés comptent des pages partagées plusieurs fois :
préférer PSS pour l'attribution. Les cgroups ne fournissent pas MemoryCurrent
ici (null), pas une valeur zéro. GPU réservé : 96 Mio, déjà hors MemTotal.
PSI avg10/60/300 = 0 lors du relevé, compteurs historiques non nuls ; pas
d'OOM dans le journal noyau du démarrage consulté, aucun swap. Deux échantillons
ne permettent pas de conclure sur une fuite longue durée. Aucun nettoyage,
swap, changement GPU ou arrêt de service justifié par ces données.
[Relevés RAM et TLS filtrés](performance/rc131-pi-readonly.json). Le processus
de diagnostic ajoute lui-même une charge ponctuelle ; le relevé n'est pas
une preuve de consommation minimale au repos.

## HTTPS : constat et procédure séparée

Certificat présenté : CN=localhost, émetteur PiKVM/localhost, auto-signé.
Validité du 24 juillet 2026 au 21 juillet 2036 ; aucun SAN IP/DNS.
Empreinte SHA256 :
`8B:22:6F:4C:39:AD:30:5D:62:18:4D:76:C7:AC:74:A2:31:8A:1F:9E:C7:89:B3:87:47:98:C5:93:5A:45:9F:9E`.
nginx utilise `/etc/kvmd/nginx/ssl/server.crt` et `server.key`.
Le renouvellement effectif n'est pas attesté par le relevé ; ne pas supposer
qu'il est automatisé. Le nom système est `pikvm`, sa résolution DNS/mDNS depuis
Windows reste à vérifier. Ajouter seulement le certificat actuel à la confiance
ne corrigerait pas son absence de SAN pour l'IP.

Le modèle inactif `config/tls/pikvm-server-request.cnf` fournit le SAN IP et
les noms proposés `pikvm.home.arpa` / `share.pikvm.home.arpa`, à configurer
explicitement dans le DNS local avant utilisation. Aucun vhost ne les active.

Proposition : CA locale privée conservée sur une machine d'administration
protégée, certificat serveur à durée limitée avec SAN IP:192.168.168.99 et
noms DNS locaux dont la résolution aura été vérifiée, y compris le futur
nom distinct de gateway. Générer la clé serveur et le CSR sur le Pi après
autorisation ; envoyer uniquement le CSR pour signature. Ne jamais exporter
la clé privée de CA, ni la stocker dans Git ou sur le Pi. Le certificat public
de CA doit être authentifié par empreinte via un canal distinct.

Après approbation Windows seulement : importer son certificat public dans
`Cert:\CurrentUser\Root` via l'assistant Windows ou
`certutil -user -addstore Root CA-publique.cer` ; noter l'empreinte pour retrait.
[Microsoft](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/certutil).
Ne pas utiliser ignore-certificate-errors ni désactiver HTTPS.

Après approbation Pi séparée : sauvegarder certificats, permissions et nginx
dans un dossier root privé ; vérifier correspondance clé/certificat, chaîne,
SAN (`openssl verify -CAfile CA-publique.pem -verify_ip 192.168.168.99 serveur.pem`),
nginx `-t`/`-T`, puis recharger nginx uniquement. Tester Chrome et l'origine
de secours ; restaurer les fichiers sauvegardés et recharger nginx si échec.
[Vérification OpenSSL](https://github.com/openssl/openssl/blob/master/doc/man1/openssl-verification-options.pod).
Prévoir contrôle d'expiration à 30 jours et renouvellement via CSR avant
échéance, sans installer automatiquement de service de renouvellement ici.

## Migration et retour RC13

Construire avec `python3 -B scripts/pikvm-portable-package.py`, vérifier le
SHA256 de l'archive et chaque entrée MANIFEST. Recréer un stage fiable et
exécuter `check` puis `backup-only --approve-security-candidate SHA_DU_MANIFEST`
avec nouvelle sauvegarde RC13 vérifiée, lecteurs libres, racine temporairement
RW pour la copie puis RO. Ne pas réutiliser la sauvegarde RC12.1 comme point
de retour RC13. Installation uniquement après nouvelle autorisation explicite,
comprenant le changement de politique Web ; aucune modification TLS liée.

Pour revenir : libérer lecteurs/SHARE, remettre racine RW sous autorisation,
exécuter `python3 -B STAGE/scripts/pikvm-portable-install restore SAUVEGARDE_RC13`,
puis remettre RO même en cas d'erreur. Les nouveaux fichiers de police sont
retirés s'ils n'existaient pas. L'état de sécurité original est restauré depuis
la sauvegarde privée ; les comptes créés ensuite sont conservés dans la copie
de l'état abandonné pour revue, pas fusionnés automatiquement. RC13 ne connaît
pas le champ optionnel strict_passwords : restaurer l'état avec l'application.
Tester les accès natifs et Portable. Aucun test de restauration réel sur ce Pi
n'est effectué pendant la préparation de RC13.1.
