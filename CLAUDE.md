# CLAUDE.md - Guide pour Claude Code

Ce fichier fournit le contexte nécessaire à Claude Code pour travailler efficacement sur ce projet.

**Auteur** : Jean-Paul Gavini ([@Sandjab](https://github.com/Sandjab))
**Date** : Janvier 2026

## Apercu du projet

VIES est un outil Python de validation de numéros SIREN français contre l'API VIES de l'Union Européenne. Il vérifie si une entreprise est enregistrée à la TVA intracommunautaire.

## Structure du projet

```
VIES/
├── vies.py          # Script principal avec CLI
├── sirens.txt       # Fichier d'entrée avec les SIRENs à valider
├── requirements.txt # Dépendances Python
├── README.md        # Documentation utilisateur
├── CLAUDE.md        # Ce fichier
└── .gitignore       # Exclusions Git
```

## Fichier principal : vies.py

### Organisation du code

1. **Imports et configuration** (lignes 1-70)
   - Constantes par défaut : `DEFAULT_WORKERS`, `DEFAULT_TIMEOUT`, etc.
   - Configuration globale via dictionnaire `config`
   - Classe `RateLimiter` : limitation thread-safe des requêtes/minute
   - `_rate_limited_request()` : wrapper HTTP avec rate limiting

2. **Fonctions utilitaires** (lignes 73-101)
   - `get_proxies()` : Configuration proxy dynamique
   - `log()` : Journalisation avec horodatage
   - `out()` : Écriture des résultats CSV
   - `verbose_print()` : Affichage conditionnel en mode verbose

3. **Logique métier** (lignes 104-210)
   - `computeVAT()` : Conversion SIREN → TVA
   - `hasValidVat()` : Validation contre l'API (avec rate limiting)
   - `processID()` : Wrapper de traitement

4. **Modes d'exécution** (lignes 213-316)
   - `dry_run()` : Mode simulation sans appel API
   - `processFile()` : Traitement en masse multi-thread

5. **Interface CLI** (lignes 319-456)
   - `parse_args()` : Configuration argparse
   - `main()` : Point d'entrée principal (initialise le rate limiter)

### Point d'entrée

Le script utilise `argparse` et s'exécute via `main()` appelé par `if __name__ == "__main__"`.

## Commandes utiles

```bash
# Installer les dépendances
pip install -r requirements.txt

# Afficher l'aide
python vies.py --help

# Exécuter le script
python vies.py sirens.txt

# Mode dry-run (sans appel API)
python vies.py sirens.txt --dry-run

# Mode verbeux
python vies.py sirens.txt -v

# Sans proxy
python vies.py sirens.txt --no-proxy
```

## Options CLI

| Option | Défaut | Description |
|--------|--------|-------------|
| `FILE` | (requis) | Fichier d'entrée |
| `-o, --output` | `<input>.out` | Fichier de sortie |
| `-w, --workers` | 10 | Threads concurrents |
| `-r, --rate-limit` | 25 | Requêtes/minute |
| `--log` | `default.log` | Fichier de log |
| `--dry-run` | - | Mode simulation |
| `-v, --verbose` | - | Mode verbeux |
| `-q, --quiet` | - | Mode silencieux |
| `--no-proxy` | - | Désactive le proxy |
| `--timeout` | 90 | Timeout HTTP (s) |
| `--max-retries` | 50 | Tentatives max |

## Conventions de code

- **Langue** : Code et commentaires en français
- **Style** : PEP 8 (indentation 4 espaces)
- **Docstrings** : Format Google pour les fonctions principales
- **Typage** : Annotations de type utilisées (`-> str`, `: str`)

## Points d'attention

### API VIES
- L'API peut être instable et renvoyer des erreurs temporaires
- Le mécanisme de retry avec backoff exponentiel est essentiel
- Respecter le rate limiting pour éviter les blocages

### Variables d'environnement
- `PROXY_USER` : Username proxy (optionnel)
- `PROXY_PWD` : Password proxy (optionnel)
- `PROXY_HOST` : Adresse proxy au format `<ip>:<port>` (optionnel)
- Utiliser `--no-proxy` pour désactiver le proxy

### Fichiers générés (non versionnés)
- `default.log` : Journal des opérations
- `*.out` : Résultats CSV

## Améliorations possibles

- [x] ~~Ajouter des arguments CLI (argparse)~~
- [x] ~~Rendre le proxy configurable sans variables d'environnement~~
- [ ] Supporter d'autres pays que la France
- [ ] Ajouter des tests unitaires

## Dépendances

| Package | Usage |
|---------|-------|
| `requests` | Requêtes HTTP vers l'API VIES |

## Exécution de tests

Actuellement, pas de tests automatisés. Pour tester manuellement :

```bash
# Mode dry-run pour vérifier le calcul TVA
python vies.py sirens.txt --dry-run

# Test avec un seul SIREN
echo "380129866" > test.txt
python vies.py test.txt --no-proxy -v
cat test.txt.out
```

## Notes pour le développement

- Le script utilise argparse pour une interface CLI standard
- Configuration centralisée via le dictionnaire `config`
- La gestion d'erreurs est robuste avec retry automatique
- Les threads permettent le traitement parallèle
- Mode `--dry-run` utile pour valider les entrées sans appel réseau
- Rate limiting thread-safe via classe `RateLimiter` (configurable via `-r`)
