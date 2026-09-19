# Câblage électrique

## GPIO

| Fonction | GPIO | Broche physique |
|---|---:|---:|
| Maintien alimentation | GPIO17 | 11 |
| Bouton | GPIO18 | 12 |
| SDA I2C | GPIO2 | 3 |
| SCL I2C | GPIO3 | 5 |

Les GPIO 22, 23, 24 et 27 restent réservés aux fonctions ATX de PiKVM.

## Alimentation principale

    Batterie 18650
          |
    Chargeur / protection
          |
         BMS+
          |
       COM relais
          |
       NO relais
          |
      VIN+ Step-Up
          |
      OUT+ 5,1 V
          |
      Raspberry Pi

Masse :

    BMS-
      |
      +-> VIN- Step-Up
      +-> GND Raspberry Pi
      +-> GND module MOSFET

Toutes les masses restent reliées en permanence.

## Contact du relais

    BMS+ -> COM
    NO   -> VIN+ Step-Up
    NC   -> non utilisé

## Bouton de démarrage

    BMS+
      |
    bouton
      |
    START

Le signal START va vers :

    START -> SS34 -> VIN+ Step-Up
    START -> SS34 -> TRIG MOSFET
    START -> 47k -> GPIO18

## Détection GPIO18

    START
      |
     47k
      |
      +---- GPIO18
      |
    100k
      |
     GND

## Maintien GPIO17

    GPIO17 -> SS34 -> TRIG MOSFET

La bague de la SS34 est orientée vers TRIG.

## Pull-down TRIG

    TRIG
      |
    100k
      |
     GND

## Bobine du relais

    Step-Up +5,1 V -> MOSFET VIN+
    Step-Up GND    -> MOSFET VIN-

    MOSFET VOUT+ -> bobine relais +
    MOSFET VOUT- -> bobine relais -

Une SS34 est placée en parallèle sur la bobine.

    bague SS34 -> bobine +
    sans bague -> bobine -

## Séquence de démarrage

    Appui bouton
        |
        +-> alimentation temporaire du Step-Up
        |
        +-> activation TRIG MOSFET
                 |
              relais ON
                 |
           COM / NO fermé
                 |
        Step-Up reste alimenté
                 |
          Raspberry Pi démarre
                 |
          GPIO17 passe HIGH
                 |
          relais maintenu ON

## Séquence d'arrêt

    GPIO17 LOW
        |
    MOSFET OFF
        |
    relais OFF
        |
    COM / NO ouvert
        |
    Step-Up non alimenté
        |
    PiKVM totalement éteint
