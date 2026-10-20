# Battery Monitor BM6 pour Home Assistant

![Licence](https://img.shields.io/github/license/Marlboro62/hass-bm6)
![Version](https://img.shields.io/github/v/release/Marlboro62/hass-bm6)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

<img src="images/icon.png" alt="Icône" width="96" align="right">

Intégration personnalisée [Home Assistant](https://www.home-assistant.io) pour le moniteur de batterie Bluetooth **BM6**. Elle lit la tension, la température, le pourcentage et l'état de la batterie via un adaptateur Bluetooth ou un proxy ESPHome.

Ce dépôt est un fork de [Rafciq/BM6](https://github.com/Rafciq/BM6), sous licence MIT.

> ⚠️ Vous utilisez cette intégration à vos propres risques. L'auteur n'est pas responsable des dommages liés à son utilisation.

## Différences avec le projet d'origine

- **Choix du proxy Bluetooth** : un proxy précis peut être imposé pour chaque BM6. En mode « Automatique », tous les scanners sont essayés, du meilleur signal au moins bon.
- **Type de batterie EFB 12 V** (Enhanced Flooded Battery, batteries start & stop).
- **Plages FLA 12 V** revues, avec une détection de charge plus sensible.
- **Corrections** : l'état renvoyé par l'appareil n'était jamais reconnu (toujours « inconnu »), et le capteur d'état de l'appareil plantait sur un code inconnu.
- **Tension corrigée** (avec l'offset) utilisée dans l'historique et les statistiques.

## Prérequis

- Home Assistant **2026.10.0** ou plus récent
- Un adaptateur Bluetooth ou un proxy Bluetooth ESPHome à portée du BM6

## Installation

### Avec HACS

1. Dans HACS, ouvrez le menu ⋮ en haut à droite, puis **Dépôts personnalisés**.
2. Ajoutez `https://github.com/Marlboro62/hass-bm6` avec le type **Intégration**.
3. Installez **Battery Monitor BM6** puis redémarrez Home Assistant.

### Manuellement

Copiez le dossier `custom_components/bm6` dans le dossier `custom_components` de votre configuration, puis redémarrez Home Assistant.

> Si l'intégration d'origine (Rafciq/BM6) est installée, supprimez-la d'abord : les deux utilisent le même domaine `bm6`. Vos appareils et entités sont conservés.

## Configuration

**Paramètres → Appareils et services → Ajouter une intégration → Battery Monitor BM6.** Les BM6 à portée sont aussi découverts automatiquement.

Réglages disponibles :

- proxy Bluetooth (automatique ou imposé)
- algorithme de calcul : par l'appareil BM6, SoC/SoD ou CVR/DVR
- intervalle de mise à jour (10 s minimum, 120 s par défaut)
- corrections de tension et de température, unité de température
- tension (6 V ou 12 V) et type de batterie : FLA, AGM, GEL, EFB, NiCd, NiMH, Li-Ion, LiFePO4, LTO ou plages personnalisées

## Capteurs

| Capteur | Description |
|---|---|
| Tension | Tension mesurée, corrigée de l'offset |
| Température | Température mesurée, corrigée de l'offset |
| Pourcentage | Charge estimée selon l'algorithme choisi |
| État | `ok`, `low_voltage`, `under_voltage`, `discharging`, `idle`, `charging`, `over_voltage` |

Capteurs de diagnostic, désactivés par défaut : RSSI, pourcentage et état renvoyés par l'appareil, scanner Bluetooth utilisé, accélération et décélération rapides.

Des déclencheurs d'appareil sur les changements d'état sont disponibles dans les automatisations.

## Signaler un problème

Le support se fait uniquement via les [issues GitHub](https://github.com/Marlboro62/hass-bm6/issues). Joignez si possible le diagnostic de l'appareil et les journaux en mode debug :

```yaml
logger:
  logs:
    custom_components.bm6: debug
```

## Soutenir le projet

[Buy Me a Coffee](https://buymeacoffee.com/marlboro62) · [Ko-fi](https://ko-fi.com/nothing_one)
