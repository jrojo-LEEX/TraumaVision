from ultralytics import YOLO

if __name__ == "__main__":
    modelo = YOLO("yolov8m.pt")
    modelo.train(
        data="modelo/fracturas.yaml",
        epochs=60,
        patience=20,
        imgsz=640,
        batch=16,
        workers=0,
        device=0,
        amp=True,
        seed=0,
        deterministic=True,
        optimizer="AdamW",
        lr0=0.001,
        lrf=0.01,
        weight_decay=0.01,
        warmup_epochs=3,
        cos_lr=True,
        close_mosaic=10,
        fliplr=0.5,
        degrees=5,
        translate=0.1,
        scale=0.5,
        hsv_v=0.3,
        mosaic=1.0,
        project="C:/Users/juanp/Documents/TraumaVision/modelo",
        name="v1r",
        exist_ok=False,
    )
