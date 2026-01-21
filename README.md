# AskVIES - Validation de TVA Intracommunautaire

Outil Python pour la validation en masse de numéros SIREN français contre l'API VIES (VAT Information Exchange System) de l'Union Européenne.

## Description

Ce projet permet de vérifier si des entreprises françaises, identifiées par leur numéro SIREN, sont enregistrées à la TVA intracommunautaire. Il utilise l'API REST officielle de la Commission Européenne pour effectuer ces vérifications.

## Fonctionnalités

- **Conversion SIREN → TVA** : Calcul automatique du numéro de TVA intracommunautaire français à partir d'un SIREN
- **Validation en masse** : Traitement parallèle de fichiers contenant plusieurs numéros SIREN
- **Gestion robuste des erreurs** : Mécanisme de retry avec backoff exponentiel configurable
- **Rate limiting** : Limitation configurable des requêtes par minute (défaut: 300 req/min, 0 pour désactiver)
- **Interface CLI complète** : Options configurables via ligne de commande
- **Mode dry-run** : Vérification des TVA calculés sans appeler l'API
- **Support proxy** : Configuration proxy pour environnements d'entreprise
- **Logging** : Journalisation horodatée des opérations

## Prérequis

- Python 3.10+ (utilisation de la syntaxe de type union `X | Y`)
- Dépendances Python :
  ```
  requests
  ```

## Installation

```bash
# Cloner le dépôt
git clone <repository-url>
cd AskVIES

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
            [--proxy URL | --no-proxy] [--timeout N] [--max-retries N]
            [--initial-delay SEC] [--backoff-multiplier N] [--max-delay SEC]
            FILE

positional arguments:
  FILE                  Fichier d'entrée contenant les SIRENs (un par ligne)

options:
  -h, --help            Affiche l'aide
  -o FILE, --output FILE
                        Fichier de sortie CSV (défaut: <input>.out)
  -w N, --workers N     Nombre de threads concurrents (défaut: 10)
  -r N, --rate-limit N  Limite de requêtes par minute (défaut: 300, 0 = désactivé)
  --log FILE            Fichier de log (défaut: default.log)
  --dry-run             Affiche les TVA calculés sans appeler l'API
  -v, --verbose         Mode verbeux (affiche plus de détails)
  -q, --quiet           Mode silencieux (pas de sortie console)
  --proxy URL           URL du proxy (ex: http://user:pass@host:port)
  --no-proxy            Désactive le proxy (connexion directe)
  --timeout N           Timeout des requêtes HTTP en secondes (défaut: 90)
  --max-retries N       Nombre maximum de tentatives par SIREN (défaut: 50)
  --initial-delay SEC   Délai initial pour le backoff en secondes (défaut: 0.2)
  --backoff-multiplier N
                        Multiplicateur de backoff exponentiel (défaut: 1.5)
  --max-delay SEC       Délai maximum pour le backoff en secondes (défaut: 30)
```

> **Note** : `--proxy` et `--no-proxy` sont mutuellement exclusifs.

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

# Avec proxy explicite
python vies.py sirens.txt --proxy http://proxy:8080
python vies.py sirens.txt --proxy http://user:pass@proxy:8080

# Sans proxy (connexion directe)
python vies.py sirens.txt --no-proxy
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

### Indicateurs de progression

Pendant le traitement, des caractères sont affichés pour indiquer l'état des requêtes :

| Caractère | Signification |
|-----------|---------------|
| `.` | Retry - Erreur API temporaire (maintenance, surcharge) |
| `P` | Proxy Error - Erreur de connexion au proxy |
| `R` | Request Error - Erreur réseau (timeout, connexion refusée, etc.) |

Ces indicateurs permettent de suivre visuellement les problèmes rencontrés pendant le traitement en masse. Chaque caractère correspond à une tentative de retry avec backoff exponentiel.

**Exemple de sortie** :
```
Traitement de 100 SIRENs...
..P.R...
siren;has_vat
931153688;True
```

> **Note** : En mode verbeux (`-v`), des messages détaillés sont affichés en plus de ces indicateurs. En mode silencieux (`-q`), aucun indicateur n'est affiché.

## Configuration du proxy

Le proxy est configuré selon cet ordre de priorité :

1. `--no-proxy` : Connexion directe (pas de proxy)
2. `--proxy URL` : URL du proxy spécifiée explicitement
3. `PROXY_HOST` (+ `PROXY_USER`/`PROXY_PWD` optionnels) : Configuration legacy
4. Auto-détection : `HTTP_PROXY`/`HTTPS_PROXY` (variables système standard)

### Option 1 : Via ligne de commande (recommandé)

```bash
# Proxy sans authentification
python vies.py sirens.txt --proxy http://proxy.example.com:8080

# Proxy avec authentification
python vies.py sirens.txt --proxy http://user:pass@proxy.example.com:8080

# Forcer la connexion directe
python vies.py sirens.txt --no-proxy
```

### Option 2 : Via variables d'environnement système

Le script détecte automatiquement les variables standard :

```bash
export HTTP_PROXY="http://proxy.example.com:8080"
export HTTPS_PROXY="http://proxy.example.com:8080"
```

### Option 3 : Via variables legacy (rétrocompatibilité)

```bash
export PROXY_HOST="proxy.example.com:8080"
export PROXY_USER="votre_username"  # optionnel
export PROXY_PWD="votre_password"   # optionnel
```

## Architecture

```
AskVIES/
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

- **Endpoint** : `https://ec.europa.eu/taxation_customs/vies/rest-api/ms/FR/vat/{TVA}`
- **Documentation** : [VIES VAT number validation](https://ec.europa.eu/taxation_customs/vies/)

## Auteur

**Jean-Paul Gavini** ([@Sandjab](https://github.com/Sandjab)) - Janvier 2026

## Contribuer

Les contributions sont les bienvenues. Merci de créer une issue ou une pull request pour toute suggestion d'amélioration.
