# VIES - Validation de TVA Intracommunautaire

Outil Python pour la validation en masse de numéros SIREN français contre l'API VIES (VAT Information Exchange System) de l'Union Européenne.

## Description

Ce projet permet de vérifier si des entreprises françaises, identifiées par leur numéro SIREN, sont enregistrées à la TVA intracommunautaire. Il utilise l'API REST officielle de la Commission Européenne pour effectuer ces vérifications.

## Fonctionnalités

- **Conversion SIREN → TVA** : Calcul automatique du numéro de TVA intracommunautaire français à partir d'un SIREN
- **Validation en masse** : Traitement parallèle de fichiers contenant plusieurs numéros SIREN
- **Gestion robuste des erreurs** : Mécanisme de retry avec backoff exponentiel
- **Rate limiting** : Limitation configurable des requêtes par minute (défaut: 25 req/min)
- **Interface CLI complète** : Options configurables via ligne de commande
- **Mode dry-run** : Vérification des TVA calculés sans appeler l'API
- **Support proxy** : Configuration proxy pour environnements d'entreprise
- **Logging** : Journalisation horodatée des opérations

## Prérequis

- Python 3.7+
- Dépendances Python :
  ```
  requests
  ```

## Installation

```bash
# Cloner le dépôt
git clone <repository-url>
cd VIES

# Installer les dépendances
pip install -r requirements.txt
```

## Utilisation

### Aide

```bash
python vies.py --help
```

### Usage simple

```bash
python vies.py sirens.txt
```

### Options disponibles

```
usage: vies [-h] [-o FILE] [-w N] [-r N] [--log FILE] [--dry-run] [-v] [-q]
            [--no-proxy] [--timeout N] [--max-retries N]
            FILE

positional arguments:
  FILE                  Fichier d'entrée contenant les SIRENs (un par ligne)

options:
  -h, --help            Affiche l'aide
  -o FILE, --output FILE
                        Fichier de sortie CSV (défaut: <input>.out)
  -w N, --workers N     Nombre de threads concurrents (défaut: 10)
  -r N, --rate-limit N  Limite de requêtes par minute (défaut: 25)
  --log FILE            Fichier de log (défaut: default.log)
  --dry-run             Affiche les TVA calculés sans appeler l'API
  -v, --verbose         Mode verbeux (affiche plus de détails)
  -q, --quiet           Mode silencieux (pas de sortie console)
  --no-proxy            Désactive le proxy
  --timeout N           Timeout des requêtes HTTP en secondes (défaut: 90)
  --max-retries N       Nombre maximum de tentatives par SIREN (défaut: 50)
```

### Exemples

```bash
# Validation simple
python vies.py sirens.txt

# Avec fichier de sortie personnalisé
python vies.py sirens.txt -o resultats.csv

# Mode dry-run (vérifier les TVA sans appeler l'API)
python vies.py sirens.txt --dry-run

# Mode verbeux avec moins de workers
python vies.py sirens.txt -v -w 5

# Mode silencieux sans proxy
python vies.py sirens.txt -q --no-proxy
```

### Sortie

Le script génère :
- **`<fichier>.out`** : Fichier CSV avec les résultats (`siren;has_vat`)
- **`default.log`** : Journal des opérations avec horodatage

Exemple de sortie CSV :
```csv
siren;has_vat
931153688;True
423038504;False
812117992;True
```

## Configuration

### Variables d'environnement (optionnel - pour proxy)

Si vous êtes derrière un proxy d'entreprise, configurez les variables suivantes :

```bash
export PROXY_USER="votre_username_proxy"
export PROXY_PWD="votre_password_proxy"
export PROXY_HOST="ip_proxy:port_proxy"  # ex: proxy.example.com:8080
```

Utilisez `--no-proxy` pour désactiver le proxy même si les variables sont définies.

## Architecture

```
VIES/
├── vies.py          # Script principal
├── sirens.txt       # Fichier d'entrée exemple
├── requirements.txt # Dépendances Python
├── README.md        # Documentation
└── CLAUDE.md        # Guide pour Claude Code
```

### Fonctions principales

| Fonction | Description |
|----------|-------------|
| `computeVAT(siren)` | Convertit un SIREN en numéro de TVA français |
| `hasValidVat(siren)` | Valide un SIREN contre l'API VIES |
| `processID(id)` | Wrapper pour le traitement d'un identifiant |
| `processFile(...)` | Traitement en masse d'un fichier |
| `dry_run(filename)` | Mode dry-run sans appel API |
| `main()` | Point d'entrée CLI |

## Formule de calcul TVA

Le numéro de TVA intracommunautaire français est calculé ainsi :

```
Clé = (12 + 3 × (SIREN mod 97)) mod 97
TVA = "FR" + Clé (sur 2 chiffres) + SIREN
```

Exemple : SIREN `380129866` → TVA `FR38380129866`

## API utilisée

- **Endpoint** : `http://ec.europa.eu/taxation_customs/vies/rest-api/ms/FR/vat/{TVA}`
- **Documentation** : [VIES VAT number validation](https://ec.europa.eu/taxation_customs/vies/)

## Auteur

**Jean-Paul Gavini** ([@Sandjab](https://github.com/Sandjab)) - Janvier 2026

## Licence

Ce projet est fourni sans licence spécifique. Utilisation à vos propres risques.

## Contribuer

Les contributions sont les bienvenues. Merci de créer une issue ou une pull request pour toute suggestion d'amélioration.
