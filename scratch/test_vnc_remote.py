import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vnc_service
import logging
import json

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("test_vnc")

# Test on 192.168.50.63
res = vnc_service.ensure_remote_vnc_server("192.168.50.63", "aluno", "1234", log)
print("RESULT:", json.dumps(res, indent=2))
