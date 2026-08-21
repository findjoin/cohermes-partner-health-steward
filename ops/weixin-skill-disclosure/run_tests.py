"""Run the disclosure tests without requiring pytest on the server."""

import test_skill_disclosure as tests


names = sorted(name for name in dir(tests) if name.startswith("test_"))
for name in names:
    getattr(tests, name)()

print(f"{len(names)} tests passed")
