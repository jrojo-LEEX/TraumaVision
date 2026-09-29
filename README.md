# TraumaVision

Detección de fracturas en radiografías de muñeca pediátrica con YOLOv8m.
Proyecto Integrador de Ingeniería Biomédica (UNC) — Juan Pablo Rojo.

## Carpetas

- `pagina/` — la aplicación web (FastAPI). Se abre con `pagina/EJECUTAR_TRAUMAVISION.bat`.
- `modelo/` — el modelo actual (v1r): entrenamiento, tests y resultados.
- `datos/` — GRAZPEDWRI-DX (entrenamiento y test interno) y PediURF (test externo).
- `venv/` — entorno de Python.

## Instalación

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

Todos los scripts de `modelo/` y `datos/` se corren desde esta carpeta:

```
venv\Scripts\python.exe modelo\test_interno.py
```

## Orden de los scripts

1. `datos/grazpedwri/armar_dataset.py` — CLAHE, solo la clase fractura, división por paciente 70/15/15.
2. `modelo/entrenar.py` — entrena YOLOv8m (60 épocas).
3. `modelo/test_interno.py` — test de GRAZPEDWRI; escribe `modelo/resultados/metricas.json`, que usa la página.
4. `datos/pediurf/sortear_muestra.py` — sortea los casos de PediURF (semilla 0).
5. `datos/pediurf/recortar.py` — recorta la muñeca a partir de `datos/pediurf/puntos.csv`.
6. `modelo/test_externo.py` — test de PediURF por caso.

## Resultados (umbral 0,22)

| | Sensibilidad | Especificidad |
|---|---|---|
| Test interno, GRAZPEDWRI (por imagen) | 96,7 % | 93,1 % |
| Test externo, PediURF (por imagen) | 97,4 % | 88,3 % |
| Test externo, PediURF (por caso) | 98,6 % | 83,2 % |

Los datos, los pesos del modelo, la base de datos y los estudios subidos no están en git.
