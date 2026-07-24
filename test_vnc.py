import sys
import time
from vnc_service import ensure_remote_vnc_server
import logging
logger = logging.getLogger('test')
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
logger.addHandler(handler)
res = ensure_remote_vnc_server('192.168.0.122', 'aluno', '1', logger, target_display=':0')
print(res)
