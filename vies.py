#!/usr/bin/env python3
"""
VIES - Validation de TVA Intracommunautaire
============================================

Outil de validation en masse de numéros SIREN français contre l'API VIES
(VAT Information Exchange System) de l'Union Européenne.

Description:
    Ce script permet de vérifier si des entreprises françaises sont enregistrées
    à la TVA intracommunautaire en validant leurs numéros SIREN contre l'API
    officielle de la Commission Européenne.

Fonctionnalités:
    - Conversion automatique SIREN → numéro de TVA français
    - Validation en masse avec traitement parallèle (multi-thread)
    - Rate limiting configurable pour respecter les limites de l'API
    - Gestion robuste des erreurs avec retry et backoff exponentiel
    - Support proxy pour environnements d'entreprise
    - Mode dry-run pour tester sans appeler l'API

Usage:
    python vies.py <fichier_sirens> [options]

Exemples:
    python vies.py sirens.txt                    # Validation simple
    python vies.py sirens.txt --dry-run          # Test sans appel API
    python vies.py sirens.txt -o result.csv -v   # Sortie personnalisée, mode verbeux
    python vies.py sirens.txt -r 10 -w 5         # 10 req/min, 5 threads

Auteur: Jean-Paul Gavini (Sandjab) - https://github.com/Sandjab
Date: Janvier 2026
Licence: Libre
"""

import argparse
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
import threading

import requests


# =============================================================================
# CONSTANTES ET CONFIGURATION
# =============================================================================

# Valeurs par défaut pour les options CLI
DEFAULT_WORKERS = 10          # Nombre de threads concurrents
DEFAULT_RATE_LIMIT = 300      # Requêtes par minute maximum (0 = désactivé)
DEFAULT_TIMEOUT = 90          # Timeout HTTP en secondes
DEFAULT_MAX_RETRIES = 50      # Nombre max de tentatives par SIREN
DEFAULT_LOG_FILE = "default.log"  # Fichier de log par défaut

# Configuration du throttling (backoff exponentiel avec jitter)
# Valeurs optimisées pour un bon équilibre entre performance et robustesse
THROTTLE_INITIAL_DELAY = 0.2  # Délai initial en secondes (réduit pour récupération rapide)
THROTTLE_MAX_DELAY = 30.0     # Délai maximum en secondes
THROTTLE_MULTIPLIER = 1.5     # Facteur multiplicatif (progression modérée)
THROTTLE_JITTER = 0.3         # Facteur de jitter (±30% du délai calculé)

# Configuration globale du script (mise à jour par les arguments CLI)
# Cette approche permet aux fonctions d'accéder à la config sans la passer en paramètre
config = {
    "verbose": False,         # Affichage détaillé
    "quiet": False,           # Mode silencieux (pas de sortie console)
    "use_proxy": True,        # Utilisation du proxy d'entreprise
    "timeout": DEFAULT_TIMEOUT,
    "max_retries": DEFAULT_MAX_RETRIES,
    "rate_limit": DEFAULT_RATE_LIMIT,
    # Configuration du backoff (paramétrable via CLI)
    "initial_delay": THROTTLE_INITIAL_DELAY,
    "backoff_multiplier": THROTTLE_MULTIPLIER,
    "max_delay": THROTTLE_MAX_DELAY,
}


# =============================================================================
# RATE LIMITING
# =============================================================================

