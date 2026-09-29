import csv
import random
import shutil
from pathlib import Path

origen = Path("datos/pediurf/original/PediURF")
destino = Path("datos/pediurf/muestra")

fracturas = sorted(origen.glob("*/Distal*/*"))
no_fracturas = sorted(origen.glob("*/Midshaft*/*")) + sorted(origen.glob("*/Proximal*/*"))

random.seed(0)
random.shuffle(fracturas)
random.shuffle(no_fracturas)

filas = []
for clase, casos in [("fractura", fracturas), ("no_fractura", no_fracturas)]:
    for orden, caso in enumerate(casos[:999], start=1):
        carpeta = destino / clase if orden <= 500 else destino / "reserva" / clase
        carpeta.mkdir(parents=True, exist_ok=True)
        for vista in ["front", "side"]:
            shutil.copy(caso / f"{vista}.jpg", carpeta / f"{orden:03d}_{caso.name}_{vista}.jpg")
        filas.append([clase, orden, caso.name, caso.parent.name.split()[0], caso.parent.parent.name])

with open(destino / "muestra.csv", "w", newline="") as f:
    escritor = csv.writer(f)
    escritor.writerow(["clase", "orden", "caso", "region", "split"])
    escritor.writerows(filas)
