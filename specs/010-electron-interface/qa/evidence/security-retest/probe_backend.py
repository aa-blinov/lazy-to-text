import sys
sys.path.insert(0,"/private/tmp/claude-501/sec-retest/proj")
import app.backends.onnx_backend  # the real import path, nothing else first
import os; print("ORT_DISABLE_TELEMETRY =", os.environ.get("ORT_DISABLE_TELEMETRY"))
exec(open(sys.argv[3]).read())
