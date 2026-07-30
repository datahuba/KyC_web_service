from core.config import settings
attrs = [a for a in dir(settings) if not a.startswith('_')]
print('\n'.join(sorted(attrs)))
