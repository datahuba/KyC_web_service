"""
Services Package
================

Este paquete contiene toda la lógica de negocio de la aplicación.

¿Qué son los servicios?
-----------------------
Los servicios contienen la lógica de negocio y operaciones sobre los modelos.
Se diferencian de los endpoints (API) porque:

- endpoints/: Manejan HTTP (requests, responses, validaciones)
- services/: Manejan lógica de negocio (cálculos, reglas, operaciones DB)

Esto permite:
- Reutilizar lógica en diferentes endpoints
- Probar la lógica de negocio sin HTTP
- Mantener los endpoints simples y limpios
"""

# Los servicios se importan según se necesiten
# No exponemos todo para evitar importaciones circulares

__all__ = []
