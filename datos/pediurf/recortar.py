import csv
import math
from pathlib import Path

import cv2

VENTANA = {"front": (2.4, 4.0, 0.50), "side": (3.4, 6.0, 0.45)}
MANO = {"arriba": (0, -1), "abajo": (0, 1), "izq": (-1, 0), "der": (1, 0)}

if __name__ == "__main__":
    muestra = Path("datos/pediurf/muestra")
    salida = Path("datos/pediurf/recortes")

    for fila in csv.DictReader(open("datos/pediurf/puntos.csv")):
        imagen = cv2.imread(str(muestra / fila["carpeta"] / fila["archivo"]), cv2.IMREAD_GRAYSCALE)
        alto, ancho = imagen.shape

        borde = max(alto, ancho)
        imagen = cv2.copyMakeBorder(imagen, borde, borde, borde, borde, cv2.BORDER_CONSTANT, value=0)

        ax = float(fila["ax"]) / 10 * ancho + borde
        ay = float(fila["ay"]) / 10 * alto + borde
        bx = float(fila["bx"]) / 10 * ancho + borde
        by = float(fila["by"]) / 10 * alto + borde

        centro = ((ax + bx) / 2, (ay + by) / 2)
        ancho_hueso = math.hypot(bx - ax, by - ay)
        angulo = math.degrees(math.atan2(by - ay, bx - ax))

        giro = cv2.getRotationMatrix2D(centro, angulo, 1)
        mano_x, mano_y = MANO[fila["mano"]]
        if giro[1][0] * mano_x + giro[1][1] * mano_y > 0:
            giro = cv2.getRotationMatrix2D(centro, angulo + 180, 1)

        imagen = cv2.warpAffine(imagen, giro, (imagen.shape[1], imagen.shape[0]))

        vista = "side" if "_side" in fila["archivo"] else "front"
        veces_ancho, veces_alto, altura_fisis = VENTANA[vista]
        w = veces_ancho * ancho_hueso
        h = veces_alto * ancho_hueso
        x1 = round(centro[0] - w / 2)
        y1 = round(centro[1] - altura_fisis * h)
        recorte = imagen[y1:y1 + round(h), x1:x1 + round(w)]

        destino = salida / fila["clase"] / fila["archivo"].replace(".jpg", ".png")
        destino.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(destino), recorte)
