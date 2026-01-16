# Version initiale du requeteur. Plus rustique, mais pas forcément moins efficace
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import re
import time
from datetime import datetime

WORKERS = 10

# Proxy settings
proxies = {
    "http": f"http://{os.getenv("PROXY_USER")}:{os.getenv("PROXY_PWD")}@{os.getenv("PROXY_HOST")}",
    "https": f"http://{os.getenv("PROXY_USER")}:{os.getenv("PROXY_PWD")}@{os.getenv("PROXY_HOST")}",
}


def log(s, filename="default.log"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filename, "a", encoding="utf-8") as f:
        print(f"[{timestamp}] {s}")
        f.write(f"[{timestamp}] {s}\n")


def out(s, filename="default.out.csv", mode="a"):

    with open(filename, mode, encoding="utf-8") as f:
        print(s)
        f.write(f"{s}\n")


def computeVAT(siren) -> str:
    """
    Construit un n° de TVA intracommunautaire français à partir d'un SIREN valide

    Args:
        siren (str): un siren bien construit

    Returns:
        string: le n° de TVA
    """

    # Vérifier que le SIREN contient exactement 9 chiffres
    if not siren.isdigit() or len(siren) != 9:
        raise ValueError("Le SIREN doit contenir exactement 9 chiffres")

    # Convertir le SIREN en entier pour les calculs
    siren_int = int(siren)

    # Calcul de la clé de contrôle
    # Formule : (12 + 3 * (SIREN modulo 97)) modulo 97
    cle = (12 + 3 * (siren_int % 97)) % 97

    # Formater la clé sur 2 chiffres
    cle_formatee = f"{cle:02d}"

    # Construire le numéro de TVA complet
    numero_tva = f"FR{cle_formatee}{siren}"

    return numero_tva


def hasValidVat(siren, max_attempts=50, initial_delay=0.1, multiplier=1.2):
    delay = initial_delay
    # URL de l'api de vérification
    url = "http://ec.europa.eu/taxation_customs/vies/rest-api/ms/FR/vat/"  # https marche aussi
    # url = "http://api.vatcomply.com/vat?vat_number="

    # On construit l'url avec le numéro de TVA
    url = url + computeVAT(siren)

    # Validation en ligne
    for attempt in range(max_attempts):
        try:
            # invoke api
            response = requests.get(url, proxies=proxies, timeout=90)
            data = response.json()  # Assuming response is JSON

            error = data.get("error", data.get("userError", None))

            # if error retry
            if (error and error != "VALID" and error != "INVALID") or (
                response.status_code != 200
            ):
                print(".", end="", flush=True)
                # print(response.status_code, error)
                # print(data)
                time.sleep(delay)
                delay = delay * multiplier
                continue

            isValid = data.get("valid", data.get("isValid", None))

            if isValid == None:
                print("None:", data)
                print("Response Status Code:", response.status_code)

            return {"siren": siren, "has_vat": isValid}

        except requests.exceptions.ProxyError as e:
            print("Proxy error:", e)
            time.sleep(10)
            continue
        except requests.exceptions.RequestException as e:
            print("Request failed:", e)
            time.sleep(5)
            continue
        except Exception as e:
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {e}")
            continue

    print("FAIL!!!!")


def processID(id: str):
    siren = id.strip()
    return hasValidVat(siren)


def processFile(infilename):
    total = 0
    resultats = []

    print(proxies)

    log(
        f"--------------------------------------------------------------------------------------------"
    )
    log(f"Début traitement fichier {infilename} ({WORKERS} workers)")
    start = time.time()
    outfilename = infilename + ".out"

    out(
        f"siren;has_vat",
        outfilename,
        mode="w",
    )

    """Lit les sirens depuis un fichier texte (un siren par ligne)"""
    with open(infilename, "r") as f:
        sirens = [line.strip() for line in f if line.strip()]

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(processID, siren): siren for siren in sirens}

        for future in as_completed(futures):
            total += 1
            r = future.result()
            # print("Future: ", r)
            out(
                f"{r["siren"]};{r["has_vat"]}",
                outfilename,
            )
            print(r)
            resultats.append(r)
    end = time.time()

    log(
        f"Fin traitement de {total} SIRENs du fichier {infilename} (Temps de traitement unitaire moyen {(end-start)/total:.2f}s)"
    )


# hasValidVat("380129866")  # Orange
# hasValidVat("443061841")  # Google

processFile("sirens.txt")
