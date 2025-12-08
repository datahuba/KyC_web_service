# Modo de Desarrollo - Bypass de Autenticación

## ¿Qué es?

El modo de desarrollo permite desactivar la autenticación en todos los endpoints para facilitar las pruebas durante el desarrollo.

## ¿Cómo activarlo?

Agrega esta línea a tu archivo `.env`:

```
DEVELOPMENT_MODE=true
```

## ¿Qué hace?

Cuando `DEVELOPMENT_MODE=true`:
- **Todos los endpoints** funcionan sin necesidad de token JWT
- El sistema retorna automáticamente un usuario **SUPERADMIN** mock
- No necesitas hacer login ni enviar headers de autenticación

## Usuario Mock

El usuario mock que se retorna tiene:
- **Username**: `dev_admin`
- **Email**: `dev@example.com`
- **Rol**: `SUPERADMIN`
- **ID**: `000000000000000000000001`

## ⚠️ IMPORTANTE

> [!CAUTION]
> **NUNCA** actives el modo de desarrollo en producción.
> 
> Esto desactiva completamente la seguridad de la aplicación.

## Uso en Desarrollo

### Con modo desarrollo activado:

```bash
# En tu .env
DEVELOPMENT_MODE=true
```

```bash
# Probar endpoint sin autenticación
curl http://localhost:8000/api/v1/students/
```

### Sin modo desarrollo (producción):

```bash
# En tu .env
DEVELOPMENT_MODE=false
# O simplemente no incluir la variable
```

```bash
# Necesitas autenticarte primero
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "password"}'

# Luego usar el token
curl http://localhost:8000/api/v1/students/ \
  -H "Authorization: Bearer <tu_token>"
```

## Verificar el modo actual

El modo de desarrollo se aplica automáticamente al iniciar el servidor. Puedes verificarlo en los logs al arrancar la aplicación.
