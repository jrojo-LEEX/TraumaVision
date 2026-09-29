from ultralytics import YOLO

if __name__ == "__main__":
    modelo = YOLO("modelo/v1r/weights/last.pt")
    modelo.train(resume=True, workers=0)
