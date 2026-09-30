import json
from datetime import date
from pathlib import Path

import cv2
from ultralytics import YOLO



def contar(resultados):
    tp = sum(1 for clase, detecta in resultados if clase == "fractura" and detecta)
    fn = sum(1 for clase, detecta in resultados if clase == "fractura" and not detecta)
    fp = sum(1 for clase, detecta in resultados if clase == "no_fractura" and detecta)
    tn = sum(1 for clase, detecta in resultados if clase == "no_fractura" and not detecta)
    return {
        "TP": tp,
        "FN": fn,
        "FP": fp,
        "TN": tn,
        "sensibilidad": round(tp / (tp + fn), 4),
        "especificidad": round(tn / (tn + fp), 4),
    }


if __name__ == "__main__":
    pesos = "modelo/v1r/weights/best.pt"
    umbral = 0.22
    modelo = YOLO(pesos)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    carpeta = Path("datos/pediurf/recortes")

    imagenes = []
    casos = {}
    for clase in ["fractura", "no_fractura"]:
        for ruta in sorted((carpeta / clase).glob("*.png")):
            imagen = cv2.imread(str(ruta), cv2.IMREAD_GRAYSCALE)
            imagen = clahe.apply(imagen)
            imagen = cv2.cvtColor(imagen, cv2.COLOR_GRAY2BGR)
            resultado = modelo.predict(imagen, conf=umbral, verbose=False)[0]
            detecta = len(resultado.boxes) > 0
            imagenes.append((clase, detecta))

            caso = (clase, ruta.stem.replace("_front", "").replace("_side", ""))
            if caso not in casos:
                casos[caso] = False
            if detecta:
                casos[caso] = True

    por_caso = contar([(clase, detecta) for (clase, _), detecta in casos.items()])
    por_imagen = contar(imagenes)

    resultado = {
        "pesos": pesos,
        "fecha": str(date.today()),
        "umbral": umbral,
        "n_casos": len(casos),
        "n_imagenes": len(imagenes),
        "por_caso": por_caso,
        "por_imagen": por_imagen,
    }

    print("por caso:", por_caso)
    print("por imagen:", por_imagen)

    Path("modelo/resultados/metricas_externo.json").write_text(json.dumps(resultado, indent=2))
