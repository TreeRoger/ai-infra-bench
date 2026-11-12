import sys, gc, weakref
sys.modules["av"] = None
from io import BytesIO
import cv2
from cv2 import videoio_registry as vr
data = open(sys.argv[1], "rb").read()
api = next(b for b in vr.getStreamBufferedBackends() if vr.hasBackend(b))
b = BytesIO(data); rc0 = sys.getrefcount(b); w = weakref.ref(b)
c = cv2.VideoCapture(b, api, [])
print("refcount before/after open:", rc0, sys.getrefcount(b))
del b; gc.collect()
print("buffer alive after del while capture open:", w() is not None)
c.release(); del c; gc.collect()
print("buffer alive after release:", w() is not None)
