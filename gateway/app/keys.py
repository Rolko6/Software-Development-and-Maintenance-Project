import base64
import os

# Pre-shared at deployment time (see docker-compose.yml) rather than fetched
# from the cloud at runtime, so there's nothing for a man-in-the-middle to
# intercept/substitute on bootstrap.
CLOUD_PUBLIC_KEY = base64.b64decode(os.environ["CLOUD_ML_KEM_PUBLIC_KEY"])
