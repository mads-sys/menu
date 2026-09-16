import sys
sys.path.insert(0, '.')
from network_service import is_hostname_consistent_with_ip

test_cases = [
    ("EABA16", "192.168.0.106", False),
    ("EABA16", "192.168.0.117", False),
    ("EABA16", "192.168.0.115", False),
    ("EABA16", "192.168.0.116", True),
    ("eaba06", "192.168.0.106", True),
    ("eaba01", "192.168.0.101", True),
    ("eaba25", "192.168.0.125", True),
    ("padre01", "192.168.50.51", True),
    ("padre16", "192.168.50.66", True),
    ("padre16", "192.168.50.53", False),
    ("DESKTOP-VLJCE9Q", "192.168.0.4", True),
]

all_passed = True
for hn, ip, expected in test_cases:
    res = is_hostname_consistent_with_ip(hn, ip)
    if res != expected:
        print(f"FAILED: hn='{hn}', ip='{ip}' -> got {res}, expected {expected}")
        all_passed = False
    else:
        print(f"PASSED: hn='{hn}', ip='{ip}' -> {res}")

if all_passed:
    print("\nALL TEST CASES PASSED!")
