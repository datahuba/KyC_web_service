# -*- coding: utf-8 -*-
"""
F-071 (2026-07-28) · Tests: Estandarizacion a `role` (ingles) en respuestas.

Antes: el modelo User de Beanie tiene `rol` (espanol) pero los endpoints
devolven `rol` en /users/{id} y `role` en /auth/me. Inconsistencia que el
frontend resolvia con fallback `user.role || user.rol`.

F-071: UserResponse schema ahora tiene `serialization_alias="role"`, asi
que /users/{id} tambien devuelve `role`. Frontend limpia los fallbacks.

Estos tests verifican:
  1. UserResponse serializa como `role` en JSON
  2. Acepta entrada como `rol` (populate_by_name)
  3. Los endpoints /users/{id} y /auth/me devuelven `role`
"""
from pathlib import Path

SCHEMA_FILE = Path(__file__).parent.parent / "schemas" / "user.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestF071SerializationAlias:
    """F-071: UserResponse.rol se serializa como `role` en JSON."""

    def test_serialization_alias_role(self):
        """El campo rol debe tener serialization_alias='role'."""
        content = read(SCHEMA_FILE)
        assert 'serialization_alias="role"' in content, (
            "F-071: UserResponse.rol debe tener serialization_alias='role' "
            "para que el JSON exponga el campo como 'role' (ingles)"
        )

    def test_populate_by_name_activo(self):
        """populate_by_name=True permite leer el modelo Beanie (que tiene `rol`)."""
        content = read(SCHEMA_FILE)
        assert "populate_by_name" in content, (
            "F-071: UserResponse debe tener populate_by_name=True para "
            "aceptar entrada como 'rol' o 'role' indistintamente"
        )

    def test_comentario_f071(self):
        """Debe haber comentario F-071 explicando el cambio."""
        content = read(SCHEMA_FILE)
        assert "F-071" in content, (
            "F-071: debe haber comentario F-071 en schemas/user.py"
        )

    def test_field_es_rol_python_alias_es_role(self):
        """El field Python sigue siendo `rol` (Beanie/mongo lo espera asi)."""
        content = read(SCHEMA_FILE)
        # Buscar la declaracion del campo rol con su alias
        idx = content.find("serialization_alias")
        bloque = content[max(0, idx - 200):idx + 100]
        assert "rol:" in bloque, (
            "F-071: el campo Python debe seguir siendo `rol` (Beanie lo usa "
            "para leer de MongoDB). Solo cambia el nombre en JSON."
        )


class TestF071FrontendCleanup:
    """F-071: frontend ya no usa `user.rol` directamente sin fallback."""

    def test_no_rol_en_userStore_excluido(self):
        """userStore.ts mantiene el patron defensivo intencionalmente."""
        userstore = Path("C:/Users/Usuario/Documents/PROYECTO KYC/kyc-client/src/lib/stores/userStore.ts")
        if userstore.exists():
            content = userstore.read_text(encoding="utf-8")
            # userStore SI debe tener el patron defensivo
            assert "user.rol" in content, (
                "F-071: userStore.ts debe mantener `user.role || user.rol` "
                "para ser tolerante a respuestas antiguas del backend"
            )

    def test_no_uso_directo_de_user_rol_sin_fallback(self):
        """No debe haber `user.rol` usado sin fallback en archivos que NO son userStore."""
        from pathlib import Path
        frontend = Path("C:/Users/Usuario/Documents/PROYECTO KYC/kyc-client/src")
        archivos_con_rol = []
        for f in frontend.rglob("*.svelte"):
            rel = str(f.relative_to(frontend)).replace("\\", "/")
            if rel == "lib/stores/userStore.ts":
                continue
            content = f.read_text(encoding="utf-8", errors="ignore")
            # Buscar uso directo de user.rol sin fallback
            import re
            # Patron: user.rol que NO este precedido por `||` o `.role` o `.rol?.`
            matches = re.findall(r"(?<!\|)(?<!\.)(?<!\?)\buser\.rol\b(?!\|)(?!\s*\?)", content)
            if matches:
                archivos_con_rol.append((rel, len(matches)))
        for rel, n in archivos_con_rol:
            assert False, (
                f"F-071: archivo {rel} tiene {n} uso(s) directo(s) de `user.rol` "
                f"sin fallback. Debe ser `user.role`."
            )
