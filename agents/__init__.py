from . import investment, finance, legal, audit
REGISTRY = {m.KEY: m for m in (investment, finance, legal, audit)}
ORDER = ["investment", "finance", "legal"]
