# Matériel utilisé

## Raspberry Pi

- Raspberry Pi Zero 2 W
- PiKVM installé sur carte microSD

## Capture vidéo

- Adaptateur HDMI vers CSI compatible PiKVM

## Écran

- OLED 128x64 I2C
- Adresse I2C : `0x3C`

Branchement :

    OLED VCC -> alimentation
    OLED GND -> GND commun
    OLED SDA -> GPIO2 / broche physique 3
    OLED SCL -> GPIO3 / broche physique 5

## Batterie

- Batterie Li-ion 18650
- Module de charge/protection 1 cellule
- MAX17048 pour la mesure de batterie
- Convertisseur Step-Up réglé à 5,1 V

Adresse I2C du MAX17048 :

    0x36

## Gestion de l'alimentation

- Relais SRD-05VDC-SL-C 5 V
- Module MOSFET low-side
- Bouton poussoir momentané
- Diodes Schottky SS34
- Résistance 47 kΩ
- Résistances 100 kΩ

## USB-C

Breakout USB-C USB 2.0 avec :

    CC1 -> 5,1 kΩ -> GND
    CC2 -> 5,1 kΩ -> GND

Les lignes D+ et D- doivent être courtes et torsadées ensemble.

Le câblage final a été validé en USB 2.0 High-Speed.
