# Portable OS 0.2.0-rc.5 — OLED dans la sidebar, maintien logique, I/O séparées

Candidate locale sur `codex/portable-os`. Aucun déploiement sur le Raspberry Pi.

## Interface et gestes

La carte Pi Zero 2 W ouvre/replie le panneau immédiatement sous la carte, dans la
colonne de gauche. Aucun dialogue OLED n'est créé. Sur téléphone, le panneau reste
dans la navigation latérale. Les pixels sont toujours ceux du rendu Pillow natif
128×64, agrandis sans interpolation ; aucun compteur n'est inventé côté navigateur.

Le bouton écran utilise Pointer Events (souris et toucher avec capture du pointeur)
et Espace/Entrée. L'appui commence au down, se termine au up et s'annule à Échap,
pointercancel, perte de capture/focus, fermeture du panneau, navigation mobile
masquée, onglet caché ou session expirée. Le maintien est réel et de durée variable.
L'API ne reçoit pas une durée déclarée par le navigateur : le serveur mesure le
geste avec son horloge monotone. Les étapes court/2 s/3 s/5 s restent celles des
boucles du menu physique.
Le compte à rebours d'inactivité reste en pause pendant le maintien, comme dans
le menu natif ; ses barres de progression utilisent la durée réelle du geste.

Pendant le maintien, le navigateur renouvelle un bail toutes les 200 ms après
réponse. Si les renouvellements cessent pendant 800 ms, le serveur **annule** le
geste. Une annulation n'est ni un clic court, ni une validation d'appui long. Le
relâchement est envoyé immédiatement, sans attendre la réponse start. Un stop reçu
avant start ne peut produire qu'un court ; un cancel reçu avant start n'en produit
aucun. Les gestes et leurs autorisations sont liés à la session KVMD et à un nonce
unique. Aucun début de geste n'est répété automatiquement après erreur réseau.

Les appuis longs de navigation (QR, gestion ISO, etc.) sont disponibles. Les actions
sensibles sont **verrouillées par défaut** : une case explicite, propre à l'écran
courant et au prochain geste, autorise soit arrêt/redémarrage, soit changement de
réseau, soit suppression de l'image affichée dans sa confirmation native. La case
est consommée au début du geste et invalidée si l'écran logique change. Le serveur
vérifie aussi la correspondance écran/permission. Les actions alimentation distantes
exigent que les deux lecteurs soient éjectés et que SHARE soit libéré. Les gardes
de suppression du programme existant restent actives. Les transferts/opérations du
navigateur désactivent l'armement. Un appui physique normal conserve ses règles ;
un chevauchement physique/virtuel annule le geste virtuel et exige un relâchement,
sans fusionner les deux durées.

**Un maintien de cinq secondes explicitement autorisé sur POWER peut donc demander
l'arrêt système existant**, comme le bouton physique. Aucun nouveau code ne change
le niveau ou la configuration de GPIO17/18. Le chemin de power-hold et son hook
d'arrêt restent inchangés. Un simple clic ou un maintien non armé ne les déclenche pas.

## Diagnostic du lag et architecture

L'analyse locale du code RC4 identifie ces chemins synchrones, cohérents avec un
CPU peu occupé lors des pauses :

- Les dessins de menus lisent Wi-Fi/batterie par des sous-processus, parfois avec
  plusieurs délais de deux ou trois secondes successifs. Le compte à rebours était
  calculé avant ces lectures.
- Le producteur normal effectue aussi les lectures MAX17048, réseau, HDMI et
  fichiers d'état avant de publier sa frame. Les lectures i2cget de ce producteur
  n'avaient pas de timeout explicite.
- `GET oled` appelle `services()` et peut attendre `systemctl show` sous un verrou
  partagé avec les autres diagnostics.
- Le rafraîchissement RC4 était interrompu par l'action de bouton dans la fenêtre.

RC5 sépare maintenant les quatre chemins :

1. Les fonctions de dessin et l'état du menu restent natifs. La télémétrie utilise
   un cache borné à 32 entrées et deux workers, sans attente dans le dessin. Chaque
   mesure n'a qu'une lecture en attente. Les dernières valeurs sont utilisées en
   attendant, avec les valeurs inconnues natives au démarrage. Les lectures
   matérielles passent dans ces workers, les i2cget ont un timeout explicite.
2. Le bouton physique a son lecteur dédié, exclusivement `pinctrl get`, sans
   reconfiguration. Une lecture incertaine ou périmée annule le geste physique ;
   elle ne prolonge jamais artificiellement un maintien.
3. L'API frame lit deux petits fichiers tmpfs : framebuffer et heartbeat du menu.
   Elle n'appelle plus systemctl, ne prend pas son verrou et ne fait pas de ping
   synchrone du bouton. Le ping privé reste utilisé par le précontrôle d'installation.
4. Le navigateur lit les frames à 200 ms, sans requêtes parallèles, même durant
   un maintien. Il redessine seulement si l'identifiant de l'image change. Les
   événements de bouton empruntent une requête indépendante. Le worker SSD1306
   et sa reconnexion non bloquante de RC4 sont conservés.

Les gardes disque et les opérations sensibles ne sont pas remplacées par des
valeurs de télémétrie mises en cache. L'entrée dans le menu conserve le transfert
de propriété du producteur normal par systemd. Les commandes longues explicitement
demandées (réseau, suppression, arrêt), ainsi que cette transition de service,
peuvent afficher une phase occupée. La correction ne prétend pas supprimer un délai
réseau, une panne KVMD ou toute latence matérielle possible. Les mesures sur le Pi
restent à faire après autorisation ; aucun diagnostic SSH n'est exécuté ici.

