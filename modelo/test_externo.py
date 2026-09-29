from pathlib import Path

import cv2
from ultralytics import YOLO

if __name__ == "__main__":
    modelo = YOLO("modelo/v1r/weights/best.pt")
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    carpeta = Path("datos/pediurf/recortes")

    tp = fn = fp = tn = 0
    for clase in ["fractura", "no_fractura"]:
        casos = {}
        for ruta in sorted((carpeta / clase).glob("*.png")):
            imagen = cv2.imread(str(ruta), cv2.IMREAD_GRAYSCALE)
            imagen = clahe.apply(imagen)
            imagen = cv2.cvtColor(imagen, cv2.COLOR_GRAY2BGR)
            resultado = modelo.predict(imagen, conf=0.22, verbose=False)[0]
            detecta = len(resultado.boxes) > 0

            caso = ruta.stem.replace("_front", "").replace("_side", "")
            if caso not in casos:
                casos[caso] = False
            if detecta:
                casos[caso] = True

        for detecta in casos.values():
            if clase == "fractura" and detecta:
                tp += 1
            elif clase == "fractura":
                fn += 1
            elif detecta:
                fp += 1
            else:
                tn += 1

    print("sensibilidad:", tp / (tp + fn))
    print("especificidad:", tn / (tn + fp))
    print("TP:", tp, "FN:", fn, "FP:", fp, "TN:", tn)
