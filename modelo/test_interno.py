import json
import math
from datetime import date
from pathlib import Path

from sklearn.metrics import average_precision_score, roc_auc_score
from ultralytics import YOLO


def wilson(aciertos, total):
    p = aciertos / total
    z = 1.96
    centro = (p + z * z / (2 * total)) / (1 + z * z / total)
    margen = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [round(centro - margen, 4), round(centro + margen, 4)]


if __name__ == "__main__":
    pesos = "modelo/v1r/weights/best.pt"
    umbral = 0.22
    modelo = YOLO(pesos)

    metricas = modelo.val(data="modelo/fracturas.yaml", split="test", workers=0)

    imagenes = sorted(Path("datos/grazpedwri/procesado/images/test").glob("*.png"))
    etiquetas = Path("datos/grazpedwri/procesado/labels/test")

    verdad = []
    puntajes = []
    cajas = 0
    for imagen in imagenes:
        resultado = modelo.predict(str(imagen), conf=0.01, verbose=False)[0]
        puntaje = float(resultado.boxes.conf.max()) if len(resultado.boxes) > 0 else 0.0
        lineas = (etiquetas / (imagen.stem + ".txt")).read_text().split("\n")
        lineas = [l for l in lineas if l.strip()]
        verdad.append(1 if lineas else 0)
        puntajes.append(puntaje)
        cajas += len(lineas)

    tp = sum(1 for v, p in zip(verdad, puntajes) if v == 1 and p >= umbral)
    fn = sum(1 for v, p in zip(verdad, puntajes) if v == 1 and p < umbral)
    fp = sum(1 for v, p in zip(verdad, puntajes) if v == 0 and p >= umbral)
    tn = sum(1 for v, p in zip(verdad, puntajes) if v == 0 and p < umbral)

    resultado = {
        "pesos": pesos,
        "fecha": str(date.today()),
        "umbral": umbral,
        "n_imagenes": len(imagenes),
        "n_instancias": cajas,
        "n_positivos": tp + fn,
        "n_negativos": fp + tn,
        "mAP50": round(float(metricas.box.map50), 4),
        "mAP50_95": round(float(metricas.box.map), 4),
        "precision": round(float(metricas.box.mp), 4),
        "recall": round(float(metricas.box.mr), 4),
        "TP": tp,
        "FN": fn,
        "FP": fp,
        "TN": tn,
        "sensibilidad": round(tp / (tp + fn), 4),
        "sensibilidad_ic95": wilson(tp, tp + fn),
        "especificidad": round(tn / (tn + fp), 4),
        "especificidad_ic95": wilson(tn, tn + fp),
        "vpp": round(tp / (tp + fp), 4),
        "vpp_ic95": wilson(tp, tp + fp),
        "auc_roc": round(roc_auc_score(verdad, puntajes), 4),
        "ap": round(average_precision_score(verdad, puntajes), 4),
    }

    for clave, valor in resultado.items():
        print(clave, ":", valor)

    Path("modelo/resultados/metricas.json").write_text(json.dumps(resultado, indent=2))