class RateLimiter:
    """
    Limiteur de débit thread-safe pour contrôler la fréquence des requêtes API.

    Cette classe implémente un algorithme simple de limitation basé sur l'intervalle
    minimum entre les appels. Elle est thread-safe grâce à l'utilisation d'un Lock.

    Algorithme:
        - Calcule l'intervalle minimum entre appels: 60s / calls_per_minute
        - Avant chaque requête, vérifie le temps écoulé depuis le dernier appel
        - Si l'intervalle n'est pas respecté, attend le temps nécessaire

    Attributes:
        calls_per_minute (int): Nombre maximum d'appels autorisés par minute.
        min_interval (float): Intervalle minimum en secondes entre deux appels.
        last_call (float): Timestamp du dernier appel effectué.
        lock (threading.Lock): Verrou pour la synchronisation entre threads.

    Example:
        >>> limiter = RateLimiter(30)  # 30 requêtes/minute max
        >>> limiter.wait()  # Attend si nécessaire avant la requête
        >>> response = requests.get(url)
    """

    def __init__(self, calls_per_minute: int):
        """
        Initialise le rate limiter avec le nombre d'appels autorisés par minute.

        Args:
            calls_per_minute (int): Nombre maximum de requêtes autorisées par minute.
                                   Valeur <= 0 désactive le rate limiting.
                                   Exemple: 300 signifie max 300 req/min,
                                   soit un intervalle minimum de 0.2 secondes entre appels.
        """
        self.calls_per_minute = calls_per_minute
        # Désactiver le rate limiting si calls_per_minute <= 0
        if calls_per_minute <= 0:
            self.min_interval = 0.0
        else:
            self.min_interval = 60.0 / calls_per_minute  # Ex: 60/300 = 0.2 secondes
        self.last_call = 0.0  # Timestamp du dernier appel (0 = jamais appelé)
        self.lock = threading.Lock()  # Verrou pour thread-safety

    def wait(self):
        """
        Attend si nécessaire pour respecter la limite de débit.

        Cette méthode est thread-safe. Elle réserve un "slot" de temps pour
        la requête courante, puis attend hors du lock pour permettre aux
        autres threads de réserver leurs propres slots en parallèle.

        Algorithme:
            1. Acquiert le lock
            2. Calcule quand ce thread peut faire sa requête
            3. Réserve ce slot en mettant à jour last_call
            4. Libère le lock
            5. Attend si nécessaire (hors du lock)

        Cela permet à plusieurs threads de réserver des slots simultanément
        au lieu de s'attendre mutuellement, améliorant significativement
        les performances en multi-thread.
        """
        # Si rate limiting désactivé, retourner immédiatement
        if self.min_interval == 0:
            return

        with self.lock:
            now = time.time()
            # Calculer quand ce thread peut faire sa requête
            next_allowed = self.last_call + self.min_interval
            sleep_time = max(0, next_allowed - now)
            # Réserver le slot pour ce thread (avant de libérer le lock)
            self.last_call = now + sleep_time

        # Attendre hors du lock - permet aux autres threads de réserver
        if sleep_time > 0:
            time.sleep(sleep_time)


# Instance globale du rate limiter, initialisée dans main()
rate_limiter = None

# Cache pour la configuration proxy (évite de recalculer pour chaque requête)
_cached_proxies = None
_proxies_initialized = False


# =============================================================================
# THROTTLING (Backoff exponentiel avec jitter)
# =============================================================================

