POLICIES = {
    "synthetic-v1": frozenset({"SYN-A", "SYN-B"}),
    "synthetic-v2": frozenset({"SYN-A"}),
}

ROUTES = {
    ("synthetic-receiver", "v1"),
    ("synthetic-receiver", "v2"),
}

ENVELOPE_FORMAT = "synthetic-json-v1"
MAX_ENVELOPE_BYTES = 1024 * 1024
