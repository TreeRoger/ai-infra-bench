import sys, gc
sys.modules["av"] = None
from io import BytesIO
import cv2
from cv2 import videoio_registry as vr
data = open(sys.argv[3], "rb").read()
api = next(b for b in vr.getStreamBufferedBackends() if vr.hasBackend(b))
held, end = sys.argv[1], sys.argv[2]
b = BytesIO(data)
c = cv2.VideoCapture(b, api, [])
while c.grab(): pass
if held == "no": del b
if end == "release": c.release()
elif end == "del": del c
elif end == "release+del": c.release(); del c
gc.collect(); print("ok", flush=True)