def calculate_backoff_delay(attempt: int) -> float:
    """
    Calcule le délai d'attente avant un retry avec backoff exponentiel et jitter.

    L'algorithme combine:
        - Backoff exponentiel: délai = initial × multiplier^attempt
        - Délai plafonné: min(délai_calculé, max_delay)
        - Jitter aléatoire: ±THROTTLE_JITTER% pour éviter les "thundering herd"

    Le jitter est important en multi-thread pour éviter que tous les threads
    retryent exactement au même moment après une erreur serveur.

    Les paramètres sont lus depuis la configuration globale (modifiable via CLI):
        - config["initial_delay"]: délai initial (--initial-delay)
        - config["backoff_multiplier"]: multiplicateur (--backoff-multiplier)
        - config["max_delay"]: délai maximum (--max-delay)

    Args:
        attempt (int): Numéro de la tentative (0 pour la première, 1 pour la deuxième, etc.)

    Returns:
        float: Délai en secondes avant le prochain retry.

    Example:
        >>> calculate_backoff_delay(0)  # ~0.2s (±jitter) avec config par défaut
        >>> calculate_backoff_delay(1)  # ~0.3s (±jitter)
        >>> calculate_backoff_delay(5)  # ~1.5s (±jitter)
        >>> calculate_backoff_delay(15) # ~30.0s (plafonné)
    """
    # Lecture des paramètres depuis la config (permet le tuning via CLI)
    initial_delay = config.get("initial_delay", THROTTLE_INITIAL_DELAY)
    multiplier = config.get("backoff_multiplier", THROTTLE_MULTIPLIER)
    max_delay = config.get("max_delay", THROTTLE_MAX_DELAY)

    # Calcul du délai de base avec backoff exponentiel
    base_delay = initial_delay * (multiplier ** attempt)

    # Plafonner au délai maximum
    capped_delay = min(base_delay, max_delay)

    # Ajouter du jitter aléatoire (±THROTTLE_JITTER%)
    jitter_range = capped_delay * THROTTLE_JITTER
    jittered_delay = capped_delay + random.uniform(-jitter_range, jitter_range)

    # S'assurer que le délai reste positif
    return max(0.1, jittered_delay)


def _rate_limited_request(url: str, proxies: dict, timeout: int) -> requests.Response:
    """
    Effectue une requête HTTP GET avec rate limiting.

    Cette fonction wrapper applique le rate limiting avant chaque requête
    pour éviter de surcharger l'API VIES.

    Args:
        url (str): URL complète de la requête API.
        proxies (dict | None): Configuration proxy au format requests.
                              Ex: {"http": "http://proxy:8080", "https": "..."}
                              None si pas de proxy.
        timeout (int): Timeout de la requête en secondes.

    Returns:
        requests.Response: Objet Response de la requête HTTP.

    Raises:
        requests.exceptions.RequestException: En cas d'erreur réseau.
        requests.exceptions.Timeout: Si le timeout est dépassé.
    """
    # Appliquer le rate limiting si configuré
    if rate_limiter:
        rate_limiter.wait()

    return requests.get(url, proxies=proxies, timeout=timeout)


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def get_proxies() -> dict | None:
    """
    Construit la configuration proxy à partir des variables d'environnement.

    Le proxy est configuré via trois variables d'environnement:
        - PROXY_USER: Nom d'utilisateur pour l'authentification proxy
        - PROXY_PWD: Mot de passe pour l'authentification proxy
        - PROXY_HOST: Adresse du serveur proxy au format <ip>:<port>

    Returns:
        dict | None: Dictionnaire de configuration proxy pour requests,
                    ou None si le proxy est désactivé ou non configuré.

    Example:
        >>> os.environ["PROXY_USER"] = "user"
        >>> os.environ["PROXY_PWD"] = "pass"
        >>> os.environ["PROXY_HOST"] = "proxy.example.com:8080"
        >>> get_proxies()
        {'http': 'http://user:pass@proxy.example.com:8080', 'https': '...'}
    """
    # Vérifier si le proxy est activé dans la config
    if not config["use_proxy"]:
        return None

    # Récupérer les credentials et l'hôte depuis l'environnement
    username = os.getenv("PROXY_USER")
    password = os.getenv("PROXY_PWD")
    proxy_host = os.getenv("PROXY_HOST")

    # Si les paramètres ne sont pas définis, pas de proxy
    if not username or not password or not proxy_host:
        return None

    # Construire l'URL du proxy avec authentification
    proxy_url = f"http://{username}:{password}@{proxy_host}"

    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def get_proxies_cached() -> dict | None:
    """
    Retourne la configuration proxy mise en cache.

    Cette fonction calcule la configuration proxy une seule fois au premier
    appel, puis retourne la valeur en cache pour les appels suivants.
    Cela évite d'appeler os.getenv() pour chaque requête, améliorant
    les performances lors du traitement en masse.

    Returns:
        dict | None: Configuration proxy mise en cache.

    Note:
        Le cache est réinitialisé si config["use_proxy"] change.
        Utiliser invalidate_proxy_cache() pour forcer un recalcul.
    """
    global _cached_proxies, _proxies_initialized

    if not _proxies_initialized:
        _cached_proxies = get_proxies()
        _proxies_initialized = True

    return _cached_proxies


