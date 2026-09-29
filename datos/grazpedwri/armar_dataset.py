from pathlib import Path

import cv2
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

if __name__ == "__main__":
    original = Path("datos/grazpedwri/original/_import_zip")
    procesado = Path("datos/grazpedwri/procesado")
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    tabla = pd.read_csv(original / "dataset.csv")
    tabla["fractura"] = (tabla["fracture_visible"] == 1).astype(int)

    division = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=42)
    indices_train, indices_resto = next(division.split(tabla, tabla["fractura"], groups=tabla["patient_id"]))
    resto = tabla.iloc[indices_resto]

    division = GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=42)
    indices_val, indices_test = next(division.split(resto, resto["fractura"], groups=resto["patient_id"]))

    tabla["split"] = ""
    tabla.loc[tabla.index[indices_train], "split"] = "train"
    tabla.loc[resto.index[indices_val], "split"] = "val"
    tabla.loc[resto.index[indices_test], "split"] = "test"

    for split in ["train", "val", "test"]:
        (procesado / "images" / split).mkdir(parents=True, exist_ok=True)
        (procesado / "labels" / split).mkdir(parents=True, exist_ok=True)

    for _, fila in tabla.iterrows():
        nombre = fila["filestem"]
        imagen = None
        for parte in ["images_part1", "images_part2", "images_part3", "images_part4"]:
            ruta = original / parte / f"{nombre}.png"
            if ruta.exists():
                imagen = cv2.imread(str(ruta), cv2.IMREAD_GRAYSCALE)
        if imagen is None:
            continue

        cv2.imwrite(str(procesado / "images" / fila["split"] / f"{nombre}.png"), clahe.apply(imagen))

        cajas = []
        etiqueta = original / "folder_structure/yolov5/labels" / f"{nombre}.txt"
        if etiqueta.exists():
            for linea in etiqueta.read_text().splitlines():
                partes = linea.split()
                if partes and partes[0] == "3":
                    cajas.append(" ".join(["0"] + partes[1:]))
        texto = "\n".join(cajas) + "\n" if cajas else ""
        (procesado / "labels" / fila["split"] / f"{nombre}.txt").write_text(texto)
