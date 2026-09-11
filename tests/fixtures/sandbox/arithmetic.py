"""Original arithmetic and seeded-PRNG fixture has independently known output."""

import json
import random

print(json.dumps({"sum": sum(range(101)), "seeded": random.random()}))
