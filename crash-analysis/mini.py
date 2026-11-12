import sys, gc
sys.modules["av"] = None
from io import BytesIO
import cv2
from cv2 import videoio_registry as vr
data = open(sys.argv[2], "rb").read()
api = next(b for b in vr.getStreamBufferedBackends() if vr.hasBackend(b))
def grab_all(c):
    n = 0
    while c.grab(): n += 1
    return n
mode = sys.argv[1]
if mode == "one-temp":            # Base pattern: temp BytesIO, one capture
    c = cv2.VideoCapture(BytesIO(data), api, []); gc.collect(); print(grab_all(c))
elif mode == "one-temp-churn":    # temp BytesIO + allocate lots so freed memory is reused
    c = cv2.VideoCapture(BytesIO(data), api, []); gc.collect()
    junk = [bytearray(len(data)) for _ in range(20)]; print(grab_all(c))
elif mode == "two-temp":          # v1: second capture (temp BytesIO) while first is open
    c1 = cv2.VideoCapture(BytesIO(data), api, []); c2 = cv2.VideoCapture(BytesIO(data), api, [])
    print(grab_all(c2)); c2.release(); print(c1.grab())
elif mode == "two-held":          # v2: second capture with buffer kept alive
    c1 = cv2.VideoCapture(BytesIO(data), api, []); b = BytesIO(data); c2 = cv2.VideoCapture(b, api, [])
    print(grab_all(c2)); c2.release(); print(c1.grab())
elif mode == "two-held-first":    # both buffers kept alive
    b1 = BytesIO(data); c1 = cv2.VideoCapture(b1, api, []); b2 = BytesIO(data); c2 = cv2.VideoCapture(b2, api, [])
    print(grab_all(c2)); c2.release(); print(c1.grab())
print("refcount-check", sys.getrefcount(BytesIO(data)))
