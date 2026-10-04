import base64
import os

# Pre-shared at deployment time (see docker-compose.yml) rather than fetched
# over the network at runtime, so there's nothing for a man-in-the-middle to
# intercept on bootstrap. The private key never leaves this process.
PRIVATE_KEY = base64.b64decode(os.environ["CLOUD_ML_KEM_PRIVATE_KEY"])
