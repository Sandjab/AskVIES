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

1. **Imports et configuration** (lignes 1-80)
   - Constantes par défaut : `DEFAULT_WORKERS`, `DEFAULT_TIMEOUT`, `DEFAULT_RATE_LIMIT`, etc.
   - Constantes de backoff : `THROTTLE_INITIAL_DELAY`, `THROTTLE_MULTIPLIER`, etc.
   - Configuration globale via dictionnaire `config`
   - Classe `RateLimiter` : limitation thread-safe des requêtes/minute (sleep hors lock pour performance)
   - `_rate_limited_request()` : wrapper HTTP avec rate limiting

2. **Fonctions utilitaires** (lignes 240-380)
   - `get_proxies()` : Configuration proxy dynamique
   - `get_proxies_cached()` : Version mise en cache pour performance
   - `log()` : Journalisation avec horodatage
   - `out()` : Écriture des résultats CSV
   - `verbose_print()` : Affichage conditionnel en mode verbose

3. **Logique métier** (lignes 365-539)
   - `computeVAT()` : Conversion SIREN → TVA
   - `hasValidVat()` : Validation contre l'API (avec rate limiting)
   - `processID()` : Wrapper de traitement

4. **Modes d'exécution** (lignes 546-681)
   - `dry_run()` : Mode simulation sans appel API
   - `processFile()` : Traitement en masse multi-thread

5. **Interface CLI** (lignes 688-845)
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

# Avec proxy explicite
python vies.py sirens.txt --proxy http://proxy:8080
python vies.py sirens.txt --proxy http://user:pass@proxy:8080

# Sans proxy (connexion directe)
python vies.py sirens.txt --no-proxy
```

## Options CLI

| Option | Défaut | Description |
|--------|--------|-------------|
| `FILE` | (requis) | Fichier d'entrée |
| `-o, --output` | `<input>.out` | Fichier de sortie |
| `-w, --workers` | 10 | Threads concurrents |
| `-r, --rate-limit` | 300 | Requêtes/minute (0 = désactivé) |
| `--log` | `default.log` | Fichier de log |
| `--dry-run` | - | Mode simulation |
| `-v, --verbose` | - | Mode verbeux |
| `-q, --quiet` | - | Mode silencieux |
| `--proxy` | - | URL du proxy (ex: http://user:pass@host:port) |
| `--no-proxy` | - | Désactive le proxy (connexion directe) |
| `--timeout` | 90 | Timeout HTTP (s) |
| `--max-retries` | 50 | Tentatives max |
| `--initial-delay` | 0.2 | Délai initial backoff (s) |
| `--backoff-multiplier` | 1.5 | Multiplicateur backoff |
| `--max-delay` | 30 | Délai max backoff (s) |

> **Note** : `--proxy` et `--no-proxy` sont mutuellement exclusifs.

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

### Configuration du proxy

Le proxy est configuré selon cet ordre de priorité :

1. `--no-proxy` : Connexion directe (pas de proxy)
2. `--proxy URL` : URL du proxy spécifiée explicitement
3. `PROXY_HOST` (+ `PROXY_USER`/`PROXY_PWD` optionnels) : Configuration legacy
4. Auto-détection : `HTTP_PROXY`/`HTTPS_PROXY` (variables système standard)

**Variables d'environnement supportées :**
- `PROXY_HOST` : Adresse proxy au format `<ip>:<port>` (legacy)
- `PROXY_USER` : Username proxy (optionnel, avec PROXY_HOST)
- `PROXY_PWD` : Password proxy (optionnel, avec PROXY_HOST)
- `HTTP_PROXY` / `HTTPS_PROXY` : Variables système standard (auto-détection)

### Fichiers générés (non versionnés)
- `default.log` : Journal des opérations
- `*.out` : Résultats CSV

## Améliorations possibles

- [x] ~~Ajouter des arguments CLI (argparse)~~
- [x] ~~Rendre le proxy configurable sans variables d'environnement~~
- [x] ~~Optimiser les performances (rate limiter, backoff, cache proxy)~~
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
- Le rate limiter fait le sleep hors du lock pour permettre le parallélisme
- Proxy configuration mise en cache via `get_proxies_cached()` pour performance
- Backoff configurable via CLI (`--initial-delay`, `--backoff-multiplier`, `--max-delay`)