def invalidate_proxy_cache() -> None:
    """
    Invalide le cache proxy pour forcer un recalcul au prochain appel.

    Utile si les variables d'environnement ou config["use_proxy"] changent.
    """
    global _proxies_initialized
    _proxies_initialized = False


def sanitize_proxy_config(proxies: dict | None) -> str:
    """
    Retourne une représentation sécurisée de la configuration proxy.

    Masque le mot de passe dans l'URL pour éviter de l'exposer dans les logs.
    Le format retourné est: http://user:****@host:port

    Args:
        proxies (dict | None): Configuration proxy au format requests,
                               ou None si pas de proxy.

    Returns:
        str: Représentation sécurisée de la config proxy, ou "None" si désactivé.

    Example:
        >>> proxies = {"http": "http://user:secret@proxy:8080", ...}
        >>> sanitize_proxy_config(proxies)
        'http://user:****@proxy:8080'
    """
    if proxies is None:
        return "None (proxy désactivé)"

    # Extraire l'URL HTTP pour l'affichage
    proxy_url = proxies.get("http", "")

    # Masquer le mot de passe: http://user:password@host -> http://user:****@host
    sanitized = re.sub(r'://([^:]+):([^@]+)@', r'://\1:****@', proxy_url)

    return sanitized


def log(message: str, filename: str = DEFAULT_LOG_FILE) -> None:
    """
    Journalise un message avec horodatage dans un fichier et sur la console.

    Format du message: [YYYY-MM-DD HH:MM:SS] message

    Args:
        message (str): Message à journaliser.
        filename (str): Chemin du fichier de log. Défaut: "default.log".

    Note:
        - L'affichage console est désactivé en mode quiet (config["quiet"]).
        - Le fichier est ouvert en mode append (ajout).
        - L'encodage UTF-8 est utilisé pour supporter les caractères français.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] {message}"

    # Afficher sur la console sauf en mode quiet
    if not config["quiet"]:
        print(formatted_message)

    # Écrire dans le fichier de log
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"{formatted_message}\n")


def out(line: str, filename: str, mode: str = "a") -> None:
    """
    Écrit une ligne dans le fichier de sortie CSV et sur la console.

    Args:
        line (str): Ligne à écrire (sans retour à la ligne).
        filename (str): Chemin du fichier de sortie.
        mode (str): Mode d'ouverture du fichier. "a" pour append, "w" pour écraser.

    Note:
        L'affichage console est désactivé en mode quiet (config["quiet"]).
    """
    # Afficher sur la console sauf en mode quiet
    if not config["quiet"]:
        print(line)

    # Écrire dans le fichier
    with open(filename, mode, encoding="utf-8") as f:
        f.write(f"{line}\n")


def verbose_print(message: str) -> None:
    """
    Affiche un message uniquement si le mode verbose est activé.

    Le message est préfixé par "[VERBOSE]" pour le distinguer des messages normaux.

    Args:
        message (str): Message à afficher.

    Note:
        Le message n'est affiché que si:
        - config["verbose"] est True ET
        - config["quiet"] est False
    """
    if config["verbose"] and not config["quiet"]:
        print(f"[VERBOSE] {message}")


# =============================================================================
# LOGIQUE MÉTIER - CALCUL ET VALIDATION TVA
# =============================================================================

def computeVAT(siren: str) -> str:
    """
    Calcule le numéro de TVA intracommunautaire français à partir d'un SIREN.

    Le numéro de TVA français est composé de:
        - "FR" (code pays)
        - 2 chiffres de clé de contrôle
        - 9 chiffres du SIREN

    Formule de calcul de la clé:
        clé = (12 + 3 × (SIREN mod 97)) mod 97

    Cette formule est la formule officielle de l'administration française
    pour calculer la clé de contrôle du numéro de TVA.

    Args:
        siren (str): Numéro SIREN de 9 chiffres exactement.
                    Exemple: "380129866" (Orange)

    Returns:
        str: Numéro de TVA complet au format "FRXXYYYYYYYYY".
             Exemple: "FR38380129866"

    Raises:
        ValueError: Si le SIREN ne contient pas exactement 9 chiffres.

    Example:
        >>> computeVAT("380129866")
        'FR38380129866'
        >>> computeVAT("443061841")  # Google France
        'FR07443061841'
    """
    # Validation: le SIREN doit contenir exactement 9 chiffres
    if not siren.isdigit() or len(siren) != 9:
        raise ValueError("Le SIREN doit contenir exactement 9 chiffres")

    # Conversion en entier pour le calcul
    siren_int = int(siren)

    # Calcul de la clé de contrôle selon la formule officielle
    # Source: https://fr.wikipedia.org/wiki/Code_Insee#Num%C3%A9ro_de_TVA
    cle = (12 + 3 * (siren_int % 97)) % 97

    # Formatage: la clé doit être sur 2 chiffres (avec zéro devant si nécessaire)
    cle_formatee = f"{cle:02d}"

    # Construction du numéro de TVA complet
    numero_tva = f"FR{cle_formatee}{siren}"

    return numero_tva


def hasValidVat(siren: str) -> dict:
    """
    Valide un numéro SIREN contre l'API VIES de l'Union Européenne.

    Cette fonction:
        1. Calcule le numéro de TVA à partir du SIREN
        2. Appelle l'API VIES pour vérifier si ce numéro est valide
        3. Gère les erreurs avec retry et backoff exponentiel + jitter

    L'API VIES peut retourner des erreurs temporaires (maintenance, surcharge).
    Le mécanisme de retry avec backoff exponentiel permet de gérer ces cas
    en réessayant avec un délai croissant, plafonné à THROTTLE_MAX_DELAY.

    Le jitter aléatoire évite les "thundering herd" (tous les threads qui
    retryent au même moment après une erreur serveur).

    Args:
        siren (str): Numéro SIREN à valider (9 chiffres).

    Returns:
        dict: Dictionnaire avec les clés:
            - "siren" (str): Le SIREN validé
            - "has_vat" (bool | None): True si valide, False si invalide,
                                       None si impossible de déterminer

    Note:
        - Le rate limiting est appliqué via _rate_limited_request()
        - Le throttling utilise calculate_backoff_delay() pour tous les types d'erreurs
        - Les paramètres de retry sont configurés via config[] et THROTTLE_*
    """
    # Récupération des paramètres depuis la config globale
    max_attempts = config["max_retries"]
    timeout = config["timeout"]
    proxies = get_proxies_cached()

    # Construction de l'URL de l'API VIES
    # Format: https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{COUNTRY}/vat/{VAT_NUMBER}
    base_url = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/FR/vat/"
    url = base_url + computeVAT(siren)

    verbose_print(f"Validation de {siren} -> {computeVAT(siren)}")

    # Boucle de retry avec backoff exponentiel unifié
    for attempt in range(max_attempts):
        try:
            # Appel API avec rate limiting
            response = _rate_limited_request(url, proxies, timeout)
            data = response.json()

            # Vérification des erreurs dans la réponse
            # L'API peut retourner "error" ou "userError" selon le type d'erreur
            error = data.get("error", data.get("userError", None))

            # Si erreur temporaire (ni VALID ni INVALID), retry avec backoff
            if (error and error != "VALID" and error != "INVALID") or (
                response.status_code != 200
            ):
                delay = calculate_backoff_delay(attempt)
                if not config["quiet"]:
                    print(".", end="", flush=True)  # Indicateur de retry
                verbose_print(
                    f"Tentative {attempt + 1}/{max_attempts} - "
                    f"Erreur API: {error} - Attente: {delay:.1f}s"
                )
                time.sleep(delay)
                continue

            # Extraction du résultat de validation
            # L'API peut retourner "valid" ou "isValid" selon la version
            isValid = data.get("valid", data.get("isValid", None))

            if isValid is None:
                verbose_print(f"Réponse inattendue: {data}")

            return {"siren": siren, "has_vat": isValid}

        except requests.exceptions.ProxyError as e:
            # Erreur proxy: utiliser le backoff unifié
            delay = calculate_backoff_delay(attempt)
            verbose_print(f"Erreur proxy (tentative {attempt + 1}): {e} - Attente: {delay:.1f}s")
            if not config["quiet"]:
                print("P", end="", flush=True)  # P = Proxy error
            time.sleep(delay)
            continue

        except requests.exceptions.RequestException as e:
            # Autres erreurs réseau: utiliser le backoff unifié
            delay = calculate_backoff_delay(attempt)
            verbose_print(f"Erreur réseau (tentative {attempt + 1}): {e} - Attente: {delay:.1f}s")
            if not config["quiet"]:
                print("R", end="", flush=True)  # R = Request error
            time.sleep(delay)
            continue

        except Exception as e:
            # Erreur inattendue: utiliser le backoff unifié
            delay = calculate_backoff_delay(attempt)
            verbose_print(f"Erreur {type(e).__name__} (tentative {attempt + 1}): {e} - Attente: {delay:.1f}s")
            time.sleep(delay)
            continue

    # Échec après toutes les tentatives
    if not config["quiet"]:
        print(f"\nÉCHEC pour {siren} après {max_attempts} tentatives")

    return {"siren": siren, "has_vat": None}


def processID(id: str) -> dict:
    """
    Traite un identifiant SIREN (wrapper pour ThreadPoolExecutor).

    Cette fonction nettoie l'entrée et appelle hasValidVat().
    Elle est conçue pour être utilisée avec ThreadPoolExecutor.submit().

    Args:
        id (str): Identifiant SIREN, potentiellement avec espaces.

    Returns:
        dict: Résultat de hasValidVat() avec "siren" et "has_vat".
    """
    siren = id.strip()  # Nettoyer les espaces
    return hasValidVat(siren)


# =============================================================================
# MODES D'EXÉCUTION
# =============================================================================

def dry_run(infilename: str) -> None:
    """
    Mode dry-run: affiche les SIRENs et leurs TVA calculés sans appeler l'API.

    Ce mode permet de:
        - Vérifier le format des SIRENs dans le fichier d'entrée
        - Visualiser les numéros de TVA qui seraient générés
        - Identifier les SIRENs invalides avant un traitement réel

    Args:
        infilename (str): Chemin du fichier contenant les SIRENs (un par ligne).

    Output:
        Affiche un tableau avec:
        - SIREN: le numéro SIREN lu
        - TVA Calculé: le numéro de TVA généré (ou N/A si erreur)
        - Statut: OK ou ERREUR avec le message d'erreur
    """
    print("=" * 60)
    print("MODE DRY-RUN - Aucun appel API ne sera effectué")
    print("=" * 60)
    print()

    # Lecture du fichier d'entrée
    with open(infilename, "r") as f:
        sirens = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]

    # En-tête du tableau
    print(f"{'SIREN':<12} {'TVA Calculé':<18} {'Statut'}")
    print("-" * 45)

    valid_count = 0
    invalid_count = 0

    # Traitement de chaque SIREN
    for siren in sirens:
        try:
            tva = computeVAT(siren)
            print(f"{siren:<12} {tva:<18} OK")
            valid_count += 1
        except ValueError as e:
            print(f"{siren:<12} {'N/A':<18} ERREUR: {e}")
            invalid_count += 1

    # Résumé
    print("-" * 45)
    print(f"Total: {len(sirens)} SIRENs ({valid_count} valides, {invalid_count} invalides)")
    print()
    print("Pour exécuter réellement, relancez sans --dry-run")


def processFile(infilename: str, outfilename: str, logfilename: str,
                workers: int, rate_limit: int) -> None:
    """
    Traite un fichier de SIRENs en parallèle avec validation API.

    Cette fonction orchestre le traitement en masse:
        1. Lit le fichier d'entrée
        2. Lance les validations en parallèle (ThreadPoolExecutor)
        3. Écrit les résultats dans le fichier de sortie CSV
        4. Journalise les statistiques

    Le rate limiting global est géré par la classe RateLimiter,
    ce qui garantit le respect des limites de l'API même avec plusieurs threads.

    Args:
        infilename (str): Chemin du fichier d'entrée (un SIREN par ligne).
        outfilename (str): Chemin du fichier de sortie CSV.
        logfilename (str): Chemin du fichier de log.
        workers (int): Nombre de threads concurrents.
        rate_limit (int): Limite de requêtes par minute (informatif,
                         le rate limiting réel est géré par RateLimiter).

    Output Files:
        - outfilename: CSV avec colonnes "siren;has_vat"
        - logfilename: Journal des opérations avec timestamps
    """
    total = 0
    resultats = []
    proxies = get_proxies_cached()

    verbose_print(f"Configuration proxy: {sanitize_proxy_config(proxies)}")

    # Journalisation du début du traitement
    log("-" * 80, logfilename)
    log(f"Début traitement fichier {infilename} ({workers} workers)", logfilename)

    start = time.time()

    # Écriture de l'en-tête CSV
    out("siren;has_vat", outfilename, mode="w")

    # Lecture des SIRENs depuis le fichier
    with open(infilename, "r") as f:
        sirens = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]

    if not config["quiet"]:
        print(f"Traitement de {len(sirens)} SIRENs...")

    # Traitement parallèle avec ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Soumettre toutes les tâches
        futures = {executor.submit(processID, siren): siren for siren in sirens}

        # Collecter les résultats au fur et à mesure
        for future in as_completed(futures):
            total += 1
            r = future.result()

            # Écrire le résultat dans le fichier CSV
            out(f'{r["siren"]};{r["has_vat"]}', outfilename)
            resultats.append(r)

    end = time.time()
    duration = end - start
    avg_time = duration / total if total > 0 else 0

    # Journalisation de la fin du traitement
    log(
        f"Fin traitement de {total} SIRENs du fichier {infilename} "
        f"(Durée: {duration:.2f}s, Moyenne: {avg_time:.2f}s/SIREN)",
        logfilename,
    )

    # Calcul des statistiques
    valid = sum(1 for r in resultats if r["has_vat"] is True)
    invalid = sum(1 for r in resultats if r["has_vat"] is False)
    failed = sum(1 for r in resultats if r["has_vat"] is None)

    # Affichage du résumé
    if not config["quiet"]:
        print()
        print("=" * 40)
        print(f"Résumé: {valid} valides, {invalid} invalides, {failed} échecs")
        print(f"Résultats écrits dans: {outfilename}")
        print("=" * 40)


# =============================================================================
# INTERFACE CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    """
    Parse les arguments de la ligne de commande.

    Returns:
        argparse.Namespace: Objet contenant tous les arguments parsés.

    Arguments parsés:
        - file: Fichier d'entrée (positionnel, requis)
        - output: Fichier de sortie (-o)
        - workers: Nombre de threads (-w)
        - rate_limit: Limite requêtes/minute (-r)
        - log: Fichier de log (--log)
        - dry_run: Mode simulation (--dry-run)
        - verbose: Mode verbeux (-v)
        - quiet: Mode silencieux (-q)
        - no_proxy: Désactiver le proxy (--no-proxy)
        - timeout: Timeout HTTP (--timeout)
        - max_retries: Tentatives max (--max-retries)
    """
    parser = argparse.ArgumentParser(
        prog="vies",
        description="Validation de numéros SIREN français contre l'API VIES de l'UE.",
        epilog="Exemple: python vies.py sirens.txt -o resultats.csv --verbose",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # === Argument positionnel ===
    parser.add_argument(
        "file",
        metavar="FILE",
        help="Fichier d'entrée contenant les SIRENs (un par ligne)",
    )

    # === Options de configuration ===
    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Fichier de sortie CSV (défaut: <input>.out)",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        metavar="N",
        help=f"Nombre de threads concurrents (défaut: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "-r", "--rate-limit",
        type=int,
        default=DEFAULT_RATE_LIMIT,
        metavar="N",
        help=f"Limite de requêtes par minute (défaut: {DEFAULT_RATE_LIMIT})",
    )
    parser.add_argument(
        "--log",
        metavar="FILE",
        default=DEFAULT_LOG_FILE,
        help=f"Fichier de log (défaut: {DEFAULT_LOG_FILE})",
    )

    # === Options de comportement ===
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les TVA calculés sans appeler l'API",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Mode verbeux (affiche plus de détails)",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Mode silencieux (pas de sortie console)",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Désactive le proxy",
    )

    # === Options avancées ===
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        metavar="N",
        help=f"Timeout des requêtes HTTP en secondes (défaut: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        metavar="N",
        help=f"Nombre maximum de tentatives par SIREN (défaut: {DEFAULT_MAX_RETRIES})",
    )

    # === Options de backoff (tuning avancé) ===
    parser.add_argument(
        "--initial-delay",
        type=float,
        default=THROTTLE_INITIAL_DELAY,
        metavar="SEC",
        help=f"Délai initial pour le backoff en secondes (défaut: {THROTTLE_INITIAL_DELAY})",
    )
    parser.add_argument(
        "--backoff-multiplier",
        type=float,
        default=THROTTLE_MULTIPLIER,
        metavar="N",
        help=f"Multiplicateur de backoff exponentiel (défaut: {THROTTLE_MULTIPLIER})",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=THROTTLE_MAX_DELAY,
        metavar="SEC",
        help=f"Délai maximum pour le backoff en secondes (défaut: {THROTTLE_MAX_DELAY})",
    )

    return parser.parse_args()


def main() -> None:
    """
    Point d'entrée principal du script.

    Cette fonction:
        1. Parse les arguments CLI
        2. Valide le fichier d'entrée
        3. Configure les paramètres globaux
        4. Initialise le rate limiter
        5. Lance le mode approprié (dry-run ou traitement normal)
    """
    global rate_limiter

    args = parse_args()

    # Vérification de l'existence du fichier d'entrée
    if not os.path.isfile(args.file):
        print(f"Erreur: le fichier '{args.file}' n'existe pas.", file=sys.stderr)
        sys.exit(1)

    # Configuration globale depuis les arguments CLI
    config["verbose"] = args.verbose
    config["quiet"] = args.quiet
    config["use_proxy"] = not args.no_proxy
    config["timeout"] = args.timeout
    config["max_retries"] = args.max_retries
    config["rate_limit"] = args.rate_limit
    # Configuration du backoff
    config["initial_delay"] = args.initial_delay
    config["backoff_multiplier"] = args.backoff_multiplier
    config["max_delay"] = args.max_delay

    # Initialisation du rate limiter avec la limite configurée
    rate_limiter = RateLimiter(args.rate_limit)
    verbose_print(f"Rate limiter configuré: {args.rate_limit} requêtes/minute")

    # Détermination du fichier de sortie
    outfile = args.output if args.output else f"{args.file}.out"

    # Exécution du mode approprié
    if args.dry_run:
        dry_run(args.file)
        return

    # Traitement normal
    processFile(
        infilename=args.file,
        outfilename=outfile,
        logfilename=args.log,
        workers=args.workers,
        rate_limit=args.rate_limit,
    )


# =============================================================================
# POINT D'ENTRÉE
# =============================================================================

if __name__ == "__main__":
    main()