## API et sécurité

`GET /extras/portable-os/api/oled` conserve les pixels et ajoute `control_id`,
identifiant de l'écran logique (sélection/cible, sans le compte à rebours).
Il ne remplace pas `id`, qui identifie toujours l'image exacte.

`POST /extras/portable-os/api/oled/button` accepte uniquement :

```json
{"action":"start","gesture_id":"32 caractères hexadécimaux","control_id":"64 caractères hexadécimaux","permit":""}
```

Puis `{"action":"keep|stop|cancel","gesture_id":"…"}`. `permit` peut être vide,
`power`, `network` ou `delete`, uniquement depuis l'écran autorisé correspondant.
La session propriétaire est ajoutée par l'API après authentification, jamais fournie
par le client. Les champs `duration`, GPIO, commande et owner sont refusés.
Toutes les mutations conservent les protections origine/CSRF existantes. Le socket
Unix privé et la vérification du client root restent en place. L'ancien endpoint
`oled/short` reste compatible, mais le panneau RC5 utilise le nouveau protocole.

## Installation et migration

Fichiers principaux modifiés : `scripts/pikvm_oled.py` (cache, heartbeat et gestes),
`scripts/pikvm-oled-custom`, `scripts/pikvm-button-menu`, `scripts/pikvm-portable-api`,
`scripts/pikvm-oled-baselines.json`, `scripts/pikvm-portable-package.py`,
`web/extras/portable-os/{modules/oled.js,index.html,style.css,package.json}`.
Tests ajoutés dans `tests/test_oled_hold.py`, tests HTTP/bouton existants adaptés,
fixture et scénario navigateur mis à jour. Le registre de modules et les routes
legacy/KVM restent identiques.

Validation locale : **110 tests Python réussis, deux exclus sous Windows**, **18
tests JavaScript réussis**, scénario Edge desktop/tactile réussi. Le test de
compteur observe réellement les frames natives 10, 9 puis 8 pendant un lecteur
de télémétrie bloqué quatre secondes. Le navigateur conserve les lectures pendant
un maintien de deux secondes et vérifie l'annulation Échap. Le transport AF_UNIX
réel et les privilèges de liens symboliques sont les deux exclusions Windows ;
la CI Linux est préparée mais n'a pas été lancée à distance.

Les empreintes connues des trois fichiers RC4 sont ajoutées au contrôle de migration.
Tout script ou module local non reconnu est refusé avant l'arrêt des services.
Les sauvegardes incluent les producteurs, le module, l'API, l'interface, nginx et
les états actif/activé des services OLED. Le contrôle de disponibilité attend une
nouvelle frame et le gestionnaire logique, sans injecter d'appui. Les interfaces
legacy, KVM, Drive 0/1 et l'arrêt automatique ne sont pas modifiés.

Sur Windows, après autorisation explicite du déploiement uniquement :

```powershell
cd C:\Users\PC\Documents\pikvm-portable
python scripts/pikvm-portable-package.py
$sshOptions = @('-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','PasswordAuthentication=yes','-o','StrictHostKeyChecking=ask')
scp @sshOptions private/pikvm-portable-os-0.2.0-rc.5.tar.gz private/pikvm-portable-os-0.2.0-rc.5.tar.gz.sha256 root@192.168.168.99:/tmp/
ssh @sshOptions root@192.168.168.99
```

Le mot de passe se saisit aux invites, sans clé SSH ni enregistrement. Sur le Pi :

```bash
cd /tmp
sha256sum -c pikvm-portable-os-0.2.0-rc.5.tar.gz.sha256
work=$(mktemp -d /tmp/portable-os-rc5.XXXXXX)
tar -xzf pikvm-portable-os-0.2.0-rc.5.tar.gz -C "$work"
cd "$work/pikvm-portable-os-0.2.0-rc.5"
sha256sum -c MANIFEST.sha256
python3 -B scripts/pikvm-portable-install check
rw
bash install-portable-os.sh
ro
```

Ne continuer après `check` que si tous les contrôles passent. Conserver le chemin
**Sauvegarde : /root/pikvm-portable-os-backups/…** imprimé. Ne pas utiliser
l'installateur global `install.sh` pour cette mise à jour. Aucun reboot matériel,
redémarrage KVMD ou démarrage du power-hold n'est demandé.

Valider sur le Pi : panneau sous la carte, compte à rebours et navigation Wi-Fi
pendant les changements de frames, appuis courts et maintiens de 2 s en navigation,
annulation par Échap/onglet caché, puis reconnexion du navigateur. Garder les cases
sensibles décochées pour ces essais ; leur armement peut provoquer les actions
matérielles natives indiquées. Comparer `systemctl show -p ActiveState -p NRestarts
pikvm-oled-custom.service pikvm-button-menu.service` avant/après, sans menu ouvert.

## Retour arrière

Avec le chemin exact imprimé lors de cette mise à jour, remplacer `DATE-ID` :

```bash
rw
python3 -B /usr/local/bin/pikvm-portable-install restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

Si le script installé est indisponible, utiliser celui de l'archive vérifiée :

```bash
rw
python3 -B "$work/pikvm-portable-os-0.2.0-rc.5/scripts/pikvm-portable-install" restore /root/pikvm-portable-os-backups/DATE-ID
ro
```

La restauration vérifie les sauvegardes avant tout arrêt, restaure fichiers/nginx
et états des services, puis recharge nginx. Elle est répétable et indépendante
du navigateur. Une restauration de RC4 remet aussi la fenêtre modale et les appuis
courts uniquement. Le contenu des images et les GPIO ne sont pas restaurés/modifiés.
